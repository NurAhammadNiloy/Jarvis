"""Speech-independent conversational repair; models propose, never execute."""
from dataclasses import dataclass
import re
import time

from core.voice_policy import words, ConfidenceGate, Recognition
from core.intent_classifier import FAMILIES, route


_YES = {'yes', 'sure', 'ok', 'confirm', 'confirmed', 'correct', 'right', 'absolutely', 'definitely',
        'affirmative', 'do', 'go'}
_YES_FILLER = _YES | {'please', 'it', 'that', 'ahead', 'sir', 'jarvis', 'just', 'to', 'exactly', 'fine',
                      'alright', "that's", 'thats'}
_NO = {'no', 'nope', 'nah', 'negative', "don't"}
_NO_FILLER = _NO | {'thanks', 'thank', 'you', 'please', 'sir', 'jarvis', 'not', 'that', 'it', 'wait', 'do'}
_NEGATIONS = {'no', 'nope', 'nah', 'not', "don't", 'never', 'negative'}
_CANCEL = {('cancel',), ('never', 'mind'), ('nevermind',), ('forget', 'it'), ('cancel', 'that'),
           ('cancel', 'it')}


def _normalize(token):
    if re.fullmatch(r"ye+s+|ye+a+h*|ya+h?|yu+p+|ye+p+", token):
        return 'yes'
    if re.fullmatch(r"o+k+(?:a+y+)?|k+|kay|okey", token):
        return 'ok'
    return token


def answer_kind(text):
    """'yes', 'no' or 'cancel' for a short answer such as 'yes do it'; else None."""
    tokens = tuple(_normalize(t) for t in words(text))
    if not tokens:
        return None
    if tokens in _CANCEL:
        return 'cancel'
    if set(tokens) & _NO and all(t in _NO_FILLER for t in tokens):
        return 'no'
    if not set(tokens) & _NEGATIONS and set(tokens) & _YES and all(t in _YES_FILLER for t in tokens):
        return 'yes'
    return None


def answer_reliable(recognition, kind):
    """Short answers score low (Google gave 'yes' 0.56), so accept >= 0.5 when every
    alternative means the same thing; >= 0.8 ignores alternatives scored below 0.5."""
    confidence = recognition.confidence
    if recognition.error or recognition.truncated or confidence is None or confidence < 0.5:
        return False
    for alternative in recognition.alternatives:
        if confidence >= 0.8 and alternative.confidence is not None and alternative.confidence < 0.5:
            continue
        if answer_kind(alternative.text) != kind:
            return False
    return True


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
        self.model_called = False  # whether the last turn called the model
        self.asked = False  # the model's last reply was a question

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
        self.asked = False

    def _validate(self, query):
        """A proposal must be a supported, non-negated command."""
        intent = route(query).intent
        if FAMILIES.get(intent, intent) not in {'reminder', 'alarm', 'timer', 'weather', 'forecast',
                                                'time', 'date', 'youtube', 'google'}:
            raise ValueError('Unsupported proposal')
        if ConfidenceGate(self.clock).assess(Recognition(query, 1.0)).kind != 'accept':
            raise ValueError('Unsafe proposal')

    def propose(self, query):
        """Confirm the user's own words without the model, e.g. when recognition
        alternatives differ only in a name ('call Mom' / 'call Mam')."""
        if self.clock() - self.updated > 120:
            self.clear()
            self.history.clear()
        self.updated = self.clock()
        self.model_called = False
        self.asked = False
        self.observe('user', query)
        self._validate(query)
        self.pending, self.repairing = query, True
        return DialogueTurn(f"I have: {query.rstrip('.!?')}. Shall I do that?")

    def turn(self, recognition, *, reason='conversation'):
        if self.clock() - self.updated > 120:
            self.clear()
            self.history.clear()
        self.updated = self.clock()
        self.model_called = False
        asked, self.asked = self.asked, False
        kind = answer_kind(recognition.text)
        reliable = kind is not None and answer_reliable(recognition, kind)
        self.observe('user', recognition.text)
        if kind == 'cancel' and reliable:
            self.clear()
            return DialogueTurn("Okay, I've dropped that request.")
        if self.pending and kind == 'yes':
            if not reliable:
                return DialogueTurn('Please say yes again clearly to confirm, or tell me what to change.')
            query = self.pending
            self.clear()  # Consume before execution: no duplicate on another yes.
            return DialogueTurn(query=query)
        if self.pending and kind == 'no' and reliable:
            self.pending = None
            self.repairing = True
            return DialogueTurn('What should I change?')
        if not self.pending and kind == 'yes' and not asked:
            return DialogueTurn('What would you like me to do?')
        # A "yes" to a question the model asked goes back to the model, which
        # can only turn it into a proposal that needs its own confirmation.
        try:
            self.model_called = True
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
                self._validate(query)
            self.pending = query
            self.repairing = query is not None or reason != 'conversation'
            if query:
                # The audible confirmation is constructed from the exact command
                # that will execute, not a potentially different model summary.
                return DialogueTurn(f"I have: {query.rstrip('.!?')}. Shall I do that?")
            self.asked = reply.rstrip().endswith('?')
            return DialogueTurn(reply)
        except Exception:
            # Preserve context, but invalidate authorization after a failed turn.
            self.pending = None
            self.repairing = True
            return DialogueTurn("I couldn't work out that follow-up. Could you explain what you want to change?")
