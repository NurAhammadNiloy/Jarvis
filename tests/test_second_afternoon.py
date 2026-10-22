"""Small fixes from the 22 Oct 2026 voice session at 14:15 (session 7ec39fa2).

Transcripts, confidences and alternatives are copied exactly from logs/conversation.jsonl.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.assistant import Assistant
from core.command_services import CommandServices
from core.dialogue import Dialogue
from core.intent_classifier import route
from core.voice_policy import Hypothesis, Recognition


def heard(text, confidence, *alternatives):
    return Recognition(text, confidence, tuple(Hypothesis(t, c) for t, c in alternatives))


START_TEA = heard('set a timer for 10 minutes called tea', 0.90885532)                                # 74
ADD_TEA = heard('add 5 minutes to the tea timer', 0.93885165)                                          # 98
ADD_MORE_2 = heard('Jarvis add more 2 minutes on the timer', 0.7144047)                                # 281
CANCEL_MORE = heard('Jarvis can you cancel that more 5 minutes on the timer', 0.87768292,              # 191
                    ('Yarvis can you cancel that more 5 minutes on the timer', 0.87768292))
CANCEL_EXTRA = heard("Jarvis cancel extra 5 minutes on T timer don't cancel the full tea timer", 0.79916698,   # 227
                     ("Jarvis cancel extra 5 minutes on tea timer don't cancel the full tea timer", 0.8108328),
                     ("Jarvis cancel extra 5 minutes on tee timer don't cancel the full tea timer", 0.79916698),
                     ("Jarvis cancel extra 5 minutes on tea timer don't cancel the full T timer", 0.79535496),
                     ("Jarvis cancel extra 5 minutes on the timer don't cancel the full tea timer", 0.79687208))
NOT_THE_TIMER = heard('not the tea timer cancel extra 5 minutes on tea timer', 0.7955513,              # 221
                      ('not the tea timer cancel extra 5 minutes on T timer', 0.76817191),
                      ('not the tea timer cancel extra 5 minutes on tee timer', 0.76817191),
                      ('knot the tea timer cancel extra 5 minutes on tea timer', 0.7955513),
                      ('not the tea timer cancel extra 5 minutes on the timer', 0.74079043))
CANCEL_2_MORE = heard('Jarvis can you cancel that 2 minute more', 0.73690027,                           # 309
                      ('Jarvis can you cancel the 2 minute more', 0.80960816),
                      ('Jarvis can you cancel that 2 minutes more', 0.66010988),
                      ('Yarvis can you cancel that 2 minute more', 0.73690027),
                      ('Jarvis can you cancel that 2 minute mode', 0.69585526))
CANCEL_2_MORE_TEA = heard('cancel that 2 minute more on tea timer', 0.82606071,                         # 333
                          ('cancel that 2 minutes more on tea timer', 0.75395304),
                          ('cancel that 2 minute more on T timer', 0.79163831),
                          ('cancel that 2 minute more on tee timer', 0.79163831),
                          ('cancel that 2 minutes more on T timer', 0.7201575))
CANCEL_TEA = heard('Jarvis cancel the tea timer', 0.85065591)                                          # 410
CANCEL_COFFEE = heard('Jarvis can you cancel coffee timer', 0.90695399)                                # 480

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 14, 20, tzinfo=TZ)


@pytest.fixture
def jarvis(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    reminders = ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=lambda: NOW)
    services = CommandServices(Mock(), reminders=reminders, now=lambda: NOW)
    resolver = Mock(return_value={'reply': 'Could you say that again?', 'query': None})
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = False
    now = [0.0]
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: now[0],
                          dialogue=Dialogue(resolver, clock=lambda: now[0]))
    yield SimpleNamespace(
        hear=assistant.process_recognition, assistant=assistant, now=now, services=services,
        said=lambda: [call.args[0] for call in output.call_args_list],
        timers=lambda: {t.label: t for t in services.timers.active_timers()},
        reminders=lambda: [(r.kind, r.text, r.recurrence) for r in reminders.store.pending()])
    services.timers.cancel_all_timers(respond=lambda message: None)


def minutes(jarvis, label='Tea'):
    return jarvis.timers()[label].duration_seconds / 60


# --- removing added time is not cancelling the timer ----------------------------------------

@pytest.mark.parametrize('utterance, intent', [
    ('can you cancel that more 5 minutes on the timer', 'remove_timer_time'),                       # 191
    ("cancel extra 5 minutes on T timer don't cancel the full tea timer", 'remove_timer_time'),   # 227
    ('not the tea timer cancel extra 5 minutes on tea timer', 'remove_timer_time'),                # 221
    ('can you cancel that 2 minute more', 'remove_timer_time'),                                    # 309
    ('cancel that 2 minute more on tea timer', 'remove_timer_time'),                               # 333
    ('remove that extra 5 minutes on the tea timer', 'remove_timer_time'),
    ('take off 5 minutes', 'remove_timer_time'),
    ('take 5 minutes off the tea timer', 'remove_timer_time'),
    ('remove 5 minutes from the pasta timer', 'remove_timer_time'),
    ('subtract 3 minutes from the timer', 'remove_timer_time'),
    ('cancel the extra time on the tea timer', 'remove_timer_time'),
    # still cancelling the timer
    ('cancel the tea timer', 'cancel_timer'),
    ('cancel the 5 minute timer', 'cancel_timer'),
    ('remove the 5 minutes timer', 'cancel_timer'),
    ('stop the timer', 'cancel_timer'),
    ('cancel all timers', 'cancel_all_timers'),
    ('add 5 minutes to the tea timer', 'add_timer_time'),
])
def test_routing(utterance, intent):
    assert route(utterance).intent == intent


def test_removing_the_extra_minutes_right_after_adding_them_is_an_undo(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(ADD_TEA)
    assert minutes(jarvis) == 15
    jarvis.now[0] += 20
    jarvis.hear(CANCEL_MORE)                                                                       # 191
    assert minutes(jarvis) == 10
    assert jarvis.said()[-1] == 'Undone.'


def test_removing_extra_time_later_subtracts_it_and_keeps_the_timer(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(ADD_TEA)
    jarvis.now[0] += 120
    jarvis.hear(CANCEL_EXTRA)                                                                      # 227
    assert minutes(jarvis) == 10
    assert 'Tea' in jarvis.timers() and jarvis.said()[-1] in ('Took 5 minutes off tea.', 'tea: 5 minutes less.',
                                                               'Tea: 5 minutes less.')


def test_a_different_amount_is_subtracted_not_undone(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(ADD_MORE_2)                                                                        # 2 minutes more
    assert minutes(jarvis) == 12
    jarvis.hear(CANCEL_MORE)                                                                       # 5 minutes, not 2
    assert minutes(jarvis) == 7
    assert 'Undone.' not in jarvis.said()


def test_cancel_that_2_minute_more_removes_those_two_minutes(jarvis):
    jarvis.hear(START_TEA)
    jarvis.now[0] += 100
    jarvis.hear(ADD_MORE_2)
    jarvis.now[0] += 100                                                                           # too late to undo
    jarvis.hear(CANCEL_2_MORE)                                                                     # 309
    assert minutes(jarvis) == 10 and 'Tea' in jarvis.timers()
    jarvis.hear(ADD_MORE_2)
    jarvis.now[0] += 100
    jarvis.hear(CANCEL_2_MORE_TEA)                                                                 # 333
    assert minutes(jarvis) == 10 and 'Tea' in jarvis.timers()


def test_removing_more_than_is_left_never_cancels_the_timer(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(heard('take off 20 minutes', 0.9))
    assert minutes(jarvis) == 10 and jarvis.said()[-1].startswith('Only ')


def test_removed_time_can_be_undone(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(heard('take off 3 minutes', 0.9))
    assert minutes(jarvis) == 7
    jarvis.hear(heard('undo', 0.9))
    assert minutes(jarvis) == 10


# --- "don't cancel" never cancels -----------------------------------------------------------

@pytest.mark.parametrize('utterance', ["don't cancel the tea timer", 'do not cancel the timer',
                                       'cancel the tea timer, not the timer', 'never cancel the tea timer'])
def test_dont_cancel_never_cancels_a_timer(jarvis, utterance):
    jarvis.hear(START_TEA)
    jarvis.hear(heard('Jarvis ' + utterance, 0.9))
    assert 'Tea' in jarvis.timers()
    from core.command_engine import execute_query
    assert execute_query(utterance, jarvis.services).messages[0] in ("Okay, I won't cancel it.", 'Okay, leaving it.')
    assert 'Tea' in jarvis.timers()


def test_not_the_tea_timer_cancel_extra_minutes_keeps_the_timer(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(NOT_THE_TIMER)                                                                     # 221
    assert 'Tea' in jarvis.timers()


# --- the first cancel of a session says how to undo it --------------------------------------

def test_first_cancel_or_delete_says_how_to_undo_it_once(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(CANCEL_TEA)
    assert jarvis.said()[-1].endswith(' Say undo to bring it back.')
    jarvis.hear(heard('set a timer for 5 minutes called coffee', 0.81986362))
    jarvis.hear(CANCEL_COFFEE)
    assert not jarvis.said()[-1].endswith('Say undo to bring it back.')
    assert jarvis.said()[-1] != ''


def test_hint_is_not_wasted_on_a_cancel_that_did_nothing(jarvis):
    jarvis.hear(CANCEL_TEA)                                                                        # no such timer
    assert 'undo' not in jarvis.said()[-1]
    jarvis.hear(START_TEA)
    jarvis.hear(CANCEL_TEA)
    assert jarvis.said()[-1].endswith('Say undo to bring it back.')


# --- "at 10 minutes" is "in 10 minutes" ---------------------------------------------------

AT_TEN_MINUTES = heard('Jarvis remind me to call my mom at 10 minutes', 0.92150974,                     # 533
                       ('Yarvis remind me to call my mom at 10 minutes', 0.92150974))


def test_reminder_at_10_minutes_is_in_10_minutes(jarvis):
    jarvis.hear(AT_TEN_MINUTES)
    (kind, text, _), = jarvis.reminders()
    assert text == 'call my mom'                                    # not "call my mom minutes"
    assert jarvis.services.reminders.store.pending()[0].due.astimezone(TZ).replace(tzinfo=None) == datetime(2026, 10, 22, 14, 30)
    assert jarvis.said()[-1] == 'Done, reminding you at 2:30 PM: call my mom.'


@pytest.mark.parametrize('request_, hour, minute, task', [
    ('remind me to stretch at 2 hours', 16, 20, 'stretch'),
    ('remind me to call mom at 10 minutes from now', 14, 30, 'call mom'),
    ('remind me to call mom in 10 minutes', 14, 30, 'call mom'),
    ('set an alarm at 10 minutes', 14, 30, None),
    ('remind me to call mom at 10 pm', 22, 0, 'call mom'),                  # a unit-less "at 10" stays a clock time
    ('remind me to call mom at 10', 10, 0, 'call mom'),
])
def test_at_with_a_unit_is_relative_without_one_it_is_a_clock_time(request_, hour, minute, task):
    from core.reminder_parser import parse_reminder
    parsed = parse_reminder(request_, NOW)
    assert (parsed.due.hour, parsed.due.minute) == (hour, minute) and parsed.task == task
