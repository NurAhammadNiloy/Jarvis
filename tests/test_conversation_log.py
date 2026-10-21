"""Diagnostic logging must preserve text and never require real audio/storage."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

from core import conversation_log
from core.assistant import Assistant
from core.command_services import CommandServices
from core.speech_output import PCMClip, SpeechController
from core.voice_capture import AudioUtterance
from core.voice_policy import Hypothesis, Recognition
from core.voice_runtime import ContinuousListener


def entries(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_append_sessions_unicode_and_concurrent_events(tmp_path):
    path = tmp_path / 'logs' / 'conversation.jsonl'
    log = conversation_log.ConversationLog(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: log.record('message', text=f"Don't delete Україна\n{i}"), range(40)))
    other = conversation_log.ConversationLog(path)
    other.record('session_started')
    rows = entries(path)
    assert len(rows) == 41
    assert [row['sequence'] for row in rows[:40]] == list(range(1, 41))
    assert rows[0]['session'] != rows[-1]['session']
    assert all(row['text'].startswith("Don't delete Україна\n") for row in rows[:40])
    assert all(row['timestamp'].endswith('+00:00') for row in rows)


def test_file_failure_does_not_break_caller(tmp_path, caplog):
    directory = tmp_path / 'directory'
    directory.mkdir()
    log = conversation_log.ConversationLog(directory)
    log.record('message', text='test')
    log.record('message', text='test again')
    assert caplog.text.count('Conversation log could not be written') == 1


def test_recognition_decision_and_playback_are_distinguishable(tmp_path, monkeypatch):
    path = tmp_path / 'conversation.jsonl'
    monkeypatch.setattr(conversation_log, '_log', conversation_log.ConversationLog(path))
    services = Mock(spec=CommandServices)
    speech = SpeechController(lambda text: PCMClip(b'\0\0', 16000), Mock())
    recognition = Recognition("don't delete that", 0.2, (Hypothesis('delete that', 0.1),))
    listener = ContinuousListener(Mock(), Mock(), lambda *a, **kw: recognition, speech)
    assistant = Assistant(listener, speech, services, speech.submit)
    try:
        result = listener.handle_final(AudioUtterance(b'pcm'))
        assistant.process_recognition(result)
        assert speech.wait(2)
    finally:
        assistant.close()
    rows = entries(path)
    raw = next(row for row in rows if row['event'] == 'recognition')
    assert raw['text'] == recognition.text
    assert raw['confidence'] == 0.2
    assert raw['alternatives'] == [{'text': 'delete that', 'confidence': 0.1}]
    assert not raw['partial']
    assert next(row for row in rows if row['event'] == 'voice_decision')['decision'] == 'clarify'
    assert any(row['event'] == 'speech_queued' and row['role'] == 'jarvis' for row in rows)
    assert any(row['event'] == 'speech_finished' and row['outcome'] == 'completed' for row in rows)
    assert not any(row['event'] == 'command_started' for row in rows)
    assert services.mock_calls == []


def test_cancelled_queue_is_not_logged_as_spoken(tmp_path, monkeypatch):
    path = tmp_path / 'conversation.jsonl'
    monkeypatch.setattr(conversation_log, '_log', conversation_log.ConversationLog(path))
    player = Mock()
    speech = SpeechController(Mock(), player)
    speech.set_input_active(True)
    try:
        job = speech.submit('This response must not play.')
        speech.stop()
        assert job.wait(1)
    finally:
        speech.close()
    rows = entries(path)
    assert rows[-1]['outcome'] in ('cancelled_before_start', 'cancelled')
    assert not any(row['event'] == 'playback_chunk_started' for row in rows)
    player.play.assert_not_called()
