"""One terminal line per heard utterance, built from conversation-log events.

  You (heard): "delete my call mom reminder"  conf 0.82 | intent delete_reminder | fast path | active 10s | stt 0.9s, total 1.4s | Jarvis: "Deleted: ..."
  You (ignored: no wake word): "Deli"  conf 0.06 | passive | stt 0.5s

Each recognition carries a uid. The assistant brackets its handling of one
utterance with turn_started / turn_finished, so a reply is printed on the line
of the utterance that caused it even when the next utterance was heard before
ChatGPT answered. A reply nothing you said asked for (a reminder going off) gets
its own line ("Jarvis: ..."). The window state (active and seconds left, or
passive) is taken when the assistant has finished with the utterance.

"total" runs from the end of your speech (as detected by the microphone, which
is about 1.4 s of silence after your last word) to the first audio of Jarvis's
reply. Partial (interruption) recognitions are not shown.
"""
from dataclasses import dataclass
import threading
import time

from core.intent_classifier import route
from core.voice_policy import strip_wake_word

_REASONS = {
    'no_wake_word': 'no wake word',
    'weak_wake_word': 'weak wake word',
    'weak_without_wake_word': 'low confidence, no wake word',
    'unrecognized_while_response_pending': 'unrecognized, reply pending',
    'repeated_unrecognized_audio': 'unrecognized again',
    'unrecognized_nothing_pending': 'unrecognized, nothing pending',
    'unaddressed_during_playback': 'spoke over Jarvis without "Jarvis"',
    'response_echo': "echo of Jarvis's own voice",
    'speakers_mode': 'Jarvis speaking (speakers mode)',
}


@dataclass
class _Turn:
    uid: object
    text: str
    confidence: object
    error: object
    stt_ms: object = None
    ended_at: object = None
    status: str = ''
    path: str = ''
    intent: str = ''
    model_ms: object = None
    reply: str = ''
    reply_id: object = None
    reply_started_at: object = None
    window: str = ''
    started: bool = False


class LiveTranscript:
    def __init__(self, out=print, clock=time.monotonic, width=60):
        self.out, self.clock, self.width = out, clock, width
        self._lock = threading.Lock()
        self._turns = {}       # uid -> heard and not printed yet, in the order heard
        self._current = None   # the turn the assistant is handling
        self._waiting = {}     # reply playback id -> finished turn, printed when the reply starts
        self._utterance_ended = None
        self._stt_ms = None

    def __call__(self, event, fields):
        with self._lock:
            try:
                self._handle(event, fields)
            except Exception:  # a display problem must never affect the assistant
                pass

    # --- event handling ------------------------------------------------------

    def _handle(self, event, f):
        if event == 'utterance_ended':
            self._utterance_ended = self.clock()
        elif event == 'recognition_timing' and not f.get('partial'):
            self._stt_ms = f.get('duration_ms')
        elif event == 'recognition' and not f.get('partial'):
            uid = f.get('uid')
            self._turns[uid] = _Turn(uid, f.get('text') or '', f.get('confidence'), f.get('error'),
                                     self._stt_ms, self._utterance_ended)
            self._stt_ms = None
        elif event == 'voice_filter':
            turn = self._turns.get(f.get('uid'))
            if turn is not None:
                reason = f.get('reason')
                verb = 'ignored' if reason == 'speakers_mode' else 'rejected'
                self._print_turn(turn, f"{verb}: {_REASONS.get(reason, reason)}")
        elif event == 'turn_started':
            self._start(f)
        elif event == 'turn_finished':
            turn, self._current = self._current, None
            if turn is not None:
                turn.window = f.get('window') or ''
                if turn.reply_id is not None and turn.reply_started_at is None:
                    self._waiting[turn.reply_id] = turn
                else:
                    self._print_turn(turn)
        elif event == 'speech_queued':
            if self._current is not None and self._current.reply_id is None:
                self._current.reply_id, self._current.reply = f.get('playback_id'), f.get('text') or ''
            else:
                self._print(f"Jarvis: {f.get('text') or ''}")
        elif event in ('playback_chunk_started', 'speech_finished'):
            playback = f.get('playback_id')
            turn = self._waiting.pop(playback, None)
            if turn is None and self._current is not None and self._current.reply_id == playback:
                turn = self._current  # playing before the assistant finished
            if turn is not None and event == 'playback_chunk_started' and turn.reply_started_at is None:
                turn.reply_started_at = self.clock()
            if turn is not None and turn is not self._current:
                self._print_turn(turn)
        elif self._current is not None:
            self._annotate(self._current, event, f)

    def _start(self, f):
        uid = f.get('uid')
        # Final results are handled in the order they were heard, so an earlier
        # one that never started was dropped (too old, or the queue was full).
        for other in list(self._turns.values()):
            if other.uid == uid:
                break
            if not other.started:
                self._print_turn(other, 'ignored: not processed (arrived too late)')
        turn = self._turns.get(uid)
        if turn is None:  # e.g. a stale-recording notice that was never recognized
            turn = self._turns[uid] = _Turn(uid, f.get('text') or '', f.get('confidence'), f.get('error'))
        turn.started = True
        self._current = turn

    def _annotate(self, turn, event, f):
        if event == 'voice_decision':
            decision, reason = f.get('decision'), f.get('reason')
            if decision == 'ignore':
                turn.status = f"ignored: {_REASONS.get(reason, reason)}"
            elif decision == 'stop':
                turn.path = 'stop'
            elif decision == 'clarify':
                turn.path = 'clarification' + (f" ({reason.replace('_', ' ')})" if reason else '')
            elif decision == 'wake':
                turn.path = 'wake word'
            elif decision == 'accept' and not turn.path:
                turn.path = 'fast path'
        elif event == 'pending_answer':
            turn.path = {'execute': 'confirmed', 'cancel': 'cancelled',
                         'fill': f"answer ({f.get('state')})"}.get(f.get('answer'), f"reply to ({f.get('state')})")
        elif event == 'dialogue_turn':
            turn.model_ms = f.get('duration_ms')
            if f.get('confirmed_query'):  # logs from before the conversation state
                turn.path = 'confirmed -> fast path'
            else:
                turn.path = 'ChatGPT dialogue' if f.get('model_called', True) else 'dialogue (no model)'
                if f.get('trigger') and f['trigger'] != 'conversation':
                    turn.path += f" ({f['trigger']})"
        elif event == 'command_result':
            turn.intent = f.get('intent') or ''
            if not turn.path:
                turn.path = 'fast path'

    # --- output --------------------------------------------------------------

    def _print_turn(self, turn, status=None):
        self._turns.pop(turn.uid, None)
        status = status or turn.status or 'heard'
        heard = self._short(turn.text) or '(unrecognized)'
        confidence = f"{turn.confidence:.2f}" if isinstance(turn.confidence, (int, float)) else '-'
        parts = [f'You ({status}): "{heard}"  conf {confidence}']
        if status == 'heard' and turn.text and turn.path != 'wake word':
            addressed = strip_wake_word(turn.text)
            parts.append(f"intent {turn.intent or route(addressed if addressed is not None else turn.text).intent}")
            if turn.path:
                parts.append(turn.path)
        elif status == 'heard' and turn.path:
            parts.append(turn.path)
        if turn.window:
            parts.append(turn.window)
        timing = []
        if turn.stt_ms is not None:
            timing.append(f"stt {turn.stt_ms / 1000:.1f}s")
        if turn.model_ms is not None:
            timing.append(f"model {turn.model_ms / 1000:.1f}s")
        if turn.reply_started_at is not None and turn.ended_at is not None:
            timing.append(f"total {turn.reply_started_at - turn.ended_at:.1f}s")
        if timing:
            parts.append(', '.join(timing))
        if turn.reply:
            parts.append(f'Jarvis: "{" ".join(turn.reply.split())}"')  # in full: its only copy
        self._print(' | '.join(parts))

    def _short(self, text):
        text = ' '.join((text or '').split())
        return text if len(text) <= self.width else text[:self.width - 3] + '...'

    def _print(self, line):
        try:
            self.out(line)
        except UnicodeEncodeError:  # e.g. a Windows console code page
            self.out(line.encode('ascii', 'replace').decode('ascii'))


_printer = None


def enable(out=print):
    """Show live transcripts if settings.SHOW_TRANSCRIPTS (default True)."""
    global _printer
    from config.settings import SHOW_TRANSCRIPTS
    if not SHOW_TRANSCRIPTS:
        return None
    from core.conversation_log import add_listener
    printer = _printer = LiveTranscript(out)
    add_listener(printer)
    return printer


def showing():
    """Whether transcripts print Jarvis's replies (so nothing else should)."""
    from core.conversation_log import has_listener
    return _printer is not None and has_listener(_printer)
