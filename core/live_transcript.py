"""One terminal line per heard utterance, built from conversation-log events.

  You (heard): "delete my call mom reminder"  conf 0.82 | intent delete_reminder | fast path | stt 0.9s, total 1.4s | Jarvis: "Deleted: ..."
  You (ignored: no wake word): "Deli"  conf 0.06 | stt 0.5s

"total" runs from the end of your speech (as detected by the microphone, which
is about 1.4 s of silence after your last word) to the first audio of Jarvis's
reply. Partial (interruption) recognitions are not shown.
"""
from dataclasses import dataclass, field
import threading
import time

from core.intent_classifier import route
from core.voice_policy import strip_wake_word

_REASONS = {
    'no_wake_word': 'no wake word',
    'weak_wake_word': 'weak wake word',
    'unrecognized_while_response_pending': 'unrecognized, reply pending',
    'repeated_unrecognized_audio': 'unrecognized again',
    'unaddressed_during_playback': 'spoke over Jarvis without "Jarvis"',
    'response_echo': "echo of Jarvis's own voice",
}


@dataclass
class _Turn:
    text: str
    confidence: object
    error: object
    stt_ms: object
    ended_at: object
    path: str = ''
    intent: str = ''
    model_ms: object = None
    reply: str = ''
    reply_id: object = None
    extra: list = field(default_factory=list)


class LiveTranscript:
    def __init__(self, out=print, clock=time.monotonic, width=60):
        self.out, self.clock, self.width = out, clock, width
        self._lock = threading.Lock()
        self._turn = None
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
            self._flush()
            self._turn = _Turn(f.get('text') or '', f.get('confidence'), f.get('error'),
                               self._stt_ms, self._utterance_ended)
            self._stt_ms = None
        elif self._turn is None:
            return
        elif event == 'voice_filter':
            self._finish(f"rejected: {_REASONS.get(f.get('reason'), f.get('reason'))}")
        elif event == 'voice_decision':
            decision, reason = f.get('decision'), f.get('reason')
            if decision == 'ignore':
                self._finish(f"ignored: {_REASONS.get(reason, reason)}")
            elif decision == 'stop':
                self._turn.path = 'stop'
                self._finish('heard')
            elif decision == 'clarify':
                self._turn.path = 'clarification' + (f" ({reason.replace('_', ' ')})" if reason else '')
            elif decision == 'wake':
                self._turn.path = 'wake word'
            elif decision == 'accept' and not self._turn.path:
                self._turn.path = 'fast path'
        elif event == 'pending_answer':
            self._turn.path = {'execute': 'confirmed', 'cancel': 'cancelled',
                               'fill': f"answer ({f.get('state')})"}.get(f.get('answer'),
                                                                        f"reply to ({f.get('state')})")
        elif event == 'dialogue_turn':
            self._turn.model_ms = f.get('duration_ms')
            if f.get('confirmed_query'):  # logs from before the conversation state
                self._turn.path = 'confirmed -> fast path'
            else:
                self._turn.path = 'ChatGPT dialogue' if f.get('model_called', True) else 'dialogue (no model)'
                if f.get('trigger') and f['trigger'] != 'conversation':
                    self._turn.path += f" ({f['trigger']})"
        elif event == 'command_result':
            self._turn.intent = f.get('intent') or ''
            if not self._turn.path:
                self._turn.path = 'fast path'
        elif event == 'speech_queued' and self._turn.reply_id is None:
            self._turn.reply_id, self._turn.reply = f.get('playback_id'), f.get('text') or ''
        elif event == 'playback_chunk_started' and f.get('playback_id') == self._turn.reply_id:
            self._finish('heard', reply_started=True)
        elif event == 'speech_finished' and f.get('playback_id') == self._turn.reply_id:
            self._finish('heard')

    # --- output --------------------------------------------------------------

    def _flush(self):
        if self._turn is not None:
            self._finish('heard')

    def _finish(self, status, reply_started=False):
        turn, self._turn = self._turn, None
        if turn is None:
            return
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
        timing = []
        if turn.stt_ms is not None:
            timing.append(f"stt {turn.stt_ms / 1000:.1f}s")
        if turn.model_ms is not None:
            timing.append(f"model {turn.model_ms / 1000:.1f}s")
        if reply_started and turn.ended_at is not None:
            timing.append(f"total {self.clock() - turn.ended_at:.1f}s")
        if timing:
            parts.append(', '.join(timing))
        if turn.reply:
            parts.append(f'Jarvis: "{self._short(turn.reply)}"')
        self._print(' | '.join(parts))

    def _short(self, text):
        text = ' '.join((text or '').split())
        return text if len(text) <= self.width else text[:self.width - 3] + '...'

    def _print(self, line):
        try:
            self.out(line)
        except UnicodeEncodeError:  # e.g. a Windows console code page
            self.out(line.encode('ascii', 'replace').decode('ascii'))


def enable(out=print):
    """Show live transcripts if settings.SHOW_TRANSCRIPTS (default True)."""
    from config.settings import SHOW_TRANSCRIPTS
    if not SHOW_TRANSCRIPTS:
        return None
    from core.conversation_log import add_listener
    printer = LiveTranscript(out)
    add_listener(printer)
    return printer
