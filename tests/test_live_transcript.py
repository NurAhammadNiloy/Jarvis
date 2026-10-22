"""Live transcript lines: one per heard utterance, built from log events."""
from core import conversation_log
from core.live_transcript import LiveTranscript


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def feed(events):
    lines, clock = [], Clock()
    printer = LiveTranscript(out=lines.append, clock=clock)
    for item in events:
        if isinstance(item, (int, float)):
            clock.now += item
        else:
            printer(*item)
    return lines


def recognition(text, confidence=None, error=None):
    return ('recognition', {'partial': False, 'text': text, 'confidence': confidence, 'error': error})


def test_fast_path_line_has_intent_path_and_timings():
    lines = feed([
        ('utterance_ended', {}),
        ('recognition_timing', {'partial': False, 'duration_ms': 900}),
        recognition('delete my call mom reminder', 0.82), 0.9,
        ('voice_decision', {'decision': 'accept'}),
        ('command_result', {'intent': 'delete_reminder', 'status': 'handled'}),
        ('speech_queued', {'playback_id': 4, 'text': 'Deleted: call mom, today at 9:00 PM.'}), 0.5,
        ('playback_chunk_started', {'playback_id': 4}),
    ])
    assert lines == ['You (heard): "delete my call mom reminder"  conf 0.82 | intent delete_reminder | fast path'
                     ' | stt 0.9s, total 1.4s | Jarvis: "Deleted: call mom, today at 9:00 PM."']


def test_rejected_and_ignored_audio_show_the_reason():
    lines = feed([
        ('recognition_timing', {'partial': False, 'duration_ms': 500}),
        recognition('yes', 0.56),
        ('voice_filter', {'reason': 'unaddressed_during_playback'}),
        recognition('Deli', 0.06),
        ('voice_decision', {'decision': 'ignore', 'reason': 'no_wake_word'}),
        recognition('', error='unrecognized'),
        ('voice_decision', {'decision': 'ignore', 'reason': 'repeated_unrecognized_audio'}),
    ])
    assert lines == [
        'You (rejected: spoke over Jarvis without "Jarvis"): "yes"  conf 0.56 | stt 0.5s',
        'You (ignored: no wake word): "Deli"  conf 0.06',
        'You (ignored: unrecognized again): "(unrecognized)"  conf -',
    ]


def test_dialogue_path_shows_why_the_model_was_used():
    lines = feed([
        ('utterance_ended', {}),
        recognition('Jarvis delete my call Mom reminder', 0.87), 0.8,
        ('dialogue_turn', {'reply': 'Shall I?', 'confirmed_query': '', 'duration_ms': 800,
                           'model_called': True, 'trigger': 'repair in progress'}),
        ('speech_queued', {'playback_id': 5, 'text': 'Shall I?'}), 0.5,
        ('playback_chunk_started', {'playback_id': 5}),
    ])
    assert lines == ['You (heard): "Jarvis delete my call Mom reminder"  conf 0.87 | intent delete_reminder'
                     ' | ChatGPT dialogue (repair in progress) | model 0.8s, total 1.3s | Jarvis: "Shall I?"']


def test_partials_are_not_shown_and_a_new_turn_flushes_the_old_one():
    lines = feed([
        ('recognition', {'partial': True, 'text': 'del', 'confidence': None}),
        recognition('what time is it', 0.9),
        recognition('thanks', 0.9),
    ])
    assert [line.split(' | ')[0] for line in lines] == ['You (heard): "what time is it"  conf 0.90']


def test_listener_receives_events_without_a_log_file_and_errors_are_contained():
    seen = []
    conversation_log.add_listener(lambda event, fields: seen.append((event, fields)))
    conversation_log.add_listener(lambda event, fields: 1 / 0)
    try:
        conversation_log.record('recognition', text='hi')
    finally:
        conversation_log._listeners.clear()
    assert seen == [('recognition', {'text': 'hi'})]


def test_setting_turns_transcripts_off(monkeypatch):
    from config import settings
    from core import live_transcript
    monkeypatch.setattr(settings, 'SHOW_TRANSCRIPTS', False)
    assert live_transcript.enable() is None
    monkeypatch.setattr(settings, 'SHOW_TRANSCRIPTS', True)
    try:
        assert live_transcript.enable(out=lambda line: None) is not None
    finally:
        conversation_log._listeners.clear()
