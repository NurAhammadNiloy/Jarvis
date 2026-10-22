"""The wake-word measurement script's counting and verdict (no microphone needed)."""
import importlib.util
from pathlib import Path

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


def test_listen_counts_detections_and_the_highest_score():
    detections, highest = measure.listen(Frames(100), Detector([0.1, 0.3, 0.8, 0.2]), 1, clock=Clock())
    assert [score for _, score in detections] == [0.8] and highest == 0.8


def test_good_verdict():
    lines = measure.summary([], 120, [(True, 0.9)] * 9 + [(False, 0.31)], 0.5)
    assert lines[0].startswith('False wake-ups: 0 in 2 min') and lines[1] == 'Detected: 9 of 10'
    assert 'Verdict: GOOD' in lines


def test_advice_when_false_wake_ups_or_misses():
    assert any(line.startswith('Advice: raise') for line in measure.summary([(40, 0.62)], 120, [(True, 0.9)] * 10, 0.5))
    lines = measure.summary([], 120, [(True, 0.9)] * 6 + [(False, 0.35)] * 4, 0.5)
    assert 'Verdict: needs tuning (see the advice below)' in lines and lines[-1].startswith('Advice: lower')
