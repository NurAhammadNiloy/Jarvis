"""Local, append-only diagnostic events; inactive until application startup."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
import uuid

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'logs' / 'conversation.jsonl'


class ConversationLog:
    def __init__(self, path):
        self.path = Path(path)
        self.session = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._sequence = 0
        self._warned = False

    def record(self, event, **fields):
        # File I/O never takes place on a PortAudio callback. A failure to log
        # must not stop listening, command execution, or output cancellation.
        with self._lock:
            try:
                self._sequence += 1
                entry = dict(fields, event=event, session=self.session,
                    sequence=self._sequence,
                    timestamp=datetime.now(timezone.utc).isoformat())
                line = json.dumps(entry, ensure_ascii=False, allow_nan=False)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(line + '\n')
            except (OSError, TypeError, ValueError):
                if not self._warned:
                    logging.getLogger(__name__).warning('Conversation log could not be written')
                    self._warned = True


_log = None
_listeners = []


def start_logging(path=DEFAULT_PATH):
    global _log
    _log = ConversationLog(path)
    record('session_started')
    return _log.path


def add_listener(listener):
    """Call listener(event, fields) for every recorded event (e.g. live transcripts)."""
    _listeners.append(listener)


def remove_listener(listener):
    if listener in _listeners:
        _listeners.remove(listener)


def record(event, **fields):
    if _log is not None:
        _log.record(event, **fields)
    for listener in list(_listeners):
        try:
            listener(event, fields)
        except Exception:  # a listener must never affect the assistant
            pass


def record_recognition(result, *, partial=False):
    record('recognition', role='user', partial=partial, **asdict(result))
