"""Lazy Google TTS generation feeding the shared cancellable output controller."""
import html
import threading
from core.speech_output import PCMClip, SoundDevicePlayer, SpeechController


def create_dynamic_ssml(text):
    # Natural provider prosody without transformer inference or long inserted
    # pauses. User/model text is data, never SSML markup.
    return "<speak>" + html.escape(text, quote=False) + "</speak>"


class GoogleSynthesizer:
    def __init__(self):
        self.client = None

    def __call__(self, text, voice_name="en-US-Wavenet-C", language_code="en-US",
                 speaking_rate=1.1, pitch=0.0):
        from google.cloud import texttospeech
        if self.client is None:
            from config.credentials import credentials
            self.client = texttospeech.TextToSpeechClient(credentials=credentials)
        response = self.client.synthesize_speech(
            input=texttospeech.SynthesisInput(ssml=create_dynamic_ssml(text)),
            voice=texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                speaking_rate=speaking_rate, pitch=pitch, sample_rate_hertz=24000),
            retry=None, timeout=8.0,
        )
        return PCMClip.from_wav(response.audio_content)


_controller = None
_lock = threading.Lock()


def get_speech_controller():
    global _controller
    with _lock:
        if _controller is None:
            _controller = SpeechController(GoogleSynthesizer(), SoundDevicePlayer())
        return _controller


def synthesize_speech(text, voice_name="en-US-Wavenet-C", language_code="en-US",
                      speaking_rate=1.1, pitch=0.0, priority=False):
    """Queue speech and return a cancellable job immediately.

    job.wait() is available for explicit synchronous callers. Generation and
    playback state are owned by one worker shared with background voice alerts.
    """
    print(f"Jarvis: {text}")
    return get_speech_controller().submit(text, voice_name=voice_name,
        language_code=language_code, speaking_rate=speaking_rate, pitch=pitch,
        priority=priority)


def is_speaking():
    return _controller.is_speaking() if _controller is not None else False


def stop_speech(expected_id=None):
    return _controller.stop(expected_id) if _controller is not None else False


def wait_for_speech_complete(timeout=None):
    return _controller.wait(timeout) if _controller is not None else True
