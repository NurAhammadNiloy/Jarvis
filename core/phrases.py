"""Everything Jarvis says in fixed words, in one place. Edit freely.

Each entry is a list of variants; one is picked at random each time, so common
replies don't sound canned. {name} placeholders are filled in by the code; keep
the same names when you rewrite a line.

Style: short, warm and natural, like a capable human assistant with a light
JARVIS touch. Most action replies stay under eight words. Say what was done,
not what you heard. No filler ("I'll keep an eye on it for you", "Let me know if
there's anything else").
"""
import random

# Roughly how often a reply that allows it gets a "sir" (1 in 5).
SIR_RATE = 0.2

PHRASES = {
    # --- conversation -------------------------------------------------------
    'greeting': ['Yes?', 'How can I help?', "I'm listening.", 'At your service.'],
    'not_heard': ['Sorry?', 'Say again?', 'Come again?'],
    'not_heard_then': ['Sorry? {question}', 'Say again? {question}'],
    'repeat_please': ['Sorry, say that again?', 'Say that once more?', 'One more time?'],
    'incomplete': ['Sorry, I missed the end. Again?', 'You cut out. Again?'],
    'cancelled': ['Cancelled.', 'Okay, cancelled.', 'Never mind, then.'],
    'okay': ['Okay.', 'Alright.', 'Sure.'],
    'what_to_do': ['What should I do?', 'What do you need?'],
    'model_failed': ['Sorry, I lost my train of thought. Say that again?'],
    'claim_fallback': ["I haven't done that yet. What should I do?"],
    'cannot_work_out': ['Sorry, I didn\'t get what to do. Say it again?'],
    'reask': ['Sorry? Should I go ahead?'],          # must never contain "yes"
    'declined': ["Okay, I won't.", 'Okay, leaving it.'],
    'which_one': ['Sorry, which one? {question}'],
    'which_timer': ['Which one: {timers}?'],
    'not_sure_then': ['Sorry? {question}', 'Didn\'t catch that. {question}'],
    'wont_act': ["I won't do that. What do you want?"],
    'control_what': ['{verb} what?'],
    'mean_timer': ['A timer?'],
    'repeat_to_confirm': ['{text}? Say it again to confirm.'],
    'thanks': ["You're welcome.", 'Anytime.', 'Happy to help.', 'My pleasure.'],

    # --- undo -----------------------------------------------------------------
    'undone': ['Undone.'],
    'nothing_to_undo': ['Nothing to undo.', "There's nothing to undo."],
    'cannot_undo': ["Sorry, I can't undo that."],
    'undo_failed': ["Sorry, I couldn't undo that."],

    # --- playback I can't control ---------------------------------------------
    'no_media_control': ["I can't control YouTube playback yet."],

    # --- time and date --------------------------------------------------------
    'time': ["It's {time}.", '{time}.'],
    'date_today': ["It's {date}.", 'Today is {date}.'],
    'date_tomorrow': ['Tomorrow is {date}.'],
    'date_yesterday': ['Yesterday was {date}.'],
    'date_day_after': ['The day after tomorrow is {date}.'],

    # --- weather and follow-ups ---------------------------------------------
    'which_city': ['Which city?', 'For which city?'],
    'glad': ['Glad to help.', 'Good.'],
    'play_what': ['What should I play?'],
    'enjoy': ['Enjoy.', 'Enjoy it.'],
    'more_about_what': ['More about what?'],

    # --- web --------------------------------------------------------------------
    'playing': ['Playing {topic}.', 'Here’s {topic}.'],
    'opening_youtube': ['Opening YouTube.'],
    'youtube_not_found': ["Couldn't find {topic} on YouTube."],
    'opening_google': ['Opening Google.', 'Google, coming up.'],
    'no_browser': ["I couldn't open your browser."],

    # --- timers -----------------------------------------------------------------
    'timer_set': ['{name} timer, {duration}.', '{duration} on the {name} timer.', '{name} timer started: {duration}.'],
    'timer_set_plain': ['Timer, {duration}.', '{duration}, starting now.', 'Timer set: {duration}.'],
    'timer_paused': ['Paused. {left} left.', '{name} paused, {left} left.'],
    'timer_resumed': ['Resumed. {left} left.', 'Back on: {left} to go.'],
    'timer_cancelled': ['{name} timer cancelled.', 'Cancelled the {name} timer.'],
    'timer_cancelled_plain': ['Timer cancelled.', 'Cancelled.'],
    'timers_all_cancelled': ['All {count} timers cancelled.', 'Cancelled all {count} timers.'],
    'no_timers': ['No timers running.', 'There are no timers.'],
    'time_added': ['Added {duration} to {name}.', '{name}: {duration} more.'],
    'time_added_plain': ['Added {duration}.', '{duration} more on the timer.'],
    'timer_status': ['{name}: {left} left.', '{left} left on {name}.'],
    'timer_status_plain': ['{left} left.', '{left} to go.'],
    'timer_status_paused': ['{name} is paused, {left} left.'],
    'timer_status_many': ['{count} timers: {list}.'],
    'timer_done': ["{name}'s done.", 'Your {name} timer is up.'],
    'timer_done_plain': ["Time's up.", "Timer's done."],
    'timer_milestone': ['{name}: {message}.'],
    'timer_milestone_plain': ['Timer: {message}.'],
    'timer_which': ['You have multiple timers. Which one should I {verb}?'],  # the code matches this wording
    'timer_not_found': ["I can't find {what}."],
    'timer_not_running': ["That timer isn't running."],
    'timer_not_paused': ["That timer isn't paused."],
    'timer_none_to': ['No timers to {verb}.'],
    'timer_no_duration': ['For how long?', 'How long should it run?'],
    'timer_zero': ['A timer needs more than zero time.'],
    'add_how_much': ['How much time should I add?'],
    'timer_next': ['Next timer starting.'],
    'pomodoro_started': ['Pomodoro {number}: focus for {work} minutes, then a {rest}-minute {kind}.'],
    'all_timers_cancelled': ['All timers cancelled.'],
    'timers_keep_running': ['Okay, they keep running.'],

    # --- reminders and alarms ---------------------------------------------------
    'reminder_set': ['Done, reminding you {when}: {task}.', 'Got it: {task} {when}.', 'Reminder set: {task} {when}.'],
    'alarm_set': ['Alarm set for {when}.', 'Done, alarm for {when}.'],
    'alarm_set_named': ['Alarm set for {when}: {label}.'],
    'reminder_due': ['Time to {task}.', 'Reminder: {task}.'],
    'reminder_due_noun': ['Reminder: {task}.', 'Heads up: {task}.'],
    'reminder_due_plain': ["Here's your reminder."],
    'alarm_due': ["It's {time} — your alarm."],
    'alarm_due_named': ["It's {time} — your alarm: {label}."],
    'reminder_missed': ['While I was off, you missed a reminder {when}: {task}.'],
    'alarm_missed': ['While I was off, your alarm {when} went off.'],
    'no_reminders': ['No {noun}s.', "You don't have any {noun}s."],
    'reminders_heading': ['{count} {noun}{s}:', 'You have {count} {noun}{s}:'],
    'reminder_deleted': ['Deleted: {label}, {when}.'],
    'reminder_snoozed': ["Snoozed. I'll remind you {when}.", 'Snoozed until {time}.'],
    'reminder_not_found': ["I can't find a {noun} about {target}."],
    'reminder_not_found_plain': ["I can't find that {noun}."],
    'reminder_which': ['I found {count} {noun}s: {options}. Which one should I {verb}?'],
    # Questions about a missing time: keep ONE variant each - the code compares a
    # new question with the one it asked to see whether an answer made progress.
    'ask_reminder_time': ['When should I remind you?'],
    'ask_reminder_task': ['What should I remind you about?'],
    'ask_alarm_time': ['What time should I set the alarm for?'],
    'ask_time_for': ['What time should I set the {noun} for?'],
    'ask_when_for': ['When should I set the {noun} for?'],
    'ask_date_for': ['Which date should I set the {noun} for?'],
    'time_passed_today': ['That time has already passed today. When should I set the {noun} for?'],
    'time_passed': ['That time has already passed. When should I set the {noun} for?'],
    'am_or_pm': ['Did you mean {time} a.m. or p.m.?'],
    'reminder_unclear': ["Sorry, what's the reminder, and when?"],
    'startup_pending': ['You have {count} pending: {items}.'],
    'startup_pending_many': ['You have {count} pending. The next is {item}.'],
}

# Replies that may get a "sir" now and then.
SIR_OK = {'greeting', 'timer_set', 'timer_set_plain', 'reminder_set', 'alarm_set', 'timer_done',
          'timer_done_plain', 'reminder_due', 'reminder_due_noun', 'alarm_due', 'thanks', 'okay',
          'cancelled', 'opening_google', 'playing'}

_choose = random.choice
_random = random.random


def say(key, **values):
    """One variant of a phrase with its placeholders filled in."""
    text = _choose(PHRASES[key]).format(**values)
    text = text[:1].upper() + text[1:]
    if key in SIR_OK and _random() < SIR_RATE:
        text = with_sir(text)
    return text


def with_sir(text):
    """'Pasta timer, 25 minutes.' -> 'Pasta timer, 25 minutes, sir.'"""
    body = text.rstrip()
    end = body[-1] if body and body[-1] in '.!?' else ''
    return f"{body[:-1] if end else body}, sir{end or '.'}"


def all_variants(key, **values):
    """Every variant of a phrase, filled in (for code that recognizes its own words)."""
    return [variant.format(**values) for variant in PHRASES[key]]
