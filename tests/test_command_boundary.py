"""Deterministic command regressions: no credentials, network or audio."""
from datetime import datetime
import importlib.abc
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from core.command_engine import execute_command, execute_query, understand_query
from core.command_output import deliver_result
from core.command_result import ActionResult, CommandResult
from core.command_services import CommandServices
from core.intent_handler import handle_query


@pytest.fixture(autouse=True)
def block_audio_and_providers():
    class BlockImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            forbidden = ('core.speech_synthesis', 'core.voice_recognition',
                         'config.credentials', 'google', 'openai', 'spacy',
                         'speech_recognition', 'pyaudio', 'playsound')
            if any(fullname == p or fullname.startswith(p + '.') for p in forbidden):
                raise AssertionError('Unexpected dependency: ' + fullname)
    guard = BlockImports()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


@pytest.fixture
def services():
    fake = Mock(spec=CommandServices)
    fake.follow_up.return_value = None
    fake.weather.return_value = 'Weather response.'
    fake.forecast.return_value = 'Forecast response.'
    fake.chat.return_value = 'Chat response.'
    fake.youtube.return_value = 'https://www.youtube.com/watch?v=example'
    fake.thanks.side_effect = lambda choose: choose(['You are welcome.', 'Anytime.'])
    fake.extract_reminder_info.return_value = {
        'task': 'call mom', 'time': '5pm', 'recurring': False, 'interval': None,
    }
    fake.extract_timer_info.return_value = {'action': 'set', 'label': 'Pasta', 'duration': (300, '5 minutes')}
    fake.reminder.return_value = ActionResult(('Reminder set.',))
    fake.timer_action.return_value = ActionResult(('Timer response.',))
    return fake


@pytest.mark.parametrize('query,expected', [
    ('what time is it', 'The current time is 02:30 PM.'),
    ("what is today's date", "Today's date is September 09, 2026."),
    ("what is tomorrow's date", "Tomorrow's date is September 10, 2026."),
    ("what was yesterday's date", "Yesterday's date was September 08, 2026."),
    ('what you are doing', 'Just here, ready to assist you, boss.'),
    ('thank you', 'You are welcome.'),
])
def test_local_responses_are_deterministic(services, query, expected):
    result = execute_query(query, services, now=lambda: datetime(2026, 9, 9, 14, 30), choose=lambda choices: choices[0])
    assert result.status == 'handled'
    assert result.messages == (expected,)
    services.chat.assert_not_called()


def test_understanding_does_not_execute_a_reminder(services):
    command = understand_query('remind me to call mom at 5pm', services)
    assert command.intent == 'create_reminder'
    assert command.arguments['task'] == 'call mom'
    services.reminder.assert_not_called()
    assert execute_command(command, services).messages == ('Reminder set.',)
    services.reminder.assert_called_once_with('call mom', '5pm', False, None)


def test_pending_reminder_returns_task_without_scheduling(services):
    services.extract_reminder_info.return_value['time'] = None
    result = execute_query('remind me to call mom', services)
    assert result.status == 'pending'
    assert result.pending_action == 'reminder_time'
    assert result.data == {'task': 'call mom'}
    assert result.legacy_value() == 'pending_reminder_time'
    services.reminder.assert_not_called()


@pytest.mark.parametrize('query,method', [('weather', 'weather'), ('forecast', 'forecast')])
def test_weather_services_and_context(services, query, method):
    result = execute_query(query, services)
    assert result.messages == (method.title() + ' response.',)
    assert getattr(services, method).call_count == 1
    assert services.set_context.call_args.kwargs['city'] == 'Kokkola'


@pytest.mark.parametrize('query,action', [
    ('set a timer for 5 minutes', 'set'), ('cancel timer', 'cancel'),
    ('cancel all timers', 'cancel_all'), ('pause timer', 'pause'),
    ('resume timer', 'resume'), ('timer status', 'status'),
    ('add 5 minutes to timer', 'add_time'), ('start pomodoro', 'pomodoro'),
])
def test_timer_dispatch(services, query, action):
    services.extract_timer_info.return_value['action'] = action
    result = execute_query(query, services)
    assert result.messages == ('Timer response.',)
    services.timer_action.assert_called_once_with(action, query, services.extract_timer_info.return_value)


def test_timer_missing_add_duration_does_not_execute(services):
    services.extract_timer_info.return_value.update(action='add_time', duration=(None, None))
    result = execute_query('add time to timer', services)
    assert result.messages == ('How much time would you like to add?',)
    services.timer_action.assert_not_called()


def test_browser_and_youtube_actions_execute_once(services):
    result = execute_query('play lofi on youtube', services)
    assert result.messages == ('Playing lofi on YouTube.',)
    services.youtube.assert_called_once_with('play lofi on youtube')
    services.open_url.assert_called_once_with(services.youtube.return_value)
    services.open_url.reset_mock()
    assert execute_query('open google', services).messages == ('Opening Google.',)
    services.open_url.assert_called_once_with('https://www.google.com')


def test_youtube_no_result_does_not_open_browser(services):
    services.youtube.return_value = None
    assert execute_query('play lofi', services).messages == ("I couldn't find lofi on YouTube.",)
    services.open_url.assert_not_called()


def test_chat_and_followup_precedence(services):
    assert execute_query('explain gravity', services).messages == ('Chat response.',)
    services.chat.assert_called_once_with('explain gravity')
    services.follow_up.return_value = 'Context response.'
    result = execute_query('yes', services)
    assert result.intent == 'follow_up'
    assert result.messages == ('Context response.',)
    assert services.chat.call_count == 1


def test_exceptions_return_error_without_retry(services):
    services.open_url.side_effect = RuntimeError('private implementation details')
    result = execute_query('open google', services)
    assert result.status == 'error'
    assert result.error == 'RuntimeError'
    assert 'private' not in str(result.messages)
    services.open_url.assert_called_once()


@pytest.mark.parametrize('query', ['', '   ', None])
def test_invalid_input_does_not_call_services(services, query):
    assert execute_query(query, services).error == 'invalid_input'
    assert services.mock_calls == []


def test_voice_wrapper_delivers_once_and_preserves_legacy_values(services):
    output = Mock()
    assert handle_query('open google', services=services, output=output) is True
    output.assert_called_once_with('Opening Google.')
    services.open_url.assert_called_once()
    services.extract_reminder_info.return_value['time'] = None
    assert handle_query('remind me to call mom', services=services, output=output) == 'pending_reminder_time'
    services.extract_reminder_info.return_value['task'] = ''
    assert handle_query('remind me', services=services, output=output) is False


def test_domain_failure_is_explicit_but_legacy_handler_still_handles_it(services):
    services.timer_action.return_value = ActionResult(('No timer found.',), False)
    result = execute_query('pause timer', services)
    assert result.status == 'error'
    assert result.legacy_value() is True


def test_delivery_failure_does_not_execute_again(services):
    output = Mock(side_effect=RuntimeError('speaker unavailable'))
    with pytest.raises(RuntimeError):
        handle_query('open google', services=services, output=output)
    services.open_url.assert_called_once()


def test_multiple_messages_keep_order():
    messages = []
    deliver_result(CommandResult('handled', 'timer', ('First', 'Second')), messages.append)
    assert messages == ['First', 'Second']


def test_fresh_process_needs_only_standard_library():
    script = '''
import importlib.abc, sys
from datetime import datetime
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'google','spacy','openai','speech_recognition','playsound','pyaudio','webrtcvad'} or fullname in {'config.credentials','core.speech_synthesis','core.voice_recognition'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Guard())
from core.command_engine import execute_query
from core.intent_handler import handle_query
assert execute_query('time', now=lambda:datetime(2026,9,9,14,30)).messages == ('The current time is 02:30 PM.',)
assert execute_query('timer status').messages == ('You have no active timers.',)
messages=[]
assert handle_query('what time is it', output=messages.append) is True
assert len(messages)==1
'''
    completed = subprocess.run([sys.executable, '-B', '-S', '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
