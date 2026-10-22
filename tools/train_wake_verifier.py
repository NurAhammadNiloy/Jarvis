"""Tune the wake word to your voice from the recordings in data/voice/.

    env\\Scripts\\python.exe -B tools\\train_wake_verifier.py        (about 1 minute)

Trains openWakeWord's personal verifier: "Hey Jarvis" clips (data/voice/wake/) against
your other speech and background sound (data/voice/speech/, data/voice/background/).
First every clip is scored by a verifier that was trained without it, so the numbers
show how it does on new attempts; then the final verifier is trained on everything and
saved as data/voice/hey_jarvis_verifier.pkl. Jarvis uses it from the next start
(WAKE_WORD_PERSONAL in config/settings.py). Nothing leaves this computer.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def describe(report, threshold):
    """Readable lines from train_verifier's report."""
    positives, negatives = report['positive'], report['negative']
    plain_hits = sum(1 for _, plain, _ in positives if plain >= threshold)
    tuned_hits = sum(1 for _, _, tuned in positives if tuned >= threshold)
    plain_noise = max((plain for _, plain, _ in negatives), default=0.0)
    tuned_noise = max((tuned for _, _, tuned in negatives), default=0.0)
    lines = [f'Checked on clips each verifier never saw (threshold {threshold:.2f}):',
             f'  "Hey Jarvis" detected:     plain {plain_hits}/{len(positives)}, tuned {tuned_hits}/{len(positives)}',
             f'  highest other-speech score: plain {plain_noise:.2f}, tuned {tuned_noise:.2f}']
    missed = [(name, tuned) for name, _, tuned in positives if tuned < threshold]
    if missed:
        lines.append('  still missed: ' + ', '.join(f'{name} ({score:.2f})' for name, score in missed))
    good = tuned_hits >= 0.9 * len(positives) and tuned_noise < threshold
    lines.append('Verdict: ' + ('GOOD' if good else 'not there yet') +
                 ' (target: at least 9 of 10 detected, no other-speech score above the threshold)')
    if not good and tuned_noise >= threshold:
        lines.append('  Your other speech reaches the threshold: record more of it (--only speech) and train again.')
    elif not good:
        lines.append('  Record more "Hey Jarvis" clips the way you missed them (--only wake) and train again.')
    return lines


def main():
    from config.settings import WAKE_WORD_THRESHOLD
    from core.wake_word import VERIFIER_PATH, VOICE_DIR, train_verifier
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--threshold', type=float, default=WAKE_WORD_THRESHOLD)
    args = parser.parse_args()
    positives = sorted((VOICE_DIR / 'wake').glob('*.wav'))
    negatives = sorted((VOICE_DIR / 'speech').glob('*.wav')) + sorted((VOICE_DIR / 'background').glob('*.wav'))
    if len(positives) < 5 or not negatives:
        print(f'Found {len(positives)} "Hey Jarvis" clips and {len(negatives)} other clips in {VOICE_DIR}.')
        print('Record them first: env\\Scripts\\python.exe -B tools\\record_voice.py')
        return 1
    report = train_verifier(positives, negatives, VERIFIER_PATH, threshold=args.threshold)
    print()
    for line in describe(report, args.threshold):
        print(line)
    print(f'\nSaved {VERIFIER_PATH}. Restart Jarvis to use it, then measure:')
    print('  env\\Scripts\\python.exe -B tools\\measure_wake_word.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
