"""Jarvis's fixed replies: short, varied, natural, all in core/phrases.py."""
import random
import string
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core import phrases
from core.phrases import PHRASES, SIR_OK, say

COMMON = ['greeting', 'not_heard', 'cancelled', 'okay', 'timer_set', 'timer_set_plain', 'timer_paused',
          'timer_resumed', 'timer_done', 'reminder_set', 'alarm_set', 'reminder_due', 'thanks', 'time']
ACTIONS = ['timer_set', 'timer_set_plain', 'timer_paused', 'timer_resumed', 'timer_cancelled', 'time_added',
           'reminder_set', 'alarm_set', 'reminder_snoozed', 'undone', 'opening_google', 'playing', 'cancelled']


def fields(variant):
    return {name for _, name, _, _ in string.Formatter().parse(variant) if name}


def filled(variant):
    return variant.format(**{name: 'x' for name in fields(variant)})


def test_every_variant_can_be_filled_with_the_values_its_phrase_gets():
    for key, variants in PHRASES.items():
        assert 1 <= len(variants) <= 4, key
        names = set().union(*(fields(v) for v in variants))
        for variant in variants:
            variant.format(**{name: 'x' for name in names})  # no KeyError


@pytest.mark.parametrize('key', COMMON)
def test_common_replies_vary(key):
    assert 2 <= len(PHRASES[key]) <= 4


@pytest.mark.parametrize('key', ACTIONS)
def test_action_replies_are_short(key):
    for variant in PHRASES[key]:
        assert len(filled(variant).split()) <= 8, variant


def test_no_filler_and_no_built_in_sir():
    text = ' '.join(v.lower() for variants in PHRASES.values() for v in variants)
    for filler in ("keep an eye", "let me know", "anything else", "i'll alert you", "feel free"):
        assert filler not in text
    assert ' sir' not in text and 'sir,' not in text


def test_the_re_ask_never_contains_yes():
    assert all('yes' not in v.lower().split() for v in PHRASES['reask'])


def test_sir_about_one_in_five_and_only_where_it_fits(monkeypatch):
    monkeypatch.setattr(phrases, '_choose', random.choice)
    monkeypatch.setattr(phrases, '_random', random.Random(7).random)
    with_sir = sum('sir' in say('timer_set', name='pasta', duration='25 minutes') for _ in range(1000))
    assert 150 <= with_sir <= 250
    assert not any('sir' in say('not_heard') for _ in range(200))
    assert 'not_heard' not in SIR_OK


def test_sir_is_added_before_the_final_punctuation():
    assert phrases.with_sir('Pasta timer, 25 minutes.') == 'Pasta timer, 25 minutes, sir.'
    assert phrases.with_sir('Yes?') == 'Yes, sir?'


def test_wording_varies(monkeypatch):
    monkeypatch.setattr(phrases, '_choose', random.Random(1).choice)
    assert len({say('timer_set', name='pasta', duration='25 minutes') for _ in range(50)}) >= 2


def test_replies_start_with_a_capital():
    assert say('timer_set', name='pasta', duration='25 minutes') == 'Pasta timer, 25 minutes.'


# --- what you hear --------------------------------------------------------------------

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 13, 0, tzinfo=TZ)


@pytest.fixture
def reminders(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    return ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=lambda: NOW)


def test_reminders_and_alarms_sound_natural(reminders):
    due = NOW.replace(hour=7, minute=0).replace(day=23)
    assert reminders.create({'task': 'drink water', 'due': NOW.replace(hour=21)}).messages == \
        ('Done, reminding you at 9 PM: drink water.',)
    assert reminders.create({'task': None, 'due': due, 'kind': 'alarm'}).messages == ('Alarm set for 7 AM tomorrow.',)
    reminder = reminders.store.pending()[0]
    alarm = reminders.store.pending()[1]
    assert reminders._announcement(reminder, NOW, False) == 'Time to drink water.'
    assert reminders._announcement(alarm, NOW, False) == "It's 7 AM — your alarm."


def test_a_reminder_that_is_not_a_verb_is_read_as_a_reminder(reminders):
    reminders.create({'task': 'dentist appointment', 'due': NOW.replace(hour=21)})
    assert reminders._announcement(reminders.store.pending()[0], NOW, False) == 'Reminder: dentist appointment.'


def test_timer_replies_are_short():
    from core.smart_timer import SmartTimerManager
    from core.command_output import TextNotifications
    said = []
    manager = SmartTimerManager(notifications=TextNotifications(said.append))
    manager.create_timer('set a pasta timer for 25 minutes', respond=said.append)
    manager.pause_timer(label='Pasta', respond=said.append)
    manager.cancel_all_timers(respond=said.append)
    assert said[0] == 'Pasta timer, 25 minutes.'
    assert said[1].startswith('Paused. ') and said[1].endswith(' left.')


def test_not_heard_is_short():
    from core.voice_policy import ConfidenceGate, Recognition
    assert ConfidenceGate(lambda: 0).assess(Recognition(error='unrecognized')).prompt == 'Sorry?'


def test_time_and_date_sound_natural():
    from core.command_engine import execute_query
    from core.command_services import CommandServices
    now = lambda: datetime(2026, 10, 22, 13, 5)  # noqa: E731
    assert execute_query('what time is it', CommandServices(), now=now).messages == ("It's 1:05 PM.",)
    assert execute_query("what's the date today", CommandServices(), now=now).messages == ("It's Thursday, October 22.",)


# --- the model's style -------------------------------------------------------------

def test_dialogue_prompt_asks_for_a_natural_concise_style():
    import json
    from unittest.mock import patch
    from core import chatgpt_service
    reply = {'choices': [{'message': {'content': json.dumps({'reply': 'Fine.', 'query': None})}}]}
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create', return_value=reply) as create:
        chatgpt_service.resolve_dialogue({'history': []})
    prompt = create.call_args.kwargs['messages'][0]['content']
    assert 'light, dry wit' in prompt and 'Never end with an offer of more help' in prompt
    assert 'Say "sir" rarely' in prompt


@pytest.mark.parametrize('reply, spoken', [
    ("Got it, let me know if there's anything else you need.", 'Okay.'),               # 22 Oct, seq 1776
    ('Focus on your achievements. Let me know if you need more tips.', 'Focus on your achievements.'),
    ('Black holes are very dense. Is there anything specific you want to know?',
     'Black holes are very dense. Is there anything specific you want to know?'),
])
def test_closing_offers_of_help_are_dropped(reply, spoken):
    from core.dialogue import without_filler
    assert without_filler(reply) == spoken
