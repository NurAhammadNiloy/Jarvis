"""Shared safety net: no test may touch the real data/ or logs/ folders."""
import pytest

from real_data_guard import protect_real_data

# Any write under data/ or logs/ now raises PermissionError instead of happening.
protect_real_data()


@pytest.fixture(autouse=True)
def isolated_reminder_storage(tmp_path, monkeypatch):
    from core import reminder_store
    monkeypatch.setattr(reminder_store, 'DEFAULT_DB', tmp_path / 'reminders.db')
    monkeypatch.setattr(reminder_store, 'LEGACY_JSON', tmp_path / 'no-legacy-reminders.json')
