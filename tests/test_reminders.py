"""Reminders and alarms: parsing, storage, scheduling and voice commands.

"Now" is frozen at Thu 22 Oct 2026 14:00 in Europe/Helsinki. Nothing waits in
real time: the scheduler is driven by calling run_due()/startup() with a
controllable clock. DST ends on Sun 25 Oct, so recurring reminders that cross
it check that wall-clock time is preserved.
"""
from datetime import datetime, timedelta
import json
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core import conversation_context
from core.command_engine import execute_query

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 14, 0, tzinfo=TZ)


def at(month, day, hour, minute=0, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class Clock:
    def __init__(self, now=NOW):
        self.value = now

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value

    def advance(self, **delta):
        self.value = self.value + timedelta(**delta)


@pytest.fixture(autouse=True)
def clean_context():
    conversation_context.clear_context()
    yield
    conversation_context.clear_context()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def spoken():
    return []


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / 'reminders.db'


def make_service(db_path, clock, spoken, legacy_json=None):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    return ReminderService(ReminderStore(db_path, legacy_json=legacy_json, zone=TZ), notify=spoken.append,
                           clock=clock)


@pytest.fixture
def service(db_path, clock, spoken):
    return make_service(db_path, clock, spoken)


@pytest.fixture
def services(service, clock):
    from core.command_services import CommandServices
    return CommandServices(notifications=Mock(), reminders=service, now=clock)


def say(services, text):
    return execute_query(text, services)


def pending(service):
    return [r for r in service.store.all() if r.status == 'pending']


# --- parsing -----------------------------------------------------------------

PARSES = [
    # phrase, task, due, recurrence, weekday, kind
    ('remind me to call mom tomorrow at 9 pm', 'call mom', at(10, 23, 21), 'none', None, 'reminder'),
    ('remind me to pay rent on December 20 at 9 am', 'pay rent', at(12, 20, 9), 'none', None, 'reminder'),
    ('remind me to take a break in one hour', 'take a break', at(10, 22, 15), 'none', None, 'reminder'),
    ('remind me to stretch at 10 am', 'stretch', at(10, 23, 10), 'none', None, 'reminder'),
    ('remind me to water plants every day at 8 am', 'water plants', at(10, 23, 8), 'daily', None, 'reminder'),
    ('remind me about standup every Monday at 9', 'standup', at(10, 26, 9), 'weekly', 0, 'reminder'),
    ('set an alarm for 7am', None, at(10, 23, 7), 'none', None, 'alarm'),
    # variants: word order, capitals, punctuation, spelled-out numbers
    ('Remind me at 5pm to stretch.', 'stretch', at(10, 22, 17), 'none', None, 'reminder'),
    ('remind me to take a break in 30 minutes', 'take a break', at(10, 22, 14, 30), 'none', None, 'reminder'),
    ('Remind me in half an hour to check the oven', 'check the oven', at(10, 22, 14, 30), 'none', None, 'reminder'),
    ('remind me to buy two apples at 6 pm', 'buy two apples', at(10, 22, 18), 'none', None, 'reminder'),
    ('remind me to call mom tonight at 9', 'call mom', at(10, 22, 21), 'none', None, 'reminder'),
    ('remind me to call mom on Friday at 9:30 am', 'call mom', at(10, 23, 9, 30), 'none', None, 'reminder'),
    ('remind me to drink water every hour', 'drink water', at(10, 22, 15), 'hourly', None, 'reminder'),
    ('Set an alarm for 7 AM every day', None, at(10, 23, 7), 'daily', None, 'alarm'),
    ('wake me up at 6:30', None, at(10, 23, 6, 30), 'none', None, 'alarm'),
    # relative times, the same for alarms and reminders (22 Oct voice session)
    ('set an alarm for 2 minutes from now', None, at(10, 22, 14, 2), 'none', None, 'alarm'),
    ('set an alarm in 2 minutes', None, at(10, 22, 14, 2), 'none', None, 'alarm'),
    ('set an alarm after 2 minutes', None, at(10, 22, 14, 2), 'none', None, 'alarm'),
    ('set an alarm after 2 minutes from now on', None, at(10, 22, 14, 2), 'none', None, 'alarm'),
    ('wake me up in ten minutes', None, at(10, 22, 14, 10), 'none', None, 'alarm'),
    ('remind me to stretch 2 minutes from now', 'stretch', at(10, 22, 14, 2), 'none', None, 'reminder'),
    ('remind me to stretch after 5 minutes', 'stretch', at(10, 22, 14, 5), 'none', None, 'reminder'),
    # "for" is a time only for an alarm
    ('set an alarm for 30 minutes', None, at(10, 22, 14, 30), 'none', None, 'alarm'),
    ('set an alarm for 7', None, at(10, 23, 7), 'none', None, 'alarm'),
    ('remind me to run for 30 minutes at 6 pm', 'run for 30 minutes', at(10, 22, 18), 'none', None, 'reminder'),
    ('remind me to book a table for 4 at 7 pm', 'book a table for 4', at(10, 22, 19), 'none', None, 'reminder'),
]


@pytest.mark.parametrize('phrase, task, due, recurrence, weekday, kind', PARSES, ids=[p[0] for p in PARSES])
def test_parse_reminder(phrase, task, due, recurrence, weekday, kind):
    from core.reminder_parser import parse_reminder
    request = parse_reminder(phrase, NOW)
    assert request.question is None
    assert (request.task, request.recurrence, request.weekday, request.kind) == (task, recurrence, weekday, kind)
    assert request.due == due
    assert request.due.tzinfo is not None


@pytest.mark.parametrize('phrase, asks', [
    ('remind me to call mom at 5', 'a.m. or p.m.'),
    ('remind me to call mom tomorrow', 'What time'),
    ('set an alarm', 'What time'),
])
def test_ambiguous_or_incomplete_times_ask_instead_of_guessing(phrase, asks):
    from core.reminder_parser import parse_reminder
    request = parse_reminder(phrase, NOW)
    assert request.due is None
    assert asks in request.question


def test_missing_time_asks_when(services, service):
    result = say(services, 'remind me to do something')
    assert result.status == 'pending'
    assert result.messages == ('When should I remind you?',)
    assert result.data == {'task': 'do something'}
    assert pending(service) == []


def test_reminder_path_needs_no_nlp_model():
    import subprocess
    import sys
    from pathlib import Path
    script = (
        "import importlib.abc, sys\n"
        "class Guard(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'spacy', 'torch', 'transformers', 'textblob'} or name == 'utils.nlp_utils':\n"
        "            raise AssertionError(name)\n"
        "sys.meta_path.insert(0, Guard())\n"
        "from core.command_services import CommandServices\n"
        "info = CommandServices().extract_reminder_info('remind me to call mom tomorrow at 9 pm')\n"
        "assert info['task'] == 'call mom' and info['due'] is not None, info\n")
    completed = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr


# --- creating, listing, firing -----------------------------------------------

def test_create_stores_the_parsed_datetime(services, service):
    result = say(services, 'remind me to call mom tomorrow at 9 pm')
    assert result.status == 'handled'
    assert result.messages == ('Reminder set for tomorrow at 9:00 PM: call mom.',)
    [reminder] = pending(service)
    assert (reminder.text, reminder.due, reminder.kind, reminder.recurrence) == ('call mom', at(10, 23, 21), 'reminder', 'none')


def test_list_reads_back_reminders_and_alarms_with_times(services):
    say(services, 'remind me to call mom tomorrow at 9 pm')
    say(services, 'remind me about standup every Monday at 9')
    say(services, 'set an alarm for 7am')
    result = say(services, 'what are my reminders')
    text = ' '.join(result.messages)
    assert result.status == 'handled'
    assert 'call mom, tomorrow at 9:00 PM' in text
    assert 'standup, every Monday at 9:00 AM' in text
    assert 'alarm, tomorrow at 7:00 AM' in text


def test_reminder_fires_once_at_its_time(services, service, clock, spoken):
    say(services, 'remind me to take a break in one hour')
    clock.set(at(10, 22, 14, 59))
    service.run_due()
    assert spoken == []
    clock.set(at(10, 22, 15))
    service.run_due()
    service.run_due()
    assert spoken == ['Sir, this is your reminder: take a break.']
    assert pending(service) == []


def test_alarm_has_distinct_wording(services, service, clock, spoken):
    say(services, 'set an alarm for 7am')
    clock.set(at(10, 23, 7))
    service.run_due()
    assert len(spoken) == 1
    assert 'alarm' in spoken[0] and '7:00 AM' in spoken[0]
    assert 'reminder' not in spoken[0]


def test_deleted_reminder_never_fires(services, service, clock, spoken):
    say(services, 'remind me to take a break in one hour')
    say(services, 'delete my break reminder')
    clock.set(at(10, 22, 15))
    service.run_due()
    assert spoken == []


# --- identity: same text, delete and snooze by target ----------------------------

def test_same_text_reminders_are_independent(services, service, clock, spoken):
    say(services, 'remind me to call mom at 9 pm')
    say(services, 'remind me to call mom tomorrow at 9 pm')
    first, second = sorted(pending(service), key=lambda r: r.due)
    assert first.id != second.id
    clock.set(at(10, 22, 21))
    service.run_due()
    assert spoken == ['Sir, this is your reminder: call mom.']
    assert [r.id for r in pending(service)] == [second.id]
    assert service.store.get(second.id).due == at(10, 23, 21)


def test_delete_affects_only_the_target(services, service):
    say(services, 'remind me to go to the dentist tomorrow at 10 am')
    say(services, 'remind me to call mom tomorrow at 9 pm')
    result = say(services, 'delete my dentist reminder')
    assert result.status == 'handled'
    assert [r.text for r in pending(service)] == ['call mom']


def test_ambiguous_target_reads_back_choices_and_changes_nothing(services, service):
    say(services, 'remind me to call mom at 9 pm')
    say(services, 'remind me to call mom tomorrow at 9 pm')
    result = say(services, 'delete the call mom reminder')
    text = ' '.join(result.messages)
    assert result.status == 'pending'
    assert 'today at 9:00 PM' in text and 'tomorrow at 9:00 PM' in text and 'Which one' in text
    assert len(pending(service)) == 2
    result = say(services, 'delete the call mom reminder tomorrow at 9 pm')
    assert result.status == 'handled'
    [left] = pending(service)
    assert left.due == at(10, 22, 21)


def test_unknown_target_says_so(services, service):
    say(services, 'remind me to call mom at 9 pm')
    result = say(services, 'delete my dentist reminder')
    assert result.status == 'error'
    assert 'dentist' in result.messages[0]
    assert len(pending(service)) == 1


def test_snooze_it_moves_the_fired_reminder_ten_minutes(services, service, clock, spoken):
    say(services, 'remind me to take a break in one hour')
    clock.set(at(10, 22, 15))
    service.run_due()
    result = say(services, 'snooze it for 10 minutes')
    assert result.status == 'handled'
    [snoozed] = pending(service)
    assert snoozed.due == at(10, 22, 15, 10)
    clock.set(at(10, 22, 15, 10))
    service.run_due()
    assert spoken == ['Sir, this is your reminder: take a break.'] * 2


def test_snooze_defaults_to_ten_minutes(services, service, clock):
    say(services, 'remind me to take a break in one hour')
    clock.set(at(10, 22, 15, 2))
    service.run_due()
    say(services, 'snooze that reminder')
    [snoozed] = pending(service)
    assert snoozed.due == at(10, 22, 15, 12)


def test_snooze_moves_only_the_target(services, service):
    say(services, 'remind me to call mom at 4 pm')
    say(services, 'remind me to feed the cat at 5 pm')
    say(services, 'snooze the cat reminder for 20 minutes')
    dues = {r.text: r.due for r in pending(service)}
    assert dues == {'call mom': at(10, 22, 16), 'feed the cat': at(10, 22, 17, 20)}


def test_complete_by_id(service, services):
    say(services, 'remind me to call mom at 9 pm')
    say(services, 'remind me to call mom tomorrow at 9 pm')
    first, second = sorted(pending(service), key=lambda r: r.due)
    service.complete(first.id)
    assert service.store.get(first.id).status == 'done'
    assert service.store.get(second.id).status == 'pending'


def test_alarm_can_be_cancelled(services, service):
    say(services, 'set an alarm for 7am')
    say(services, 'remind me to call mom at 9 pm')
    result = say(services, 'cancel my alarm')
    assert result.status == 'handled'
    assert [r.kind for r in pending(service)] == ['reminder']


# --- recurrence and restarts --------------------------------------------------

def test_daily_reminder_advances_after_firing(services, service, clock, spoken):
    say(services, 'remind me to water plants every day at 8 am')
    clock.set(at(10, 23, 8))
    service.run_due()
    assert spoken == ['Sir, this is your reminder: water plants.']
    [reminder] = pending(service)
    assert reminder.due == at(10, 24, 8)


def test_hourly_reminder_keeps_its_minute(services, service, clock):
    say(services, 'remind me to drink water every hour')
    clock.set(at(10, 22, 15))
    service.run_due()
    [reminder] = pending(service)
    assert reminder.due == at(10, 22, 16)


def test_recurring_reminder_is_restored_after_restart(db_path, clock, spoken, services):
    say(services, 'remind me to water plants every day at 8 am')
    say(services, 'remind me about standup every Monday at 9')
    # The app is off from Thursday afternoon until Tuesday noon (DST ended Sunday).
    clock.set(at(10, 27, 12))
    restarted = make_service(db_path, clock, spoken)
    restarted.startup()
    assert len(spoken) == 2
    assert any('water plants' in s for s in spoken) and any('standup' in s for s in spoken)
    dues = {r.text: r.due for r in pending(restarted)}
    assert dues == {'water plants': at(10, 28, 8), 'standup': at(11, 2, 9)}
    assert dues['water plants'].hour == 8 and dues['standup'].hour == 9
    restarted.startup()
    make_service(db_path, clock, spoken).startup()
    assert len(spoken) == 2


def test_missed_reminder_is_announced_once_at_startup(db_path, clock, spoken, services):
    say(services, 'remind me to call mom at 9 pm')
    clock.set(at(10, 23, 10))
    first = make_service(db_path, clock, spoken)
    first.startup()
    assert len(spoken) == 1 and 'call mom' in spoken[0]
    first.run_due()
    clock.advance(minutes=5)
    make_service(db_path, clock, spoken).startup()
    assert len(spoken) == 1
    assert pending(first) == []


def test_ids_are_stable_across_restarts(db_path, clock, spoken, services, service):
    say(services, 'remind me to call mom tomorrow at 9 pm')
    [before] = pending(service)
    [after] = pending(make_service(db_path, clock, spoken))
    assert (after.id, after.text, after.due) == (before.id, before.text, before.due)


def test_scheduler_waits_until_next_due_but_never_long(services, service, clock):
    assert service.seconds_until_next() == 60
    say(services, 'remind me to take a break in one hour')
    assert service.seconds_until_next() == 60
    clock.set(at(10, 22, 14, 59) + timedelta(seconds=30))
    assert service.seconds_until_next() == 30
    clock.set(at(10, 22, 15, 1))
    assert service.seconds_until_next() == 0


# --- migration from reminders.json ---------------------------------------------

def test_migrates_legacy_json_once_and_keeps_the_file(tmp_path, clock, spoken):
    legacy = tmp_path / 'reminders.json'
    legacy.write_text(json.dumps([
        {'task': 'call my mom', 'time': '2026-11-02 08:20:00', 'recurring': False, 'interval': None, 'completed': False},
        {'task': 'stretch', 'time': '2026-11-01 07:30:00', 'recurring': True, 'interval': 'daily', 'completed': False},
        {'task': 'call my wife', 'time': '2026-01-01 20:28:00', 'recurring': False, 'interval': None, 'completed': True},
    ]))
    original = legacy.read_text()
    db = tmp_path / 'reminders.db'
    from core.reminder_store import ReminderStore
    store = ReminderStore(db, legacy_json=legacy, zone=TZ)
    assert store.migrated == 3
    rows = {r.text: r for r in store.all()}
    assert rows['call my mom'].due == at(11, 2, 8, 20) and rows['call my mom'].status == 'pending'
    assert rows['stretch'].recurrence == 'daily'
    assert rows['call my wife'].status == 'done'
    assert rows['stretch'].due.hour == 7 and rows['stretch'].due.tzinfo is not None
    assert legacy.read_text() == original
    again = ReminderStore(db, legacy_json=legacy, zone=TZ)
    assert again.migrated == 0
    assert len(again.all()) == 3


# --- voice follow-ups: the answer completes the original request -----------------

@pytest.mark.parametrize('first, question, answer, confirmation', [
    ('remind me to call mom', 'When should I remind you?', 'tomorrow at 9 pm',
     'Reminder set for tomorrow at 9:00 PM: call mom.'),
    ('remind me to call mom at 5', 'Did you mean 5 a.m. or p.m.?', 'p.m.',
     'Reminder set for today at 5:00 PM: call mom.'),
    ('set an alarm', 'What time should I set the alarm for?', '7am',
     'Alarm set for tomorrow at 7:00 AM.'),
])
def test_voice_follow_up_completes_the_request(services, service, first, question, answer, confirmation):
    from core.assistant import Assistant
    from core.voice_policy import Recognition
    output = Mock()
    speech = Mock()
    speech.is_speaking.return_value = False
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0)
    assistant.process_recognition(Recognition(first, .95))
    output.assert_called_with(question)
    assert pending(service) == []
    assistant.process_recognition(Recognition(answer, .95))
    output.assert_called_with(confirmation)
    assert len(pending(service)) == 1


@pytest.mark.parametrize('phrase, message', [
    ('remind me to pay rent on December 20 at 9 am', 'Reminder set for Sunday, December 20 at 9:00 AM: pay rent.'),
    ('remind me to drink water every hour', 'Reminder set for every hour on the hour, next today at 3:00 PM: drink water.'),
    ('remind me to water plants every day at 8 am', 'Reminder set for every day at 8:00 AM: water plants.'),
])
def test_confirmation_wording(services, phrase, message):
    assert say(services, phrase).messages == (message,)


def test_long_choice_lists_are_shortened(services):
    for hour in range(15, 22):
        say(services, f'remind me to stretch at {hour}:00')
    text = say(services, 'delete my stretch reminder').messages[0]
    assert 'I found 7 reminders' in text and 'and 2 more' in text


# --- startup summary ------------------------------------------------------------------

def test_startup_summary(services, service):
    assert service.startup_summary() == ''
    say(services, 'set an alarm for 11:26 am')
    assert service.startup_summary() == 'You have 1 pending: alarm today at 11:26 AM.' or \
        service.startup_summary() == 'You have 1 pending: alarm tomorrow at 11:26 AM.'
    say(services, "remind me to drink water at 6 pm")
    summary = service.startup_summary()
    assert summary.startswith('You have 2 pending: ') and "reminder 'drink water' today at 6:00 PM" in summary


def test_startup_summary_with_many_gives_count_and_next(services, service):
    for hour in range(15, 20):
        say(services, f'remind me to stretch at {hour}:00')
    assert service.startup_summary() == "You have 5 pending. The next is reminder 'stretch' today at 3:00 PM."


def test_main_speaks_the_summary_after_restoring(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sys
    import types
    from core import conversation_log, reminder_manager
    monkeypatch.setattr(conversation_log, 'start_logging', lambda: 'test-log')
    monkeypatch.setattr(conversation_log, 'record', Mock())
    monkeypatch.setattr(conversation_log, '_listeners', [])
    spoken = []

    class Assistant:
        output = staticmethod(spoken.append)

        def wait_for_wake_word(self):
            raise StopIteration()

        def close(self):
            pass
    fake = types.ModuleType('core.assistant')
    fake.Assistant = Assistant
    monkeypatch.setitem(sys.modules, 'core.assistant', fake)
    service = Mock()
    service.startup_summary.return_value = 'You have 1 pending: alarm today at 11:26 AM.'
    monkeypatch.setattr(reminder_manager, 'initialize_reminders', lambda: service)
    spec = importlib.util.spec_from_file_location('test_main_summary', Path(__file__).resolve().parents[1] / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(StopIteration):
        module.main()
    assert spoken == ['You have 1 pending: alarm today at 11:26 AM.']
