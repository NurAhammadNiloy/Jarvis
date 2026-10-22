"""Speech-independent conversation and request repair; models propose, never execute.

What is pending (a proposal to confirm, a missing time) lives in
core.conversation_state, which the assistant checks before anything reaches here.
"""
from dataclasses import dataclass
import re
import time

from core.conversation_state import answer_kind
from core.voice_policy import ConfidenceGate, Recognition
from core.intent_classifier import COMMAND_INTENTS, route


# Asking for detail allows a longer answer (up to ~6 sentences); otherwise short.
_DETAIL = re.compile(
    r"\b(?:tell\s+me\s+(?:all\s+|more\s+|everything\s+)?about|tell\s+me\s+more|explain|describe|elaborate"
    r"|(?:full|whole|entire)\s+story|in\s+(?:more\s+|great\s+|full\s+)?detail|detailed|history\s+of"
    r"|everything\s+(?:about|on))\b", re.IGNORECASE)
_REPLY_LIMIT = {'short': 500, 'long': 1500}  # characters
CLAIM_FALLBACK = "I haven't done anything yet. What should I do?"


def answer_length(text):
    """'long' when the user asks for detail ("tell me about", "explain", "full story")."""
    return 'long' if _DETAIL.search(text) else 'short'


# The model cannot execute anything, so it must never say that something was done.
# Only the executor's result may say that. A sentence that claims an action is
# removed from the model's reply (in code, not only in the prompt).
_DONE = (r"(?:set(?!\s+out)|saved|created|scheduled|cancel(?:l)?ed|deleted|removed|added|started|stopped|paused"
         r"|resumed|snoozed|booked|turned\s+off|opened|played|updated|changed|taken\s+care\s+of)")
_CLAIMS = (
    # "I'll set that reminder", "I've cancelled it", "I have gone ahead and added ..."
    re.compile(r"\bI(?:['’]ve|['’]ll|['’]m|\s+have|\s+will|\s+just|\s+already)?\s+(?:now\s+|just\s+|already\s+)?"
               r"(?:gone\s+ahead\s+and\s+|going\s+to\s+)?" + _DONE + r"\b", re.IGNORECASE),
    # "Your reminder is set", "it's been cancelled", "the timer has been started"
    re.compile(r"\b(?:reminder|alarm|timer|it|that)s?(?:['’]s|\s+is|\s+has\s+been|\s+have\s+been|\s+was|\s+are)"
               r"\s+(?:now\s+|all\s+)?(?:been\s+)?" + _DONE + r"\b", re.IGNORECASE),
    # "Done." / "All set!" / "Consider it done."
    re.compile(r"^\W*(?:done|all\s+set|consider\s+it\s+done)\b", re.IGNORECASE),
)


def without_action_claims(reply):
    """The reply without sentences that claim an action happened ('' if all did)."""
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    # A question ("Should I set an alarm?") never claims anything was done.
    kept = [s for s in sentences if s.rstrip().endswith('?') or not any(p.search(s) for p in _CLAIMS)]
    return ' '.join(kept).strip()


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
        if route(query).intent not in COMMAND_INTENTS:
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
            length = answer_length(recognition.text)
            result = self.resolve({'history': list(self.history), 'pending_query': pending,
                'reason': reason, 'answer_length': length, 'recognition': {'text': recognition.text,
                    'confidence': recognition.confidence,
                    'alternatives': [a.text for a in recognition.alternatives]}})
            if not isinstance(result, dict) or set(result) != {'reply', 'query'}:
                raise ValueError('Invalid dialogue response')
            reply, query = result['reply'], result['query']
            if not isinstance(reply, str) or not 0 < len(reply) <= _REPLY_LIMIT[length]:
                raise ValueError('Invalid reply')
            if query is not None and (not isinstance(query, str) or not 0 < len(query) <= 400):
                raise ValueError('Invalid proposal')
            honest = without_action_claims(reply)
            if honest != reply:
                from core.conversation_log import record
                record('dialogue_claim_removed', reply=reply, kept=honest)
                reply = honest
            if query is not None:
                self._validate(query)
                return DialogueTurn(reply, proposal=query)
            if not reply:
                return DialogueTurn(CLAIM_FALLBACK)
            self.asked = reply.rstrip().endswith('?')
            return DialogueTurn(reply)
        except Exception:
            # Keep the history, but nothing from a failed turn can be proposed.
            return DialogueTurn("I couldn't work out that follow-up. Could you explain what you want to change?")
