"""What a parsed command will do, in words: "Start a new 5-minute timer".

Confirmations and either/or questions read this back instead of the transcript,
so what you hear is what will run ("at 5 minutes to pass the timer" is read back
as "Start a new 5-minute timer", not repeated verbatim).
"""
from core.reminder_manager import clock_text, describe_when
from core.reminder_parser import WEEKDAYS, local_now


def duration_words(seconds, adjective=False):
    """'5 minutes' / '5-minute', '1 hour' / '1-hour', '90 seconds' / '90-second'."""
    seconds = int(seconds)
    for size, unit in ((3600, 'hour'), (60, 'minute'), (1, 'second')):
        if seconds % size == 0 and seconds >= size:
            amount = seconds // size
            if adjective:
                return f"{amount}-{unit}"
            return f"{amount} {unit}{'s' if amount != 1 else ''}"
    return f"{seconds}-second" if adjective else f"{seconds} seconds"


def _the_timer(label):
    return f"the {label.lower()} timer" if label else 'the timer'


def describe_command(command, now=None):
    """A short imperative phrase for what `command` will do, without a final period."""
    intent, args = command.intent, command.arguments
    label = args.get('label')
    seconds = (args.get('duration') or (None, None))[0]
    if intent == 'start_timer':
        if seconds:
            return f"Start a new {duration_words(seconds, True)} {label.lower() + ' ' if label else ''}timer"
        return f"Start a {label.lower() + ' ' if label else ''}timer"
    if intent == 'add_timer_time':
        return f"Add {duration_words(seconds)} to {_the_timer(label)}" if seconds else f"Add time to {_the_timer(label)}"
    if intent in ('pause_timer', 'resume_timer', 'cancel_timer'):
        verb = {'pause_timer': 'Pause', 'resume_timer': 'Resume', 'cancel_timer': 'Cancel'}[intent]
        return f"{verb} {_the_timer(label)}"
    if intent == 'cancel_all_timers':
        return 'Cancel all timers'
    if intent == 'timer_status':
        return 'Check the timers'
    if intent == 'pomodoro':
        return 'Start a pomodoro'
    if intent in ('create_reminder', 'alarm') and args.get('operation', 'create') == 'create':
        return _describe_new(args, now)
    if intent == 'alarm' and args.get('operation') == 'delete':
        return 'Delete the alarm'
    if intent == 'alarm':
        return 'List your alarms'
    if intent == 'delete_reminder':
        return f"Delete the {args['target']} reminder" if args.get('target') else 'Delete that reminder'
    if intent == 'snooze_reminder':
        minutes = args.get('minutes', 10)
        what = f"the {args['target']} reminder" if args.get('target') else 'the reminder'
        return f"Snooze {what} for {minutes} minute{'s' if minutes != 1 else ''}"
    if intent == 'list_reminders':
        return 'List your reminders'
    if intent == 'weather':
        return f"Get the weather in {args['city']}" if args.get('city') else 'Get the weather'
    if intent == 'forecast':
        return f"Get the forecast for {args['city']}" if args.get('city') else 'Get the forecast'
    if intent in ('time', 'date'):
        return f"Tell you the {intent}"
    if intent == 'youtube':
        return f"Play {args['topic']} on YouTube" if args.get('topic') else 'Open YouTube'
    if intent == 'google':
        return 'Open Google'
    return command.query[:1].upper() + command.query[1:].rstrip('.!?')


def _describe_new(args, now):
    alarm = args.get('kind') == 'alarm'
    due, task = args.get('due'), args.get('task')
    noun = 'alarm' if alarm else 'reminder'
    recurrence = args.get('recurrence', 'none')
    if due is None:
        return f"Set an {noun}" if alarm else f"Set a reminder: {task}" if task else 'Set a reminder'
    now = now or local_now()
    if recurrence == 'weekly':
        weekday = due.weekday() if args.get('weekday') is None else args['weekday']
        when = f"{WEEKDAYS[weekday].title()}s at {clock_text(due)}"
        text = f"Set a weekly {noun}, {when}"
    elif recurrence == 'daily':
        text = f"Set a daily {noun} at {clock_text(due)}"
    elif recurrence == 'hourly':
        text = f"Set an hourly {noun}"
    else:
        text = f"Set {'an' if alarm else 'a'} {noun} for {describe_when(due, now)}"
    return spoken_times(text) + (f": {task}" if task else '')


def spoken_times(text):
    """'9:00 AM' -> '9 AM': how people say it."""
    return text.replace(':00 AM', ' AM').replace(':00 PM', ' PM')
