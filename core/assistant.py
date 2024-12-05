import dateparser
from core.voice_recognition import listen
from core.speech_synthesis import synthesize_speech
from core.intent_handler import handle_query
from utils.nlp_utils import extract_entities
import spacy
import time
import random
from datetime import datetime

nlp = spacy.load("en_core_web_trf")

class Assistant:
    def __init__(self):
        self.active_conversation = False
        self.conversation_timeout = 120  # 2 minutes
        self.last_active_time = time.time()
        self.pending_reminder = None

    def listen_for_command(self):
        self.active_conversation = True
        self.last_active_time = time.time()

        while self.active_conversation:
            query = listen()
            if query:
                doc = nlp(query)
                entities = extract_entities(doc)
                task = entities.get('TASK', '').strip()
                reminder_time = entities.get('TIME', None)

                if 'remind me' in query or 'set a reminder' in query:
                    if reminder_time:
                        parsed_time = dateparser.parse(reminder_time)
                        if parsed_time:
                            formatted_time = parsed_time.strftime("%A, %B %d at %I:%M %p")
                            synthesize_speech(f"Got it. I'll remind you to {task} on {formatted_time}.")
                            handle_query(f"remind me to {task} at {formatted_time}")
                        else:
                            synthesize_speech("I'm sorry, I couldn't understand the time. Could you tell me again?")
                    else:
                        self.pending_reminder = {'task': task}
                        synthesize_speech("I heard the task, but could you tell me when you'd like the reminder?")
                elif self.pending_reminder:
                    if reminder_time:
                        parsed_time = dateparser.parse(reminder_time)
                        if parsed_time:
                            formatted_time = parsed_time.strftime("%A, %B %d at %I:%M %p")
                            task_description = self.pending_reminder['task']
                            synthesize_speech(f"Got it. I'll remind you to {task_description} on {formatted_time}.")
                            handle_query(f"{task_description} at {formatted_time}")
                            self.pending_reminder = None
                        else:
                            synthesize_speech("I couldn't understand that time. Could you say it again?")
                else:
                    if not handle_query(query):
                        synthesize_speech("I'm sorry, I didn't understand that. Can you rephrase?")
                    else:
                        self.last_active_time = time.time()

            if time.time() - self.last_active_time > self.conversation_timeout:
                self.active_conversation = False
                synthesize_speech("I'm here whenever you need me. Just say 'Jarvis' to wake me up.")
                break

    def wait_for_wake_word(self):
        greetings = [
            "Sir, I am online and fully operational.",
            "Awaiting your command, sir.",
            "Ready for your instructions, sir. How can I assist?",
            "At your service, sir. What can I do for you?",
            "Standing by, sir. How may I be of assistance?",
            "Systems are active, sir. Ready when you are.",
            "Good to have you, sir. What would you like to do today?"
        ]

        def get_time_based_greeting():
            current_hour = datetime.now().hour
            if current_hour < 12:
                return "Good morning, sir."
            elif 12 <= current_hour < 18:
                return "Good afternoon, sir."
            else:
                return "Good evening, sir."

        while True:
            print("Passive mode activated. Say 'Jarvis' to wake me up.")
            query = listen(timeout=10, phrase_time_limit=3)
            if query and 'jarvis' in query.lower():
                # 30% chance to use a time-based greeting, adjust as needed
                if random.random() < 0.5:
                    response = get_time_based_greeting()
                else:
                    response = random.choice(greetings)  # Select a regular greeting

                synthesize_speech(response)
                return

