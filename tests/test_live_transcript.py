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


def recognition(uid, text, confidence=None, error=None):
    return ('recognition', {'uid': uid, 'partial': False, 'text': text, 'confidence': confidence, 'error': error})


def started(uid):
    return ('turn_started', {'uid': uid})


def finished(uid, window='active 10s'):
    return ('turn_finished', {'uid': uid, 'window': window})


def test_fast_path_line_has_intent_path_window_and_timings():
    lines = feed([
        ('utterance_ended', {}),
        ('recognition_timing', {'partial': False, 'duration_ms': 900}),
        recognition(1, 'delete my call mom reminder', 0.82), 0.9,
        started(1),
        ('voice_decision', {'decision': 'accept'}),
        ('command_result', {'intent': 'delete_reminder', 'status': 'handled'}),
        ('speech_queued', {'playback_id': 4, 'text': 'Deleted: call mom, today at 9:00 PM.'}),
        finished(1), 0.5,
        ('playback_chunk_started', {'playback_id': 4}),
    ])
    assert lines == ['You (heard): "delete my call mom reminder"  conf 0.82 | intent delete_reminder | fast path'
                     ' | active 10s | stt 0.9s, total 1.4s | Jarvis: "Deleted: call mom, today at 9:00 PM."']


def test_rejected_and_ignored_audio_show_the_reason():
    lines = feed([
        ('recognition_timing', {'partial': False, 'duration_ms': 500}),
        recognition(1, 'yes', 0.56),
        ('voice_filter', {'reason': 'unaddressed_during_playback', 'uid': 1}),
        recognition(2, 'Deli', 0.06),
        started(2), ('voice_decision', {'decision': 'ignore', 'reason': 'no_wake_word'}), finished(2, 'passive'),
        recognition(3, '', error='unrecognized'),
        started(3), ('voice_decision', {'decision': 'ignore', 'reason': 'repeated_unrecognized_audio'}),
        finished(3, 'active 4s'),
        recognition(4, 'hey Google set a timer', 0.55),
        ('voice_filter', {'reason': 'speakers_mode', 'uid': 4}),
    ])
    assert lines == [
        'You (rejected: spoke over Jarvis without "Jarvis"): "yes"  conf 0.56 | stt 0.5s',
        'You (ignored: no wake word): "Deli"  conf 0.06 | passive',
        'You (ignored: unrecognized again): "(unrecognized)"  conf - | active 4s',
        'You (ignored: Jarvis speaking (speakers mode)): "hey Google set a timer"  conf 0.55',
    ]


def test_dialogue_path_shows_why_the_model_was_used():
    lines = feed([
        ('utterance_ended', {}),
        recognition(1, 'Jarvis delete my call Mom reminder', 0.87), 0.8,
        started(1),
        ('dialogue_turn', {'reply': 'Shall I?', 'duration_ms': 800, 'model_called': True,
                           'trigger': 'similar alternatives'}),
        ('speech_queued', {'playback_id': 5, 'text': 'Shall I?'}),
        finished(1), 0.5,
        ('playback_chunk_started', {'playback_id': 5}),
    ])
    assert lines == ['You (heard): "Jarvis delete my call Mom reminder"  conf 0.87 | intent delete_reminder'
                     ' | ChatGPT dialogue (similar alternatives) | active 10s | model 0.8s, total 1.3s'
                     ' | Jarvis: "Shall I?"']


def test_reply_goes_to_its_own_utterance_even_when_the_next_was_heard_first():
    lines = feed([
        recognition(1, 'Jarvis tell me about Finland', 0.95),
        recognition(2, '', error='unrecognized'),    # heard while ChatGPT is thinking
        started(1),
        ('dialogue_turn', {'reply': 'Finland is a Nordic country.', 'duration_ms': 900, 'model_called': True}),
        ('speech_queued', {'playback_id': 7, 'text': 'Finland is a Nordic country.'}),
        ('playback_chunk_started', {'playback_id': 7}),  # may start before the turn ends
        finished(1),
        started(2), ('voice_decision', {'decision': 'ignore', 'reason': 'unrecognized_nothing_pending'}),
        finished(2),
    ])
    assert lines[0].startswith('You (heard): "Jarvis tell me about Finland"')
    assert lines[0].endswith('Jarvis: "Finland is a Nordic country."')
    assert lines[1] == 'You (ignored: unrecognized, nothing pending): "(unrecognized)"  conf - | active 10s'


def test_partials_are_not_shown_and_an_utterance_never_handled_is_reported():
    lines = feed([
        ('recognition', {'partial': True, 'text': 'del', 'confidence': None, 'uid': 9}),
        recognition(1, 'what time is it', 0.9),     # dropped: the queue moved on
        recognition(2, 'thanks', 0.9),
        started(2), ('command_result', {'intent': 'thank'}), finished(2),
    ])
    assert lines[0] == 'You (ignored: not processed (arrived too late)): "what time is it"  conf 0.90'
    assert lines[1].startswith('You (heard): "thanks"')
    assert len(lines) == 2


def test_replies_nobody_asked_for_get_their_own_line():
    lines = feed([('speech_queued', {'playback_id': 3, 'text': 'Sir, this is your reminder: stretch.'})])
    assert lines == ['Jarvis: Sir, this is your reminder: stretch.']


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


def test_answers_to_a_pending_state_show_what_they_answered():
    lines = feed([
        recognition(1, '2 minutes from now', 0.94), started(1),
        ('pending_answer', {'state': 'awaiting time for alarm', 'answer': 'fill'}),
        ('command_result', {'intent': 'alarm', 'status': 'handled'}),
        ('speech_queued', {'playback_id': 2, 'text': 'Alarm set for today at 10:38 AM.'}),
        finished(1),
        ('playback_chunk_started', {'playback_id': 2}),
        recognition(2, 'Jarvis stop', 0.73), started(2),
        ('pending_answer', {'state': 'awaiting time for alarm', 'answer': 'cancel'}),
        ('speech_queued', {'playback_id': 3, 'text': 'Cancelled.'}),
        finished(2),
        ('playback_chunk_started', {'playback_id': 3}),
    ])
    assert lines[0].startswith('You (heard): "2 minutes from now"  conf 0.94 | intent alarm'
                               ' | answer (awaiting time for alarm)')
    assert lines[0].endswith('Jarvis: "Alarm set for today at 10:38 AM."')
    assert ' | cancelled | ' in lines[1] and lines[1].endswith('Jarvis: "Cancelled."')
