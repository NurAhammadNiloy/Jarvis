import speech_recognition as sr
from silero_vad import get_speech_timestamps, read_audio
import whisper
from google.cloud import speech
from config.credentials import credentials  # Import your Google Cloud credentials
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Initialize Google Cloud Speech client with imported credentials
google_client = speech.SpeechClient(credentials=credentials)

# Load Whisper model
whisper_model = whisper.load_model("base")  # Choose from tiny, base, small, medium, large

# Initialize SpeechRecognition
recognizer = sr.Recognizer()

def is_speech(data, sample_rate=16000):
    """
    Check if the audio data contains speech using Silero VAD.
    """
    try:
        audio = read_audio(data, sampling_rate=sample_rate)
        speech_timestamps = get_speech_timestamps(audio, sampling_rate=sample_rate)
        return len(speech_timestamps) > 0
    except Exception as e:
        print(f"[ERROR] Silero VAD failed: {e}")
        return False

def recognize_with_google_cloud(audio_data):
    """
    Use Google Cloud Speech-to-Text to recognize speech.
    """
    try:
        audio = speech.RecognitionAudio(content=audio_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US"
        )
        # Perform synchronous speech recognition
        response = google_client.recognize(config=config, audio=audio)
        for result in response.results:
            return result.alternatives[0].transcript
    except Exception as e:
        print(f"[ERROR] Google Cloud Speech-to-Text failed: {e}")
        return None

def recognize_with_whisper(audio_data):
    """
    Use Whisper to recognize speech.
    """
    try:
        result = whisper_model.transcribe(audio_data)
        return result.get("text", None)
    except Exception as e:
        print(f"[ERROR] Whisper transcription failed: {e}")
        return None

def listen(timeout=None, phrase_time_limit=None, ambient_duration=2):
    """
    Continuously listen and process speech using Silero VAD and Whisper, 
    with Google Cloud Speech-to-Text as a fallback.
    """
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=ambient_duration)
        print("[INFO] Listening...")

        while True:
            try:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)

                # Step 1: Use Silero VAD to detect human speech
                if is_speech(raw_data, sample_rate=16000):
                    print("\n[INFO] Detected human speech. Processing...")

                    # Step 2: Transcribe with Whisper
                    transcript = recognize_with_whisper(raw_data)
                    if transcript:
                        print(f"User: {transcript}")
                    else:
                        print("[INFO] Whisper failed. Trying Google Cloud Speech-to-Text...")
                        # Step 3: Fallback to Google Cloud Speech-to-Text
                        transcript = recognize_with_google_cloud(raw_data)
                        if transcript:
                            print(f"User: {transcript}")
                        else:
                            print("[INFO] Google Cloud Speech-to-Text also failed.")
                else:
                    print("[INFO] No speech detected.")

            except sr.WaitTimeoutError:
                print("[INFO] Listening timed out. Waiting for input...")
            except KeyboardInterrupt:
                print("[INFO] Stopped by user.")
                break  # Exit loop gracefully on keyboard interrupt

def keyword_verification(text):
    """
    Verify if the recognized text matches or is similar to 'Jarvis'.
    """
    keywords = ["jarvis", "jar", "javis", "jarv"]
    for keyword in keywords:
        if keyword in text.lower():
            return "jarvis"  # Normalize to 'Jarvis'
    return text

if __name__ == '__main__':
    try:
        listen()
    except KeyboardInterrupt:
        print("Stopped by user.")
