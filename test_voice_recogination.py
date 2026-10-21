# -*- coding: utf-8 -*-

# This file demonstrates how to use the Google Cloud Speech API
# to perform streaming speech recognition.

import re
import sys
import os
from google.cloud import speech_v1 as speech
import pyaudio
import queue

# This import assumes you have a valid credentials object in this file.
from config.credentials import credentials

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

# Initialize the Google Cloud Speech client with your credentials
# This line will only work if the import from config.credentials is successful.
try:
    client = speech.SpeechClient(credentials=credentials)
except Exception as e:
    print(f"Error initializing Google Cloud Speech client: {e}")
    print("Please ensure your 'config/credentials.py' file is correct and accessible.")
    sys.exit(1)


class MicrophoneStream(object):
    """
    Opens a recording stream as a generator yielding audio chunks.
    This class correctly handles the microphone stream using a queue for stability.
    """
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True
        self._audio_interface = None
        self._audio_stream = None

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream into the buffer."""
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            yield b''.join(data)

def listen_print_loop(responses):
    """
    Iterates through server responses and prints them.
    This function handles both interim and final transcriptions for real-time display.
    """
    num_chars_printed = 0
    for response in responses:
        if not response.results:
            continue

        result = response.results[0]
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript
        overwrite_chars = ' ' * (num_chars_printed - len(transcript))

        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + '\r')
            sys.stdout.flush()
            num_chars_printed = len(transcript)
        else:
            print(transcript + overwrite_chars)
            # Exit if the user says "bye".
            if re.search(r'\b(bye)\b', transcript, re.I):
                print('Exiting.')
                break
            num_chars_printed = 0

def main():
    """Starts a bi-directional streaming audio recognition process."""
    # Define speech adaptation for improved accuracy on specific phrases.
    # This gives the model hints for words and phrases that are not in its base vocabulary.
    speech_context = speech.SpeechContext(
        phrases=["Niloy", "Nur Ahammad Niloy", "sreepur, gazipur", "Centria University of applied science", "shahinur akter"],
        boost=20.0
    )

    config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code="en-US",
            enable_automatic_punctuation=True,
            speech_contexts=[speech_context],
        ),
        interim_results=True,
    )

    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )

        responses = client.streaming_recognize(config=config, requests=requests)

        print("Please speak into the microphone... (Press Ctrl+C to stop)")
        try:
            listen_print_loop(responses)
        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
