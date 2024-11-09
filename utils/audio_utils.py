import playsound
import os
import threading

def play_audio(audio_file):
    def play():
        try:
            playsound.playsound(audio_file)
        finally:
            if os.path.exists(audio_file):
                os.remove(audio_file)

    play_thread = threading.Thread(target=play)
    play_thread.start()
    play_thread.join()
