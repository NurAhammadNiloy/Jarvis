"""On-device wake-word detection: openWakeWord's "hey jarvis" model, ONNX on the CPU.

Nothing here touches the network except ensure_models(), which downloads the
model files once into models/wake_word/ (inside the project, gitignored).

The wake phrase is "Hey Jarvis" only: the model was trained on it, and plain
"Jarvis" was detected 0 of 10 times when measured on 22 Oct 2026 (tools/measure_wake_word.py).

Personal tuning: a custom verifier (openWakeWord's speaker-specific logistic
regression over the model's audio features) trained on your own recordings in
data/voice/. When the plain model scores a moment at least VERIFIER_GATE, the
verifier's score replaces it: your "Hey Jarvis" that the plain model only half
recognized (0.39, 0.49) can pass, and other speech that resembles it is pushed down.
"""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'models' / 'wake_word'
VOICE_DIR = ROOT / 'data' / 'voice'                  # your recordings: gitignored, never uploaded
VERIFIER_PATH = VOICE_DIR / 'hey_jarvis_verifier.pkl'
WAKE_MODEL = 'hey_jarvis_v0.1'
KEYWORD = 'hey jarvis'
_FEATURE_FILES = ('melspectrogram.onnx', 'embedding_model.onnx')
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280      # openWakeWord scores 80 ms chunks of 16-bit audio
CHUNK_BYTES = CHUNK_SAMPLES * 2
VERIFIER_GATE = 0.05      # plain-model score from which the verifier decides


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


def load_model(model_dir=MODEL_DIR, verifier_path=None, verifier_gate=VERIFIER_GATE):
    """The openWakeWord model, with the personal verifier when one is given."""
    from openwakeword.model import Model
    model_dir = ensure_models(model_dir)
    options = {}
    if verifier_path is not None:
        options = dict(custom_verifier_models={WAKE_MODEL: str(verifier_path)},
                       custom_verifier_threshold=verifier_gate)
    return Model(wakeword_models=[str(model_dir / (WAKE_MODEL + '.onnx'))], inference_framework='onnx',
                 melspec_model_path=str(model_dir / 'melspectrogram.onnx'),
                 embedding_model_path=str(model_dir / 'embedding_model.onnx'), **options)


class OpenWakeWordDetector:
    """Feed 16 kHz int16 frames of any size; process() returns a WakeEvent once per
    utterance of the wake word (then stays quiet for `refractory_seconds`)."""

    def __init__(self, threshold=0.5, model=None, model_dir=MODEL_DIR, refractory_seconds=1.5,
                 verifier_path=None, verifier_gate=VERIFIER_GATE):
        if not 0 < threshold < 1:
            raise ValueError('WAKE_WORD_THRESHOLD must be between 0 and 1')
        self.threshold = threshold
        self.personal = verifier_path is not None
        self._model = model if model is not None else load_model(model_dir, verifier_path, verifier_gate)
        self._buffer = bytearray()
        self._refractory_bytes = int(refractory_seconds * SAMPLE_RATE) * 2
        self._quiet_for = 0  # bytes of audio still inside the refractory period
        self.last_score = 0.0

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


def create_detector(engine, threshold, personal=True, verifier_path=VERIFIER_PATH, verifier_gate=VERIFIER_GATE):
    """The configured detector, or None when the wake word is checked on the transcript.
    The personal verifier is used when `personal` and it has been trained."""
    if not engine:
        return None
    if engine != 'openwakeword':
        raise ValueError(f"Unknown WAKE_WORD_ENGINE {engine!r}; use 'openwakeword' or None")
    verifier = Path(verifier_path) if personal and verifier_path and Path(verifier_path).exists() else None
    return OpenWakeWordDetector(threshold, verifier_path=verifier, verifier_gate=verifier_gate)


# --- personal tuning ------------------------------------------------------------------

def read_wav(path):
    """16 kHz, 16-bit mono samples of a WAV file (as the recording tool writes them)."""
    import wave
    import numpy as np
    with wave.open(str(path), 'rb') as clip:
        if (clip.getframerate(), clip.getsampwidth(), clip.getnchannels()) != (SAMPLE_RATE, 2, 1):
            raise ValueError(f'{path}: expected 16 kHz, 16-bit mono')
        return np.frombuffer(clip.readframes(clip.getnframes()), dtype=np.int16)


# Steady hiss at -50 dBFS already lifts the plain model to about 0.17 over two minutes
# (measured with synthetic noise, 22 Oct 2026); a quiet headset mic sits well below that.
NOISY_FLOOR_DB = -50
CLIPPED_SAMPLE = 32700


def audio_levels(samples):
    """Microphone health of int16 samples, in dBFS: the noise floor (the quietest 10% of
    20 ms frames), the loudest 20 ms frame, the peak sample, and how many samples clipped."""
    import numpy as np
    samples = np.asarray(samples, dtype=np.int16)
    frames = samples[:len(samples) // 320 * 320].reshape(-1, 320).astype(np.float64)
    rms = np.sqrt((frames ** 2).mean(axis=1)) if len(frames) else np.zeros(1)
    magnitude = np.abs(samples.astype(np.int32))

    def dbfs(value):
        return round(float(20 * np.log10(max(value, 1.0) / 32768)), 1)
    return {'noise_floor_db': dbfs(np.percentile(rms, 10)), 'loudest_db': dbfs(rms.max()),
            'peak_db': dbfs(magnitude.max() if len(samples) else 0),
            'clipped': int(np.count_nonzero(magnitude >= CLIPPED_SAMPLE))}


def level_warnings(levels):
    """What is wrong with the microphone signal, if anything."""
    warnings = []
    if levels['clipped']:
        warnings.append(f"{levels['clipped']} samples clipped: lower the microphone level "
                        "(Windows Settings > System > Sound > your input > Input volume).")
    if levels['noise_floor_db'] > NOISY_FLOOR_DB:
        warnings.append(f"noise floor {levels['noise_floor_db']:.0f} dBFS is high (hiss, hum or fan noise on "
                        "the mic): it lifts wake-word scores. Check the headset plug, or lower the mic boost.")
    return warnings


def clip_frames(model, samples, offset=0):
    """[(plain-model score, audio features)] for each 80 ms step of a clip; the
    features are what a verifier sees at that moment (openWakeWord's method)."""
    import numpy as np
    model.reset()
    samples = np.concatenate([np.zeros(SAMPLE_RATE // 2, np.int16), samples[offset:], np.zeros(SAMPLE_RATE // 2, np.int16)])
    frames = []
    for start in range(0, len(samples) - CHUNK_SAMPLES + 1, CHUNK_SAMPLES):
        score = model.predict(samples[start:start + CHUNK_SAMPLES])[WAKE_MODEL]
        frames.append((float(score), model.preprocessor.get_features(model.model_inputs[WAKE_MODEL])))
    return frames


def positive_examples(frames, gate=VERIFIER_GATE, threshold=0.25):
    """The moments of a "Hey Jarvis" clip that are the wake phrase: the frames the plain
    model scores near its peak for that clip (at least `gate`)."""
    peak = max((score for score, _ in frames), default=0.0)
    if peak < gate:
        return []
    cut = max(gate, min(threshold, 0.7 * peak))
    return [features for score, features in frames if score >= cut]


def verified_score(verifier, frames, gate=VERIFIER_GATE):
    """The highest score a clip gets with the verifier applied as openWakeWord applies it."""
    best = 0.0
    for score, features in frames:
        if score >= gate:
            score = float(verifier.predict_proba(features)[0][-1])
        best = max(best, score)
    return best


def train_verifier(positive_clips, negative_clips, output_path, *, folds=5, threshold=0.5,
                   gate=VERIFIER_GATE, model_dir=MODEL_DIR, progress=print):
    """Train the personal verifier, after checking it on clips it was not trained on.

    Returns a report: per held-out clip, the plain and the tuned peak score.
    """
    import pickle
    import numpy as np
    from openwakeword.custom_verifier_model import train_verifier_model

    positive_clips, negative_clips = [Path(p) for p in positive_clips], [Path(p) for p in negative_clips]
    if len(positive_clips) < 5 or not negative_clips:
        raise ValueError('Need at least 5 "Hey Jarvis" clips and some other speech; run tools/record_voice.py')
    model = load_model(model_dir)
    progress(f'Reading {len(positive_clips)} "Hey Jarvis" clips and {len(negative_clips)} other clips...')
    # Positives at four small shifts, as openWakeWord does, for slightly different features.
    positives = [[clip_frames(model, read_wav(clip), offset) for offset in (0, 320, 640, 960)]
                 for clip in positive_clips]
    negatives = [clip_frames(model, read_wav(clip)) for clip in negative_clips]

    def fit(pos_indices, neg_indices):
        pos = [f for i in pos_indices for shifted in positives[i] for f in positive_examples(shifted, gate)]
        neg = [features for i in neg_indices for _, features in negatives[i]]
        if len(pos) < 5:
            raise ValueError('Too few usable "Hey Jarvis" moments: the plain model barely reacted to the clips. '
                             'Re-record them closer to the microphone.')
        return train_verifier_model(np.vstack(pos + neg), np.array([1] * len(pos) + [0] * len(neg)))

    # Check on held-out clips first: each clip is scored by a verifier that never saw it.
    report = {'positive': [], 'negative': []}
    folds = max(2, min(folds, len(positive_clips), len(negative_clips) if len(negative_clips) > 1 else 2))
    for fold in range(folds):
        test_pos = [i for i in range(len(positive_clips)) if i % folds == fold]
        test_neg = [i for i in range(len(negative_clips)) if i % folds == fold]
        verifier = fit([i for i in range(len(positive_clips)) if i not in test_pos],
                       [i for i in range(len(negative_clips)) if i not in test_neg] or list(range(len(negative_clips))))
        for i in test_pos:
            frames = positives[i][0]
            report['positive'].append((positive_clips[i].name, max(s for s, _ in frames), verified_score(verifier, frames, gate)))
        for i in test_neg:
            report['negative'].append((negative_clips[i].name, max(s for s, _ in negatives[i]),
                                       verified_score(verifier, negatives[i], gate)))
        progress(f'  checked fold {fold + 1} of {folds}')

    verifier = fit(range(len(positive_clips)), range(len(negative_clips)))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as stream:
        pickle.dump(verifier, stream)
    report['threshold'] = threshold
    return report
