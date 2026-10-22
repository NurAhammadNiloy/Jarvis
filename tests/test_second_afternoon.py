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


# --- cancel all (the) reminders ---------------------------------------------------------------

CANCEL_ALL = heard('Jarvis cancel all the reminders', 0.87971485,                                       # 681
                   ('Yarvis cancel all the reminders', 0.87971485), ('where is cancel all the reminders', 0.7235834))
EVERYTHING = heard('everything', 0.74927092, ('everthing', 0.74927092), ('everyting', 0.74927092))      # 729
ALL_OF_THEM = heard('all of them', 0.8941285)                                                           # 792
DELETE_ALL_BEFORE = heard('delete all of them before', 0.90412074,                                      # 862
                          ('delete all of them the phone', 0.84785175), ('delete all of them the four', 0.90167409),
                          ('delete all of them Tha phone', 0.84785175), ('delete all of them the 4:00', 0.80462366))
SESSION_REMINDERS = ('call my Mom', 'delete my old emails', 'call my mom minutes', 'stand up')


@pytest.fixture
def four(jarvis):
    """The four reminders of the 14:15 session (an alarm is added by the tests that need one)."""
    for index, task in enumerate(SESSION_REMINDERS):
        jarvis.services.reminders.create({'task': task, 'due': NOW.replace(hour=15 + index)})
    return jarvis


def pending_tasks(jarvis):
    return [text for _, text, _ in jarvis.reminders()]


def test_cancel_all_the_reminders_cancels_them_all_and_can_be_undone(four):
    four.hear(CANCEL_ALL)
    assert four.said()[-1] == 'All 4 reminders cancelled. Say undo to bring it back.'
    assert pending_tasks(four) == []
    four.hear(heard('undo', 0.9))
    assert four.said()[-1] == 'Undone.' and pending_tasks(four) == list(SESSION_REMINDERS)


@pytest.mark.parametrize('answer', [EVERYTHING, ALL_OF_THEM, DELETE_ALL_BEFORE, heard('all', 0.8)])
def test_all_answers_to_which_one_cancel_everything(four, answer):
    four.hear(heard('Jarvis delete a reminder', 0.9))
    assert 'Which one should I delete?' in four.said()[-1] and four.assistant.state.pending
    four.hear(answer)
    assert four.said()[-1].startswith('All 4 reminders cancelled.')
    assert pending_tasks(four) == [] and not four.assistant.state.pending


def test_which_one_reads_three_then_and_n_more(four):
    four.hear(heard('Jarvis delete a reminder', 0.9))
    assert four.said()[-1] == ('I found 4 reminders: call my Mom, today at 3:20 PM; delete my old emails, today at 4:20 PM; '
                               'call my mom minutes, today at 5:20 PM; and 1 more. Which one should I delete?')


def test_which_one_can_still_be_answered_by_name_or_position(four):
    four.hear(heard('Jarvis delete a reminder', 0.9))
    four.hear(heard('the stand up one', 0.9))
    assert 'stand up' not in pending_tasks(four) and len(pending_tasks(four)) == 3
    four.hear(heard('Jarvis delete a reminder', 0.9))
    four.hear(heard('the first one', 0.9))
    assert pending_tasks(four) == ['delete my old emails', 'call my mom minutes']


def test_a_name_that_matches_nothing_asks_again_and_a_new_request_is_not_swallowed(four):
    four.hear(heard('Jarvis delete a reminder', 0.9))
    four.hear(heard('the dentist', 0.9))
    assert four.said()[-1].startswith('Sorry, which one?') and len(pending_tasks(four)) == 4
    four.hear(heard('what time is it', 0.9))
    assert len(pending_tasks(four)) == 4 and not four.assistant.state.pending


def test_a_word_that_names_a_reminder_is_not_all(jarvis):
    jarvis.services.reminders.create({'task': 'all hands meeting', 'due': NOW.replace(hour=16)})
    jarvis.services.reminders.create({'task': 'stand up', 'due': NOW.replace(hour=17)})
    jarvis.hear(heard('Jarvis delete a reminder', 0.9))
    jarvis.hear(heard('the all hands one', 0.9))
    assert pending_tasks(jarvis) == ['stand up']


def test_cancel_all_reminders_leaves_alarms_and_cancel_all_alarms_leaves_reminders(four):
    four.services.reminders.create({'task': None, 'due': NOW.replace(hour=22), 'kind': 'alarm'})
    four.hear(CANCEL_ALL)
    assert pending_tasks(four) == [None]
    four.services.reminders.create({'task': 'stand up', 'due': NOW.replace(hour=18)})
    four.hear(heard('Jarvis delete all alarms', 0.9))
    assert pending_tasks(four) == ['stand up']


def test_cancel_all_timers_and_all_as_the_answer(jarvis):
    jarvis.hear(START_TEA)
    jarvis.hear(heard('set a timer for 5 minutes called coffee', 0.81986362))
    jarvis.hear(heard('Jarvis cancel all timers', 0.9))
    assert jarvis.timers() == {} and jarvis.said()[-1].startswith('All 2 timers cancelled.')
    jarvis.hear(heard('undo', 0.9))
    assert set(jarvis.timers()) == {'Tea', 'Coffee'}
    jarvis.hear(heard('Jarvis cancel a timer', 0.9))
    assert 'Which one' in jarvis.said()[-1] and jarvis.assistant.state.pending
    jarvis.hear(heard('all of them', 0.9))
    assert jarvis.timers() == {}


def test_which_timer_reads_three_then_and_n_more():
    from core.assistant import _list_timers
    timers = [SimpleNamespace(label=name, duration_seconds=60) for name in ('Tea', 'Coffee', 'Pasta', 'Rice', 'Eggs')]
    assert _list_timers(timers[:3]) == 'tea, coffee or pasta'
    assert _list_timers(timers) == 'tea, coffee, pasta and 2 more'


# --- the reminder list says how many first ----------------------------------------------------

HOW_MANY = heard('Jarvis how many reminders I have', 0.94322705,                                        # 581
                 ('Yarvis how many reminders I have', 0.94322705), ('Jarvis hHow many reminders I have', 0.94322705))


def test_reminder_list_says_the_count_first_then_the_items(four):
    four.hear(HOW_MANY)
    assert four.said() == ['You have 4 reminders.', 'call my Mom, today at 3:20 PM.', 'delete my old emails, today at 4:20 PM.',
                           'call my mom minutes, today at 5:20 PM.', 'stand up, today at 6:20 PM.']


def test_a_single_reminder_and_an_empty_list(jarvis):
    jarvis.hear(heard('Jarvis list my reminders', 0.9))
    assert jarvis.said()[-1] == 'No reminders.'
    jarvis.services.reminders.create({'task': 'stand up', 'due': NOW.replace(hour=17)})
    jarvis.hear(heard('Jarvis list my reminders', 0.9))
    assert jarvis.said()[-2:] == ['You have 1 reminder.', 'stand up, today at 5:20 PM.']


# --- weather: advice in one short sentence, wording in core/phrases.py -----------------------------

def weather_reply(temp=10.4, description='clear sky', wind=5.0, feels=9.5):
    """What OpenWeatherMap said at 14:25 in Kokkola (seq 1058), adjustable."""
    return Mock(status_code=200, json=Mock(return_value={
        'main': {'temp': temp, 'feels_like': feels, 'humidity': 60},
        'weather': [{'description': description, 'main': description.split()[-1]}],
        'wind': {'speed': wind}, 'visibility': 10000, 'clouds': {'all': 0},
        'sys': {'sunrise': 0, 'sunset': 9999999999}}))


@pytest.fixture
def kokkola(monkeypatch):
    from core import weather_service
    monkeypatch.setattr(weather_service.requests, 'get', lambda *a, **k: weather_reply())
    return weather_service


JACKET = heard('Jarvis should I wear a jacket today', 0.90784991, ('Yarvis should I wear a jacket today', 0.90784991))  # 1053


def test_should_i_wear_a_jacket_gets_one_short_sentence_with_the_reason(jarvis, kokkola):
    jarvis.hear(JACKET)
    assert jarvis.said() == ['Light jacket: 10 degrees and breezy.']


@pytest.mark.parametrize('question, answer', [
    ('Jarvis do I need an umbrella', 'No: clear sky.'),
    ('Jarvis should I go outside', 'Yes: 10 degrees, clear sky.'),
    ('Jarvis do I need a coat', 'Light jacket: 10 degrees and breezy.'),
    ('Jarvis what should I wear', 'Light jacket: 10 degrees and breezy.'),
])
def test_other_advice_questions_are_one_sentence_too(jarvis, kokkola, question, answer):
    jarvis.hear(heard(question, 0.9))
    assert jarvis.said() == [answer]


@pytest.mark.parametrize('question', ['Jarvis should I wear a jacket, tell me everything about it',
                                      'Jarvis should I wear a jacket, in detail'])
def test_full_details_only_when_asked_for(jarvis, kokkola, question):
    jarvis.hear(heard(question, 0.9))
    text = jarvis.said()[-1]
    assert 'Humidity is at 60%, and cloud cover is 0%.' in text and "I'd recommend a light jacket" in text
    assert ' sir' not in text.lower()


def test_the_plain_weather_report_is_unchanged_in_substance(jarvis, kokkola):
    jarvis.hear(heard('Jarvis what is the weather today', 0.84072971))
    assert jarvis.said() == ['Mild weather in Kokkola. 10 degrees, clear sky.']
    jarvis.hear(heard('Jarvis tell me about the weather', 0.9))
    text = jarvis.said()[-1]
    assert 'Humidity is at 60%' in text and 'moderate breeze at 5 meters per second' in text


@pytest.mark.parametrize('temp, description, wind, feels, expected', [
    (-25, 'clear sky', 1, -25, 'Heavy coat and warm layers: -25 degrees.'),
    (-12, 'clear sky', 1, -12, 'Warm winter coat: -12 degrees.'),
    (-3, 'light snow', 1, -3, 'Winter jacket: -3 degrees and snowy.'),
    (5, 'clear sky', 1, 5, 'Warm jacket: 5 degrees.'),
    (5, 'clear sky', 6, -1, 'Warm jacket: 5 degrees, feels like -1 degree.'),
    (12, 'light rain', 2, 12, 'Light jacket: 12 degrees and rainy.'),
    (14, 'few clouds', 9, 14, 'Light jacket: 14 degrees and windy.'),
    (22, 'clear sky', 1, 22, 'No jacket needed: 22 degrees.'),
])
def test_jacket_advice_names_the_key_reason(temp, description, wind, feels, expected):
    from core.weather_service import _get_advice
    assert _get_advice('clothing', temp, feels, description, wind) == expected


def test_umbrella_and_outdoor_advice():
    from core.weather_service import _get_advice
    assert _get_advice('umbrella', 12, 12, 'light rain', 2) == 'Yes: light rain.'
    assert _get_advice('umbrella', -2, -2, 'light snow', 2) == 'Not for snow: light snow.'
    assert _get_advice('go_outside', -20, -25, 'clear sky', 2) == 'Better to stay in: -20 degrees.'
    assert _get_advice('go_outside', -6, -6, 'clear sky', 2) == 'Bundle up: -6 degrees, clear sky.'
    assert _get_advice('go_outside', 12, 12, 'thunderstorm', 2) == 'Better wait: thunderstorm.'


@pytest.mark.parametrize('utterance', ['should I wear a jacket', 'do I need an umbrella', 'will it rain today',
                                       'do I need a coat', 'should I go outside'])
def test_advice_questions_route_to_the_weather(utterance):
    assert route(utterance).intent == 'weather'


def test_no_fixed_weather_wording_is_left_in_the_weather_service():
    import re
    from pathlib import Path
    from core.phrases import PHRASES
    source = Path('core/weather_service.py').read_text(encoding='utf-8')
    for old in ('Freezing in', "I'd recommend", 'Perfect weather', 'Well sir', 'dangerously cold', 'Visibility is',
                'Humidity is', "Here's the outlook", 'light breeze', 'Bundle up', 'Keep an umbrella', 'Sir,'):
        assert old not in source, old
    reports = source[source.index('def _format_temperature'):]
    assert not re.search(r'(?<![\w"])f"[^"\n]*[A-Za-z]{4,} [A-Za-z]{3,}', reports)    # no sentence built in f-strings
    assert all('sir' not in ' '.join(v).lower().split() for k, v in PHRASES.items() if k.startswith(('weather', 'adv_')))
