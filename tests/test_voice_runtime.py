"""Connected voice-runtime tests using queues, fake transports and fake devices."""
from dataclasses import replace
import queue
import threading
import time
from unittest.mock import Mock
import pytest

from core.assistant import Assistant
from core.command_result import ActionResult
from core.command_services import CommandServices
from core.speech_output import SpeechSnapshot
from core.voice_capture import AudioUtterance, VoiceConfig
from core.voice_policy import Hypothesis, Recognition
from core.voice_runtime import ContinuousListener


class QueueSource:
    def __init__(self):
        self.frames = queue.Queue()
        self.closed = threading.Event()
        self.read_count = 0
        self.continued_capture = threading.Event()

    def __enter__(self):
        return self

    def read(self, timeout):
        try:
            item = self.frames.get(timeout=timeout)
            self.read_count += 1
            if self.read_count > 90:
                self.continued_capture.set()
            if isinstance(item, Exception):
                raise item
            return item
        except queue.Empty:
            return None

    def __exit__(self, *args):
        self.closed.set()


def fake_speech(job_id=None):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot(job_id, 'It is sunny outside.', job_id is not None)
    speech.is_speaking.return_value = job_id is not None
    speech.stop.return_value = True
    return speech


def test_silence_timeout_returns_control_and_closes_capture():
    source = QueueSource()
    listener = ContinuousListener(source, lambda f: True, Mock(), fake_speech())
    assert listener.listen(timeout=0.02) is None
    listener.close()
    assert source.closed.wait(1)
    assert all(not thread.is_alive() for thread in listener._threads)


def test_capture_and_barge_in_continue_while_final_recognition_is_blocked():
    source = QueueSource()
    speech = fake_speech(1)
    entered, release, interrupted = threading.Event(), threading.Event(), threading.Event()
    speech.stop.side_effect = lambda **kwargs: interrupted.set() or True
    def recognize(pcm, partial=False):
        if partial:
            return Recognition('stop', 0.99)
        entered.set()
        assert release.wait(3)
        return Recognition('Jarvis what time is it', 0.99)
    # Frame count supplies a deterministic capture clock; no real audio sleeps.
    listener = ContinuousListener(source, lambda f: f[0] == 1, recognize, speech,
                                  clock=lambda: source.read_count * 0.02)
    listener.start()
    try:
        for _ in range(20):
            source.frames.put(b'\1' * 640)
        for _ in range(70):
            source.frames.put(b'\0' * 640)
        assert entered.wait(1)
        for _ in range(100):
            source.frames.put(b'\1' * 640)
        assert interrupted.wait(1)
        assert source.continued_capture.wait(1)
        assert not release.is_set()
        assert source.read_count > 90
        speech.stop.assert_called_with(expected_id=1)
    finally:
        release.set()
        listener.close()


def test_short_stop_is_detected_during_following_silence():
    source = QueueSource()
    speech = fake_speech(1)
    interrupted = threading.Event()
    speech.stop.side_effect = lambda **kwargs: interrupted.set() or True
    listener = ContinuousListener(source, lambda f: f[0] == 1,
        lambda pcm, partial=False: Recognition('stop', 0.99), speech,
        clock=lambda: source.read_count * 0.02)
    listener.start()
    try:
        for _ in range(10):
            source.frames.put(b'\1' * 640)
        for _ in range(40):
            source.frames.put(b'\0' * 640)
        assert interrupted.wait(1)
        # Less than the final endpoint silence: this came from the barge-in lane.
        assert listener.results.empty()
        speech.stop.assert_called_with(expected_id=1)
    finally:
        listener.close()


def test_partial_transcripts_never_enter_command_results():
    speech = fake_speech(1)
    recognizer = Mock(return_value=Recognition('cancel all timers', 0.99))
    listener = ContinuousListener(QueueSource(), lambda f: True, recognizer, speech)
    assert not listener.handle_interruption(AudioUtterance(b'pcm', playback_id=1))
    speech.stop.assert_not_called()
    assert listener.results.empty()


def test_echo_and_unaddressed_playback_mixture_cannot_execute_actions():
    recognizer = Mock(return_value=Recognition('It is sunny outside', 0.99))
    listener = ContinuousListener(QueueSource(), lambda f: True, recognizer, fake_speech(1))
    utterance = AudioUtterance(b'pcm', playback_id=1, playback_text='It is sunny outside.')
    assert listener.handle_final(utterance) is None
    recognizer.return_value = Recognition('set a timer for 5 minutes', 0.99)
    assert listener.handle_final(utterance) is None
    recognizer.return_value = Recognition('Jarvis set a timer for 5 minutes', 0.99)
    assert listener.handle_final(utterance).text == recognizer.return_value.text


def test_truncated_audio_is_not_sent_to_recognition():
    recognizer = Mock()
    listener = ContinuousListener(QueueSource(), lambda f: True, recognizer, fake_speech())
    result = listener.handle_final(AudioUtterance(b'partial command', truncated=True))
    assert result.truncated
    recognizer.assert_not_called()


def test_microphone_failure_surfaces_once_and_closes_source():
    source = QueueSource()
    source.frames.put(RuntimeError('device disconnected'))
    listener = ContinuousListener(source, lambda f: True, Mock(), fake_speech())
    try:
        assert listener.listen(timeout=1).error == 'microphone_RuntimeError'
        assert source.closed.wait(1)
    finally:
        listener.close()


def test_old_queued_transcript_is_not_dispatched():
    listener = ContinuousListener(QueueSource(), lambda f: True, Mock(), fake_speech(), clock=lambda: 20)
    listener.results.put(Recognition('cancel all timers', 0.99, captured_at=0))
    try:
        assert listener.listen(timeout=1).error == 'stale_recording'
    finally:
        listener.close()


def assistant_fixture(clock=lambda: 0):
    services = Mock(spec=CommandServices)
    services.follow_up.return_value = None
    services.chat.return_value = 'Answer.'
    services.extract_timer_info.return_value = {'action': 'cancel_all', 'label': None, 'duration': (None, None)}
    services.timer_action.return_value = ActionResult(('Cancelled.',))
    output, speech, listener = Mock(), fake_speech(), Mock()
    listener.is_capturing = False
    assistant = Assistant(listener, speech, services, output, clock)
    return assistant, services, output, speech, listener


def test_assistant_does_not_execute_weak_or_conflicting_actions():
    assistant, services, output, _, _ = assistant_fixture()
    assistant.process_recognition(Recognition('cancel all timers', 0.3))  # ignored: weak, no wake word
    assistant.process_recognition(Recognition('cancel all timers', 0.99, (Hypothesis("don't cancel all timers"),)))
    services.timer_action.assert_not_called()  # alternatives disagree on a negation: never guessed
    assert output.call_count == 1


def test_unknown_confidence_requires_repeat_then_executes_once():
    assistant, services, _, _, _ = assistant_fixture()
    assistant.process_recognition(Recognition('cancel all timers'))
    services.timer_action.assert_not_called()
    assistant.process_recognition(Recognition('cancel all timers'))
    services.timer_action.assert_called_once()


def test_stop_is_local_quiet_and_uses_captured_playback_identity():
    assistant, services, output, speech, _ = assistant_fixture()
    assistant.process_recognition(Recognition('stop', 0.99, playback_id=7))
    speech.stop.assert_called_once_with(expected_id=7)
    assert services.mock_calls == []
    output.assert_not_called()


def test_wake_sentence_has_no_five_second_gate_and_preserves_negation():
    assistant, services, output, _, _ = assistant_fixture()
    assert not assistant.process_recognition(Recognition('jar of coffee', 0.99), passive=True)
    assert assistant.process_recognition(Recognition("Jarvis I'm not good", 0.99), passive=True)
    services.chat.assert_called_once_with("I'm not good")
    output.assert_called_once_with('Answer.')


def test_idle_timeout_runs_but_not_while_user_is_still_talking():
    now = [0]
    assistant, _, output, _, listener = assistant_fixture(clock=lambda: now[0])
    calls = []
    def listen(timeout):
        calls.append(timeout)
        now[0] = 121
        listener.is_capturing = len(calls) == 1
        return None
    listener.listen.side_effect = listen
    assistant.listen_for_command()
    assert len(calls) == 2
    assert not assistant.active_conversation
    output.assert_not_called()  # back to passive silently; wait_for_wake_word prints it


def test_pending_time_answer_is_confidence_checked_before_execution():
    from dataclasses import asdict
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.reminder_parser import parse_reminder
    assistant, services, output, _, _ = assistant_fixture()
    now = datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo('Europe/Helsinki'))
    services.extract_reminder_info.side_effect = lambda query: asdict(parse_reminder(query, now))
    assistant.state.await_slot('create_reminder', 'time', 'remind me to call mom', 'When should I remind you?')
    assistant.process_recognition(Recognition('5pm', 0.2))
    services.reminder.assert_not_called()
    output.assert_called_once_with("I'm not sure I heard that. When should I remind you?")
    assert assistant.state.pending


@pytest.mark.parametrize('passive', [False, True])
@pytest.mark.parametrize('text,confidence', [
    ('Jarvis', 0.62109393), ('Jarvis', 0.64156437), ('Jarvis', 0.70855391),
    ('Jarvis Jarvis Jarvis', 0.51408696),
])
def test_recorded_wake_attempts_acknowledged_in_both_modes(passive, text, confidence):
    assistant, services, output, speech, _ = assistant_fixture()
    assert assistant.process_recognition(Recognition(text, confidence), passive=passive)
    assert assistant.active_conversation
    output.assert_called_once()
    speech.stop.assert_called_once()
    assert services.mock_calls == []


def test_wake_threshold_does_not_authorize_weak_inline_command():
    assistant, services, output, _, _ = assistant_fixture()
    assistant.process_recognition(Recognition('Jarvis cancel all timers', 0.45), passive=True)
    services.timer_action.assert_not_called()
    output.assert_called_once()


def test_repeated_recognition_failures_do_not_spam_or_extend_session():
    now = [0]
    assistant, services, output, _, _ = assistant_fixture(clock=lambda: now[0])
    # Noise is only answered while Jarvis waits for something (and then once).
    assistant.state.await_slot('alarm', 'time', 'set an alarm', 'What time should I set the alarm for?')
    now[0] = 50
    for _ in range(5):
        assistant.process_recognition(Recognition(error='unrecognized'))
    output.assert_called_once_with("I couldn't hear that. What time should I set the alarm for?")
    assert assistant.last_active_time == 0
    assistant.process_recognition(Recognition('Jarvis', 0.7))
    assistant.process_recognition(Recognition(error='unrecognized'))
    assert output.call_count == 3
    assert services.mock_calls == []


def test_passive_noise_and_incomplete_wake_do_not_greet():
    assistant, services, output, _, _ = assistant_fixture()
    assert not assistant.process_recognition(Recognition(error='unrecognized'), passive=True)
    assert not assistant.process_recognition(Recognition('Jarvis', 0.2), passive=True)
    output.assert_not_called()
    assistant.process_recognition(Recognition('Jarvis', 0.99, truncated=True), passive=True)
    assert 'incomplete' in output.call_args.args[0]
    assert services.mock_calls == []


def test_noise_cannot_queue_clarification_behind_pending_response():
    assistant, services, output, speech, _ = assistant_fixture()
    speech.is_speaking.return_value = True
    assert not assistant.process_recognition(Recognition(error='unrecognized'))
    output.assert_not_called()
    assert services.mock_calls == []


def test_new_uncertain_request_cancels_old_output_before_clarification():
    assistant, _, output, speech, _ = assistant_fixture()
    order = []
    speech.stop.side_effect = lambda **kw: order.append('stop')
    output.side_effect = lambda text: order.append('clarify')
    assistant.process_recognition(Recognition('cancel all timers', 0.6))
    assert order == ['stop', 'clarify']


def test_silent_generation_is_not_treated_as_speaker_overlap():
    source = QueueSource()
    speech = fake_speech(1)
    speech.snapshot.return_value = SpeechSnapshot(1, 'Preparing response', False)
    listener = ContinuousListener(source, lambda f: f[0] == 1,
        lambda *args, **kw: Recognition('what time is it', 0.99), speech)
    try:
        for _ in range(10):
            source.frames.put(b'\1' * 640)
        for _ in range(70):
            source.frames.put(b'\0' * 640)
        result = listener.listen(timeout=1)
        assert result.text == 'what time is it'
        assert result.playback_id is None
    finally:
        listener.close()
