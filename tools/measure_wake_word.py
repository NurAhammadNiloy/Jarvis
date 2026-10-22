"""Measure the on-device wake word in your room, with your voice and microphone.

    env\\Scripts\\python.exe -B tools\\measure_wake_word.py                  (about 3 minutes)
    env\\Scripts\\python.exe -B tools\\measure_wake_word.py --threshold 0.4

1. Two minutes of normal room sound (talk, type, play a video; just don't say
   "Hey Jarvis"). You note what was playing; it is printed with the results.
2. You say "Hey Jarvis" 10 times when prompted.

The same audio goes to the plain model and, once you have trained it
(tools/train_wake_verifier.py), to the model tuned to your voice, so the two can be
compared directly. Target: at least 9 of 10 detected, and no background score at or
above the threshold. Nothing is recorded or saved, and nothing is sent anywhere.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# A suggested threshold stays this far above the highest background score, and never below
# MIN_THRESHOLD: two minutes of background cannot show everything a day brings (your
# plain-"Jarvis" run hit 0.43 in background that peaked at 0.05 an hour earlier).
MARGIN = 0.1
MIN_THRESHOLD = 0.3


def listen(frames, detectors, seconds, clock=time.monotonic):
    """Feed `seconds` of audio to every detector: per detector, (detections as
    (time, score), highest score)."""
    results = [([], 0.0) for _ in detectors]
    started = clock()
    while clock() - started < seconds:
        try:
            frame = frames.read(timeout=0.1)
        except OverflowError:  # a few frames were lost; keep going
            continue
        if frame is None:
            continue
        for index, detector in enumerate(detectors):
            event = detector.process(frame)
            found, highest = results[index]
            if event is not None:
                found.append((clock() - started, event.score))
            results[index] = (found, max(highest, detector.last_score))
    return results


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
    from core.wake_word import VERIFIER_PATH, OpenWakeWordDetector
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--threshold', type=float, default=WAKE_WORD_THRESHOLD)
    parser.add_argument('--background-seconds', type=float, default=120)
    parser.add_argument('--tries', type=int, default=10)
    parser.add_argument('--device', default=None, help='input device name or index (default: the system microphone)')
    args = parser.parse_args()

    from core.voice_capture import MicrophoneFrames, VoiceConfig
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
        background = [([], 0.0) for _ in detectors]
        for start in range(0, int(args.background_seconds), 10):
            results = listen(frames, detectors, min(10, args.background_seconds - start))
            for index, (found, peak) in enumerate(results):
                previous, highest = background[index]
                background[index] = (previous + [(start + t, s) for t, s in found], max(highest, peak))
            print(f"  {start + 10:.0f} s, highest so far: "
                  + ', '.join(f"{n.lower()} {b[1]:.2f}" for n, b in zip(names, background)), end='\r')
        print('\n')

        print("Step 2: say \"Hey Jarvis\" when prompted, at your normal distance and volume.")
        tries = [[] for _ in detectors]
        for number in range(1, args.tries + 1):
            listen(frames, detectors, 1.5)  # a pause, and the end of the previous try
            print(f"  ({number}/{args.tries}) Say \"Hey Jarvis\" now...", end=' ', flush=True)
            results = listen(frames, detectors, 4)
            for index, (found, peak) in enumerate(results):
                tries[index].append((bool(found), found[0][1] if found else peak))
            print(', '.join(f"{n.lower()}: " + (f"detected {t[-1][1]:.2f}" if t[-1][0] else f"missed ({t[-1][1]:.2f})")
                            for n, t in zip(names, tries)))

    print(f"\nResults (threshold {args.threshold:.2f}; background: {playing or 'not noted'})")
    for name, back, tried in zip(names, background, tries):
        for line in summary(name, back, tried, args.threshold):
            print(line)


if __name__ == '__main__':
    main()
