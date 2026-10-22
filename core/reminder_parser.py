"""Reminder and alarm requests -> one timezone-aware due datetime.

Regex finds the time, date, relative offset and recurrence; dateparser only
resolves explicit calendar dates ("December 20"). The result carries the
resolved datetime, so nothing downstream parses a string again. Ambiguous or
missing times produce a question instead of a guess.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re
from typing import Optional

from core.smart_timer import _words_to_digits

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
_WEEKDAY = r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_HOUR_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
               'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12}
_HOUR = r"(?P<h>\d{1,2}|" + '|'.join(_HOUR_WORDS) + r")"
_MERIDIEM = r"(?P<ap>[ap])\.?\s?m\b\.?"
_MINUTE_WORDS = {'fifteen': 15, 'thirty': 30, 'forty five': 45, 'forty-five': 45}


def local_zone():
    """Zone for reminders: settings.TIMEZONE, else the system zone."""
    from config.settings import TIMEZONE
    if TIMEZONE:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    try:
        from tzlocal import get_localzone
        return get_localzone()
    except Exception:
        return datetime.now().astimezone().tzinfo


def local_now():
    return datetime.now(local_zone()).replace(microsecond=0)


@dataclass(frozen=True)
class ReminderRequest:
    task: Optional[str]
    due: Optional[datetime]
    recurrence: str = 'none'       # none / hourly / daily / weekly
    weekday: Optional[int] = None  # 0 = Monday, for weekly
    kind: str = 'reminder'         # reminder / alarm
    question: Optional[str] = None  # asked instead of guessing


_PREFIX = re.compile(
    r"^\W*(?:(?:hey|ok|okay)\s+)?(?:jarvis\W+)?(?:(?:can|could|would|will)\s+you\s+|please\s+)*"
    r"(?:remind\s+(?:me|us)|(?:set|create|add|make)\s+(?:(?:a|an|another|new)\s+)*(?:reminder|alarm)"
    r"|wake\s+me(?:\s+up)?)\b", re.IGNORECASE)
_ALARM = re.compile(r"\balarms?\b|\bwake\s+me\b", re.IGNORECASE)

_RECURRENCES = (
    ('weekly', re.compile(r"\b(?:every|each)\s+" + _WEEKDAY + r"s?\b|\bon\s+" + _WEEKDAY.replace('wd', 'wd2') + r"s\b", re.IGNORECASE)),
    ('daily', re.compile(r"\b(?:every\s*day|each\s+day|daily|every\s+(?P<part>morning|evening|night))\b", re.IGNORECASE)),
    ('hourly', re.compile(r"\b(?:every|each)\s+hour\b|\bhourly\b", re.IGNORECASE)),
    ('weekly', re.compile(r"\b(?:every|each)\s+week\b|\bweekly\b", re.IGNORECASE)),
)
_RELATIVE = re.compile(
    r"\bin\s+(?P<amount>\d+(?:\.\d+)?|an?|half\s+an?|a\s+couple\s+of|a\s+few|"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
    r"\s+(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b", re.IGNORECASE)
_CLOCKS = (
    re.compile(r"\b(?:at\s+|for\s+|by\s+)?" + _HOUR + r"(?:[:.](?P<m>\d{2}))?\s*" + _MERIDIEM, re.IGNORECASE),
    re.compile(r"\b(?:at\s+|for\s+|by\s+)?(?P<h>\d{1,2}):(?P<m>\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?:at|by)\s+" + _HOUR + r"(?:\s+(?P<mw>o['’]?clock|fifteen|thirty|forty[\s-]five))?\b"
               r"(?:\s*" + _MERIDIEM + r")?", re.IGNORECASE),
    re.compile(r"\b(?:at\s+)?(?P<word>noon|midday|midnight)\b", re.IGNORECASE),
)
_DATES = (
    ('day_after', re.compile(r"\b(?:the\s+)?day\s+after\s+tomorrow\b", re.IGNORECASE)),
    ('tomorrow', re.compile(r"\btomorrow\b", re.IGNORECASE)),
    ('today', re.compile(r"\b(?:today|tonight)\b", re.IGNORECASE)),
    ('calendar', re.compile(r"\b(?:on\s+)?(?:the\s+)?(?:" + _MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r")(?:,?\s+\d{4})?\b", re.IGNORECASE)),
    ('weekday', re.compile(r"\b(?:on\s+|next\s+|this\s+|coming\s+)?" + _WEEKDAY + r"\b", re.IGNORECASE)),
)
_PM_HINT = re.compile(r"\b(?:tonight|evening|afternoon|night)\b", re.IGNORECASE)
_AM_HINT = re.compile(r"\b(?:morning|wake\s+me)\b", re.IGNORECASE)
_PART_OF_DAY = re.compile(r"\b(?:in\s+the\s+|this\s+)?(?:morning|afternoon|evening)\b", re.IGNORECASE)
_EDGE_WORDS = re.compile(r"^(?:(?:to|about|that|of|at|on|in|for|by|and|me)\b\W*)+|(?:\W*\b(?:to|about|at|on|in|for|by|and|from now))+\W*$",
                         re.IGNORECASE)


class _Text:
    """The request text; consumed spans are blanked so positions stay valid."""

    def __init__(self, text):
        self.original = text
        self.working = text

    def take(self, pattern):
        match = pattern.search(self.working)
        if match:
            self.working = self.working[:match.start()] + ' ' * (match.end() - match.start()) + self.working[match.end():]
        return match

    def remainder(self):
        task = ' '.join(re.sub(r"[?!.,;\"]", ' ', self.working).split())
        while True:
            shorter = _EDGE_WORDS.sub('', task).strip()
            if shorter == task:
                return task or None
            task = shorter


def _number(text):
    text = text.lower().strip()
    special = {'a': 1, 'an': 1, 'half a': .5, 'half an': .5, 'a couple of': 2, 'a few': 3}
    if text in special:
        return special[text]
    return float(_words_to_digits(text).replace(' ', ''))


def _clock(text):
    """(hour, minute, explicit_meridiem) or None. Hour is 0-23 only when explicit."""
    for pattern in _CLOCKS:
        match = text.take(pattern)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get('word'):
            return (0 if groups['word'].lower() == 'midnight' else 12), 0, True
        hour = groups['h']
        hour = _HOUR_WORDS[hour.lower()] if hour.lower() in _HOUR_WORDS else int(hour)
        minute = int(groups['m']) if groups.get('m') else 0
        if groups.get('mw'):
            minute = _MINUTE_WORDS.get(re.sub(r"\s+", ' ', groups['mw'].lower()).replace(' ', '-'),
                                       _MINUTE_WORDS.get(groups['mw'].lower(), 0))
        if hour > 23 or minute > 59:
            return None
        meridiem = (groups.get('ap') or '').lower()
        if meridiem:
            if hour > 12:
                return None
            hour = hour % 12 + (12 if meridiem == 'p' else 0)
            return hour, minute, True
        return hour, minute, hour == 0 or hour >= 13
    return None


def _resolve_hour(hour, explicit, text):
    """Bare 7-11 are morning and 12 is noon; 1-6 without a.m./p.m. is ambiguous."""
    if explicit:
        return hour
    if _PM_HINT.search(text):
        return hour % 12 + 12
    if _AM_HINT.search(text):
        return hour % 12
    if 7 <= hour <= 12:
        return hour
    return None


def _calendar_date(span, now):
    import dateparser
    parsed = dateparser.parse(
        span, languages=['en'],
        settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': now.replace(tzinfo=None),
                  'PREFER_DAY_OF_MONTH': 'first', 'REQUIRE_PARTS': ['day', 'month']})
    return parsed.date() if parsed else None


def _next_weekday(start, weekday):
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _at(day, hour, minute, zone):
    return datetime.combine(day, time(hour, minute), tzinfo=zone)


def parse_reminder(text, now):
    """Parse once. `now` must be timezone-aware; its zone is used for the result."""
    zone = now.tzinfo
    source = _Text(text)
    prefix = source.take(_PREFIX)
    kind = 'alarm' if prefix and _ALARM.search(prefix.group(0)) else 'reminder'
    noun = 'alarm' if kind == 'alarm' else 'reminder'

    recurrence, weekday = 'none', None
    for name, pattern in _RECURRENCES:
        match = source.take(pattern)
        if match:
            recurrence = name
            day_name = match.groupdict().get('wd') or match.groupdict().get('wd2')
            weekday = WEEKDAYS.index(day_name.lower()) if day_name else None
            break

    relative = source.take(_RELATIVE)
    clock = _clock(source)
    date_kind, date_value = None, None
    for name, pattern in _DATES:
        match = source.take(pattern)
        if match:
            date_kind = name
            if name == 'calendar':
                date_value = _calendar_date(match.group(0), now)
            elif name == 'weekday':
                date_value = WEEKDAYS.index(match.group('wd').lower())
            break
    source.take(_PART_OF_DAY)
    task = None if kind == 'alarm' and not _has_words(source.remainder()) else source.remainder()

    def ask(question):
        return ReminderRequest(task, None, recurrence, weekday, kind, question)

    # A relative offset: "in one hour", "in 2 days".
    if relative:
        amount, unit = _number(relative.group('amount')), relative.group('unit').lower()
        if unit.startswith(('day', 'week')):
            days = amount * (7 if unit.startswith('week') else 1)
            day = now.date() + timedelta(days=int(days))
            if not clock:
                return ask(f"What time should I set the {noun} for?")
            hour = _resolve_hour(clock[0], clock[2], text)
            if hour is None:
                return ask(_meridiem_question(clock))
            return ReminderRequest(task, _at(day, hour, clock[1], zone), recurrence, weekday, kind)
        seconds = amount * {'s': 1, 'm': 60, 'h': 3600}[unit[0]]
        if seconds <= 0:
            return ask(f"When should I set the {noun} for?")
        due = (now + timedelta(seconds=seconds)).replace(microsecond=0)
        return ReminderRequest(task, due, recurrence, weekday, kind)

    if recurrence == 'hourly':
        minute = clock[1] if clock else now.minute
        due = now.replace(minute=minute, second=0, microsecond=0)
        while due <= now:
            due += timedelta(hours=1)
        return ReminderRequest(task, due, recurrence, None, kind)

    if not clock:
        if date_kind or recurrence != 'none' or kind == 'alarm':
            return ask(f"What time should I set the {noun} for?")
        return ReminderRequest(task, None, recurrence, weekday, kind)
    hour = _resolve_hour(clock[0], clock[2], text)
    if hour is None:
        return ask(_meridiem_question(clock))
    minute = clock[1]

    today = now.date()
    if recurrence == 'weekly':
        if weekday is None:
            weekday = date_value if date_kind == 'weekday' else today.weekday()
        due = _at(_next_weekday(today, weekday), hour, minute, zone)
        if due <= now:
            due = _at(_next_weekday(today, weekday) + timedelta(days=7), hour, minute, zone)
        return ReminderRequest(task, due, recurrence, weekday, kind)

    if date_kind == 'calendar':
        if date_value is None:
            return ask(f"Which date should I set the {noun} for?")
        due = _at(date_value, hour, minute, zone)
    elif date_kind == 'weekday':
        due = _at(_next_weekday(today, date_value), hour, minute, zone)
        if due <= now:
            due = _at(_next_weekday(today, date_value) + timedelta(days=7), hour, minute, zone)
    elif date_kind in ('tomorrow', 'day_after'):
        due = _at(today + timedelta(days=1 if date_kind == 'tomorrow' else 2), hour, minute, zone)
    else:
        due = _at(today, hour, minute, zone)
        if due <= now:
            if date_kind == 'today':
                return ask(f"That time has already passed today. When should I set the {noun} for?")
            due = _at(today + timedelta(days=1), hour, minute, zone)
    if due <= now:
        return ask(f"That time has already passed. When should I set the {noun} for?")
    return ReminderRequest(task, due, recurrence, weekday, kind)


def _meridiem_question(clock):
    spoken = f"{clock[0]}:{clock[1]:02d}" if clock[1] else str(clock[0])
    return f"Did you mean {spoken} a.m. or p.m.?"


def _has_words(text):
    return bool(text and re.search(r"[a-z]", text, re.IGNORECASE))


def find_clock(text):
    """(hour, minute, explicit) in a command such as 'delete the 9 pm reminder'."""
    return _clock(_Text(text))


def find_day(text, now):
    """The calendar date a command refers to (today/tomorrow/weekday/date), or None."""
    source = _Text(text)
    for name, pattern in _DATES:
        match = source.take(pattern)
        if not match:
            continue
        today = now.date()
        if name == 'today':
            return today
        if name == 'tomorrow':
            return today + timedelta(days=1)
        if name == 'day_after':
            return today + timedelta(days=2)
        if name == 'weekday':
            return _next_weekday(today, WEEKDAYS.index(match.group('wd').lower()))
        return _calendar_date(match.group(0), now)
    return None


_LENGTH = re.compile(r"\bfor\s+(?P<span>.+?\b(?:seconds?|secs?|minutes?|mins?|hours?|hrs?))\b", re.IGNORECASE)


def snooze_minutes(text, default=10):
    """Snooze length in minutes from 'for 10 minutes' / 'for an hour'."""
    from core.smart_timer import SmartTimerManager
    match = _LENGTH.search(text)
    if not match:
        return default
    span = re.sub(r"\ban?\s+(hour|minute|second)", r"1 \1", match.group('span'), flags=re.IGNORECASE)
    seconds, _ = SmartTimerManager.parse_duration(span)
    if not seconds or seconds <= 0:
        return default
    return max(1, round(seconds / 60))
