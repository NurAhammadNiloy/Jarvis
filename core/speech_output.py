"""Single-owner, cancellable speech generation and playback. Hardware is injected."""
from collections import deque
from dataclasses import dataclass, field
import io
import logging
import re
import threading
import time
import wave
from core.conversation_log import record

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PCMClip:
    data: bytes
    sample_rate: int
    channels: int = 1
    sample_width: int = 2

    @classmethod
    def from_wav(cls, data):
        with wave.open(io.BytesIO(data), 'rb') as stream:
            if stream.getsampwidth() != 2:
                raise ValueError('Expected signed 16-bit PCM')
            return cls(stream.readframes(stream.getnframes()), stream.getframerate(), stream.getnchannels())


def speech_chunks(text, limit=240):
    """Bound synthesis latency without dropping or rewriting response words."""
    chunks = []
    for sentence in re.split(r'(?<=[.!?])\s+', text.strip()):
        while len(sentence) > limit:
            cut = sentence.rfind(' ', 0, limit + 1)
            cut = cut if cut > 0 else limit
            chunks.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if sentence:
            chunks.append(sentence)
    # Short multi-sentence replies need one provider request, not one per sentence.
    packed = []
    for chunk in chunks:
        if packed and len(packed[-1]) + 1 + len(chunk) <= limit:
            packed[-1] += ' ' + chunk
        else:
            packed.append(chunk)
    return packed


@dataclass
class SpeechJob:
    id: int
    text: str
    options: dict
    clip: object = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    error: object = None

    def wait(self, timeout=None):
        return self.done.wait(timeout)

    def cancel(self):
        self.cancelled.set()


@dataclass(frozen=True)
class SpeechSnapshot:
    id: object = None
    text: str = ''
    audible: bool = False


class SoundDevicePlayer:
    """Only the owner worker opens/closes streams; cancellation uses an Event.

    The callback observes cancellation every 20 ms. Device buffering adds its
    own latency. No PortAudio method is called concurrently by the listener.
    """
    def __init__(self, device=None, backend=None):
        self.device = device
        self.backend = backend

    def play(self, clip, cancelled):
        if cancelled.is_set():
            return
        sd = self.backend
        if sd is None:
            import sounddevice as sd
        finished = threading.Event()
        offset = 0
        def callback(outdata, frames, timing, status):
            nonlocal offset
            if cancelled.is_set():
                outdata[:] = b'\0' * len(outdata)
                raise sd.CallbackAbort()
            length = frames * clip.channels * clip.sample_width
            data = clip.data[offset:offset + length]
            outdata[:] = data + b'\0' * (length - len(data))
            offset += len(data)
            if offset >= len(clip.data):
                raise sd.CallbackStop()
        stream = sd.RawOutputStream(samplerate=clip.sample_rate, channels=clip.channels,
            dtype='int16', device=self.device, blocksize=clip.sample_rate // 50,
            latency='low', callback=callback, finished_callback=finished.set)
        try:
            if cancelled.is_set():
                return
            stream.start()
            deadline = time.monotonic() + len(clip.data) / (clip.sample_rate * clip.channels * clip.sample_width) + 3
            while not finished.wait(0.02):
                if cancelled.is_set():
                    stream.abort()
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Audio device did not complete playback')
        finally:
            stream.close()


class SpeechController:
    def __init__(self, synthesizer, player, max_pending=16):
        self.synthesizer = synthesizer
        self.player = player
        self.max_pending = max_pending
        self._condition = threading.Condition()
        self._pending = deque()
        self._active = None
        self._audible = False
        self._counter = 0
        self._worker = None
        self._closed = False
        self._input_active = False

    def submit(self, text, *, priority=False, clip=None, **options):
        if priority:
            self.stop()
        with self._condition:
            if self._closed:
                raise RuntimeError('Speech output is closed')
            if len(self._pending) >= self.max_pending:
                raise RuntimeError('Speech output queue is full')
            self._counter += 1
            job = SpeechJob(self._counter, text, options, clip)
            record('speech_queued', role='jarvis', text=text, playback_id=job.id,
                   audio_kind='clip' if clip is not None else 'speech')
            self._pending.append(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='jarvis-speech', daemon=True)
                self._worker.start()
            self._condition.notify_all()
            return job

    def set_input_active(self, active):
        with self._condition:
            self._input_active = active
            self._condition.notify_all()

    def snapshot(self):
        with self._condition:
            job = self._active
            if job is None or job.cancelled.is_set():
                return SpeechSnapshot()
            return SpeechSnapshot(job.id, job.text, self._audible)

    def is_speaking(self):
        with self._condition:
            return bool(self._pending or (self._active and not self._active.cancelled.is_set()))

    def stop(self, expected_id=None):
        """Invalidate active and queued audio, including late synthesis results."""
        with self._condition:
            if expected_id is not None and (self._active is None or self._active.id != expected_id):
                return False
            if self._active:
                self._active.cancelled.set()
                record('speech_cancel_requested', playback_id=self._active.id)
            for job in self._pending:
                job.cancelled.set()
                job.done.set()
                record('speech_finished', playback_id=job.id, outcome='cancelled_before_start')
            self._pending.clear()
            self._condition.notify_all()
            return True

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._active or self._pending:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self):
        self.stop()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._worker:
            self._worker.join(timeout=2)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                job = self._pending.popleft()
                self._active = job
            try:
                chunks = [None] if job.clip is not None else speech_chunks(job.text)
                playback_started = False
                for text in chunks:
                    if job.cancelled.is_set():
                        break
                    started = time.monotonic()
                    record('synthesis_started', playback_id=job.id)
                    clip = job.clip if job.clip is not None else self.synthesizer(text, **job.options)
                    record('synthesis_finished', playback_id=job.id,
                           duration_ms=round((time.monotonic() - started) * 1000))
                    # A cancelled network request may finish later. Never play it.
                    if job.cancelled.is_set():
                        break
                    with self._condition:
                        # Prepare audio during input; only its first playback
                        # waits for the endpoint. Later chunks must not wait on
                        # VAD triggered by this response's own speaker echo.
                        if not playback_started and self._input_active:
                            waiting = time.monotonic()
                            record('playback_waiting_for_input', playback_id=job.id)
                            while self._input_active and not job.cancelled.is_set() and not self._closed:
                                self._condition.wait(timeout=0.05)
                            record('playback_input_wait_finished', playback_id=job.id,
                                   duration_ms=round((time.monotonic() - waiting) * 1000))
                        if job.cancelled.is_set() or self._closed:
                            break
                        self._audible = True
                        playback_started = True
                    record('playback_chunk_started', playback_id=job.id, text=text)
                    self.player.play(clip, job.cancelled)
                    with self._condition:
                        self._audible = False
            except Exception as exc:
                job.error = exc
                logger.error('Speech output failed (%s)', type(exc).__name__)
            finally:
                record('speech_finished', playback_id=job.id,
                       outcome='failed' if job.error else 'cancelled' if job.cancelled.is_set() else 'completed',
                       error=type(job.error).__name__ if job.error else None)
                with self._condition:
                    self._active = None
                    self._audible = False
                    job.done.set()
                    self._condition.notify_all()
