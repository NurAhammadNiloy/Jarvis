"""On-device wake-word detection: openWakeWord's "hey jarvis" model, ONNX on the CPU.

Nothing here touches the network except ensure_models(), which downloads the
model files once into models/wake_word/ (inside the project, gitignored).

The wake phrase is "Hey Jarvis" only: the model was trained on it, and plain
"Jarvis" was detected 0 of 10 times when measured on 22 Oct 2026 (tools/measure_wake_word.py).
"""
from dataclasses import dataclass
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[1] / 'models' / 'wake_word'
WAKE_MODEL = 'hey_jarvis_v0.1'
KEYWORD = 'hey jarvis'
_FEATURE_FILES = ('melspectrogram.onnx', 'embedding_model.onnx')
SAMPLE_RATE = 16000
CHUNK_BYTES = 1280 * 2  # openWakeWord scores 80 ms chunks of 16-bit audio


@dataclass(frozen=True)
class WakeEvent:
    keyword: str
    score: float


def ensure_models(model_dir=MODEL_DIR):
    """Download the model files once; returns the directory."""
    model_dir = Path(model_dir)
    needed = [model_dir / name for name in (WAKE_MODEL + '.onnx',) + _FEATURE_FILES]
    if not all(path.exists() for path in needed):
        from openwakeword.utils import download_models
        print(f"Downloading the wake-word model to {model_dir} (once)...")
        download_models([WAKE_MODEL], target_directory=str(model_dir))
    return model_dir


class OpenWakeWordDetector:
    """Feed 16 kHz int16 frames of any size; process() returns a WakeEvent once per
    utterance of the wake word (then stays quiet for `refractory_seconds`)."""

    def __init__(self, threshold=0.5, model=None, model_dir=MODEL_DIR, refractory_seconds=1.5):
        if not 0 < threshold < 1:
            raise ValueError('WAKE_WORD_THRESHOLD must be between 0 and 1')
        self.threshold = threshold
        self._model = model if model is not None else self._load(ensure_models(model_dir))
        self._buffer = bytearray()
        self._refractory_bytes = int(refractory_seconds * SAMPLE_RATE) * 2
        self._quiet_for = 0  # bytes of audio still inside the refractory period
        self.last_score = 0.0

    @staticmethod
    def _load(model_dir):
        from openwakeword.model import Model
        return Model(wakeword_models=[str(model_dir / (WAKE_MODEL + '.onnx'))], inference_framework='onnx',
                     melspec_model_path=str(model_dir / 'melspectrogram.onnx'),
                     embedding_model_path=str(model_dir / 'embedding_model.onnx'))

    def process(self, frame):
        import numpy as np
        self._buffer += frame
        event = None
        while len(self._buffer) >= CHUNK_BYTES:
            chunk = np.frombuffer(bytes(self._buffer[:CHUNK_BYTES]), dtype=np.int16)
            del self._buffer[:CHUNK_BYTES]
            score = float(max(self._model.predict(chunk).values()))
            self.last_score = score
            if self._quiet_for > 0:
                self._quiet_for -= CHUNK_BYTES
            elif score >= self.threshold and event is None:
                event = WakeEvent(KEYWORD, round(score, 3))
                self._quiet_for = self._refractory_bytes
        return event

    def reset(self):
        self._buffer.clear()
        self._quiet_for = 0
        self._model.reset()


def create_detector(engine, threshold):
    """The configured detector, or None when the wake word is checked on the transcript."""
    if not engine:
        return None
    if engine != 'openwakeword':
        raise ValueError(f"Unknown WAKE_WORD_ENGINE {engine!r}; use 'openwakeword' or None")
    return OpenWakeWordDetector(threshold)
