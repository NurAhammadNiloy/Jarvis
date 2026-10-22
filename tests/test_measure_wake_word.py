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


# --- background peaks and the microphone check ---------------------------------------------

def test_a_score_from_before_the_window_does_not_count_in_it():
    # The warm-up ended on 0.9; the background window's own frames only reach 0.1.
    detector = Detector([0.1, 0.1])
    detector.last_score = 0.9

    class Idle(Detector):  # no new 80 ms chunk yet in the first frames of the window
        def process(self, frame):
            return None
    idle = Idle([])
    idle.last_score = 0.9
    [(_, peak), (_, idle_peak)] = measure.listen(Frames(2), [detector, idle], 1, clock=Clock())
    assert peak == 0.1 and idle_peak == 0.0


class Scripted:
    """20 ms frames: a quiet hiss, with one loud frame at `loud`."""
    def __init__(self, count, loud=None):
        import numpy as np
        rng = np.random.default_rng(0)
        self.frames = [(rng.normal(0, 30, 320)).astype(np.int16).tobytes() for _ in range(count)]
        if loud is not None:
            self.frames[loud] = np.full(320, 32767, np.int16).tobytes()

    def read(self, timeout):
        return self.frames.pop(0) if self.frames else None


def test_background_moments_above_0_2_are_logged_with_their_time_and_saved(tmp_path):
    import json
    from datetime import datetime
    log = measure.AudioLog(tmp_path, ['Plain model'], now=lambda: datetime(2026, 10, 22, 14, 3, 12))
    scores = [0.05] * 150 + [0.43, 0.3] + [0.05] * 200 + [0.15]     # a peak 3 s in, then quiet
    for index, frame in enumerate(Scripted(len(scores)).frames):
        log.add(frame, [scores[index]])
    log.finish()
    [clip] = tmp_path.glob('*.wav')
    assert clip.name == 'peak_20261022_140312_0.43.wav'
    from core.wake_word import read_wav
    assert len(read_wav(clip)) == (100 + 2 + 50) * 320               # 2 s before, 1 s after the last high score
    [entry] = [json.loads(line) for line in (tmp_path / 'peaks.jsonl').read_text(encoding='utf-8').splitlines()]
    assert entry['time'] == '2026-10-22T14:03:12' and entry['seconds_into_background'] == 3.0
    assert entry['scores'] == {'Plain model': 0.43} and entry['file'] == clip.name
    assert measure.peak_lines(log)[1] == '    3.0 s (14:03:12): plain model 0.43  peak_20261022_140312_0.43.wav'


def test_a_quiet_background_saves_nothing_and_a_peak_at_the_end_is_still_saved(tmp_path):
    quiet = measure.AudioLog(tmp_path / 'quiet')
    for frame in Scripted(300).frames:
        quiet.add(frame, [0.2, 0.1])                                 # 0.20 itself is not above
    quiet.finish()
    assert not (tmp_path / 'quiet').exists() and measure.peak_lines(quiet) == ['Background moments above 0.20: none']
    late = measure.AudioLog(tmp_path / 'late')
    for frame in Scripted(10).frames:
        late.add(frame, [0.6])
    late.finish()
    assert len(list((tmp_path / 'late').glob('*.wav'))) == 1


def test_without_a_folder_the_log_only_keeps_levels_and_counts_lost_frames():
    class Lossy(Scripted):
        def read(self, timeout):
            if len(self.frames) == 45:
                self.frames.pop(0)
                raise OverflowError
            return super().read(timeout)
    log = measure.AudioLog()
    measure.listen(Lossy(50, loud=10), [Detector([0.9] * 20)], 1, clock=Clock(), log=log)
    assert log.lost == 1 and log.peaks == [] and log.levels()['clipped'] == 320


def test_the_microphone_check_reports_noise_clipping_and_lost_frames():
    quiet, loud = measure.AudioLog(), measure.AudioLog()
    for frame in Scripted(100).frames:
        quiet.add(frame, [0.0])
    for frame in Scripted(100, loud=50).frames:
        loud.add(frame, [0.0])
    lines = measure.microphone_lines(quiet, quiet)
    assert lines[0].startswith('Microphone: background noise floor -61 dBFS') and len(lines) == 1
    loud.lost = 2
    lines = measure.microphone_lines(quiet, loud)
    assert any('320 samples clipped' in line for line in lines) and 'lost frames' in lines[-1]


# --- the tries start on a clear cue --------------------------------------------------------------

SPOKEN, QUIET = b'\x01\x00' * 320, b'\x00' * 640


def scripted_listen(*tries):
    """A stand-in for listen(): each try window hears (audio, per-detector results) in turn."""
    tries, calls = list(tries), []

    def fake(frames, detectors, seconds, clock=None, log=None):
        calls.append(seconds)
        if log is None:
            return [([], 0.0) for _ in detectors]
        audio, results = tries.pop(0)
        log.audio += audio
        return results
    return fake, calls


def test_tries_start_after_enter_a_countdown_and_now(capsys):
    fake, calls = scripted_listen((SPOKEN * 30, [([(1.0, 0.8)], 0.8)]))
    waited = []
    tries = measure.run_tries(None, [None], ['Tuned'], 1, lambda f: f == SPOKEN, measure.AudioLog(),
                              wait=waited.append, listen=fake)
    assert tries == [[(True, 0.8)]] and waited and calls == [1, 1, 1, 4]   # 3, 2, 1, then the try at once
    out = capsys.readouterr().out
    assert '  3... 2... 1...\n' in out and '(1/1) Now! Say "Hey Jarvis"... tuned: detected 0.80' in out


def test_a_try_without_any_speech_is_repeated_once_not_counted(capsys):
    late = (QUIET * 200, [([], 0.0), ([], 0.0)])
    spoken = (SPOKEN * 30, [([], 0.31), ([(1.0, 0.72)], 0.72)])
    log = measure.AudioLog()
    fake, _ = scripted_listen(late, spoken, late, late)
    tries = measure.run_tries(None, [None, None], ['Plain', 'Tuned'], 2, lambda f: f == SPOKEN, log,
                              wait=lambda *_: '', listen=fake)
    assert tries == [[(False, 0.31), (False, 0.0)], [(True, 0.72), (False, 0.0)]]   # silent twice: a miss
    assert capsys.readouterr().out.count("I didn't hear you") == 2
    assert len(log.audio) == len(QUIET * 200) * 3 + len(SPOKEN * 30)        # every try's audio is checked for levels


# --- scenarios and the summary table -------------------------------------------------------------

def run(scenario, plain, tuned, time='2026-10-22T21:30:00', threshold=0.5):
    names = ['Plain model', 'Tuned to your voice']
    background = [([(5.0, 0.6)] * plain[1], plain[2]), ([(5.0, 0.6)] * tuned[1], tuned[2])]
    tries = [[(True, 0.9)] * plain[0] + [(False, 0.1)] * (10 - plain[0]), [(True, 0.9)] * tuned[0] + [(False, 0.1)] * (10 - tuned[0])]
    record = measure.result_record(scenario, 'notes', threshold, names, background, tries, {'noise_floor_db': -90.3})
    record['time'] = time
    return record


def test_results_are_saved_locally_and_the_summary_shows_the_latest_run_of_each_scenario(tmp_path):
    path = tmp_path / 'voice' / 'measurements.jsonl'
    assert measure.summary_table(measure.load_results(path))[0].startswith('No measurements yet')
    measure.save_result(path, run('video', (5, 1, 0.86), (9, 0, 0.04), time='2026-10-22T21:14:00'))
    measure.save_result(path, run('quiet', (6, 0, 0.05), (9, 0, 0.10), time='2026-10-22T20:00:00'))
    measure.save_result(path, run('video', (5, 0, 0.30), (8, 0, 0.20), time='2026-10-23T09:05:00'))   # replaces the first
    table = measure.summary_table(measure.load_results(path))
    assert table[0].split() == ['Scenario', 'Model', 'Detected', 'False', 'wake-ups', 'Highest', 'background', 'Verdict', 'Measured']
    rows = [line.split() for line in table[2:-1]]
    assert [(r[0], r[1]) for r in rows] == [('quiet', 'Plain'), ('quiet', 'Tuned'), ('video', 'Plain'), ('video', 'Tuned')]
    text = '\n'.join(table)
    assert '6/10' in text and '9/10' in text and '8/10' in text and '5/10' in text
    assert '2026-10-23 09:05' in text and '21:14' not in text          # the later video run, not the first
    assert [('GOOD' in line) for line in table[2:-1]] == [False, True, False, False]   # only quiet-tuned: 9/10, 0.10
    assert 'threshold 0.50' in table[-1]


def test_a_run_without_a_scenario_is_labelled(tmp_path):
    assert run(None, (9, 0, 0.1), (9, 0, 0.1))['scenario'] == 'unlabelled'


def test_summary_needs_no_microphone(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr('core.wake_word.MEASUREMENTS_PATH', tmp_path / 'none.jsonl')
    monkeypatch.setattr('sys.argv', ['measure_wake_word.py', '--summary'])
    measure.main()
    assert 'No measurements yet' in capsys.readouterr().out
