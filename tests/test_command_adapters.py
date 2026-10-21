"""Real domain adapters, with temporary storage and controlled scheduling."""
from datetime import datetime, timedelta
import importlib.abc
import json
import sys
from unittest.mock import Mock

import pytest

from core.command_engine import execute_query
from core.command_output import TextNotifications, VoiceNotifications
from core.command_services import CommandServices
from core import conversation_context


@pytest.fixture(autouse=True)
def isolated_context_and_no_audio():
    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in ('core.speech_synthesis', 'core.voice_recognition', 'config.credentials'):
                raise AssertionError('Audio dependency requested: ' + fullname)
    guard = Guard()
    sys.meta_path.insert(0, guard)
    conversation_context.clear_context()
    yield
    conversation_context.clear_context()
    sys.meta_path.remove(guard)


@pytest.fixture
def timer_services(monkeypatch, tmp_path):
    from core.smart_timer import SmartTimerManager
    monkeypatch.setattr(SmartTimerManager, '_load_history', lambda self: None)
    notifications = []
    services = CommandServices(TextNotifications(notifications.append))
    services.timers.history_file = str(tmp_path / 'history.json')
    monkeypatch.setattr(services.timers, '_start_timer_thread', Mock())
    return services, notifications


def test_real_timer_lifecycle_and_output_separation(timer_services):
    services, notifications = timer_services
    assert execute_query('set a pasta timer for 5 minutes', services).status == 'handled'
    timer = next(iter(services.timers.timers.values()))
    assert timer.duration_seconds == 300
    assert execute_query('pause pasta timer', services).status == 'handled'
    assert timer.state.value == 'paused'
    status = execute_query('pasta timer status', services)
    assert len(status.messages) == 1
    assert 'paused' in status.messages[0]
    assert execute_query('add 2 minutes to pasta timer', services).status == 'handled'
    assert timer.duration_seconds == 420
    assert execute_query('resume pasta timer', services).status == 'handled'
    assert timer.state.value == 'running'
    assert execute_query('cancel pasta timer', services).status == 'handled'
    assert services.timers.timers == {}
    assert notifications == []


def test_timer_completion_uses_notification_adapter(timer_services):
    services, notifications = timer_services
    result = execute_query('set a pasta timer for 5 minutes', services)
    timer = next(iter(services.timers.timers.values()))
    services.timers._announce_milestone(timer, '10 seconds remaining', 10)
    services.timers._complete_timer(timer)
    assert len(result.messages) == 1  # Returned results do not mutate later.
    assert len(notifications) == 2
    assert 'complete' in notifications[-1]
    assert not services.timers.timers


def test_pomodoro_chain_keeps_background_output_separate(timer_services):
    services, notifications = timer_services
    result = execute_query('start pomodoro', services)
    assert len(result.messages) == 2
    work = next(iter(services.timers.timers.values()))
    assert work.duration_seconds == 1500
    services.timers._complete_timer(work)
    rest = next(iter(services.timers.timers.values()))
    assert rest.duration_seconds == 300
    assert rest.label == 'short break'
    assert len(notifications) == 3  # Completion, chain transition, new timer.


def test_followup_cancellation_uses_same_timer_service(timer_services):
    services, notifications = timer_services
    execute_query('set a timer for 5 minutes', services)
    conversation_context.set_context(topic='timer', pending_action='confirm_cancel')
    result = execute_query('yes', services)
    assert result.messages == ('All timers have been cancelled, sir.',)
    assert not services.timers.timers
    assert not notifications


def test_weather_followup_uses_injected_provider(monkeypatch):
    services = CommandServices()
    monkeypatch.setattr(services, 'weather', Mock(return_value='Detailed weather.'))
    conversation_context.set_context(topic='forecast', city='Kokkola')
    assert execute_query('yes', services).messages == ('Sure thing, sir. Detailed weather.',)
    services.weather.assert_called_once_with('Kokkola', detailed=True)


@pytest.fixture
def reminders(monkeypatch, tmp_path):
    from core import reminder_manager as manager
    monkeypatch.setattr(manager, 'REMINDER_FILE', str(tmp_path / 'reminders.json'))
    monkeypatch.setattr(manager, 'reminders', [])
    monkeypatch.setattr(manager, '_initialized', False)
    monkeypatch.setattr(manager, 'run_scheduled_jobs', Mock())
    timer = Mock()
    monkeypatch.setattr(manager.threading, 'Timer', timer)
    return manager, timer


def test_reminder_response_and_delayed_notification(reminders, monkeypatch):
    manager, timer = reminders
    notifications = []
    services = CommandServices(TextNotifications(notifications.append))
    monkeypatch.setattr(services, 'extract_reminder_info', lambda q: {
        'task': 'call mom', 'time': 'in 5 minutes', 'recurring': False, 'interval': None,
    })
    result = execute_query('remind me to call mom in 5 minutes', services)
    assert result.status == 'handled'
    assert len(result.messages) == 1 and 'Reminder set' in result.messages[0]
    assert notifications == []
    timer.return_value.start.assert_called_once()
    timer.call_args.args[1]()  # Execute the scheduled callback without waiting.
    assert notifications == ['Sir, this is your reminder: call mom']
    with open(manager.REMINDER_FILE) as stream:
        assert json.load(stream)[0]['completed'] is True


def test_reminder_parse_failure_does_not_schedule(reminders):
    manager, timer = reminders
    result = CommandServices().reminder('task', 'not a date', False, None)
    assert not result.succeeded
    assert len(result.messages) == 1
    timer.assert_not_called()


def test_restoration_is_explicit_idempotent_and_uses_selected_output(reminders):
    manager, timer = reminders
    record = {'task': 'task', 'time': (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S'),
              'completed': False, 'recurring': False, 'interval': None}
    with open(manager.REMINDER_FILE, 'w') as stream:
        json.dump([record], stream)
    notifications = []
    manager.initialize_reminders(notify=notifications.append)
    manager.initialize_reminders(notify=notifications.append)
    timer.assert_called_once()
    timer.call_args.args[1]()
    assert notifications == ['Sir, this is your reminder: task']


def test_recurring_reminder_callback_uses_selected_output(reminders, monkeypatch):
    manager, _ = reminders
    schedule = Mock()
    monkeypatch.setattr(manager, 'schedule', schedule)
    notifications = []
    manager.schedule_recurring_reminder('2030-01-01 12:00:00', 'task', 'daily', notify=notifications.append)
    callback = schedule.every.return_value.day.at.return_value.do.call_args.args[0]
    callback()
    assert notifications == ['Sir, this is your recurring reminder: task']


def test_voice_notification_adapter_preserves_smart_dispatch(monkeypatch):
    from core import timer_alerts
    milestone, completion = Mock(), Mock()
    monkeypatch.setattr(timer_alerts, 'dispatch_milestone_alert', milestone)
    monkeypatch.setattr(timer_alerts, 'dispatch_completion_alert', completion)
    output = VoiceNotifications()
    output.milestone(timer_label='Pasta', message='10 seconds', remaining_seconds=10, remaining_fn=lambda: 10)
    output.completion(timer_label='Pasta', message='Done', category='cooking')
    milestone.assert_called_once()
    completion.assert_called_once_with(timer_label='Pasta', message='Done', category='cooking')


def test_main_restores_reminders_before_listening(monkeypatch):
    import importlib.util
    from pathlib import Path
    import types
    from core import reminder_manager
    from core import conversation_log
    monkeypatch.setattr(conversation_log, 'start_logging', lambda: 'test-log')
    monkeypatch.setattr(conversation_log, 'record', Mock())
    events = []

    class Assistant:
        def wait_for_wake_word(self):
            events.append('listen')
            raise StopIteration()

        def close(self):
            events.append('close')

    fake_assistant = types.ModuleType('core.assistant')
    fake_assistant.Assistant = Assistant
    monkeypatch.setitem(sys.modules, 'core.assistant', fake_assistant)
    monkeypatch.setattr(reminder_manager, 'initialize_reminders', lambda: events.append('restore'))
    spec = importlib.util.spec_from_file_location('test_main_entry', Path(__file__).resolve().parents[1] / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert events == []
    with pytest.raises(StopIteration):
        module.main()
    assert events == ['restore', 'listen', 'close']


def test_domain_imports_do_not_start_jobs_or_read_user_storage():
    from pathlib import Path
    import subprocess
    script = '''
import builtins, os, threading, importlib.abc, sys
original_open = builtins.open
def guarded_open(file, *args, **kwargs):
    if isinstance(file, (str, os.PathLike)) and os.fspath(file).replace('\\\\', '/').startswith('data/'):
        raise AssertionError('Import accessed runtime storage')
    return original_open(file, *args, **kwargs)
def start_thread(self):
    raise AssertionError('Import started background work')
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'core.speech_synthesis','core.voice_recognition','config.credentials'}:
            raise AssertionError(fullname)
builtins.open = guarded_open
threading.Thread.start = start_thread
sys.meta_path.insert(0, Guard())
import core.reminder_manager
import core.smart_timer
assert not core.reminder_manager._initialized
assert core.smart_timer._manager is None
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
