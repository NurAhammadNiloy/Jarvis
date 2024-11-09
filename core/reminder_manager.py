import schedule
import threading
import datetime
import json
import dateparser
from core.speech_synthesis import synthesize_speech

# Persistent reminder storage file
REMINDER_FILE = 'reminders.json'

reminders = []

def load_reminders():
    global reminders
    try:
        with open(REMINDER_FILE, 'r') as file:
            reminders = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        reminders = []

def save_reminders():
    with open(REMINDER_FILE, 'w') as file:
        json.dump(reminders, file)

def handle_reminder(task, reminder_time, recurring=False, interval=None):
    parsed_time = dateparser.parse(reminder_time)
    if parsed_time:
        reminder_time_str = parsed_time.strftime("%Y-%m-%d %H:%M:%S")
        reminder = {
            'task': task,
            'time': reminder_time_str,
            'recurring': recurring,
            'interval': interval,
            'completed': False
        }
        reminders.append(reminder)
        save_reminders()  # Ensure data is persisted after appending

        if recurring:
            schedule_recurring_reminder(reminder_time_str, task, interval)
        else:
            schedule_one_time_reminder(reminder_time_str, task)

        synthesize_speech(f"Reminder set for {parsed_time.strftime('%A, %B %d at %I:%M %p')}: {task}")
    else:
        synthesize_speech("I'm sorry, I couldn't parse the reminder time. Please try again.")


def schedule_one_time_reminder(reminder_time, task):
    def job():
        synthesize_speech(f"Sir, this is your reminder: {task}")
        mark_reminder_as_completed(task)

    schedule.every().day.at(reminder_time.split(" ")[1]).do(job)
    run_scheduled_jobs()

def schedule_recurring_reminder(reminder_time, task, interval):
    """Schedule a recurring reminder."""
    def job():
        synthesize_speech(f"Sir, this is your recurring reminder: {task}")

    time_str = reminder_time.split(" ")[1]  # Extract time portion for scheduling
    if interval == 'daily':
        schedule.every().day.at(time_str).do(job)
    elif interval == 'weekly':
        schedule.every(7).days.at(time_str).do(job)  # Adjust for `schedule` limitations
    elif interval == 'hourly':
        schedule.every().hour.at(":00").do(job)

    run_scheduled_jobs()


def mark_reminder_as_completed(task):
    """Mark a reminder as completed."""
    for reminder in reminders:
        if reminder['task'] == task:
            reminder['completed'] = True
    save_reminders()

def get_reminders():
    """List all active reminders."""
    active_reminders = [r for r in reminders if not r['completed']]
    if active_reminders:
        for reminder in active_reminders:
            synthesize_speech(f"Active reminder: {reminder['task']} at {reminder['time']}")
    else:
        synthesize_speech("You have no active reminders.")

def list_upcoming_reminders():
    """List all upcoming reminders sorted by time."""
    upcoming_reminders = sorted(
        [r for r in reminders if not r['completed']],
        key=lambda x: datetime.datetime.strptime(x['time'], "%Y-%m-%d %H:%M:%S")
    )
    if upcoming_reminders:
        for reminder in upcoming_reminders:
            synthesize_speech(f"Upcoming reminder: {reminder['task']} at {reminder['time']}")
    else:
        synthesize_speech("You have no upcoming reminders.")


def delete_reminder(task):
    """Delete a specific reminder."""
    global reminders
    reminders = [r for r in reminders if r['task'] != task]
    save_reminders()
    synthesize_speech(f"Reminder '{task}' has been deleted.")

def snooze_reminder(task, snooze_minutes=10):
    """Snooze a specific reminder for a given number of minutes."""
    for reminder in reminders:
        if reminder['task'] == task:
            new_time = datetime.datetime.strptime(reminder['time'], "%Y-%m-%d %H:%M:%S") + datetime.timedelta(minutes=snooze_minutes)
            reminder['time'] = new_time.strftime("%Y-%m-%d %H:%M:%S")
            save_reminders()
            synthesize_speech(f"Reminder '{task}' has been snoozed for {snooze_minutes} minutes.")
            return
    synthesize_speech(f"No reminder found for '{task}'.")

def run_scheduled_jobs():
    """Run scheduled jobs in the background."""
    def job_runner():
        while True:
            schedule.run_pending()

    thread = threading.Thread(target=job_runner)
    thread.daemon = True
    thread.start()

# Load reminders at the start
load_reminders()
