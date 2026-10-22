"""Measure the on-device wake word in your room, with your voice and microphone.

    env\\Scripts\\python.exe -B tools\\measure_wake_word.py                  (about 3 minutes)
    env\\Scripts\\python.exe -B tools\\measure_wake_word.py --threshold 0.4

1. Two minutes of normal room sound (talk, type, play a video; just don't say
   "Hey Jarvis"). You note what was playing; it is printed with the results.
2. You say "Hey Jarvis" 10 times, each right after "Now!" (the first after Enter and a
   countdown). A try in which no speech was heard at all is repeated once, so a late
   start is not counted as a miss.

The same audio goes to the plain model and, once you have trained it
(tools/train_wake_verifier.py), to the model tuned to your voice, so the two can be
compared directly. Target: at least 9 of 10 detected, and no background score at or
above the threshold.

Every background moment scoring above 0.20 is logged with its time and saved as a short
clip (2 s before, 1 s after) in data/voice/background_peaks/, so you can listen to what
caused it; the next training (tools/train_wake_verifier.py) learns them as "not the wake
word" (other voices saying "Jarvis" included). Nothing else is saved, and nothing is sent anywhere. The results also show the
microphone's noise floor, clipping and lost frames.
"""
import argparse
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# A suggested threshold stays this far above the highest background score, and never below
# MIN_THRESHOLD: two minutes of background cannot show everything a day brings (your
# plain-"Jarvis" run hit 0.43 in background that peaked at 0.05 an hour earlier).
MARGIN = 0.1
MIN_THRESHOLD = 0.3
CLIP_SCORE = 0.2          # background moments above this are saved to listen to
SAMPLE_RATE, FRAME_BYTES = 16000, 640


def listen(frames, detectors, seconds, clock=time.monotonic, log=None):
    """Feed `seconds` of audio to every detector: per detector, (detections as
    (time, score), highest score). `log` (an AudioLog) sees every frame and its scores."""
    results = [([], 0.0) for _ in detectors]
    for detector in detectors:
        detector.last_score = 0.0  # a score from before this window must not count in it
    started = clock()
    while clock() - started < seconds:
        try:
            frame = frames.read(timeout=0.1)
        except OverflowError:  # a few frames were lost; keep going
            if log is not None:
                log.lost += 1
            continue
        if frame is None:
            continue
        for index, detector in enumerate(detectors):
            event = detector.process(frame)
            found, highest = results[index]
            if event is not None:
                found.append((clock() - started, event.score))
            results[index] = (found, max(highest, detector.last_score))
        if log is not None:
            log.add(frame, [detector.last_score for detector in detectors])
    return results


class AudioLog:
    """The audio of a measurement window, for its microphone levels. With a folder, every
    moment scoring above `min_score` is saved as a clip (`before` s of lead-in, until
    `after` s past the last high score) and logged with its time in peaks.jsonl."""

    def __init__(self, folder=None, names=(), min_score=CLIP_SCORE, before=2.0, after=1.0,
                 max_seconds=8.0, now=datetime.now):
        self.folder = Path(folder) if folder else None
        self.names, self.min_score, self.now = list(names), min_score, now
        self.audio, self.lost, self.peaks = bytearray(), 0, []
        self._history = deque(maxlen=int(before * SAMPLE_RATE * 2 / FRAME_BYTES))
        self._after = int(after * SAMPLE_RATE * 2 / FRAME_BYTES)
        self._max_bytes = int(max_seconds * SAMPLE_RATE) * 2
        self._open = None

    @property
    def seconds(self):
        return len(self.audio) / (SAMPLE_RATE * 2)

    def add(self, frame, scores):
        self.audio += frame
        if self.folder is None:
            return
        score = max(scores, default=0.0)
        moment = self._open
        if moment is not None:
            moment['audio'] += frame
            if score > moment['score']:
                moment.update(score=score, scores=list(scores), at=self.seconds, time=self.now())
            moment['left'] = self._after if score > self.min_score else moment['left'] - 1
            if moment['left'] <= 0 or len(moment['audio']) >= self._max_bytes:
                self._save()
        elif score > self.min_score:
            self._open = {'audio': bytearray(b''.join(self._history) + frame), 'left': self._after,
                          'score': score, 'scores': list(scores), 'at': self.seconds, 'time': self.now()}
        self._history.append(frame)

    def finish(self):
        if self._open is not None:
            self._save()

    def levels(self):
        import numpy as np
        from core.wake_word import audio_levels
        return audio_levels(np.frombuffer(bytes(self.audio), dtype=np.int16))

    def _save(self):
        import numpy as np
        from core.wake_word import audio_levels
        moment, self._open = self._open, None
        audio = bytes(moment['audio'])
        path = self.folder / f"peak_{moment['time']:%Y%m%d_%H%M%S}_{moment['score']:.2f}.wav"
        self.folder.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), 'wb') as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(SAMPLE_RATE)
            clip.writeframes(audio)
        names = self.names or [f'detector {i + 1}' for i in range(len(moment['scores']))]
        entry = {'time': moment['time'].isoformat(timespec='seconds'),
                 'seconds_into_background': round(moment['at'], 1),
                 'scores': {name: round(score, 2) for name, score in zip(names, moment['scores'])},
                 'file': path.name, 'levels': audio_levels(np.frombuffer(audio, dtype=np.int16))}
        with open(self.folder / 'peaks.jsonl', 'a', encoding='utf-8') as manifest:
            manifest.write(json.dumps(entry) + '\n')
        self.peaks.append(entry)
        print(f"\r  score {moment['score']:.2f} at {moment['at']:.1f} s ({moment['time']:%H:%M:%S}): "
              f"saved {path.name}" + ' ' * 10)


def peak_lines(log):
    """The background moments that were saved, with their times."""
    if not log.peaks:
        return [f"Background moments above {CLIP_SCORE:.2f}: none"]
    lines = [f"Background moments above {CLIP_SCORE:.2f}: {len(log.peaks)}, saved in {log.folder} (listen to them):"]
    for peak in log.peaks:
        scores = ', '.join(f"{name.lower()} {score:.2f}" for name, score in peak['scores'].items())
        lines.append(f"  {peak['seconds_into_background']:5.1f} s ({peak['time'][11:]}): {scores}  {peak['file']}")
    return lines


def voiced_ms(audio, vad):
    return sum(1 for i in range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES)
               if vad(audio[i:i + FRAME_BYTES])) * FRAME_BYTES * 1000 // (SAMPLE_RATE * 2)


def run_tries(frames, detectors, names, count, vad, log, countdown=3, wait=input, listen=listen):
    """`count` tries of "Hey Jarvis", each started by a clear "Now!": per detector, a list of
    (detected, score). A try with no speech at all (under 0.2 s) and no detection was a late
    start, not a miss: it is repeated, once."""
    wait('Press Enter when you are ready; the first try starts after a countdown. ')
    print(' ', end='')
    for number in range(countdown, 0, -1):
        print(f' {number}...', end='', flush=True)
        listen(frames, detectors, 1)
    print()
    tries = [[] for _ in detectors]
    number, repeating = 1, False
    while number <= count:
        if number > 1 or repeating:
            listen(frames, detectors, 1.5)  # a pause, and the end of the previous try
        print(f'  ({number}/{count}) Now! Say "Hey Jarvis"...', end=' ', flush=True)
        heard = AudioLog()
        results = listen(frames, detectors, 4, log=heard)
        log.audio += heard.audio
        log.lost += heard.lost
        if not repeating and voiced_ms(heard.audio, vad) < 200 and not any(found for found, _ in results):
            print("I didn't hear you; this one again.")
            repeating = True
            continue
        repeating = False
        for index, (found, peak) in enumerate(results):
            tries[index].append((bool(found), found[0][1] if found else peak))
        print(', '.join(f"{n.lower()}: " + (f"detected {t[-1][1]:.2f}" if t[-1][0] else f"missed ({t[-1][1]:.2f})")
                        for n, t in zip(names, tries)))
        number += 1
    return tries


def microphone_lines(background, tries):
    """The microphone check: levels of the background and of your tries, and lost frames."""
    from core.wake_word import level_warnings
    back, spoken = background.levels(), tries.levels()
    lost = background.lost + tries.lost
    lines = [f"Microphone: background noise floor {back['noise_floor_db']:.0f} dBFS, loudest {back['loudest_db']:.0f} dBFS, "
             f"{back['clipped']} clipped samples; your tries loudest {spoken['loudest_db']:.0f} dBFS, "
             f"{spoken['clipped']} clipped samples; {lost} lost-frame events"]
    for warning in level_warnings(back) + [w for w in level_warnings(spoken) if 'clipped' in w]:
        lines.append("  warning: " + warning)
    if lost:
        lines.append("  warning: the microphone lost frames (the computer was busy); the joins can cause odd scores.")
    return lines


def advice(background_peak, tries, threshold):
    """A threshold suggestion that never goes at or below the background peak (+ a margin)."""
    misses = [score for hit, score in tries if not hit]
    floor = round(max(background_peak + MARGIN, MIN_THRESHOLD), 2)
    if background_peak >= threshold:
        return (f"Background reached {background_peak:.2f}, at or above the threshold: raise WAKE_WORD_THRESHOLD "
                f"to at least {min(floor, 0.95):.2f}" + (", or tune to your voice." if misses else "."))
    if not misses:
        return None
    wanted = round(min(misses) - MARGIN, 2)
    if floor >= threshold:
        return (f"No safe lower threshold: background reached {background_peak:.2f}, too close to {threshold:.2f}. "
                "Tune the wake word to your voice (tools/record_voice.py, tools/train_wake_verifier.py).")
    suggestion = max(wanted, floor)
    caught = sum(1 for score in misses if score >= suggestion)
    text = (f"Lowering WAKE_WORD_THRESHOLD to {suggestion:.2f} (safely above the background peak "
            f"{background_peak:.2f}) would catch {caught} of the {len(misses)} misses.")
    if caught < len(misses):
        text += " The rest are too weak for any safe threshold: tune the wake word to your voice."
    return text


def summary(name, background, tries, threshold):
    """Result lines for one detector: background (detections, highest), tries [(hit, score)]."""
    false_wakes, highest = background
    detected = sum(1 for hit, _ in tries if hit)
    misses = [score for hit, score in tries if not hit]
    lines = [f"{name}:",
             f"  background: highest score {highest:.2f}, {len(false_wakes)} false wake-up(s)"
             + (" at " + ', '.join(f"{s:.2f}" for _, s in false_wakes) if false_wakes else ""),
             f"  detected: {detected} of {len(tries)}"
             + (" (misses peaked at " + ', '.join(f"{s:.2f}" for s in misses) + ")" if misses else "")]
    good = detected >= 0.9 * len(tries) and highest < threshold
    lines.append("  verdict: GOOD" if good else "  verdict: not there yet")
    tip = advice(highest, tries, threshold)
    if tip and not good:
        lines.append("  advice: " + tip)
    return lines


def main():
    from config.settings import WAKE_WORD_THRESHOLD, WAKE_WORD_VERIFIER_GATE
    from core.wake_word import VERIFIER_PATH, VOICE_DIR, OpenWakeWordDetector
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--threshold', type=float, default=WAKE_WORD_THRESHOLD)
    parser.add_argument('--background-seconds', type=float, default=120)
    parser.add_argument('--tries', type=int, default=10)
    parser.add_argument('--device', default=None, help='input device name or index (default: the system microphone)')
    args = parser.parse_args()

    from core.voice_capture import MicrophoneFrames, VoiceConfig, create_vad
    names, detectors = ['Plain model'], [OpenWakeWordDetector(args.threshold)]
    if VERIFIER_PATH.exists():
        names.append('Tuned to your voice')
        detectors.append(OpenWakeWordDetector(args.threshold, verifier_path=VERIFIER_PATH,
                                              verifier_gate=WAKE_WORD_VERIFIER_GATE))
    else:
        print("Not tuned to your voice yet (tools/record_voice.py, then tools/train_wake_verifier.py): "
              "measuring the plain model only.")
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    print(f'Wake-word test: "Hey Jarvis", threshold {args.threshold:.2f}\n')
    playing = input("What will be playing in the background (e.g. 'quiet room', 'YouTube video, typing')? ").strip()

    with MicrophoneFrames(VoiceConfig(input_device=device)) as frames:
        print(f"\nStep 1: {args.background_seconds / 60:.0f} minutes of normal room sound. Talk, type or play a video,")
        print("but don't say \"Hey Jarvis\". Starting in 3 seconds...")
        listen(frames, detectors, 3)
        background_log, tries_log = AudioLog(VOICE_DIR / 'background_peaks', names), AudioLog()
        background = [([], 0.0) for _ in detectors]
        for start in range(0, int(args.background_seconds), 10):
            results = listen(frames, detectors, min(10, args.background_seconds - start), log=background_log)
            for index, (found, peak) in enumerate(results):
                previous, highest = background[index]
                background[index] = (previous + [(start + t, s) for t, s in found], max(highest, peak))
            print(f"  {start + 10:.0f} s, highest so far: "
                  + ', '.join(f"{n.lower()} {b[1]:.2f}" for n, b in zip(names, background)), end='\r')
        background_log.finish()
        print('\n')

        print("Step 2: say \"Hey Jarvis\" right after each \"Now!\", at your normal distance and volume.")
        tries = run_tries(frames, detectors, names, args.tries, create_vad(VoiceConfig()), tries_log)

    print(f"\nResults (threshold {args.threshold:.2f}; background: {playing or 'not noted'})")
    for name, back, tried in zip(names, background, tries):
        for line in summary(name, back, tried, args.threshold):
            print(line)
    for line in peak_lines(background_log) + microphone_lines(background_log, tries_log):
        print(line)


if __name__ == '__main__':
    main()
