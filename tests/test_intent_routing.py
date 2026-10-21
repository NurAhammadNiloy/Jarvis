"""Table-driven routing regressions: phrase -> intent and key arguments.

Routing goes through understand_query, so the table also covers the argument
extraction (city, YouTube topic, timer label/duration, reminder target). The
reminder NLP extractor is stubbed: routing must never need spaCy.
"""
from unittest.mock import Mock

import pytest

from config.settings import DEFAULT_LOCATION
from core.command_engine import execute_query, understand_query
from core.command_services import CommandServices

DEFAULT = DEFAULT_LOCATION


class RoutingServices:
    """Only what understanding needs; timer parsing is the real pure parser."""

    def extract_reminder_info(self, query):
        return {'task': None, 'time': None, 'recurring': False, 'interval': None}

    def extract_timer_info(self, query):
        from core.smart_timer import extract_timer_info
        return extract_timer_info(query)


def observed_fields(arguments):
    """Project the command arguments onto the fields this table checks."""
    fields = {}
    if 'city' in arguments:
        fields['city'] = arguments['city']
    if 'topic' in arguments:
        fields['topic'] = arguments['topic']
    if 'label' in arguments:
        fields['label'] = arguments['label'].lower() if arguments['label'] else None
    if 'duration' in arguments:
        fields['seconds'] = arguments['duration'][0]
    if 'target' in arguments:
        fields['target'] = arguments['target']
    return fields


ROUTES = [
    # --- reminders: operations on existing reminders before creation
    ('what are my reminders', 'list_reminders', {}),
    ('What are my reminders?', 'list_reminders', {}),
    ('list my reminders', 'list_reminders', {}),
    ('do I have any reminders', 'list_reminders', {}),
    ('delete my dentist reminder', 'delete_reminder', {'target': 'dentist'}),
    ('Delete the dentist reminder.', 'delete_reminder', {'target': 'dentist'}),
    ('cancel the reminder about the dentist', 'delete_reminder', {'target': 'dentist'}),
    ('snooze that reminder', 'snooze_reminder', {}),
    ('Snooze the reminder for 10 minutes', 'snooze_reminder', {}),
    ('snooze it', 'snooze_reminder', {}),
    ('snooze the dentist reminder for 10 minutes', 'snooze_reminder', {'target': 'dentist'}),
    ('Snooze the reminder for 10 minutes.', 'snooze_reminder', {'target': None}),
    ('remind me to call mom tomorrow at 9 pm', 'create_reminder', {}),
    ('Remind me at 5pm to stretch.', 'create_reminder', {}),
    ('set a reminder to call mom', 'create_reminder', {}),
    ('remind me to delete my old emails', 'create_reminder', {}),
    # --- alarm (unsupported, but must not become a timer or chat)
    ('set an alarm for 7am', 'alarm', {}),
    ('Set an alarm for 7 AM.', 'alarm', {}),
    ('wake me up at 6:30', 'alarm', {}),
    ('set an alarm for 30 minutes', 'alarm', {}),
    # --- timers: resume before pause, specific operations before start
    ('unpause the pasta timer', 'resume_timer', {'label': 'pasta'}),
    ('Unpause the pasta timer!', 'resume_timer', {'label': 'pasta'}),
    ('resume the pasta timer', 'resume_timer', {'label': 'pasta'}),
    ('resume', 'resume_timer', {}),
    ('continue the timer', 'resume_timer', {}),
    ('pause the pasta timer', 'pause_timer', {'label': 'pasta'}),
    ('Pause it.', 'pause_timer', {}),
    ('pause timer', 'pause_timer', {}),
    ('cancel the pasta timer', 'cancel_timer', {'label': 'pasta'}),
    ('Stop the timer.', 'cancel_timer', {}),
    ('cancel all timers', 'cancel_all_timers', {}),
    ('Clear all my timers', 'cancel_all_timers', {}),
    ('how much time is left on the pasta timer', 'timer_status', {'label': 'pasta'}),
    ('Timer status?', 'timer_status', {}),
    ('how long is left', 'timer_status', {}),
    ('add five minutes to the pasta timer', 'add_timer_time', {'label': 'pasta', 'seconds': 300}),
    ('Add 2 minutes to my timer', 'add_timer_time', {'seconds': 120}),
    ('start a pomodoro', 'pomodoro', {}),
    ('Pomodoro please', 'pomodoro', {}),
    ('set a timer for twenty five minutes', 'start_timer', {'seconds': 1500}),
    ('Set a timer for twenty-five minutes.', 'start_timer', {'seconds': 1500}),
    ('timer for 5 minutes', 'start_timer', {'seconds': 300}),
    ('set a pasta timer for 10 minutes', 'start_timer', {'label': 'pasta', 'seconds': 600}),
    ('start a timer for one hour and thirty minutes', 'start_timer', {'seconds': 5400}),
    ('set a timer for -5 minutes', 'start_timer', {'seconds': -300}),
    ('set a timer for minus five minutes', 'start_timer', {'seconds': -300}),
    # --- weather: the city is a span after in/at/for, never a fragment
    ('weather in Helsinki', 'weather', {'city': 'Helsinki'}),
    ('weather in Washington', 'weather', {'city': 'Washington'}),
    ('weather in Athens', 'weather', {'city': 'Athens'}),
    ('WEATHER IN HELSINKI', 'weather', {'city': 'Helsinki'}),
    ("what's the weather like in Washington?", 'weather', {'city': 'Washington'}),
    ('weather in athens today', 'weather', {'city': 'Athens'}),
    ('how cold is it in New York right now', 'weather', {'city': 'New York'}),
    ("what's the weather like today?", 'weather', {'city': DEFAULT}),
    ('Weather?', 'weather', {'city': DEFAULT}),
    ('should I wear a jacket', 'weather', {'city': DEFAULT}),
    ('what should I wear at the office', 'weather', {'city': DEFAULT}),
    ("what's the forecast for Helsinki", 'forecast', {'city': 'Helsinki'}),
    ('Forecast?', 'forecast', {'city': DEFAULT}),
    ('what will the weather be like this week in Athens', 'forecast', {'city': 'Athens'}),
    ("what's the weather in New York tomorrow", 'forecast', {'city': 'New York'}),
    # --- YouTube: only an explicit play request or a YouTube mention
    ('play lofi music on youtube', 'youtube', {'topic': 'lofi music'}),
    ('Play lofi music on YouTube.', 'youtube', {'topic': 'lofi music'}),
    ('can you play some jazz', 'youtube', {'topic': 'jazz'}),
    ('open youtube', 'youtube', {'topic': ''}),
    ('Jarvis, can you play despacito please', 'youtube', {'topic': 'despacito'}),
    # --- browser, time, date, small talk
    ('open google', 'google', {}),
    ('Open Google.', 'google', {}),
    ('google', 'google', {}),
    ('what time is it', 'time', {}),
    ("What's the time?", 'time', {}),
    ('time', 'time', {}),
    ("what's today's date", 'date', {}),
    ('What is the date?', 'date', {}),
    ("what's the date day after tomorrow", 'date', {}),
    ('thank you', 'thank', {}),
    ('Thanks!', 'thank', {}),
    ('thanks Jarvis', 'thank', {}),
    ('what are you doing', 'what you are doing', {}),
    # --- everything else is conversation
    ('update my preference', 'chat', {}),
    ('explain runtime errors', 'chat', {}),
    ('tell me about the play Hamlet', 'chat', {}),
    ('Tell me about the play "Hamlet".', 'chat', {}),
    ('continue explaining', 'chat', {}),
    ('what is the status of my order', 'chat', {}),
    ("let's play a game", 'chat', {}),
    ('help me update my resume', 'chat', {}),
    ('explain gravity', 'chat', {}),
    ('what time is it in Tokyo', 'chat', {}),
    ('what is the temperature of the sun', 'chat', {}),
]


@pytest.mark.parametrize('phrase, intent, fields', ROUTES, ids=[r[0] for r in ROUTES])
def test_routing_table(phrase, intent, fields):
    command = understand_query(phrase, RoutingServices())
    assert command.intent == intent
    observed = observed_fields(command.arguments)
    for key, value in fields.items():
        assert observed.get(key) == value, (key, observed)


def test_routing_needs_no_nlp_model():
    import subprocess
    import sys
    from pathlib import Path
    script = (
        "import importlib.abc, sys\n"
        "class Guard(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'spacy', 'torch', 'transformers', 'dateparser'} or name == 'utils.nlp_utils':\n"
        "            raise AssertionError(name)\n"
        "sys.meta_path.insert(0, Guard())\n"
        "from core.intent_classifier import route\n"
        f"for phrase in {[r[0] for r in ROUTES]!r}:\n"
        "    route(phrase)\n")
    completed = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


def timer_services():
    fake = Mock(spec=CommandServices)
    fake.follow_up.return_value = None
    fake.extract_timer_info.side_effect = RoutingServices().extract_timer_info
    return fake


@pytest.mark.parametrize('phrase', [
    'set a timer for -5 minutes',
    'set a timer for minus five minutes',
    'set a timer for 0 minutes',
    'add -2 minutes to the pasta timer',
])
def test_non_positive_durations_are_rejected_without_a_timer(phrase):
    services = timer_services()
    result = execute_query(phrase, services)
    assert result.status == 'error'
    assert len(result.messages) == 1 and 'zero' in result.messages[0]
    services.timer_action.assert_not_called()
