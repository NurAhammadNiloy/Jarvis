"""SQLite storage for reminders and alarms (data/reminders.db).

Times are stored as UTC ISO-8601 and returned as aware datetimes in the
store's zone. Ids are AUTOINCREMENT, so they are never reused. Every call
opens its own short connection, which keeps the store safe to use from the
scheduler thread and the conversation thread.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Optional

DATA_DIR = Path(__file__).resolve().parents[1] / 'data'
DEFAULT_DB = DATA_DIR / 'reminders.db'
LEGACY_JSON = DATA_DIR / 'reminders.json'

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    due_at TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'none' CHECK (recurrence IN ('none', 'hourly', 'daily', 'weekly')),
    weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
    kind TEXT NOT NULL DEFAULT 'reminder' CHECK (kind IN ('reminder', 'alarm')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reminders_pending_due ON reminders (status, due_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_COLUMNS = 'id, text, due_at, recurrence, weekday, kind, status, created_at'


@dataclass(frozen=True)
class Reminder:
    id: int
    text: Optional[str]
    due: datetime
    recurrence: str
    weekday: Optional[int]
    kind: str
    status: str
    created_at: datetime


def _utc(moment):
    return moment.astimezone(timezone.utc).isoformat()


class ReminderStore:
    def __init__(self, path=None, legacy_json=None, zone=None):
        if zone is None:
            from core.reminder_parser import local_zone
            zone = local_zone()
        # Resolved now, not at import, so a redirected DEFAULT_DB (tests) applies.
        self.path, self.zone = Path(path if path is not None else DEFAULT_DB), zone
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(SCHEMA)
        self.migrated = self._migrate(Path(legacy_json)) if legacy_json else 0

    def _connection(self):
        return _Transaction(self.path, self._lock)

    def _row(self, row):
        rid, text, due_at, recurrence, weekday, kind, status, created_at = row
        return Reminder(rid, text, datetime.fromisoformat(due_at).astimezone(self.zone), recurrence,
                        weekday, kind, status, datetime.fromisoformat(created_at).astimezone(self.zone))

    def add(self, text, due, recurrence='none', weekday=None, kind='reminder', status='pending', created_at=None):
        created_at = created_at or datetime.now(timezone.utc)
        with self._connection() as conn:
            return conn.execute(
                f'INSERT INTO reminders ({_COLUMNS[4:]}) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (text, _utc(due), recurrence, weekday, kind, status, _utc(created_at))).lastrowid

    def get(self, reminder_id):
        with self._connection() as conn:
            row = conn.execute(f'SELECT {_COLUMNS} FROM reminders WHERE id = ?', (reminder_id,)).fetchone()
        return self._row(row) if row else None

    def all(self):
        with self._connection() as conn:
            rows = conn.execute(f'SELECT {_COLUMNS} FROM reminders ORDER BY due_at, id').fetchall()
        return [self._row(row) for row in rows]

    def pending(self):
        with self._connection() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM reminders WHERE status = 'pending' "
                                'ORDER BY due_at, id').fetchall()
        return [self._row(row) for row in rows]

    def due(self, now):
        """Pending reminders whose time has come, earliest first."""
        with self._connection() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM reminders WHERE status = 'pending' AND due_at <= ? "
                                'ORDER BY due_at, id', (_utc(now),)).fetchall()
        return [self._row(row) for row in rows]

    def next_due(self):
        with self._connection() as conn:
            row = conn.execute("SELECT MIN(due_at) FROM reminders WHERE status = 'pending'").fetchone()
        return datetime.fromisoformat(row[0]).astimezone(self.zone) if row and row[0] else None

    def set_status(self, reminder_id, status):
        with self._connection() as conn:
            conn.execute('UPDATE reminders SET status = ? WHERE id = ?', (status, reminder_id))

    def set_due(self, reminder_id, due, status='pending'):
        with self._connection() as conn:
            conn.execute('UPDATE reminders SET due_at = ?, status = ? WHERE id = ?', (_utc(due), status, reminder_id))

    def _migrate(self, legacy_json):
        """Import data/reminders.json once. The JSON file is left untouched."""
        if not legacy_json.exists():
            return 0
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM meta WHERE key = 'legacy_json_migrated'").fetchone():
                return 0
            try:
                entries = json.loads(legacy_json.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                entries = []
            count = 0
            now = _utc(datetime.now(timezone.utc))
            for entry in entries if isinstance(entries, list) else []:
                try:
                    due = datetime.strptime(entry['time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=self.zone)
                except (KeyError, TypeError, ValueError):
                    continue
                interval = entry.get('interval') if entry.get('recurring') else None
                recurrence = interval if interval in ('hourly', 'daily', 'weekly') else 'none'
                conn.execute(
                    f'INSERT INTO reminders ({_COLUMNS[4:]}) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (entry.get('task'), _utc(due), recurrence, due.weekday() if recurrence == 'weekly' else None,
                     'reminder', 'done' if entry.get('completed') else 'pending', now))
                count += 1
            conn.execute("INSERT INTO meta (key, value) VALUES ('legacy_json_migrated', ?)",
                         (json.dumps({'source': str(legacy_json), 'count': count, 'at': now}),))
        return count


class _Transaction:
    """One locked connection; commits on success, rolls back on error."""

    def __init__(self, path, lock):
        self.path, self.lock = path, lock

    def __enter__(self):
        self.lock.acquire()
        try:
            self.conn = sqlite3.connect(self.path)
        except Exception:
            self.lock.release()
            raise
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            with closing(self.conn):
                if exc_type is None:
                    self.conn.commit()
                else:
                    self.conn.rollback()
        finally:
            self.lock.release()
