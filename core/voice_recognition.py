"""Google recognition transport; transcript interpretation is deliberately lossless.

The continuous runtime owns capture and endpointing. Imports are hardware-free.
"""
import threading
from core.voice_policy import Hypothesis, Recognition
from core.voice_capture import VoiceConfig


def parse_google_result(result):
    if not isinstance(result, dict):
        return Recognition(error="unrecognized")
    hypotheses = []
    for alternative in result.get("alternative", []):
        text = alternative.get("transcript", "").strip()
        score = alternative.get("confidence")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            score = None
        if text:
            hypotheses.append(Hypothesis(text, score))
    if not hypotheses:
        return Recognition(error="unrecognized")
    first = hypotheses[0]
    return Recognition(first.text, first.confidence, tuple(hypotheses[1:]))


class GoogleRecognizer:
    def __init__(self, config=VoiceConfig()):
        self.config = config

    def __call__(self, pcm, *, partial=False):
        import speech_recognition as sr
        # Separate instances prevent concurrent request/configuration races.
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 3 if partial else 8
        audio = sr.AudioData(pcm, self.config.sample_rate, 2)
        try:
            result = recognizer.recognize_google(audio, language=self.config.language, show_all=True)
            return parse_google_result(result)
        except sr.UnknownValueError:
            return Recognition(error="unrecognized")
        except sr.RequestError:
            return Recognition(error="recognition_unavailable")


_listener = None
_lock = threading.Lock()


def get_listener(speech=None, config=None):
    global _listener
    with _lock:
        if _listener is None:
            if config is None:
                from config.settings import ECHO_MODE
                config = VoiceConfig(echo_mode=ECHO_MODE)
            from core.voice_capture import MicrophoneFrames, create_vad
            from core.voice_runtime import ContinuousListener
            if speech is None:
                from core.speech_synthesis import get_speech_controller
                speech = get_speech_controller()
            _listener = ContinuousListener(MicrophoneFrames(config), create_vad(config),
                                          GoogleRecognizer(config), speech, config)
        return _listener


def listen_result(timeout=30):
    return get_listener().listen(timeout=timeout)


def listen(timeout=30, phrase_time_limit=None, ambient_duration=None):
    """Legacy string adapter. New callers use listen_result for confidence.

    Per-call phrase caps and repeated ambient calibration no longer truncate
    the shared stream. Configure endpointing through VoiceConfig instead.
    """
    result = listen_result(timeout)
    return result.text if result is not None and not result.error and not result.truncated else None


def recognize_speech(audio):
    result = GoogleRecognizer()(audio.get_raw_data(convert_rate=16000, convert_width=2))
    return result.text or None, [a.text for a in result.alternatives], result.confidence


# Compatibility helpers intentionally do not rewrite user words or select
# an alternative hypothesis based on what the assistant hoped to hear.
def interpret_with_context(raw_text, alternatives=None):
    return raw_text.strip() if raw_text else ""


def interpret_general(text, alternatives=None):
    return interpret_with_context(text)


def select_best_question_form(primary, alternatives=None):
    return interpret_with_context(primary)


def keyword_verification(text, alternatives=None):
    return interpret_with_context(text)


def match_short_utterance(text):
    return None


def set_context(assistant_message, expecting=None):
    # Retained for callers; assistant output must never alter recognition text.
    return None
