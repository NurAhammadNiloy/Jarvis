import schedule
import threading

def run_scheduled_jobs():
    """
    Run scheduled jobs in a background thread to keep them active.
    """
    def job_runner():
        while True:
            schedule.run_pending()
    
    thread = threading.Thread(target=job_runner)
    thread.daemon = True  # Daemon thread exits when the main program does
    thread.start()

def schedule_job(time, task_function):
    """
    Schedule a job at a specific time.
    
    Args:
        time (str): The time to run the job (e.g., "14:30").
        task_function (function): The function to execute at the scheduled time.
    """
    schedule.every().day.at(time).do(task_function)
    run_scheduled_jobs()
