from core.assistant import Assistant

def main():
    assistant = Assistant()
    assistant.wait_for_wake_word()
    assistant.listen_for_command()

if __name__ == "__main__":
    main()
