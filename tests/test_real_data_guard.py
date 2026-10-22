"""Tests and replays cannot write the real data/ or logs/ folders."""
import sqlite3

import pytest

from real_data_guard import ROOT


@pytest.mark.parametrize('name', ['data/reminders.db', 'data/new-file.json', 'logs/conversation.jsonl'])
def test_writes_to_real_folders_are_refused(name):
    with pytest.raises(PermissionError):
        open(ROOT / name, 'a').close()
    with pytest.raises(PermissionError):
        (ROOT / name).write_text('x')


def test_sqlite_on_the_real_database_is_refused():
    with pytest.raises(PermissionError):
        sqlite3.connect(ROOT / 'data' / 'reminders.db')
    with pytest.raises(PermissionError):
        sqlite3.connect('file:data/reminders.db?mode=ro', uri=True)


def test_reading_and_temporary_files_still_work(tmp_path):
    assert (ROOT / 'data' / 'reminders.json').read_bytes()
    (tmp_path / 'x.db').write_text('ok')
    sqlite3.connect(tmp_path / 'y.db').close()


def test_default_reminder_store_is_the_test_copy():
    from core.reminder_store import ReminderStore
    store = ReminderStore()
    assert 'data' not in store.path.parts[-2:-1] and store.path.name == 'reminders.db'
    assert store.path.parent != ROOT / 'data'
