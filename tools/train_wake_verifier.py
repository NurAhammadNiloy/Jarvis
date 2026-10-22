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


# Verifier gates shown side by side after training (WAKE_WORD_VERIFIER_GATE is one of them).
GATES = (0.03, 0.05, 0.07, 0.09, 0.12, 0.15)


def share(count, total):
    return f'{100 * count / total:.0f}% ({count}/{total})' if total else '-'


def describe(report, gate, threshold=None):
    """Readable lines from train_verifier's report, at verifier gate `gate`."""
    from core.wake_word import evaluate
    threshold = report['threshold'] if threshold is None else threshold
    result = evaluate(report, gate, threshold)
    alignments = max((len(tries) for tries in report['positive'].values()), default=0)
    false_wakes = sum(result['false_wakes'].values())
    lines = [f'Checked on clips each verifier never saw, each at {alignments} chunk alignments '
             f'(threshold {threshold:.2f}, verifier gate {gate:.2f}):',
             f'  "Hey Jarvis" detected:  plain {share(result["plain_detected"], result["tries"])}, '
             f'tuned {share(result["detected"], result["tries"])}',
             f'  other speech and sound: highest score plain {result["plain_highest"]:.2f}, tuned {result["highest"]:.2f}; '
             f'tuned false wake-ups {false_wakes} of {result["negative_tries"]}']
    if report.get('peaks'):
        accepted = [name for name in report['peaks'] if result['false_wakes'].get(name)]
        lines.append(f'  saved background peaks ({len(report["peaks"])}): '
                     + ('all rejected' if not accepted else 'still accepted: ' + ', '.join(accepted)))
    missed = [(name, count) for name, count in result['missed'].items() if count]
    if missed:
        lines.append('  still missed: ' + ', '.join(f'{name} ({count} of {alignments})' for name, count in missed))
    lines.append('Verifier gate (WAKE_WORD_VERIFIER_GATE): lower rescues more of your tries, higher trusts the '
                 'tuning less on sounds it was never taught:')
    for option in sorted(set(GATES) | {gate}):
        at = evaluate(report, option, threshold)
        lines.append(f'  {option:.2f}: detected {share(at["detected"], at["tries"])}, '
                     f'false wake-ups {sum(at["false_wakes"].values())}' + ('   <- in use' if option == gate else ''))
    good = result['detected'] >= 0.9 * result['tries'] and not false_wakes
    lines.append('Verdict: ' + ('GOOD' if good else 'not there yet') +
                 ' (target: at least 9 of 10 detected, no false wake-ups)')
    if not good and false_wakes:
        lines.append('  Other sound reaches the threshold: record more of it (--only speech or --only background) '
                     'and train again.')
    elif not good:
        lines.append('  Record more "Hey Jarvis" clips the way you missed them (--only wake) and train again.')
    return lines


def main():
    from config.settings import WAKE_WORD_THRESHOLD, WAKE_WORD_VERIFIER_GATE
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
    for line in describe(report, WAKE_WORD_VERIFIER_GATE, args.threshold):
        print(line)
    print(f'\nSaved {VERIFIER_PATH}. Restart Jarvis to use it, then measure:')
    print('  env\\Scripts\\python.exe -B tools\\measure_wake_word.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
