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


@pytest.fixture(autouse=True)
def predictable_phrases(monkeypatch):
    """Tests hear the first variant of each phrase, without a random "sir"."""
    from core import phrases
    monkeypatch.setattr(phrases, '_choose', lambda variants: variants[0])
    monkeypatch.setattr(phrases, '_random', lambda: 1.0)
