"""Refuse writes to the real data/ and logs/ folders from tests and replay tools.

An audit hook sees every file open (builtins, pathlib, os.open), every
sqlite3.connect and every rename/remove, whatever code path makes them. A
replay script must call protect_real_data() before importing Jarvis modules.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = tuple(os.path.normcase(str(ROOT / name)) + os.sep for name in ('data', 'logs'))
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_installed = False


def is_protected(path):
    if isinstance(path, int) or path is None:
        return False
    path = os.fsdecode(os.fspath(path))
    if path.startswith('file:'):  # sqlite URI
        path = path[5:].split('?')[0]
    if not path or path == ':memory:':
        return False
    return os.path.normcase(os.path.abspath(path)).startswith(PROTECTED)


def _hook(event, args):
    if event == 'open':
        path, mode, flags = args
        writing = any(c in mode for c in 'wax+') if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
        targets = (path,) if writing else ()
    elif event == 'sqlite3.connect':  # sqlite writes journals even when "reading"
        targets = args[:1]
    elif event in ('os.remove', 'os.rmdir'):
        targets = args[:1]
    elif event == 'os.rename':
        targets = args[:2]
    else:
        return
    for target in targets:
        if is_protected(target):
            raise PermissionError(f'Tests and replays must not write the real {target}')


def protect_real_data():
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
