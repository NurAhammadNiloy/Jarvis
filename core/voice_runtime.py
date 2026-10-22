"""Continuous input with independent final-recognition and interruption workers."""
from collections import deque
from dataclasses import replace
import queue
import threading
import time

from core.voice_capture import AudioUtterance, Endpointer, VoiceConfig
from core.voice_policy import Recognition, can_interrupt, is_echo, means_stop, stop_heard, strip_wake_word
from core.conversation_log import record, record_recognition


def put_latest(target, value):
    """Bound backlog: do not execute stale commands after a slow provider call."""
    while True:
        try:
            target.put_nowait(value)
            return
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass


class ContinuousListener:
    def __init__(self, source, vad, recognize, speech, config=VoiceConfig(), clock=time.monotonic):
        self.source, self.vad, self.recognize, self.speech = source, vad, recognize, speech
        self.config, self.clock = config, clock
        self.endpoint = Endpointer(config)
        self.utterances = queue.Queue(maxsize=2)
        self.interruptions = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._threads = []
        self._start_lock = threading.Lock()

    def start(self):
        with self._start_lock:
            if not self._threads:
                for target, name in ((self._capture, 'capture'), (self._recognize_final, 'recognize'), (self._recognize_interruptions, 'barge-in')):
                    thread = threading.Thread(target=target, name='jarvis-' + name, daemon=True)
                    self._threads.append(thread)
                    thread.start()
        return self

    def listen(self, timeout=30):
        self.start()
        try:
            result = self.results.get(timeout=timeout)
            if result.captured_at is not None and self.clock() - result.captured_at > 10:
                return Recognition(error='stale_recording')
            return result
        except queue.Empty:
            return None

    @property
    def is_capturing(self):
        return self.endpoint.active or self.endpoint.draining

    def close(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1)
        self.speech.set_input_active(False)

    def _capture(self):
        c = self.config
        recent = deque(maxlen=c.barge_window_ms // c.frame_ms)
        recent_voice = deque(maxlen=recent.maxlen)
        recent_job = None
        last_partial = self.clock()
        try:
            with self.source as source:
                while not self._stop.is_set():
                    try:
                        frame = source.read(timeout=0.1)
                    except OverflowError:
                        record('capture_error', error='input_overflow')
                        self.endpoint.reset()
                        self.endpoint.draining = True
                        recent.clear()
                        recent_voice.clear()
                        put_latest(self.results, Recognition(error='input_overflow', truncated=True))
                        continue
                    if frame is None:
                        continue
                    snapshot = self.speech.snapshot()
                    if snapshot.id != recent_job:
                        # A rolling window from an old response must not be
                        # attributed to a newly started response.
                        recent.clear()
                        recent_voice.clear()
                        recent_job = snapshot.id
                        last_partial = self.clock()
                    voiced = self.vad(frame)
                    recent.append(frame)
                    recent_voice.append(voiced)
                    # Generation is silent: do not label the user's speech as
                    # speaker overlap merely because a job is being prepared.
                    utterance = self.endpoint.push(frame, voiced,
                        snapshot.id if snapshot.audible else None,
                        snapshot.text if snapshot.audible else '')
                    self.speech.set_input_active(self.endpoint.active or self.endpoint.draining)
                    if utterance:
                        record('utterance_ended', duration_ms=len(utterance.pcm) * 1000 // (c.sample_rate * 2),
                               truncated=utterance.truncated, playback_id=utterance.playback_id)
                        put_latest(self.utterances, (utterance, self.clock()))
                    # Barge-in recognition only while Jarvis is actually audible;
                    # silent synthesis or a held reply cannot be interrupted.
                    if (snapshot.id is not None and snapshot.audible and
                            sum(recent_voice) * c.frame_ms >= c.minimum_speech_ms and len(recent) >= 15 and
                            self.clock() - last_partial >= c.barge_interval_ms / 1000):
                        last_partial = self.clock()
                        partial = AudioUtterance(b''.join(recent), playback_id=snapshot.id, playback_text=snapshot.text)
                        put_latest(self.interruptions, (partial, self.clock()))
        except Exception as exc:
            record('capture_error', error=type(exc).__name__)
            put_latest(self.results, Recognition(error='microphone_' + type(exc).__name__))
            self._stop.set()
        finally:
            self.speech.set_input_active(False)

    def _transcribe(self, utterance, *, partial=False):
        if utterance.truncated:
            return Recognition(truncated=True)
        try:
            started = self.clock()
            result = self.recognize(utterance.pcm, partial=partial)
            record('recognition_timing', partial=partial,
                   duration_ms=round((self.clock() - started) * 1000))
        except Exception as exc:
            result = Recognition(error=type(exc).__name__)
        result = replace(result, playback_id=utterance.playback_id,
                         playback_text=utterance.playback_text)
        record_recognition(result, partial=partial)
        return result

    def handle_final(self, utterance):
        """Testable final-result policy, independent of capture threads."""
        result = self._transcribe(utterance)
        if result.playback_id is not None:
            echo = is_echo(result.text, result.playback_text)
            addressed = strip_wake_word(result.text) is not None
            if self.config.echo_mode == 'speakers' and (echo or not (addressed or stop_heard(result, 0.35))):
                # Began while Jarvis was audible (or within 0.3 s after): only
                # "Jarvis ..." or "stop" count. Keep what you said afterwards.
                record('voice_filter', reason='speakers_mode', text=result.text, uid=result.uid)
                return self._after_playback(utterance)
            if echo:
                record('voice_filter', reason='response_echo', text=result.text, uid=result.uid)
                return None
            if not addressed and not means_stop(result.text):
                if result.text and utterance.voiced_after_playback_ms >= self.config.after_playback_speech_ms:
                    # Jarvis's echo opened the utterance, but you kept speaking
                    # after it stopped (e.g. answering "Shall I do that?").
                    record('voice_filter_passed', reason='spoke_after_playback', text=result.text,
                           voiced_after_playback_ms=utterance.voiced_after_playback_ms, uid=result.uid)
                    return replace(result, playback_id=None, playback_text='')
                record('voice_filter', reason='unaddressed_during_playback', text=result.text, uid=result.uid)
                # Mixed loudspeaker audio must not turn into an executable action.
                return None
            if can_interrupt(result, self.stop_confidence):
                self.speech.stop(expected_id=result.playback_id)
        return result

    @property
    def stop_confidence(self):
        """Over loudspeakers a short "stop" is often heard weakly ('Genesis stop' 0.40)."""
        return 0.35 if self.config.echo_mode == 'speakers' else 0.65

    def _after_playback(self, utterance):
        """Speakers mode: recognize only the audio after Jarvis stopped (plus the
        tail), free of its echo; None if you did not keep speaking."""
        if not utterance.after_playback_pcm:
            return None
        result = self._transcribe(AudioUtterance(utterance.after_playback_pcm))
        if result.error or not result.text:
            record('voice_filter', reason='nothing_after_playback', text=result.text, uid=result.uid)
            return None
        record('voice_filter_passed', reason='spoke_after_playback', text=result.text, uid=result.uid)
        return result

    def _recognize_final(self):
        while not self._stop.is_set():
            try:
                utterance, captured = self.utterances.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.clock() - captured > 10:
                put_latest(self.results, Recognition(error='stale_recording'))
                continue
            result = self.handle_final(utterance)
            if result is not None and not self._stop.is_set():
                put_latest(self.results, replace(result, captured_at=captured))

    def handle_interruption(self, utterance):
        """Never puts partial words on the command queue."""
        result = self._transcribe(utterance, partial=True)
        if not self._stop.is_set() and can_interrupt(result, self.stop_confidence):
            stopped = self.speech.stop(expected_id=utterance.playback_id)
            record('interruption', text=result.text, playback_id=utterance.playback_id,
                   stopped=bool(stopped))
            return stopped
        return False

    def _recognize_interruptions(self):
        while not self._stop.is_set():
            try:
                utterance, captured = self.interruptions.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.clock() - captured > 2 or self.speech.snapshot().id != utterance.playback_id:
                continue
            self.handle_interruption(utterance)
