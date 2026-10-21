from core.assistant import Assistant

def main():
    from core.conversation_log import start_logging, record
    print(f"Conversation log: {start_logging()}")
    print("  JARVIS AI ASSISTANT")
    print("=" * 50)
    print()
    
    # Reminder restoration is an explicit voice-runtime startup action.
    from core.reminder_manager import initialize_reminders
    initialize_reminders()
    assistant = Assistant()
    
    try:
        while True:
            assistant.wait_for_wake_word()
            assistant.listen_for_command()
    finally:
        try:
            assistant.close()
        finally:
            record('session_ended')

if __name__ == "__main__":
    main()
