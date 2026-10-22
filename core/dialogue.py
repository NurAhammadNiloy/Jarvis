"""Speech-independent conversation and request repair; models propose, never execute.

What is pending (a proposal to confirm, a missing time) lives in
core.conversation_state, which the assistant checks before anything reaches here.
"""
from dataclasses import dataclass
import time

from core.conversation_state import answer_kind
from core.voice_policy import ConfidenceGate, Recognition
from core.intent_classifier import FAMILIES, route


@dataclass(frozen=True)
class DialogueTurn:
    reply: str = ''
    proposal: str = ''  # a validated command for the user to confirm; never executed here


class Dialogue:
    def __init__(self, resolve=None, clock=time.monotonic):
        self.resolve = resolve or self._resolve
        self.clock = clock
        self.history = []
        self.updated = 0
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
        self.asked = False

    def _start_turn(self, text):
        if self.clock() - self.updated > 120:
            self.clear()
            self.history.clear()
        self.updated = self.clock()
        self.model_called = False
        self.observe('user', text)

    def _validate(self, query):
        """A proposal must be a supported, non-negated command."""
        intent = route(query).intent
        if FAMILIES.get(intent, intent) not in {'reminder', 'alarm', 'timer', 'weather', 'forecast',
                                                'time', 'date', 'youtube', 'google'}:
            raise ValueError('Unsupported proposal')
        if ConfidenceGate(self.clock).assess(Recognition(query, 1.0)).kind != 'accept':
            raise ValueError('Unsafe proposal')

    def propose(self, query):
        """Propose the user's own words without the model, e.g. when recognition
        alternatives differ only in a name ('call Mom' / 'call Mam')."""
        self._start_turn(query)
        self.asked = False
        self._validate(query)
        return DialogueTurn(proposal=query)

    def turn(self, recognition, *, reason='conversation', pending=None):
        """One model turn. `pending` is a request still on the table (e.g. a proposal
        the user is correcting), given to the model as context only."""
        self._start_turn(recognition.text)
        asked, self.asked = self.asked, False
        kind = answer_kind(recognition.text)
        if not pending and kind == 'cancel':
            return DialogueTurn('Okay.')
        if not pending and kind == 'yes' and not asked:
            return DialogueTurn('What would you like me to do?')
        # A "yes" to a question the model asked goes back to the model, which
        # can only turn it into a proposal that needs its own confirmation.
        try:
            self.model_called = True
            result = self.resolve({'history': list(self.history), 'pending_query': pending,
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
                return DialogueTurn(reply, proposal=query)
            self.asked = reply.rstrip().endswith('?')
            return DialogueTurn(reply)
        except Exception:
            # Keep the history, but nothing from a failed turn can be proposed.
            return DialogueTurn("I couldn't work out that follow-up. Could you explain what you want to change?")
