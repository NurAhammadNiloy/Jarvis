"""Regressions from the 22 Oct 2026 voice session (docs/voice-session-2026-10-22.md).

Transcripts, confidences and alternatives are copied from logs/conversation.jsonl.
"""
from datetime import datetime
import threading
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.assistant import Assistant
from core.command_services import CommandServices
from core.command_result import Command
from core.conversation_state import ConversationState, answer_kind, answer_reliable
from core.dialogue import Dialogue
from core.intent_classifier import route
from core.speech_output import PCMClip, SpeechController, SpeechSnapshot
from core.voice_capture import AudioUtterance, Endpointer, VoiceConfig
from core.voice_policy import ConfidenceGate, Hypothesis, Recognition, conflict_reason
from core.voice_runtime import ContinuousListener


def heard(text, confidence, *alternatives):
    return Recognition(text, confidence, tuple(Hypothesis(t, c) for t, c in alternatives))


# Exactly as recognized in the session.
YES = heard('yes', 0.5571546, ('yesss', 0.5571546), ('yessss', 0.5571546), ('yess', 0.5571546),
            ('yesssss', 0.5571546))
YES_DO_IT = heard('yes do it', 0.86252826, ('just do it', 0.66811371), ('yesss do it', 0.86252826),
                  ('yess do it', 0.86252826), ('yes to it', 0.82491493))
YES_PLEASE = heard('yes please', 0.87025976)
YES_PLEASE_2 = heard('yes please', 0.89210927)
DELETE = heard('Jarvis delete my call Mom reminder', 0.87481689,
               ('Jarvis delete my call Mam reminder', 0.87481689), ('Yarvis delete my call Mom reminder', 0.87481689),
               ('Jarvis delete my call momm reminder', 0.87481689), ('Jarvis delete my call mome reminder', 0.87481689))
DELETE_POLITE = heard('Jarvis can you delete my call Mom reminder', 0.82668012,
                      ('Jarvis can you delete my call Mam reminder', 0.82668012),
                      ('Jarvis can you delete my call momm reminder', 0.82668012),
                      ('Yarvis can you delete my call Mom reminder', 0.82668012),
                      ('Jarvis can you delete my call mome reminder', 0.82668012))
DEFINITION = heard('definition', 0.084044158, ('vision', 0.12234839), ('defination', 0.084044158))
# The same misheard turn addressed to Jarvis: without the wake word, 0.08 is now ignored.
ADDRESSED_DEFINITION = heard('Jarvis definition', 0.084044158, ('Jarvis vision', 0.12234839),
                             ('Jarvis defination', 0.084044158))
ALARM_OVER_JARVIS = heard('set an alarm for 6:30 a.m.', 0.87636822,
                          ('what do you want me to set an alarm for 6:30 a.m.', 0.68531543),
                          ('set an alarm for 6:30 tomorrow morning', 0.66481829))
SHALL_I = "I have: delete reminder 'call Mom'. Shall I do that?"


# --- answers to "Shall I do that?" ----------------------------------------------

DELETE_MOM = Command('delete_reminder', 'delete my call Mom reminder', {'target': 'call mom'})


def awaiting_delete():
    state = ConversationState(clock=lambda: 0)
    state.confirm(DELETE_MOM, SHALL_I)
    return state


@pytest.mark.parametrize('answer', [YES, YES_DO_IT, YES_PLEASE, YES_PLEASE_2])
def test_every_logged_yes_confirms(answer):
    assert answer_kind(answer.text) == 'yes'
    assert answer_reliable(answer, 'yes')
    decided = awaiting_delete().check(answer, answer.text)
    assert decided.kind == 'execute' and decided.command == DELETE_MOM


@pytest.mark.parametrize('text, kind', [
    ('go ahead', 'yes'), ('yeah', 'yes'), ('ok', 'yes'), ("that's right", 'yes'), ('sure, do it', 'yes'),
    ('no', 'no'), ('nope', 'no'), ('no thanks', 'no'), ("don't", 'no'),
    ('cancel', 'cancel'), ('never mind', 'cancel'), ('forget it', 'cancel'),
    ('thank you', None), ('please', None), ('is that right', None), ('yes delete the dentist one', None),
    ('no yes', None),
])
def test_answer_kinds(text, kind):
    assert answer_kind(text) == kind


@pytest.mark.parametrize('recognition', [
    Recognition('yes', 0.3), Recognition('yes'), heard('yes', 0.95, ('no', 0.9)), heard('yes', 0.6, ('yes no', 0.6)),
])
def test_weak_or_contradicted_yes_still_does_not_confirm(recognition):
    state = awaiting_delete()
    assert state.check(recognition, recognition.text).kind == 'reply'
    assert state.current.command == DELETE_MOM


def test_yes_to_a_model_question_goes_back_to_the_model():
    resolver = Mock(side_effect=[{'reply': 'Would you like to set an alarm for 6:30 AM?', 'query': None},
                                 {'reply': 'Ready', 'query': 'set an alarm for 6:30 am'}])
    dialogue = Dialogue(resolver, clock=lambda: 0)
    dialogue.turn(heard('wake up at 6:30', 0.19501866, ('wake up', 0.28538975)), reason='unclear')
    turn = dialogue.turn(YES_PLEASE)
    assert turn.proposal == 'set an alarm for 6:30 am'  # the assistant asks for its own "yes"
    assert resolver.call_count == 2


# --- the gate: spelling variants are not a different request ----------------------

def test_wake_word_and_stretched_letter_variants_do_not_conflict():
    assert conflict_reason(YES, important=True) is None
    assert conflict_reason(heard('Jarvis delete my call Mom reminder', 0.87,
                                 ('Yarvis delete my call Mom reminder', 0.87),
                                 ('Jarvis delete my call momm reminder', 0.87)), important=True) is None


def test_name_variants_are_a_wording_conflict_but_meaning_conflicts_stay():
    assert conflict_reason(DELETE, important=True) == 'wording'
    assert conflict_reason(heard('cancel timer', 0.9, ("don't cancel timer", 0.9)), important=True) == 'meaning'
    assert conflict_reason(heard('set timer for 5 minutes', 0.9, ('set timer for 9 minutes', 0.9))) == 'meaning'
    assert ConfidenceGate(lambda: 0).assess(DELETE, text='delete my call Mom reminder').reason == 'wording'


# --- the whole delete flow, through the assistant ---------------------------------

TZ = ZoneInfo('Europe/Helsinki')


@pytest.fixture
def assistant_with_reminder(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    now = lambda: datetime(2026, 10, 22, 9, 50, tzinfo=TZ)
    reminders = ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=now)
    reminders.create({'task': 'call mom', 'due': datetime(2026, 10, 22, 21, 0, tzinfo=TZ)})
    services = CommandServices(Mock(), reminders=reminders, now=now)
    resolver = Mock(return_value={'reply': 'Could you clarify what you need a definition for?', 'query': None})
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = False
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0,
                          dialogue=Dialogue(resolver, clock=lambda: 0))
    return assistant, reminders, resolver, output


@pytest.mark.parametrize('command, answer', [(DELETE, YES), (DELETE, YES_DO_IT), (DELETE_POLITE, YES_PLEASE)])
def test_logged_delete_is_confirmed_once_and_deletes(assistant_with_reminder, command, answer):
    assistant, reminders, resolver, output = assistant_with_reminder
    assistant.process_recognition(ADDRESSED_DEFINITION)  # the misheard turn that started a repair
    assert resolver.call_count == 1
    assistant.process_recognition(command)
    output.assert_called_with('Delete the call mom reminder?')
    assert resolver.call_count == 1  # name variants are confirmed without ChatGPT
    assistant.process_recognition(answer)
    output.assert_called_with('Deleted: call mom, today at 9:00 PM.')
    assert reminders.store.pending() == []
    assert resolver.call_count == 1


def test_clear_command_during_a_repair_takes_the_fast_path(assistant_with_reminder):
    assistant, reminders, resolver, output = assistant_with_reminder
    assistant.process_recognition(ADDRESSED_DEFINITION)
    assistant.process_recognition(Recognition('delete my call mom reminder', 0.95))
    output.assert_called_with('Deleted: call mom, today at 9:00 PM.')
    assert resolver.call_count == 1
    assert not assistant.state.pending


# --- answers that overlapped Jarvis's own voice --------------------------------------

def listener_returning(recognition, echo_mode='headset'):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot()
    return ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: recognition, speech,
                              VoiceConfig(echo_mode=echo_mode))


@pytest.mark.parametrize('answer', [YES, YES_PLEASE, YES_PLEASE_2,
                                    heard('delete my call Mom reminder', 0.95281059)])
def test_answer_spoken_after_jarvis_stopped_is_kept(answer):
    utterance = AudioUtterance(b'pcm', playback_id=5, playback_text=SHALL_I, voiced_after_playback_ms=1700)
    result = listener_returning(answer).handle_final(utterance)
    assert result is not None and result.text == answer.text and result.playback_id is None


def test_speech_entirely_over_jarvis_is_still_rejected():
    utterance = AudioUtterance(b'pcm', playback_id=10, playback_text='Would you like to set an alarm for 6:30 AM?',
                               voiced_after_playback_ms=0)
    assert listener_returning(ALARM_OVER_JARVIS).handle_final(utterance) is None


def test_unrecognized_audio_after_playback_is_still_dropped():
    utterance = AudioUtterance(b'pcm', playback_id=5, playback_text=SHALL_I, voiced_after_playback_ms=2000)
    assert listener_returning(Recognition(error='unrecognized')).handle_final(utterance) is None


def test_endpointer_measures_speech_after_playback_stops():
    config = VoiceConfig()
    endpoint = Endpointer(config)
    frame = b'\0' * config.frame_bytes
    result = None
    for _ in range(50):   # 1 s: Jarvis audible, its echo opens the detector
        result = endpoint.push(frame, True, playback_id=5, playback_text=SHALL_I) or result
    for _ in range(25):   # 0.5 s: you answer after Jarvis stopped
        result = endpoint.push(frame, True) or result
    for _ in range(80):   # silence ends the utterance
        result = endpoint.push(frame, False) or result
    assert result.playback_id == 5
    assert result.voiced_after_playback_ms == 500


def test_endpointer_reports_no_after_speech_for_pure_overlap():
    config = VoiceConfig()
    endpoint = Endpointer(config)
    frame = b'\0' * config.frame_bytes
    result = None
    for _ in range(50):
        result = endpoint.push(frame, True, playback_id=10, playback_text='Would you like...') or result
    for _ in range(80):
        result = endpoint.push(frame, False) or result
    assert result.playback_id == 10 and result.voiced_after_playback_ms == 0


# --- routing gaps from the session ------------------------------------------------

def test_wake_up_at_is_an_alarm():
    assert route('wake up at 6:30').intent == 'alarm'
    assert route('Jarvis, wake up at 6:30').intent == 'alarm'
    assert route('I wake up at 6:30 every day').intent == 'chat'


def test_quoted_reminder_name_from_a_model_proposal_is_the_target():
    assert route("delete reminder 'call Mom'").fields == {'target': 'call mom'}
    assert route('delete the reminder "dentist"').fields == {'target': 'dentist'}


# --- latency quick wins ------------------------------------------------------------

def test_reply_is_not_held_forever_by_a_busy_microphone():
    played = threading.Event()
    player = Mock()
    player.play.side_effect = lambda clip, cancelled: played.set()
    output = SpeechController(lambda text: PCMClip(b'\0' * 960, 24000), player, max_input_wait=0.2)
    try:
        output.set_input_active(True)  # e.g. echo keeps the detector open
        output.submit('At your service, sir.')
        assert played.wait(2)
    finally:
        output.close()


def test_no_barge_in_recognition_while_jarvis_is_silent():
    import queue

    class Frames:
        def __init__(self):
            self.frames = queue.Queue()
            for _ in range(60):
                self.frames.put(b'\1' * 640)

        def __enter__(self):
            return self

        def read(self, timeout=0.1):
            try:
                return self.frames.get(timeout=timeout)
            except queue.Empty:
                return None

        def __exit__(self, *args):
            pass

    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot(1, 'Preparing response', False)
    calls = []
    listener = ContinuousListener(Frames(), lambda f: f[0] == 1,
                                  lambda pcm, partial=False: calls.append(partial) or Recognition('x', 0.9), speech)
    try:
        listener.listen(timeout=0.5)
    finally:
        listener.close()
    assert True not in calls


def test_a_reply_waits_at_most_1_5_seconds_for_a_busy_microphone():
    # 193aa5d4: replies were held 2.1 s and 3.0 s (8.6 s over five replies) because the
    # detector stayed open on noise.
    output = SpeechController(lambda text: PCMClip(b'\0' * 960, 24000), Mock())
    try:
        assert output.max_input_wait == 1.5
    finally:
        output.close()
