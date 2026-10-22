"""Recording your voice and tuning the wake word to it (no microphone needed)."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from core import wake_word
from core.wake_word import OpenWakeWordDetector, create_detector, read_wav, train_verifier

TOOLS = Path(__file__).parents[1] / 'tools'
DATA = Path(__file__).parent / 'data'
MODEL_READY = (Path(__file__).parents[1] / 'models' / 'wake_word' / 'hey_jarvis_v0.1.onnx').exists()


def tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


record = tool('record_voice')
train = tool('train_wake_verifier')
SPEECH, SILENCE = b'\x01\x00' * 320, b'\x00' * 640


class Frames:
    """20 ms frames from a script of (count, voiced) runs, then silence."""
    def __init__(self, *runs):
        self.frames = [SPEECH if voiced else SILENCE for count, voiced in runs for _ in range(count)]

    def read(self, timeout):
        return self.frames.pop(0) if self.frames else SILENCE


def vad(frame):
    return frame == SPEECH


# --- recording ------------------------------------------------------------------------------

def test_read_seconds_and_voiced_time():
    audio = record.read_seconds(Frames((10, True), (40, False)), 1)
    assert len(audio) == 32000 and record.voiced_ms(audio, vad) == 200


def test_an_utterance_runs_from_speech_to_the_pause_and_silence_gives_none():
    audio = record.read_utterance(Frames((20, False), (50, True), (100, False)), vad, silence_ms=1200)
    assert record.voiced_ms(audio, vad) == 1000
    assert len(audio) == (14 + 50 + 60) * 640          # 0.28 s before, the speech, the closing pause
    assert record.read_utterance(Frames(), vad, wait_seconds=1) is None


def test_wake_clips_are_saved_and_silent_tries_repeated(tmp_path):
    # A silent first try (3 s), then two tries of 3 s, each followed by the 0.7 s pause.
    frames = Frames((150, False), (40, True), (110, False), (35, False), (40, True), (110, False), (35, False))
    record.record_wake(frames, vad, tmp_path, prompts=['normally', 'quickly'], wait=lambda *_: '')
    clips = sorted(tmp_path.glob('*.wav'))
    assert [c.name for c in clips] == ['hey_jarvis_001.wav', 'hey_jarvis_002.wav']
    assert len(read_wav(clips[0])) == 3 * 16000


def test_commands_are_saved_with_the_exact_text(tmp_path):
    frames = Frames((10, False), (40, True), (80, False), (10, False), (30, True), (80, False))
    record.record_commands(frames, vad, tmp_path, commands=('what time is it', 'yes do it'), wait=lambda *_: '')
    manifest = [json.loads(line) for line in (tmp_path / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [(m['file'], m['text']) for m in manifest] == [('command_001.wav', 'what time is it'),
                                                          ('command_002.wav', 'yes do it')]


def test_speech_is_saved_in_ten_second_pieces_and_background_can_be_skipped(tmp_path):
    record.record_speech(Frames(), tmp_path / 'speech', seconds=20, wait=lambda *_: '')
    assert len(list((tmp_path / 'speech').glob('speech_*.wav'))) == 2
    record.record_background(Frames(), tmp_path / 'background', wait=lambda *_: 's')
    assert not (tmp_path / 'background').exists()


def test_numbering_continues_and_fresh_clears(tmp_path):
    record.write_wav(tmp_path / 'hey_jarvis_007.wav', SILENCE)
    assert record.next_path(tmp_path, 'hey_jarvis').name == 'hey_jarvis_008.wav'
    record.clear(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_command_list_has_twenty_commands_and_the_wake_list_thirty_varied_prompts():
    assert len(record.COMMANDS) == 20 and len(set(record.COMMANDS)) == 20
    assert len(record.WAKE_PROMPTS) == 30 and len(set(record.WAKE_PROMPTS)) == 5
    assert 'hey jarvis' not in record.SPEECH_TEXT.lower().replace('"hey jarvis"', '')


def test_recordings_go_to_data_voice():
    assert wake_word.VOICE_DIR == Path(__file__).parents[1] / 'data' / 'voice'
    assert wake_word.VERIFIER_PATH.parent == wake_word.VOICE_DIR


# --- training ------------------------------------------------------------------------------

def clips(tmp_path):
    """Five "Hey Jarvis" clips (one recording at different starts and volumes) and two others."""
    hey, other = read_wav(DATA / 'hey_jarvis_what_time.wav'), read_wav(DATA / 'what_time.wav')
    positives = []
    for i, (start, gain) in enumerate([(0, 1.0), (800, 0.7), (1600, 1.2), (2400, 0.5), (3200, 0.9)]):
        path = tmp_path / 'wake' / f'hey_jarvis_{i:03d}.wav'
        record.write_wav(path, (hey[start:] * gain).astype(np.int16).tobytes())
        positives.append(path)
    negatives = [record.write_wav(tmp_path / 'speech' / f'speech_{i:03d}.wav', (other * g).astype(np.int16).tobytes())
                 for i, g in enumerate((1.0, 0.6))]
    return positives, negatives


@pytest.mark.skipif(not MODEL_READY, reason='wake-word model not downloaded')
def test_training_checks_on_unseen_clips_saves_the_verifier_and_the_app_uses_it(tmp_path):
    positives, negatives = clips(tmp_path)
    report = train_verifier(positives, negatives, tmp_path / 'verifier.pkl', progress=lambda *_: None)
    assert len(report['positive']) == 5 and len(report['negative']) == 2
    assert all(len(tries) == 4 for tries in report['positive'].values())      # four chunk alignments
    result = wake_word.evaluate(report, gate=0.09)
    assert result['tries'] == 20 and result['detected'] == 20
    assert result['negative_tries'] == 8 and not any(result['false_wakes'].values())

    detector = create_detector('openwakeword', 0.5, verifier_path=tmp_path / 'verifier.pkl')
    assert detector.personal
    audio = b'\x00' * 32000 + read_wav(DATA / 'hey_jarvis_what_time.wav').tobytes() + b'\x00' * 32000
    assert [e for e in (detector.process(audio[i:i + 640]) for i in range(0, len(audio) - 639, 640)) if e]
    assert not create_detector('openwakeword', 0.5, personal=False, verifier_path=tmp_path / 'verifier.pkl').personal
    assert not create_detector('openwakeword', 0.5, verifier_path=tmp_path / 'missing.pkl').personal


def test_training_needs_enough_recordings(tmp_path):
    with pytest.raises(ValueError, match='at least 5'):
        train_verifier([tmp_path / 'a.wav'], [tmp_path / 'b.wav'], tmp_path / 'v.pkl')


def test_positive_examples_are_the_moments_near_the_clip_peak():
    frames = [(0.01, 'silence'), (0.2, 'hey'), (0.45, 'jarvis'), (0.3, 'tail'), (0.02, 'after')]
    assert wake_word.positive_examples(frames) == ['jarvis', 'tail']
    assert wake_word.positive_examples([(0.03, 'x')]) == []          # never reached the gate


def test_the_verifier_decides_only_from_the_gate():
    # (plain score, verifier score) per 80 ms frame
    assert wake_word.tuned_peak([(0.04, 0.9), (0.3, 0.6)], gate=0.09) == 0.6
    assert wake_word.tuned_peak([(0.09, 0.9)], gate=0.09) == 0.9           # at the gate counts, as in openWakeWord
    assert wake_word.tuned_peak([(0.073, 0.6), (0.02, 0.1)], gate=0.09) == 0.073


def report(positive, negative, peaks=()):
    return {'positive': positive, 'negative': negative, 'peaks': list(peaks), 'threshold': 0.5}


# A rescued try (plain 0.11, verifier 0.8), a weak one (plain 0.06, verifier 0.7), and a video
# the verifier wrongly likes at plain 0.07.
TRIES = {'hey_jarvis_001.wav': [[(0.9, 0.95)]] * 4, 'hey_jarvis_002.wav': [[(0.11, 0.8)]] * 4,
         'hey_jarvis_003.wav': [[(0.06, 0.7)]] * 4}
VIDEO = {'peak_1.wav': [[(0.07, 0.6)]] * 2 + [[(0.02, 0.6)]] * 2, 'speech_001.wav': [[(0.3, 0.1)]] * 4}


def test_evaluation_at_a_gate_counts_every_alignment():
    at_low = wake_word.evaluate(report(TRIES, VIDEO), gate=0.05)
    assert (at_low['detected'], at_low['plain_detected'], at_low['tries']) == (12, 4, 12)
    assert at_low['false_wakes'] == {'peak_1.wav': 2, 'speech_001.wav': 0} and at_low['highest'] == 0.6
    at_gate = wake_word.evaluate(report(TRIES, VIDEO), gate=0.09)
    assert at_gate['detected'] == 8 and at_gate['missed']['hey_jarvis_003.wav'] == 4
    assert not any(at_gate['false_wakes'].values()) and at_gate['plain_highest'] == 0.3


def test_training_report_shows_the_gate_trade_off_and_the_verdict():
    lines = train.describe(report(TRIES, VIDEO, peaks=['peak_1.wav']), gate=0.05)
    assert '  saved background peaks (1): still accepted: peak_1.wav' in lines
    assert '  0.09: detected 67% (8/12), false wake-ups 0' in lines
    assert '  0.05: detected 100% (12/12), false wake-ups 2   <- in use' in lines
    assert lines[-2].startswith('Verdict: not there yet') and 'record more of it' in lines[-1]
    good = train.describe(report({'a.wav': [[(0.4, 0.9)]] * 10}, VIDEO), gate=0.09)
    assert good[-1].startswith('Verdict: GOOD')


def test_training_tool_explains_when_nothing_is_recorded(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wake_word, 'VOICE_DIR', tmp_path)
    monkeypatch.setattr('sys.argv', ['train_wake_verifier.py'])
    assert train.main() == 1
    assert 'record_voice.py' in capsys.readouterr().out


# --- microphone health -------------------------------------------------------------------------

def test_audio_levels_measure_noise_floor_and_clipping():
    from core.wake_word import audio_levels, level_warnings
    rng = np.random.default_rng(0)
    hiss = rng.normal(0, 30, 16000).astype(np.int16)                  # about -61 dBFS
    assert audio_levels(hiss)['noise_floor_db'] == pytest.approx(-61, abs=1.5)
    assert audio_levels(hiss)['clipped'] == 0 and level_warnings(audio_levels(hiss)) == []
    clipped = np.concatenate([hiss, np.full(100, -32768, np.int16)])
    assert audio_levels(clipped)['clipped'] == 100 and audio_levels(clipped)['peak_db'] == 0.0
    noisy = rng.normal(0, 600, 16000).astype(np.int16)                # about -35 dBFS
    assert 'noise floor' in level_warnings(audio_levels(noisy))[0]
    assert audio_levels(np.zeros(0, np.int16))['clipped'] == 0


def test_check_reports_noise_and_clipping_per_part(tmp_path):
    rng = np.random.default_rng(0)
    quiet = rng.normal(0, 30, 48000).astype(np.int16)
    record.write_wav(tmp_path / 'wake' / 'hey_jarvis_001.wav', quiet.tobytes())
    loud = quiet.copy()
    loud[1000:1050] = 32767
    record.write_wav(tmp_path / 'wake' / 'hey_jarvis_002.wav', loud.tobytes())
    record.write_wav(tmp_path / 'speech' / 'speech_001.wav', rng.normal(0, 600, 48000).astype(np.int16).tobytes())
    lines = record.check(tmp_path)
    assert lines[0].startswith('wake: 2 clips, noise floor -61 dBFS') and lines[0].endswith('clipped in 1: hey_jarvis_002.wav')
    assert '--only wake --fresh' in lines[1]
    assert lines[2].startswith('speech: 1 clips') and 'noise floor is high' in lines[3]
    assert lines[4:] == ['background: no recordings', 'commands: no recordings']
    assert 'CLIPPED (50 samples)' in record.clip_note(loud.tobytes()) and record.clip_note(quiet.tobytes()) == ''
