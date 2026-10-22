"""Frame-based endpointing and microphone transport with injectable VAD."""
from collections import deque
from dataclasses import dataclass
import queue


@dataclass(frozen=True)
class VoiceConfig:
    sample_rate: int = 16000
    frame_ms: int = 20
    silence_ms: int = 1400
    preroll_ms: int = 300
    minimum_speech_ms: int = 100
    max_utterance_ms: int = 60000
    vad_mode: int = 1
    input_device: object = None
    language: str = 'en-US'
    barge_window_ms: int = 1800
    barge_interval_ms: int = 800
    # Speech after Jarvis stopped that marks an overlapping utterance as yours.
    after_playback_speech_ms: int = 300

    def __post_init__(self):
        if self.sample_rate not in (8000, 16000, 32000, 48000) or self.frame_ms not in (10, 20, 30):
            raise ValueError('WebRTC VAD requires a supported sample rate and frame duration')
        if not 600 <= self.silence_ms < self.max_utterance_ms:
            raise ValueError('Invalid endpointing limits')

    @property
    def frame_bytes(self):
        return self.sample_rate * self.frame_ms // 1000 * 2


@dataclass(frozen=True)
class AudioUtterance:
    pcm: bytes
    truncated: bool = False
    playback_id: object = None
    playback_text: str = ''
    voiced_after_playback_ms: int = 0  # speech after the last audible playback frame


class Endpointer:
    """Speech onset hysteresis, pre-roll, and sustained-silence endpointing.

    Hitting the safety limit emits an explicitly incomplete utterance and drains
    the remaining speech until silence. A cut-off tail cannot become a command.
    """
    def __init__(self, config=VoiceConfig()):
        self.config = config
        self.reset()

    def reset(self):
        c = self.config
        self.pre = deque(maxlen=max(1, c.preroll_ms // c.frame_ms))
        self.onset = deque(maxlen=5)
        self.frames = []
        self.voiced = 0
        self.silence = 0
        self.draining = False
        self.playback_id = None
        self.playback_text = ''
        self.after_playback = 0

    @property
    def active(self):
        return bool(self.frames)

    def push(self, frame, voiced, playback_id=None, playback_text=''):
        c = self.config
        if len(frame) != c.frame_bytes:
            raise ValueError('Expected one complete PCM frame')
        if self.draining:
            self.silence = 0 if voiced else self.silence + c.frame_ms
            if self.silence >= c.silence_ms:
                self.reset()
            return None
        if not self.frames:
            self.pre.append((frame, voiced, playback_id, playback_text))
            self.onset.append(voiced)
            if sum(self.onset) < 3:
                return None
            self.frames = [item[0] for item in self.pre]
            self.voiced = sum(item[1] for item in self.pre) * c.frame_ms
            for _, was_voiced, job_id, text in self.pre:
                if job_id is not None:
                    self.playback_id, self.playback_text = job_id, text
                    self.after_playback = 0
                elif was_voiced and self.playback_id is not None:
                    self.after_playback += c.frame_ms
        else:
            self.frames.append(frame)
            self.voiced += c.frame_ms if voiced else 0
            if playback_id is None and voiced and self.playback_id is not None:
                self.after_playback += c.frame_ms
        if playback_id is not None:
            self.playback_id = playback_id
            self.after_playback = 0
            if playback_text and playback_text not in self.playback_text:
                self.playback_text += ' ' + playback_text
        self.silence = 0 if voiced else self.silence + c.frame_ms
        limited = len(self.frames) * c.frame_ms >= c.max_utterance_ms
        if self.silence >= c.silence_ms or limited:
            result = AudioUtterance(b''.join(self.frames), limited, self.playback_id, self.playback_text,
                                    self.after_playback)
            enough_speech = self.voiced >= c.minimum_speech_ms
            self.reset()
            self.draining = limited
            return result if enough_speech else None
        return None


class MicrophoneFrames:
    """One PortAudio input stream. Callback only copies frames to a bounded queue."""
    def __init__(self, config=VoiceConfig()):
        self.config = config
        self.frames = queue.Queue(maxsize=150)
        self.overflow = False
        self.stream = None

    def __enter__(self):
        import sounddevice as sd
        c = self.config
        def callback(data, frames, timing, status):
            if status.input_overflow:
                self.overflow = True
            try:
                self.frames.put_nowait(bytes(data))
            except queue.Full:
                self.overflow = True
        self.stream = sd.RawInputStream(samplerate=c.sample_rate,
            blocksize=c.sample_rate * c.frame_ms // 1000, channels=1,
            dtype='int16', device=c.input_device, callback=callback)
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            raise
        return self

    def read(self, timeout=0.1):
        if self.overflow:
            self.overflow = False
            while not self.frames.empty():
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    break
            raise OverflowError('Microphone frames were lost')
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            if self.stream is not None and not self.stream.active:
                raise RuntimeError('Microphone stream stopped')
            return None

    def __exit__(self, *args):
        if self.stream is not None:
            self.stream.abort()
            self.stream.close()


def create_vad(config):
    import webrtcvad
    detector = webrtcvad.Vad(config.vad_mode)
    return lambda frame: detector.is_speech(frame, config.sample_rate)
