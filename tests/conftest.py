"""Shared safety net: no test may touch the real data/reminders.db or reminders.json."""
import pytest


@pytest.fixture(autouse=True)
def isolated_reminder_storage(tmp_path, monkeypatch):
    from core import reminder_store
    monkeypatch.setattr(reminder_store, 'DEFAULT_DB', tmp_path / 'reminders.db')
    monkeypatch.setattr(reminder_store, 'LEGACY_JSON', tmp_path / 'no-legacy-reminders.json')
