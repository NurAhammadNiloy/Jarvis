import schedule
import threading
import datetime
import time
import json
import dateparser
from core.command_output import speak as synthesize_speech

# Persistent reminder storage file
REMINDER_FILE = 'data/reminders.json'

reminders = []
_scheduler_running = False  # Prevent multiple threads
_initialized = False

def load_reminders(notify=synthesize_speech):
    global reminders
    try:
        with open(REMINDER_FILE, 'r') as file:
            reminders = json.load(file)
            # Re-schedule loaded reminders
            for reminder in reminders:
                if not reminder['completed']:
                    reschedule_reminder(reminder, notify=notify)
    except (FileNotFoundError, json.JSONDecodeError):
        reminders = []

def reschedule_reminder(reminder, notify=synthesize_speech):
    """Re-schedule a reminder after loading from file."""
    reminder_time = datetime.datetime.strptime(reminder['time'], "%Y-%m-%d %H:%M:%S")
    if reminder_time > datetime.datetime.now():
        if reminder['recurring']:
            schedule_recurring_reminder(reminder['time'], reminder['task'], reminder['interval'], notify=notify)
        else:
            schedule_one_time_reminder(reminder['time'], reminder['task'], notify=notify)

def save_reminders():
    with open(REMINDER_FILE, 'w') as file:
        json.dump(reminders, file, indent=2)

def handle_reminder(task, reminder_time, recurring=False, interval=None, *,
                    respond=synthesize_speech, notify=synthesize_speech):
    parsed_time = dateparser.parse(reminder_time)
    if parsed_time:
        # Ensure future time
        if parsed_time < datetime.datetime.now():
            parsed_time += datetime.timedelta(days=1)
        
        reminder_time_str = parsed_time.strftime("%Y-%m-%d %H:%M:%S")
        reminder = {
            'task': task,
            'time': reminder_time_str,
            'recurring': recurring,
            'interval': interval,
            'completed': False
        }
        reminders.append(reminder)
        save_reminders()

        if recurring:
            schedule_recurring_reminder(reminder_time_str, task, interval, notify=notify)
        else:
            schedule_one_time_reminder(reminder_time_str, task, notify=notify)

        respond(f"Reminder set for {parsed_time.strftime('%A, %B %d at %I:%M %p')}: {task}")
        return True
    else:
        respond("I'm sorry, I couldn't parse the reminder time. Please try again.")
        return False

def schedule_one_time_reminder(reminder_time, task, *, notify=synthesize_speech):
    """Schedule a one-time reminder using delay-based approach."""
    def job():
        notify(f"Sir, this is your reminder: {task}")
        mark_reminder_as_completed(task)
        return schedule.CancelJob  # Remove after execution
    
    # Calculate seconds until reminder
    target_time = datetime.datetime.strptime(reminder_time, "%Y-%m-%d %H:%M:%S")
    delay_seconds = (target_time - datetime.datetime.now()).total_seconds()
    
    if delay_seconds > 0:
        # Use threading.Timer for one-time reminders with specific dates
        timer = threading.Timer(delay_seconds, job)
        timer.daemon = True
        timer.start()
        print(f"Reminder scheduled in {delay_seconds:.0f} seconds")
    else:
        print("Reminder time is in the past, skipping.")

def schedule_recurring_reminder(reminder_time, task, interval, *, notify=synthesize_speech):
    """Schedule a recurring reminder."""
    def job():
        notify(f"Sir, this is your recurring reminder: {task}")

    time_str = reminder_time.split(" ")[1][:5]  # Extract HH:MM only
    
    if interval == 'daily':
        schedule.every().day.at(time_str).do(job)
    elif interval == 'weekly':
        schedule.every(7).days.at(time_str).do(job)
    elif interval == 'hourly':
        schedule.every().hour.at(":00").do(job)

    run_scheduled_jobs()

def mark_reminder_as_completed(task):
    """Mark a reminder as completed."""
    for reminder in reminders:
        if reminder['task'] == task:
            reminder['completed'] = True
    save_reminders()

def get_reminders(*, respond=synthesize_speech):
    """List all active reminders."""
    active_reminders = [r for r in reminders if not r['completed']]
    if active_reminders:
        for reminder in active_reminders:
            respond(f"Active reminder: {reminder['task']} at {reminder['time']}")
    else:
        respond("You have no active reminders.")

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
            schedule_one_time_reminder(reminder['time'], task)  # Re-schedule
            synthesize_speech(f"Reminder '{task}' has been snoozed for {snooze_minutes} minutes.")
            return
    synthesize_speech(f"No reminder found for '{task}'.")

def run_scheduled_jobs():
    """Run scheduled jobs in the background (singleton)."""
    global _scheduler_running
    if _scheduler_running:
        return
    
    def job_runner():
        while True:
            schedule.run_pending()
            time.sleep(1)  # Check every second

    thread = threading.Thread(target=job_runner)
    thread.daemon = True
    thread.start()
    _scheduler_running = True
    # Scheduler running silently in background

def initialize_reminders(*, notify=synthesize_speech):
    """Explicit startup: imports must not start jobs or touch runtime storage."""
    global _initialized
    if not _initialized:
        load_reminders(notify=notify)
        run_scheduled_jobs()
        _initialized = True
