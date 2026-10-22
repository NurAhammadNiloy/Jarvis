"""The wake-word measurement script's counting, verdict and advice (no microphone needed)."""
import importlib.util
from pathlib import Path

import pytest

from core.wake_word import WakeEvent

spec = importlib.util.spec_from_file_location(
    'measure_wake_word', Path(__file__).parents[1] / 'tools' / 'measure_wake_word.py')
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class Frames:
    def __init__(self, count):
        self.count = count

    def read(self, timeout):
        self.count -= 1
        return b'frame' if self.count >= 0 else None


class Detector:
    def __init__(self, scores):
        self.scores, self.last_score = list(scores), 0.0

    def process(self, frame):
        self.last_score = self.scores.pop(0) if self.scores else 0.0
        return WakeEvent('hey jarvis', self.last_score) if self.last_score >= 0.5 else None


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.02
        return self.now


def test_listen_feeds_the_same_audio_to_every_detector():
    (plain_hits, plain_peak), (tuned_hits, tuned_peak) = measure.listen(
        Frames(100), [Detector([0.1, 0.3, 0.4, 0.2]), Detector([0.1, 0.3, 0.8, 0.2])], 1, clock=Clock())
    assert (plain_hits, plain_peak) == ([], 0.4)
    assert [score for _, score in tuned_hits] == [0.8] and tuned_peak == 0.8


# Your measurements, 22 Oct 2026 (wired headset, threshold 0.50).
HEY_JARVIS = [(True, 0.9)] * 6 + [(False, 0.08), (False, 0.49), (False, 0.39), (False, 0.49)]
PLAIN_JARVIS = [(False, s) for s in (0.0, 0.05, 0.15, 0.1, 0.0, 0.12, 0.02, 0.08, 0.0, 0.03)]


def suggested(text):
    import re
    match = re.search(r'to (?:at least )?(\d\.\d\d)', text or '')
    return float(match.group(1)) if match else None


def test_advice_never_goes_at_or_below_the_background_peak():
    # Plain "Jarvis": background 0.43, attempts up to 0.15 - the old script said "lower to 0.10".
    tip = measure.advice(0.43, PLAIN_JARVIS, 0.5)
    assert tip.startswith('No safe lower threshold') and 'Tune the wake word' in tip
    # "Hey Jarvis": background 0.05; the safe floor is 0.30, which catches 0.49, 0.39 and 0.49 but not 0.08.
    tip = measure.advice(0.05, HEY_JARVIS, 0.5)
    assert suggested(tip) == 0.30 and 'catch 3 of the 4 misses' in tip and 'tune the wake word' in tip


@pytest.mark.parametrize('background, misses', [(0.0, [0.12]), (0.2, [0.31]), (0.33, [0.45, 0.2]), (0.43, [0.1])])
def test_any_suggested_lower_threshold_stays_above_background_and_minimum(background, misses):
    tip = measure.advice(background, [(False, m) for m in misses], 0.5)
    value = suggested(tip)
    assert value is None or (value > background + 0.05 and value >= measure.MIN_THRESHOLD)


def test_background_at_the_threshold_means_raise_it():
    tip = measure.advice(0.55, [(True, 0.9)] * 10, 0.5)
    assert tip.startswith('Background reached 0.55') and suggested(tip) == 0.65


def test_verdict_needs_nine_of_ten_and_quiet_background():
    good = measure.summary('Tuned to your voice', ([], 0.12), [(True, 0.9)] * 9 + [(False, 0.3)], 0.5)
    assert good[-1] == '  verdict: GOOD'
    noisy = measure.summary('Plain model', ([(30.0, 0.6)], 0.6), [(True, 0.9)] * 10, 0.5)
    assert '  verdict: not there yet' in noisy and noisy[-1].startswith('  advice: Background reached')
    weak = measure.summary('Plain model', ([], 0.05), HEY_JARVIS, 0.5)
    assert weak[2] == '  detected: 6 of 10 (misses peaked at 0.08, 0.49, 0.39, 0.49)'
