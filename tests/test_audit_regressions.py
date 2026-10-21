"""Regressions for the small bugs found in the 21 Oct 2026 audit."""
from datetime import datetime
from unittest.mock import Mock

import pytest

from core.command_engine import execute_query
from core.command_services import CommandServices
from core.intent_classifier import route
from core.smart_timer import SmartTimerManager, extract_timer_info

NOW = lambda: datetime(2026, 10, 21, 10, 0)


@pytest.fixture
def services():
    fake = Mock(spec=CommandServices)
    fake.follow_up.return_value = None
    fake.chat.return_value = 'Chat response.'
    fake.open_url.return_value = True
    fake.youtube.return_value = 'https://www.youtube.com/watch?v=x'
    return fake


def test_day_after_tomorrow_is_two_days_ahead(services):
    result = execute_query("what's the date day after tomorrow", services, now=NOW)
    assert result.messages == ('The day after tomorrow is October 23, 2026.',)


def test_tomorrow_is_still_one_day_ahead(services):
    result = execute_query("what is tomorrow's date", services, now=NOW)
    assert result.messages == ("Tomorrow's date is October 22, 2026.",)


def test_unpause_the_pasta_timer_resumes():
    assert route('unpause the pasta timer').intent == 'resume_timer'
    assert extract_timer_info('unpause the pasta timer')['label'] == 'Pasta'


def test_pause_still_pauses():
    assert route('pause the pasta timer').intent == 'pause_timer'


class QuietTimers(SmartTimerManager):
    def _start_timer_thread(self, timer):
        pass


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    return QuietTimers(notifications=Mock())


def spoken(action, **kwargs):
    messages = []
    result = action(respond=messages.append, **kwargs)
    return result, messages


def test_cancel_unknown_label_does_not_cancel_the_only_timer(manager):
    manager.create_timer('set a pasta timer for 10 minutes', label='Pasta', respond=lambda m: None)
    ok, messages = spoken(manager.cancel_timer, label='Laundry')
    assert ok is False
    assert 'Laundry' in messages[0]
    assert len(manager.timers) == 1


def test_cancel_without_a_name_still_uses_the_only_timer(manager):
    manager.create_timer('set a pasta timer for 10 minutes', label='Pasta', respond=lambda m: None)
    ok, _ = spoken(manager.cancel_timer)
    assert ok is True
    assert not manager.timers


@pytest.mark.parametrize('method', ['pause_timer', 'resume_timer'])
def test_pause_and_resume_unknown_label_report_not_found(manager, method):
    manager.create_timer('set a pasta timer for 10 minutes', label='Pasta', respond=lambda m: None)
    ok, messages = spoken(getattr(manager, method), label='Laundry')
    assert ok is False
    assert 'Laundry' in messages[0]


def test_add_time_unknown_label_does_not_extend_the_only_timer(manager):
    manager.create_timer('set a pasta timer for 10 minutes', label='Pasta', respond=lambda m: None)
    before = list(manager.timers.values())[0].duration_seconds
    ok, messages = spoken(manager.add_time, seconds=60, label='Laundry')
    assert ok is False
    assert list(manager.timers.values())[0].duration_seconds == before


def test_open_google_reports_browser_failure(services):
    services.open_url.return_value = False
    result = execute_query('open google', services)
    assert result.status == 'error'
    assert result.messages == ("I couldn't open your browser.",)


def test_youtube_reports_browser_failure(services):
    services.open_url.return_value = False
    result = execute_query('play lofi on youtube', services)
    assert result.status == 'error'
    assert 'Playing' not in result.messages[0]


def test_status_goes_to_chat_not_a_fixed_reply(services):
    result = execute_query('status', services)
    assert result.messages == ('Chat response.',)
    services.chat.assert_called_once_with('status')
    assert 'operational' not in result.messages[0]


def test_weather_failure_is_an_error_not_handled(services):
    from core.service_errors import ServiceError
    services.weather.side_effect = ServiceError("I couldn't find weather data for Oslo. Could you check the spelling?")
    result = execute_query('weather in Oslo', services)
    assert result.status == 'error'
    assert result.legacy_value() is False
