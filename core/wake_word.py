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
MEASUREMENTS_PATH = VOICE_DIR / 'measurements.jsonl'   # tools/measure_wake_word.py results
# Your real situations, recorded (tools/record_voice.py --scenario) and measured
# (tools/measure_wake_word.py --scenario) one by one. Other names work too.
SCENARIOS = {
    'quiet': 'your quiet room as it usually is: sit, type, move a little',
    'talking': 'someone talking beside you, or the two of you talking',
    'video': 'a video playing on your phone or laptop at your usual volume',
    'household': 'household noise: the blender, cooking, chairs moving, doors',
}
WAKE_MODEL = 'hey_jarvis_v0.1'
KEYWORD = 'hey jarvis'
_FEATURE_FILES = ('melspectrogram.onnx', 'embedding_model.onnx')
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280      # openWakeWord scores 80 ms chunks of 16-bit audio
CHUNK_BYTES = CHUNK_SAMPLES * 2
VERIFIER_GATE = 0.09      # plain-model score from which the verifier decides (see settings)


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


def scenario_name(text):
    """'Household noise' -> 'household-noise': a scenario label usable as a folder name."""
    import re
    name = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    if not name:
        raise ValueError(f'Not a usable scenario name: {text!r}')
    return name


def clip_label(path):
    """Where a clip sits under data/voice/: 'background/video/background_001.wav'."""
    path = Path(path)
    try:
        return path.resolve().relative_to(VOICE_DIR.resolve()).as_posix()
    except ValueError:
        return f'{path.parent.name}/{path.name}'


# The kinds of "not the wake word" sound, as the training report names them.
_KINDS = {'speech': 'your speech', 'commands': 'your commands', 'background': 'background',
          'background_peaks': 'saved peaks', 'other_voices': 'other voices saying "Jarvis"'}


def clip_kind(label):
    """'background/video/background_001.wav' -> 'background: video'."""
    parts = label.split('/')
    kind = _KINDS.get(parts[0], parts[0])
    if parts[0] in ('background', 'background_peaks'):
        return f'{kind}: {parts[1]}' if len(parts) > 2 else f'{kind} (no scenario)'
    return kind


def training_clips(voice_dir=None):
    """The recordings to train on: ("Hey Jarvis" clips, other speech and sound, saved
    peaks). Background clips are in a folder per scenario (and loose ones from before);
    other_voices/ holds optional clips of other people saying "Jarvis"."""
    voice_dir = Path(voice_dir or VOICE_DIR)

    def wavs(part, deep=False):
        return sorted((voice_dir / part).rglob('*.wav') if deep else (voice_dir / part).glob('*.wav'))
    others = [clip for part in ('speech', 'commands') for clip in wavs(part)]
    return (wavs('wake'), others + wavs('background', deep=True) + wavs('other_voices'),
            wavs('background_peaks', deep=True))


def tuned_peak(scored, gate=VERIFIER_GATE):
    """The highest score of a clip whose frames are (plain score, verifier score): the
    verifier decides from `gate` up, as openWakeWord applies it (score >= gate)."""
    return max(((verifier if plain >= gate else plain) for plain, verifier in scored), default=0.0)


def evaluate(report, gate=VERIFIER_GATE, threshold=None):
    """Held-out results of train_verifier's report at a verifier gate: every clip at every
    chunk alignment counts as one try."""
    threshold = report['threshold'] if threshold is None else threshold
    positive = [scored for tries in report['positive'].values() for scored in tries]
    negative = {name: [tuned_peak(scored, gate) for scored in tries] for name, tries in report['negative'].items()}
    return {'tries': len(positive),
            'plain_detected': sum(max(plain for plain, _ in scored) >= threshold for scored in positive),
            'detected': sum(tuned_peak(scored, gate) >= threshold for scored in positive),
            'missed': {name: sum(tuned_peak(scored, gate) < threshold for scored in tries)
                       for name, tries in report['positive'].items()},
            'negative_tries': sum(len(scores) for scores in negative.values()),
            'false_wakes': {name: sum(score >= threshold for score in scores) for name, scores in negative.items()},
            'plain_highest': max((plain for tries in report['negative'].values() for scored in tries
                                  for plain, _ in scored), default=0.0),
            'highest': max((max(scores) for scores in negative.values()), default=0.0)}


# Where an 80 ms chunk starts relative to your words changes the scores a lot (a phone video
# scored 0.20-0.50 at different alignments), so every clip is checked at four of them.
ALIGNMENTS = (0, 320, 640, 960)
# Your "Hey Jarvis" moments are learned from this plain score up, whatever the gate.
TRAINING_FLOOR = 0.05


def train_verifier(positive_clips, negative_clips, output_path, *, peak_clips=(), folds=5, threshold=0.5,
                   model_dir=MODEL_DIR, progress=print):
    """Train the personal verifier, after checking it on clips it was not trained on.

    `peak_clips` are background moments that once scored high (tools/measure_wake_word.py):
    negatives, learned at every alignment because each is a rare example of a near-miss.
    Returns a report: per held-out clip and alignment, the (plain, verifier) score of each
    80 ms frame, so evaluate() can show the results at any gate.
    """
    import pickle
    import numpy as np
    from openwakeword.custom_verifier_model import train_verifier_model

    positive_clips = [Path(p) for p in positive_clips]
    negative_clips = [Path(p) for p in negative_clips] + [Path(p) for p in peak_clips]
    peaks = set(range(len(negative_clips) - len(peak_clips), len(negative_clips)))
    if len(positive_clips) < 5 or not negative_clips:
        raise ValueError('Need at least 5 "Hey Jarvis" clips and some other speech; run tools/record_voice.py')
    model = load_model(model_dir)
    progress(f'Reading {len(positive_clips)} "Hey Jarvis" clips and {len(negative_clips)} other clips...')
    positives = [[clip_frames(model, read_wav(clip), offset) for offset in ALIGNMENTS] for clip in positive_clips]
    negatives = [[clip_frames(model, read_wav(clip), offset) for offset in ALIGNMENTS] for clip in negative_clips]

    def fit(pos_indices, neg_indices):
        pos = [f for i in pos_indices for shifted in positives[i] for f in positive_examples(shifted, TRAINING_FLOOR)]
        neg = [features for i in neg_indices for k in (range(len(ALIGNMENTS)) if i in peaks else (0, 2))
               for _, features in negatives[i][k]]
        if len(pos) < 5:
            raise ValueError('Too few usable "Hey Jarvis" moments: the plain model barely reacted to the clips. '
                             'Re-record them closer to the microphone.')
        return train_verifier_model(np.vstack(pos + neg), np.array([1] * len(pos) + [0] * len(neg)))

    def scored(verifier, frames):
        probabilities = verifier.predict_proba(np.vstack([features for _, features in frames]))[:, -1]
        return [(plain, float(p)) for (plain, _), p in zip(frames, probabilities)]

    # Check on held-out clips first: each clip is scored by a verifier that never saw it.
    labels = [clip_label(clip) for clip in negative_clips]       # unique, and say which scenario
    report = {'positive': {}, 'negative': {}, 'peaks': [labels[i] for i in sorted(peaks)],
              'threshold': threshold}
    folds = max(2, min(folds, len(positive_clips), len(negative_clips) if len(negative_clips) > 1 else 2))
    for fold in range(folds):
        test_pos = [i for i in range(len(positive_clips)) if i % folds == fold]
        test_neg = [i for i in range(len(negative_clips)) if i % folds == fold]
        verifier = fit([i for i in range(len(positive_clips)) if i not in test_pos],
                       [i for i in range(len(negative_clips)) if i not in test_neg] or list(range(len(negative_clips))))
        for i in test_pos:
            report['positive'][positive_clips[i].name] = [scored(verifier, frames) for frames in positives[i]]
        for i in test_neg:
            report['negative'][labels[i]] = [scored(verifier, frames) for frames in negatives[i]]
        progress(f'  checked fold {fold + 1} of {folds}')

    verifier = fit(range(len(positive_clips)), range(len(negative_clips)))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as stream:
        pickle.dump(verifier, stream)
    return report
