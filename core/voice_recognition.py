import speech_recognition as sr

recognizer = sr.Recognizer()

def listen(timeout=15, phrase_time_limit=7):
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)
        print("Listening...")
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            query = recognizer.recognize_google(audio)
            print(f"You said: {query}")
            return query.lower()
        except sr.UnknownValueError:
            print("I didn't understand that.")
            return ""
        except sr.RequestError:
            print("Service unavailable.")
            return ""
        except sr.WaitTimeoutError:
            print("Listening timeout.")
            return ""
