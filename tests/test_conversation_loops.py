"""Conversation loops from the second 22 Oct 2026 voice run (session 0a4a1722...).

Transcripts, confidences and alternatives are copied from logs/conversation.jsonl;
the clock is frozen at the time of the alarm attempts (10:36:09, Helsinki).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core import conversation_log
from core.assistant import Assistant
from core.command_services import CommandServices
from core.dialogue import Dialogue
from core.live_transcript import LiveTranscript
from core.voice_policy import Hypothesis, Recognition, conflict_reason


def heard(text, confidence, *alternatives):
    return Recognition(text, confidence, tuple(Hypothesis(t, c) for t, c in alternatives))


# Exactly as recognized in the session (sequence numbers from the log).
ALARM_FULL = heard('Jarvis set an alarm for 2 minutes from now', 0.9395082,              # 221
                   ('Yarvis set an alarm for 2 minutes from now', 0.9395082))
SET_ALARM = heard('set an alarm', 0.98379922)                                             # 273
TWO_MINUTES = heard('2 minutes from now', 0.93844938)                                     # 248
AFTER_TWO_MINUTES = heard('after 2 minutes from now', 0.92299557)                         # 294
AFTER_TWO_MINUTES_ON = heard('after 2 minutes from now on', 0.86714858)                   # 339
STRETCH = heard('remind me to stretch in 2 minutes', 0.94240671,                          # 50
                ('remind me to strech in 2 minutes', 0.94240671))
SHALL_I_YES = heard('shall I do that yes', 0.66736883, ('yes', 0.73953891),                # 69
                    ('shall I do that yesss', 0.66736883), ('should I do that yes', 0.56713855))
YES_DO_IT = heard('yes do it', 0.86605543, ('shall I do that yes do it', 0.72870833),       # 89
                  ('yesss do it', 0.86605543), ('yess do it', 0.86605543))
YES = heard('yes', 0.61275631, ('yesss', 0.61275631), ('yessss', 0.61275631),             # 362
            ('yess', 0.61275631))
JARVIS_STOP = heard('Jarvis stop', 0.72958487, ('Jarvis stopped', 0.72958487),             # 423
                    ('Jarvis stahp', 0.72958487), ('Yarvis stop', 0.72958487))
STOP = heard('stop', 0.91)
NOISE = Recognition(error='unrecognized')                                                 # 138, 177, 442
DEFINITION = heard('definition', 0.084044158, ('vision', 0.12234839), ('defination', 0.084044158))

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 10, 36, 9, tzinfo=TZ)
IN_TWO_MINUTES = NOW + timedelta(minutes=2)
ALARM_PROPOSAL = {'reply': 'Setting an alarm.', 'query': 'set an alarm for 2 minutes from now'}  # 340


@pytest.fixture
def jarvis(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    reminders = ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=lambda: NOW)
    services = CommandServices(Mock(), reminders=reminders, now=lambda: NOW)
    resolver = Mock(return_value={'reply': 'Could you say that again?', 'query': None})
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = False
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0,
                          dialogue=Dialogue(resolver, clock=lambda: 0))
    return SimpleNamespace(
        hear=assistant.process_recognition, assistant=assistant, resolver=resolver, output=output, speech=speech,
        said=lambda: [call.args[0] for call in output.call_args_list],
        pending=lambda: [(r.kind, r.due) for r in reminders.store.pending()])


def asked_a_question(jarvis):
    return any(line.rstrip().endswith('?') for line in jarvis.said())


# --- alarms with relative times -------------------------------------------------------

def test_full_alarm_request_sets_the_alarm_without_a_question(jarvis):
    jarvis.hear(ALARM_FULL)
    assert jarvis.pending() == [('alarm', IN_TWO_MINUTES)]
    assert jarvis.said() == ['Alarm set for today at 10:38 AM.']
    jarvis.resolver.assert_not_called()


@pytest.mark.parametrize('answer', [TWO_MINUTES, AFTER_TWO_MINUTES])
def test_time_answer_completes_the_alarm_instead_of_starting_a_new_request(jarvis, answer):
    jarvis.hear(SET_ALARM)
    assert jarvis.said() == ['What time should I set the alarm for?']
    jarvis.hear(answer)
    assert jarvis.pending() == [('alarm', IN_TWO_MINUTES)]
    assert jarvis.said()[-1] == 'Alarm set for today at 10:38 AM.'
    jarvis.resolver.assert_not_called()


def test_confirmed_proposal_executes_its_parsed_values_without_asking_again(jarvis):
    jarvis.resolver.return_value = ALARM_PROPOSAL
    jarvis.hear(AFTER_TWO_MINUTES_ON)  # idle: conversation, so the model proposes
    assert jarvis.said() == ['I have: set an alarm for 2 minutes from now. Shall I do that?']
    jarvis.hear(YES)
    assert jarvis.pending() == [('alarm', IN_TWO_MINUTES)]
    assert jarvis.said()[-1] == 'Alarm set for today at 10:38 AM.'
    assert jarvis.resolver.call_count == 1


# --- a clear reminder is not "unclear audio" --------------------------------------------

def test_reminder_with_a_spelling_variant_takes_the_fast_path(jarvis):
    jarvis.hear(STRETCH)
    assert jarvis.said() == ['Reminder set for today at 10:38 AM: stretch.']
    assert jarvis.pending() == [('reminder', IN_TWO_MINUTES)]
    jarvis.resolver.assert_not_called()


def test_spelling_variants_are_not_a_conflict_but_names_and_meridiem_are():
    # Why 0.94 was "unclear audio": 'stretch' / 'strech' counted as different wording.
    assert conflict_reason(STRETCH, important=True) is None
    assert conflict_reason(heard('remind me to call Mom', 0.9, ('remind me to call Mam', 0.9)), important=True) == 'wording'
    assert conflict_reason(heard('set an alarm at 7 am', 0.9, ('set an alarm at 7 pm', 0.9)), important=True) == 'wording'
    assert conflict_reason(heard('in 2 minutes', 0.9, ('in 3 minutes', 0.9)), important=True) == 'meaning'


# --- confirmation in any dialogue state -----------------------------------------------

def propose_fresh(jarvis):
    jarvis.resolver.side_effect = [ALARM_PROPOSAL]
    jarvis.hear(AFTER_TWO_MINUTES_ON)


def propose_during_repair(jarvis):
    # The misheard turn starts a repair; the model asks, then proposes.
    jarvis.resolver.side_effect = [{'reply': 'What do you need a definition for?', 'query': None},
                                   ALARM_PROPOSAL]
    jarvis.hear(DEFINITION)
    jarvis.hear(AFTER_TWO_MINUTES_ON)


def propose_then_unclear_answer(jarvis):
    jarvis.resolver.side_effect = [ALARM_PROPOSAL]
    jarvis.hear(AFTER_TWO_MINUTES_ON)
    jarvis.hear(heard('yes', 0.3))  # too weak to act on: asked again, still pending


@pytest.mark.parametrize('setup', [propose_fresh, propose_during_repair, propose_then_unclear_answer])
@pytest.mark.parametrize('answer', [YES_DO_IT, SHALL_I_YES, YES], ids=['yes do it', 'shall I do that yes', 'yes'])
def test_yes_confirms_a_pending_proposal_in_any_state(jarvis, setup, answer):
    setup(jarvis)
    assert jarvis.pending() == []
    calls = jarvis.resolver.call_count
    jarvis.hear(answer)
    assert jarvis.pending() == [('alarm', IN_TWO_MINUTES)]
    assert jarvis.said()[-1] == 'Alarm set for today at 10:38 AM.'
    assert jarvis.resolver.call_count == calls


def test_reprompt_for_an_unclear_answer_does_not_contain_yes(jarvis):
    # "Please say yes again..." made the echo filter drop the next real "yes" (seq 110).
    propose_fresh(jarvis)
    jarvis.hear(heard('yes', 0.3))
    assert 'yes' not in jarvis.said()[-1].lower().split()


# --- stop / cancel while something is pending ----------------------------------------

def pending_confirmation(jarvis):
    propose_fresh(jarvis)


def pending_time(jarvis):
    jarvis.hear(SET_ALARM)


@pytest.mark.parametrize('setup', [pending_confirmation, pending_time])
@pytest.mark.parametrize('stop', [JARVIS_STOP, STOP], ids=['Jarvis stop', 'stop'])
def test_stop_cancels_whatever_is_pending_without_the_model(jarvis, setup, stop):
    setup(jarvis)
    calls = jarvis.resolver.call_count
    jarvis.hear(stop)
    assert jarvis.said()[-1] == 'Cancelled.'
    assert jarvis.resolver.call_count == calls
    jarvis.speech.stop.assert_called()
    jarvis.hear(YES)  # nothing left to confirm
    jarvis.hear(TWO_MINUTES)  # nor to complete
    assert jarvis.pending() == []


def test_jarvis_stop_with_nothing_pending_only_stops_speech(jarvis):
    jarvis.hear(JARVIS_STOP)
    jarvis.resolver.assert_not_called()
    jarvis.output.assert_not_called()
    jarvis.speech.stop.assert_called()


# --- the conversation state ------------------------------------------------------

def test_slot_answer_can_ask_the_next_question(jarvis):
    jarvis.hear(heard('set an alarm at 6', 0.95))
    assert jarvis.said() == ['Did you mean 6 a.m. or p.m.?']
    assert jarvis.assistant.state.current.describe() == 'awaiting time for alarm'
    jarvis.hear(heard('p.m.', 0.9))
    assert jarvis.pending() == [('alarm', NOW.replace(hour=18, minute=0, second=0))]
    assert not jarvis.assistant.state.pending


def test_slot_answer_that_is_a_request_of_its_own_runs_as_a_new_request(jarvis):
    jarvis.hear(SET_ALARM)
    jarvis.hear(heard('what time is it', 0.95))
    assert jarvis.said()[-1].startswith('The current time is')
    assert not jarvis.assistant.state.pending
    assert jarvis.pending() == []


def test_proposal_without_a_time_asks_for_it_instead_of_shall_i(jarvis):
    jarvis.resolver.return_value = {'reply': 'Sure.', 'query': 'set an alarm'}
    jarvis.hear(heard('I need to get up early', 0.95))
    assert jarvis.said() == ['What time should I set the alarm for?']
    jarvis.hear(heard('at 7 am', 0.95))
    assert jarvis.pending() == [('alarm', (NOW + timedelta(days=1)).replace(hour=7, minute=0, second=0))]


# --- unrecognized audio ---------------------------------------------------------------

def test_unrecognized_audio_with_nothing_pending_is_ignored_silently(jarvis):
    for _ in range(3):
        assert not jarvis.hear(NOISE)
    jarvis.output.assert_not_called()
    jarvis.resolver.assert_not_called()


@pytest.mark.parametrize('setup', [pending_confirmation, pending_time])
def test_unrecognized_audio_while_waiting_says_so(jarvis, setup):
    setup(jarvis)
    jarvis.hear(NOISE)
    assert jarvis.said()[-1].startswith("I couldn't hear that.")


# --- the terminal -------------------------------------------------------------------

def test_each_reply_is_printed_exactly_once(monkeypatch, capsys):
    from core import speech_synthesis, live_transcript

    class Controller:
        jobs = 0

        def submit(self, text, **kwargs):
            Controller.jobs += 1
            conversation_log.record('speech_queued', role='jarvis', text=text, playback_id=Controller.jobs)
            conversation_log.record('playback_chunk_started', playback_id=Controller.jobs, text=text)

    monkeypatch.setattr(speech_synthesis, 'get_speech_controller', Controller)
    monkeypatch.setattr('config.settings.SHOW_TRANSCRIPTS', True)
    monkeypatch.setattr(live_transcript, '_printer', None, raising=False)  # restored afterwards
    printer = live_transcript.enable(out=print)
    try:
        conversation_log.record('recognition', role='user', partial=False, text='set an alarm',
                                confidence=0.98, error=None)
        conversation_log.record('voice_decision', decision='accept', text='set an alarm')
        conversation_log.record('command_result', intent='alarm', status='pending')
        speech_synthesis.synthesize_speech('What time should I set the alarm for?')
        speech_synthesis.synthesize_speech('Sir, this is your reminder: stretch.')  # not tied to a turn
    finally:
        conversation_log.remove_listener(printer)
    out = capsys.readouterr().out
    assert out.count('What time should I set the alarm for?') == 1
    assert out.count('Sir, this is your reminder: stretch.') == 1
