"""Reminder and alarm scheduling on one thread, with all state in SQLite.

ReminderService runs a single daemon thread that sleeps on a condition until
the earliest pending due time (at most MAX_WAIT_SECONDS, so clock changes and
sleep/resume are noticed) or until a create, delete or snooze wakes it. Each
wake fires every reminder whose time has come: the row is updated first
(one-time -> done, recurring -> its next occurrence) and only then announced,
so nothing is announced twice, even across a crash or restart. Cancelling and
rescheduling are row updates plus a wake-up; there are no per-reminder timer
handles to lose.

Importing this module performs no I/O and starts nothing; main.py calls
initialize_reminders() explicitly.
"""
from datetime import datetime, timedelta, timezone
import re
import threading

from core.command_result import ActionResult
from core.reminder_parser import WEEKDAYS, find_clock, find_day, local_now

MAX_WAIT_SECONDS = 60
LATE_AFTER = timedelta(minutes=5)  # announced as missed rather than on time

_service = None
_initialized = False
_service_lock = threading.Lock()


def _plus(moment, delta):
    """Elapsed-time arithmetic (UTC), so DST changes don't shift the result."""
    return (moment.astimezone(timezone.utc) + delta).astimezone(moment.tzinfo)


def next_occurrence(due, recurrence, weekday, after, zone):
    """First occurrence of the rule strictly after `after`.

    Hourly keeps the minute in elapsed time; daily and weekly keep the local
    wall-clock time, so 08:00 stays 08:00 across a DST change.
    """
    if recurrence == 'hourly':
        start, target, step = due.astimezone(timezone.utc), after.astimezone(timezone.utc), timedelta(hours=1)
        if start > target:
            return due
        return (start + ((target - start) // step + 1) * step).astimezone(zone)
    local = due.astimezone(zone)
    day, step = max(local.date(), after.astimezone(zone).date()), 1
    if recurrence == 'weekly':
        step = 7
        day += timedelta(days=((local.weekday() if weekday is None else weekday) - day.weekday()) % 7)
    candidate = datetime.combine(day, local.time(), tzinfo=zone)
    while candidate <= after:
        day += timedelta(days=step)
        candidate = datetime.combine(day, local.time(), tzinfo=zone)
    return candidate


def clock_text(moment):
    return moment.strftime('%I:%M %p').lstrip('0')


def describe_when(moment, now):
    """'today at 9:00 PM', 'tomorrow at ...', 'on Monday at ...', 'on Sunday, December 20 at ...'."""
    days = (moment.date() - now.date()).days
    if days == 0:
        day = 'today'
    elif days == 1:
        day = 'tomorrow'
    elif 1 < days < 7:
        day = f"on {moment:%A}"
    else:
        day = f"on {moment:%A}, {moment:%B} {moment.day}" + (f", {moment.year}" if moment.year != now.year else '')
    return f"{day} at {clock_text(moment)}"


def describe(reminder, now):
    if reminder.recurrence == 'daily':
        return f"every day at {clock_text(reminder.due)}"
    if reminder.recurrence == 'weekly':
        weekday = reminder.due.weekday() if reminder.weekday is None else reminder.weekday
        return f"every {WEEKDAYS[weekday].title()} at {clock_text(reminder.due)}"
    if reminder.recurrence == 'hourly':
        minute = 'on the hour' if reminder.due.minute == 0 else f"at {reminder.due.minute} minutes past"
        return f"every hour {minute}, next {describe_when(reminder.due, now)}"
    return describe_when(reminder.due, now)


def label(reminder):
    if reminder.kind == 'alarm':
        return f"alarm: {reminder.text}" if reminder.text else 'alarm'
    return reminder.text or 'reminder'


class ReminderService:
    def __init__(self, store, notify, clock=local_now):
        self.store, self.notify, self.clock = store, notify, clock
        self.zone = store.zone
        self._wake = threading.Condition()
        self._fire_lock = threading.Lock()
        self._thread = None
        self._stopping = False
        self._last_fired = None
        self._fired = set()

    def now(self):
        return self.clock().astimezone(self.zone)

    # --- scheduler ---------------------------------------------------------

    def start(self):
        """Announce anything missed while the app was off, then run the thread."""
        self.startup()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='reminders', daemon=True)
            self._thread.start()

    def stop(self):
        with self._wake:
            self._stopping = True
            self._wake.notify_all()

    def startup(self):
        self._fire(missed=True)

    def run_due(self):
        self._fire(missed=False)

    def seconds_until_next(self):
        due = self.store.next_due()
        if due is None:
            return MAX_WAIT_SECONDS
        return max(0, min(MAX_WAIT_SECONDS, (due - self.now()).total_seconds()))

    def _run(self):
        while True:
            with self._wake:
                if self._stopping:
                    return
                self._wake.wait(self.seconds_until_next())
                if self._stopping:
                    return
            try:
                self.run_due()
            except Exception as exc:  # keep the scheduler alive
                from core.conversation_log import record
                record('reminder_scheduler_error', error=type(exc).__name__)

    def _changed(self):
        with self._wake:
            self._wake.notify_all()

    def _fire(self, missed):
        now = self.now()
        fired = []
        with self._fire_lock:
            for reminder in self.store.due(now):
                if reminder.recurrence == 'none':
                    self.store.set_status(reminder.id, 'done')
                else:
                    self.store.set_due(reminder.id, next_occurrence(
                        reminder.due, reminder.recurrence, reminder.weekday, now, self.zone))
                fired.append(reminder)
                self._fired.add(reminder.id)
                self._last_fired = reminder.id
        for reminder in fired:
            try:
                self.notify(self._announcement(reminder, now, missed or now - reminder.due > LATE_AFTER))
            except Exception as exc:  # the row is already updated: never repeat
                from core.conversation_log import record
                record('reminder_notify_failed', reminder_id=reminder.id, error=type(exc).__name__)

    def _announcement(self, reminder, now, missed):
        if reminder.kind == 'alarm':
            if missed:
                return f"While I was offline, your alarm for {describe_when(reminder.due, now)} went off."
            return f"Sir, it's {clock_text(reminder.due)}. This is your alarm." + (
                f" {reminder.text}." if reminder.text else '')
        if missed:
            return f"While I was offline, you missed a reminder {describe_when(reminder.due, now)}: {reminder.text}."
        return f"Sir, this is your reminder: {reminder.text}."

    # --- operations by id --------------------------------------------------

    def create(self, request):
        reminder_id = self.store.add(request['task'], request['due'], request.get('recurrence', 'none'),
                                     request.get('weekday'), request.get('kind', 'reminder'),
                                     created_at=self.now())
        self._changed()
        reminder = self.store.get(reminder_id)
        when = describe(reminder, self.now())
        when = when[3:] if when.startswith('on ') else when  # "set for Sunday", not "for on Sunday"
        if reminder.kind == 'alarm':
            return ActionResult((f"Alarm set for {when}." + (f" {reminder.text}." if reminder.text else ''),))
        return ActionResult((f"Reminder set for {when}: {reminder.text}.",))

    def complete(self, reminder_id):
        self.store.set_status(reminder_id, 'done')
        self._changed()

    def startup_summary(self, limit=3):
        """One sentence about what is pending, or '' (read-only; nothing is changed)."""
        now = self.now()
        items = self.store.pending()
        if not items:
            return ''

        def part(r):
            what = 'alarm' if r.kind == 'alarm' and not r.text else (
                f"alarm '{r.text}'" if r.kind == 'alarm' else f"reminder '{r.text or 'reminder'}'")
            return f"{what} {describe(r, now)}"
        if len(items) > limit:
            return f"You have {len(items)} pending. The next is {part(items[0])}."
        return f"You have {len(items)} pending: " + ', '.join(part(r) for r in items) + '.'

    def list_reminders(self, kind=None):
        now = self.now()
        items = [r for r in self.store.pending() if kind in (None, r.kind)]
        noun = 'alarm' if kind == 'alarm' else 'reminder'
        if not items:
            return ActionResult((f"You have no {noun}s.",))
        heading = f"You have {len(items)} {noun}{'s' if len(items) != 1 else ''}."
        return ActionResult((heading,) + tuple(f"{label(r)}, {describe(r, now)}." for r in items))

    def delete(self, target=None, when_text='', kind=None):
        noun = 'alarm' if kind == 'alarm' else 'reminder'
        matches = self._matches(target, when_text, kind)
        if not matches:
            return self._not_found(target, noun)
        if len(matches) > 1:
            return self._which(matches, noun, 'delete')
        reminder = matches[0]
        self.store.set_status(reminder.id, 'cancelled')
        self._changed()
        return ActionResult((f"Deleted: {label(reminder)}, {describe(reminder, self.now())}.",))

    def snooze(self, target=None, minutes=10, when_text=''):
        now = self.now()
        if target or find_clock(when_text) or find_day(when_text, now):
            matches = self._matches(target, when_text, include_fired=True)
        elif self._last_fired is not None:
            matches = [self.store.get(self._last_fired)]
        else:
            matches = self.store.pending()
        if not matches:
            return self._not_found(target, 'reminder')
        if len(matches) > 1:
            return self._which(matches, 'reminder', 'snooze')
        reminder, delta = matches[0], timedelta(minutes=minutes)
        if reminder.recurrence != 'none':
            # Snoozing one occurrence must not move the whole series.
            due = _plus(now, delta)
            self.store.add(reminder.text, due, 'none', None, reminder.kind, created_at=now)
        else:
            due = _plus(reminder.due if reminder.status == 'pending' and reminder.due > now else now, delta)
            self.store.set_due(reminder.id, due, 'pending')
        self._changed()
        return ActionResult((f"Snoozed for {minutes} minute{'s' if minutes != 1 else ''}. "
                             f"I'll remind you {describe_when(due, now)}.",))

    def _matches(self, target, when_text='', kind=None, include_fired=False):
        now = self.now()
        candidates = self.store.pending()
        if include_fired:
            known = {r.id for r in candidates}
            candidates += [r for r in (self.store.get(i) for i in self._fired)
                           if r and r.id not in known and r.status == 'done']
        if kind:
            candidates = [r for r in candidates if r.kind == kind]
        if target:
            wanted = re.findall(r"\w+", target.lower())
            candidates = [r for r in candidates
                          if all(w in re.findall(r"\w+", (r.text or '').lower()) for w in wanted)]
        clock = find_clock(when_text) if when_text else None
        if clock:
            hour, minute, explicit = clock
            hours = {hour} if explicit else {hour % 12, hour % 12 + 12}
            candidates = [r for r in candidates if r.due.hour in hours and r.due.minute == minute]
        day = find_day(when_text, now) if when_text else None
        if day:
            candidates = [r for r in candidates if r.due.date() == day]
        return candidates

    def _not_found(self, target, noun):
        if target:
            return ActionResult((f"I couldn't find a {noun} about {target}.",), False)
        return ActionResult((f"I couldn't find that {noun}.",), False)

    def _which(self, matches, noun, verb):
        now = self.now()
        options = '; '.join(f"{label(r)}, {describe(r, now)}" for r in matches[:5])
        if len(matches) > 5:
            options += f"; and {len(matches) - 5} more"
        return ActionResult((f"I found {len(matches)} {noun}s: {options}. Which one should I {verb}? "
                             f"Please say it again with the day or time.",), False, pending=True)


def get_service(notify=None):
    """The application's reminder service, created and started on first use."""
    global _service, _initialized
    with _service_lock:
        if _service is None:
            from core.reminder_store import DEFAULT_DB, LEGACY_JSON, ReminderStore
            if notify is None:
                from core.command_output import speak as notify
            store = ReminderStore(DEFAULT_DB, legacy_json=LEGACY_JSON)
            if store.migrated:
                from core.conversation_log import record
                print(f"Migrated {store.migrated} reminders from {LEGACY_JSON.name} to {DEFAULT_DB.name}.")
                record('reminders_migrated', count=store.migrated)
            _service = ReminderService(store, notify)
            _service.start()
            _initialized = True
        return _service


def initialize_reminders(*, notify=None):
    """Explicit startup: open storage, announce missed reminders, start the scheduler."""
    return get_service(notify)
