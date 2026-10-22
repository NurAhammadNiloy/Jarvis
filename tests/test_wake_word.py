"""On-device wake word: nothing reaches cloud recognition while Jarvis is passive
until the wake word fires; a misheard "Jarvis" in the transcript no longer matters."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from core.assistant import Assistant
from core.command_services import CommandServices
from core.dialogue import Dialogue
from core.speech_output import SpeechSnapshot
from core.voice_capture import AudioUtterance, VoiceConfig
from core.voice_policy import Recognition
from core.voice_runtime import ContinuousListener
from core.wake_word import OpenWakeWordDetector, WakeEvent

CONFIG = VoiceConfig(echo_mode='headset')
FRAME = CONFIG.frame_bytes
SPEECH, SILENCE = b'\x01\x00' * (FRAME // 2), b'\x00' * FRAME


def pcm(*spans):
    """spans: (frames, voiced) runs of 20 ms frames."""
    return b''.join((SPEECH if voiced else SILENCE) * frames for frames, voiced in spans)


class Recognizer:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, audio, partial=False):
        self.calls.append(audio)
        return self.results.pop(0)


def listener(*results, wake_required=True, detector=None):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot()
    recognizer = Recognizer(*results)
    jarvis = ContinuousListener(Mock(), lambda frame: frame == SPEECH, recognizer, speech, CONFIG,
                                wake_detector=detector or Mock())
    jarvis.wake_required = lambda: wake_required
    return jarvis, recognizer


# 0.4 s "hey Jarvis", a 0.3 s pause, 1 s of request, 1.4 s of silence
WAKE_THEN_REQUEST = pcm((20, True), (15, False), (50, True), (70, False))
WAKE_OFFSET = 35 * FRAME   # the request starts after the pause


def woken(audio=WAKE_THEN_REQUEST, score=0.97, offset=WAKE_OFFSET):
    return AudioUtterance(audio, wake_score=score, wake_offset=offset)


# --- the gate: passive audio without the wake word never leaves the machine --------------------

def test_passive_speech_without_the_wake_word_is_not_recognized():
    jarvis, recognizer = listener(Recognition('what time is it', 0.9))
    assert jarvis.handle_final(AudioUtterance(WAKE_THEN_REQUEST)) is None
    assert recognizer.calls == []


def test_active_window_and_pending_answers_need_no_wake_word():
    jarvis, recognizer = listener(Recognition('what time is it', 0.9), wake_required=False)
    assert jarvis.handle_final(AudioUtterance(WAKE_THEN_REQUEST)).text == 'what time is it'
    assert len(recognizer.calls) == 1


def test_wake_word_heard_in_the_transcript_too_is_kept_as_it_is():
    jarvis, recognizer = listener(Recognition('hey Jarvis what time is it', 0.9))
    result = jarvis.handle_final(woken())
    assert result.text == 'hey Jarvis what time is it' and result.wake_score == 0.97
    assert len(recognizer.calls) == 1


@pytest.mark.parametrize('misheard', [Recognition('nervous what time is it', 0.63),     # 22 Oct
                                      Recognition('Punjabi what time is it', 0.84),
                                      Recognition(error='unrecognized')])
def test_a_misheard_wake_word_is_replaced_by_the_request_after_it(misheard):
    jarvis, recognizer = listener(misheard, Recognition('what time is it', 0.91))
    result = jarvis.handle_final(woken())
    assert (result.text, result.confidence, result.wake_score, result.error) == ('what time is it', 0.91, 0.97, None)
    assert result.uid == misheard.uid                      # one line in the transcript
    assert recognizer.calls[1] == WAKE_THEN_REQUEST[WAKE_OFFSET:]


def test_the_wake_word_alone_needs_no_second_recognition():
    jarvis, recognizer = listener(Recognition('hey service', 0.5))
    result = jarvis.handle_final(woken(pcm((20, True), (70, False)), offset=20 * FRAME))
    assert (result.text, result.wake_score, result.error) == ('', 0.97, None)
    assert len(recognizer.calls) == 1


def test_recognition_failure_is_not_hidden():
    jarvis, _ = listener(Recognition(error='recognition_unavailable'))
    assert jarvis.handle_final(woken()).error == 'recognition_unavailable'


# --- tagging utterances in the capture thread ---------------------------------------------

def test_utterance_is_tagged_with_the_detection_and_the_pause_after_it():
    jarvis, _ = listener()
    frames = len(WAKE_THEN_REQUEST) // FRAME
    jarvis._frame_index = 1000                                  # the frame that ended the utterance
    first = 1000 - frames + 1
    jarvis._wakes.append((first + 25, WakeEvent('hey jarvis', 0.88)))   # fired in the pause after "Jarvis"
    tagged = jarvis._with_wake(AudioUtterance(WAKE_THEN_REQUEST))
    assert tagged.wake_score == 0.88
    assert tagged.wake_offset == 26 * FRAME                    # in the pause: after "Jarvis", before the request


def test_a_detection_in_the_request_itself_starts_at_the_preceding_pause():
    jarvis, _ = listener()
    frames = len(WAKE_THEN_REQUEST) // FRAME
    jarvis._frame_index = 1000
    first = 1000 - frames + 1
    jarvis._wakes.append((first + 38, WakeEvent('hey jarvis', 0.8)))    # 3 frames into the request
    assert jarvis._with_wake(AudioUtterance(WAKE_THEN_REQUEST)).wake_offset == WAKE_OFFSET


def test_old_detections_do_not_tag_a_later_utterance():
    jarvis, _ = listener()
    jarvis._frame_index = 5000
    jarvis._wakes.append((100, WakeEvent('hey jarvis', 0.9)))
    assert jarvis._with_wake(AudioUtterance(WAKE_THEN_REQUEST)).wake_score is None


def test_wake_word_while_jarvis_speaks_stops_it_at_once():
    detector = Mock()
    detector.process.return_value = WakeEvent('hey jarvis', 0.93)
    jarvis, _ = listener(detector=detector)
    jarvis.speech.stop.return_value = True
    jarvis._detect_wake(SPEECH, SpeechSnapshot(4, 'It is 2:30 PM.', True))
    jarvis.speech.stop.assert_called_once_with(expected_id=4)


def test_a_failing_detector_turns_itself_off_instead_of_stopping_capture():
    detector = Mock()
    detector.process.side_effect = RuntimeError('onnx')
    jarvis, _ = listener(detector=detector)
    jarvis._detect_wake(SPEECH, SpeechSnapshot())
    assert jarvis.wake_detector is None


# --- the detector -------------------------------------------------------------------------

class FakeModel:
    def __init__(self, scores):
        self.scores = list(scores)

    def predict(self, chunk):
        assert len(chunk) == 1280
        return {'hey_jarvis_v0.1': self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        pass


def test_detector_scores_80ms_chunks_and_fires_once_per_wake_word():
    detector = OpenWakeWordDetector(0.5, model=FakeModel([0.1, 0.7, 0.9, 0.95, 0.2] + [0.0] * 20 + [0.8]))
    events = [detector.process(SILENCE) for _ in range(4 * 26)]   # 20 ms frames, 26 chunks
    fired = [(i, e) for i, e in enumerate(events) if e]
    assert [e.score for _, e in fired] == [0.7, 0.8]               # the burst counts once
    assert fired[0][0] == 7                                        # at the end of the second chunk


def test_threshold_must_be_a_probability():
    with pytest.raises(ValueError):
        OpenWakeWordDetector(1.5, model=FakeModel([]))


DATA = Path(__file__).parent / 'data'


@pytest.mark.skipif(not (Path(__file__).parents[1] / 'models' / 'wake_word' / 'hey_jarvis_v0.1.onnx').exists(),
                    reason='wake-word model not downloaded')
def test_real_model_on_recorded_clips():
    # Windows' built-in voice saying "Hey Jarvis, what time is it?" / "What time is it?"
    def scores(name):
        detector = OpenWakeWordDetector(0.5)
        with wave.open(str(DATA / name)) as clip:
            audio = b'\x00' * 32000 + clip.readframes(clip.getnframes()) + b'\x00' * 32000
        return [e for e in (detector.process(audio[i:i + FRAME]) for i in range(0, len(audio) - FRAME + 1, FRAME)) if e]
    assert len(scores('hey_jarvis_what_time.wav')) == 1
    assert scores('what_time.wav') == []


# --- the assistant -----------------------------------------------------------------------

@pytest.fixture
def assistant():
    speech, output, listener_ = Mock(), Mock(), Mock()
    speech.is_speaking.return_value = False
    jarvis = Assistant(listener_, speech, CommandServices(Mock()), output, clock=lambda: 0,
                       dialogue=Dialogue(Mock(return_value={'reply': 'Hm.', 'query': None}), clock=lambda: 0))
    return SimpleNamespace(jarvis=jarvis, listener=listener_, said=lambda: [c.args[0] for c in output.call_args_list])


def test_the_assistant_tells_the_listener_when_the_wake_word_is_needed(assistant):
    assert assistant.listener.wake_required() is True             # passive
    assistant.jarvis.active_conversation = True
    assert assistant.listener.wake_required() is False            # active window
    assistant.jarvis.active_conversation = False
    assistant.jarvis.state.await_slot('alarm', 'time', 'set an alarm', 'What time should I set the alarm for?')
    assert assistant.listener.wake_required() is False            # waiting for your answer


def test_a_request_after_the_detected_wake_word_is_addressed(assistant):
    assert assistant.jarvis.process_recognition(Recognition('what time is it', 0.91, wake_score=0.97), passive=True)
    assert assistant.said()[-1].startswith("It's ")


def test_the_detected_wake_word_alone_greets(assistant):
    assert assistant.jarvis.process_recognition(Recognition('', wake_score=0.6), passive=True)
    assert assistant.jarvis.active_conversation and len(assistant.said()) == 1


def test_without_a_detection_passive_speech_still_needs_jarvis_in_the_transcript(assistant):
    assert not assistant.jarvis.process_recognition(Recognition('what time is it', 0.91), passive=True)


# --- the transcript ------------------------------------------------------------------------

def test_transcript_shows_detections_with_their_score():
    from core.live_transcript import LiveTranscript
    lines = []
    printer = LiveTranscript(out=lines.append, clock=lambda: 0)
    printer('wake_detected', {'keyword': 'hey jarvis', 'score': 0.873})
    printer('recognition', {'uid': 1, 'partial': False, 'text': 'what time is it', 'confidence': 0.91,
                            'error': None, 'wake_score': 0.873})
    printer('turn_started', {'uid': 1})
    printer('turn_finished', {'uid': 1, 'window': 'active 30s'})
    printer('recognition', {'uid': 2, 'partial': False, 'text': '', 'confidence': None, 'error': None,
                            'wake_score': 0.61})
    printer('turn_started', {'uid': 2})
    printer('voice_decision', {'decision': 'wake'})
    printer('turn_finished', {'uid': 2, 'window': 'active 30s'})
    assert lines[0] == 'Wake word: "hey jarvis"  score 0.87'
    assert lines[1].startswith('You (heard): "what time is it"  conf 0.91  wake 0.87 | intent time')
    assert lines[2].startswith('You (heard): "(wake word only)"  conf -  wake 0.61 | wake word')


# --- end to end through the capture thread (real VAD and model, fake microphone and cloud) ---------

@pytest.mark.skipif(not (Path(__file__).parents[1] / 'models' / 'wake_word' / 'hey_jarvis_v0.1.onnx').exists(),
                    reason='wake-word model not downloaded')
@pytest.mark.parametrize('clip, recognized', [('hey_jarvis_what_time.wav', 1), ('what_time.wav', 0)])
def test_passive_listener_sends_only_woken_speech_to_recognition(clip, recognized):
    import queue
    from core.voice_capture import create_vad

    class ClipSource:
        def __init__(self, audio):
            self.frames = queue.Queue()
            for i in range(0, len(audio) - FRAME + 1, FRAME):
                self.frames.put(audio[i:i + FRAME])

        def __enter__(self):
            return self

        def read(self, timeout):
            try:
                return self.frames.get(timeout=timeout)
            except queue.Empty:
                return None

        def __exit__(self, *args):
            pass

    with wave.open(str(DATA / clip)) as source:
        audio = b'\x00' * 16000 + source.readframes(source.getnframes()) + b'\x00' * 64000
    recognizer = Recognizer(Recognition('hey Jarvis what time is it', 0.9))
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot()
    jarvis = ContinuousListener(ClipSource(audio), create_vad(CONFIG), recognizer, speech, CONFIG,
                                wake_detector=OpenWakeWordDetector(0.5))
    jarvis.wake_required = lambda: True
    try:
        result = jarvis.listen(timeout=5 if recognized else 1.5)
    finally:
        jarvis.close()
    assert len(recognizer.calls) == recognized
    if recognized:
        assert result.text == 'hey Jarvis what time is it' and result.wake_score >= 0.5
    else:
        assert result is None


# --- a false wake costs one recognition, never a spoken reply -------------------------------------

@pytest.mark.parametrize('text, heard', [('hey Jarvis', True), ('Yarvis stop', True), ('nervous what time is it', True),
                                         ('hey service', True), ('New Jersey', True), ("Jarvis's", True),
                                         ('Travis', True), ('and then the video says hello', False), ('', False),
                                         ('subscribe to my channel', False), ('hey guys', False)])
def test_wake_like_words_in_a_transcript(text, heard):
    from core.voice_policy import wake_like
    assert wake_like(text) is heard


def test_the_listener_says_whether_the_transcript_backs_up_the_detection():
    jarvis, _ = listener(Recognition('hey Jarvis what time is it', 0.9))
    assert jarvis.handle_final(woken()).wake_heard is True
    jarvis, _ = listener(Recognition('nervous what time is it', 0.63), Recognition('what time is it', 0.91))
    assert jarvis.handle_final(woken()).wake_heard is True
    jarvis, _ = listener(Recognition('so in this video we', 0.8), Recognition('we', 0.5))
    assert jarvis.handle_final(woken()).wake_heard is False
    jarvis, _ = listener(Recognition(error='unrecognized'), Recognition(error='unrecognized'))
    assert jarvis.handle_final(woken()).wake_heard is False
    jarvis, _ = listener(Recognition(error='recognition_unavailable'))
    assert jarvis.handle_final(woken()).wake_heard is None


@pytest.mark.parametrize('text', ['', 'we', 'subscribe to my channel'])
def test_an_unconfirmed_wake_without_a_command_stays_silent_and_passive(assistant, text):
    assert not assistant.jarvis.process_recognition(
        Recognition(text, 0.8, wake_score=0.53, wake_heard=False), passive=True)
    assert assistant.said() == [] and not assistant.jarvis.active_conversation


def test_an_unconfirmed_wake_with_a_command_is_still_carried_out(assistant):
    # "Hey Jarvis" lost entirely by the recognizer, the request heard: act on it.
    assert assistant.jarvis.process_recognition(
        Recognition('what time is it', 0.91, wake_score=0.8, wake_heard=False), passive=True)
    assert assistant.said()[-1].startswith("It's ")


def test_a_confirmed_or_unknown_wake_still_greets(assistant):
    assert assistant.jarvis.process_recognition(Recognition('', wake_score=0.8, wake_heard=True), passive=True)
    assert assistant.said() == [assistant.said()[0]] and assistant.jarvis.active_conversation


def test_only_passive_listening_is_silenced(assistant):
    # Waiting for an answer, the wake word is not needed: the reply is handled as before.
    assistant.jarvis.state.await_slot('alarm', 'time', 'set an alarm', 'What time should I set the alarm for?')
    assert assistant.jarvis.process_recognition(Recognition('', wake_score=0.8, wake_heard=False), passive=True)
