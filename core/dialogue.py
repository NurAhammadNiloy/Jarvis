"""Speech-independent conversational repair; models propose, never execute."""
from dataclasses import dataclass
import time

from core.voice_policy import words, alternatives_conflict, ConfidenceGate, Recognition
from core.intent_classifier import classify_intent


@dataclass(frozen=True)
class DialogueTurn:
    reply: str = ''
    query: str = ''


class Dialogue:
    def __init__(self, resolve=None, clock=time.monotonic):
        self.resolve = resolve or self._resolve
        self.clock = clock
        self.history = []
        self.pending = None
        self.updated = 0
        self.repairing = False

    @staticmethod
    def _resolve(context):
        from core.chatgpt_service import resolve_dialogue
        return resolve_dialogue(context)

    def observe(self, role, text):
        self.history.append({'role': role, 'text': text})
        self.history = self.history[-16:]

    def clear(self):
        self.pending = None
        self.repairing = False

    def turn(self, recognition, *, reason='conversation'):
        if self.clock() - self.updated > 120:
            self.clear()
            self.history.clear()
        self.updated = self.clock()
        tokens = words(recognition.text)
        reliable = (not recognition.error and not recognition.truncated and
                    recognition.confidence is not None and recognition.confidence >= 0.8 and
                    not alternatives_conflict(recognition, important=True))
        self.observe('user', recognition.text)
        if reliable and tokens in {('cancel',), ('never', 'mind'), ('forget', 'it')}:
            self.clear()
            return DialogueTurn("Okay, I've dropped that request.")
        if self.pending and tokens in {('yes',), ('yes', 'please'), ('confirm',)}:
            if not reliable:
                return DialogueTurn('Please say yes again clearly to confirm, or tell me what to change.')
            query = self.pending
            self.clear()  # Consume before execution: no duplicate on another yes.
            return DialogueTurn(query=query)
        if self.pending and reliable and tokens in {('no',), ('nope',)}:
            self.pending = None
            self.repairing = True
            return DialogueTurn('What should I change?')
        if not self.pending and tokens in {('yes',), ('confirm',)}:
            return DialogueTurn('What would you like me to do?')
        try:
            result = self.resolve({'history': list(self.history), 'pending_query': self.pending,
                'reason': reason, 'recognition': {'text': recognition.text,
                    'confidence': recognition.confidence,
                    'alternatives': [a.text for a in recognition.alternatives]}})
            if not isinstance(result, dict) or set(result) != {'reply', 'query'}:
                raise ValueError('Invalid dialogue response')
            reply, query = result['reply'], result['query']
            if not isinstance(reply, str) or not 0 < len(reply) <= 500:
                raise ValueError('Invalid reply')
            if query is not None and (not isinstance(query, str) or not 0 < len(query) <= 400):
                raise ValueError('Invalid proposal')
            if query is not None:
                if classify_intent(query) not in {'reminder', 'timer', 'weather', 'forecast', 'time', 'date', 'youtube', 'google'}:
                    raise ValueError('Unsupported proposal')
                if ConfidenceGate(self.clock).assess(Recognition(query, 1.0)).kind != 'accept':
                    raise ValueError('Unsafe proposal')
            self.pending = query
            self.repairing = query is not None or reason != 'conversation'
            if query:
                # The audible confirmation is constructed from the exact command
                # that will execute, not a potentially different model summary.
                return DialogueTurn(f"I have: {query.rstrip('.!?')}. Shall I do that?")
            return DialogueTurn(reply)
        except Exception:
            # Preserve context, but invalidate authorization after a failed turn.
            self.pending = None
            self.repairing = True
            return DialogueTurn("I couldn't work out that follow-up. Could you explain what you want to change?")
