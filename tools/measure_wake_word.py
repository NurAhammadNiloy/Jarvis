"""Measure the on-device wake word in your room, with your voice and microphone.

    env\\Scripts\\python.exe -B tools\\measure_wake_word.py
    env\\Scripts\\python.exe -B tools\\measure_wake_word.py --phrase "Jarvis" --threshold 0.4

1. Two minutes of normal room sound (talk, type, play a video; just don't say
   "Jarvis"): every detection is a false wake-up.
2. You say the wake phrase 10 times when prompted: how many were detected.

It prints the scores so you can choose WAKE_WORD_THRESHOLD in config/settings.py.
Nothing is recorded or saved, and nothing is sent anywhere.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def listen(frames, detector, seconds, clock=time.monotonic):
    """Feed `seconds` of audio to the detector: (detections as (time, score), highest score)."""
    detections, highest, started = [], 0.0, clock()
    while clock() - started < seconds:
        try:
            frame = frames.read(timeout=0.1)
        except OverflowError:  # a few frames were lost; keep going
            continue
        if frame is None:
            continue
        event = detector.process(frame)
        highest = max(highest, detector.last_score)
        if event is not None:
            detections.append((clock() - started, event.score))
    return detections, highest


def summary(false_wakes, background_seconds, tries, threshold):
    """The verdict lines, from false wake-ups and per-try (detected, highest score)."""
    detected = sum(1 for hit, _ in tries if hit)
    per_hour = len(false_wakes) * 3600 / background_seconds if background_seconds else 0
    lines = [f"False wake-ups: {len(false_wakes)} in {background_seconds / 60:.0f} min (about {per_hour:.0f} per hour)",
             f"Detected: {detected} of {len(tries)}"]
    misses = [score for hit, score in tries if not hit]
    if misses:
        lines.append("Missed tries peaked at " + ', '.join(f"{s:.2f}" for s in misses)
                     + f" (threshold {threshold:.2f})")
    good = not false_wakes and detected >= 0.9 * len(tries)
    lines.append("Verdict: GOOD" if good else "Verdict: needs tuning (see the advice below)")
    if false_wakes:
        lines.append("Advice: raise WAKE_WORD_THRESHOLD a little above the false wake-up scores "
                     + ', '.join(f"{s:.2f}" for _, s in false_wakes) + ".")
    if misses and not false_wakes:
        lines.append(f"Advice: lower WAKE_WORD_THRESHOLD towards {max(min(misses) - 0.05, 0.1):.2f}, then run this again.")
    return lines


def main():
    from config.settings import WAKE_WORD_THRESHOLD
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--threshold', type=float, default=WAKE_WORD_THRESHOLD)
    parser.add_argument('--phrase', default='Hey Jarvis')
    parser.add_argument('--background-seconds', type=float, default=120)
    parser.add_argument('--tries', type=int, default=10)
    parser.add_argument('--device', default=None, help='input device name or index (default: the system microphone)')
    args = parser.parse_args()

    from core.voice_capture import MicrophoneFrames, VoiceConfig
    from core.wake_word import OpenWakeWordDetector
    detector = OpenWakeWordDetector(args.threshold)
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    print(f"Wake-word test: phrase \"{args.phrase}\", threshold {args.threshold:.2f}\n")

    with MicrophoneFrames(VoiceConfig(input_device=device)) as frames:
        print(f"Step 1: {args.background_seconds / 60:.0f} minutes of normal room sound. Talk, type or play a video,")
        print("but don't say \"Jarvis\". Starting in 3 seconds...")
        listen(frames, detector, 3)
        false_wakes, highest = [], 0.0
        for start in range(0, int(args.background_seconds), 10):
            found, peak = listen(frames, detector, min(10, args.background_seconds - start))
            false_wakes += [(start + t, s) for t, s in found]
            highest = max(highest, peak)
            for t, s in found:
                print(f"  false wake-up at {start + t:.0f} s, score {s:.2f}")
            print(f"  {start + 10:.0f} s, highest score so far {highest:.2f}", end='\r')
        print(f"\nHighest background score: {highest:.2f}\n")

        print(f"Step 2: say \"{args.phrase}\" when prompted, at your normal distance and volume.")
        tries = []
        for number in range(1, args.tries + 1):
            listen(frames, detector, 1.5)  # a pause, and the end of the previous try
            print(f"  ({number}/{args.tries}) Say \"{args.phrase}\" now...", end=' ', flush=True)
            found, peak = listen(frames, detector, 4)
            hit = bool(found)
            tries.append((hit, found[0][1] if hit else peak))
            print(f"detected, score {found[0][1]:.2f}" if hit else f"missed (highest score {peak:.2f})")

    print()
    for line in summary(false_wakes, args.background_seconds, tries, args.threshold):
        print(line)


if __name__ == '__main__':
    main()
