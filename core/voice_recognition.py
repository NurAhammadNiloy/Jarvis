import speech_recognition as sr
import webrtcvad
import numpy as np

# Initialize WebRTC VAD
vad = webrtcvad.Vad()
vad.set_mode(3)  # Mode 3 for aggressive filtering

recognizer = sr.Recognizer()

def is_speech(data, sample_rate=16000, frame_duration_ms=30):
    """Check if the audio data contains speech."""
    frame_size = int(sample_rate * (frame_duration_ms / 1000.0) * 2)  # Multiply by 2 for 16-bit (2 bytes)
    
    # Process the audio data in fixed frame sizes
    for start in range(0, len(data), frame_size):
        frame = data[start:start + frame_size]
        if len(frame) < frame_size:
            continue  # Skip if the frame is smaller than required
        if vad.is_speech(frame, sample_rate):
            return True
    return False

def listen(timeout=30, phrase_time_limit=60, ambient_duration=1):
    """Listen continuously and process speech inputs."""
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=ambient_duration)
        print("Listening...")

        while True:  # Continuously listen for human speech
            try:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

                # Ensure the audio data is in the correct format
                raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
                
                # Use WebRTC VAD to check if the audio contains human speech
                if is_speech(raw_data, sample_rate=16000):
                    print("Detected human speech, processing...")
                    try:
                        query = recognizer.recognize_google(audio)
                        verified_query = keyword_verification(query.lower())
                        print(f"Processed result: {verified_query}")
                        return verified_query  # Return the result and immediately continue listening
                    except sr.UnknownValueError:
                        print("I didn't catch that. Please try again.")
                        continue  # Continue listening if recognition fails for part of the input
                else:
                    print("Detected noise, no human speech.")
            
            except sr.RequestError:
                print("Network error. Please check your connection.")
                break  # Stop listening if there's a network issue
            
            except sr.WaitTimeoutError:
                # Continue listening immediately if no speech is detected within the timeout period
                print("Listening timed out without detecting speech. Waiting for input...")
                continue

def keyword_verification(text):
    """Verify if the recognized text matches or is similar to 'Jarvis'."""
    keywords = ["jarvis", "jar", "javis", "jarv"]
    for keyword in keywords:
        if keyword in text:
            return "jarvis"  # Normalize to 'Jarvis'
    return text

# Ensure 'listen' starts immediately after processing a command in main.py or wherever it's used
