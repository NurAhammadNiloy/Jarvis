"""Speech-independent conversation and request repair; models propose, never execute.

What is pending (a proposal to confirm, a missing time) lives in
core.conversation_state, which the assistant checks before anything reaches here.
"""
from dataclasses import dataclass
import re
import time

from core.conversation_state import answer_kind
from core.phrases import PHRASES, say
from core.voice_policy import ConfidenceGate, Recognition
from core.intent_classifier import COMMAND_INTENTS, route


# Asking for detail allows a longer answer (up to ~6 sentences); otherwise short.
_DETAIL = re.compile(
    r"\b(?:tell\s+me\s+(?:all\s+|more\s+|everything\s+)?about|tell\s+me\s+more|explain|describe|elaborate"
    r"|(?:full|whole|entire)\s+story|in\s+(?:more\s+|great\s+|full\s+)?detail|detailed|history\s+of"
    r"|everything\s+(?:about|on))\b", re.IGNORECASE)
_REPLY_LIMIT = {'short': 500, 'long': 1500}  # characters
CLAIM_FALLBACK = PHRASES['claim_fallback'][0]
MODEL_FAILED = PHRASES['model_failed'][0]


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


# Closing offers of more help: dropped, Jarvis just stops talking.
_FILLER = re.compile(r"^\W*(?:(?:alright|all\s+right|okay|ok|sure|got\s+it|great|of\s+course)\W+)?(?:let\s+me\s+know\s+if|is\s+there\s+anything\s+else|anything\s+else\s+(?:i\s+can|you)"
                     r"|feel\s+free\s+to|if\s+you\s+(?:need|have)\s+(?:anything|any\s+(?:more|other))|hope\s+(?:this|that)\s+helps"
                     r"|i'?m\s+here\s+(?:if|whenever))", re.IGNORECASE)


def without_filler(reply):
    """The reply without closing offers of more help ("Okay." if that was all of it)."""
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    kept = [s for s in sentences if not _FILLER.match(s)]
    return ' '.join(kept).strip() or say('okay')


def without_action_claims(reply):
    """The reply without sentences that claim an action happened ('' if all did)."""
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    # A question ("Should I set an alarm?") never claims anything was done.
    kept = [s for s in sentences if s.rstrip().endswith('?') or not any(p.search(s) for p in _CLAIMS)]
    return ' '.join(kept).strip()


def _shorten(reply, limit):
    """Cut an over-long reply at the last full sentence that fits."""
    if len(reply) <= limit:
        return reply
    cut = reply[:limit]
    end = max(cut.rfind('. '), cut.rfind('? '), cut.rfind('! '))
    return cut[:end + 1] if end > 0 else cut


def parse_model_reply(raw):
    """{'reply': str, 'query': str or None} from the model's text, tolerating code
    fences, prose around the object, extra keys and a missing query."""
    import json
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", '', text, flags=re.IGNORECASE)
        try:
            data = json.loads(text)
        except ValueError:
            start, end = text.find('{'), text.rfind('}')
            if start < 0 or end <= start:
                raise ValueError('No JSON object in the model reply')
            data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('The model reply is not a JSON object')
    reply, query = data.get('reply'), data.get('query')
    if reply is not None and not isinstance(reply, str):
        raise ValueError('reply is not text')
    if isinstance(query, str) and not query.strip() or query in ('null', 'None'):
        query = None
    if query is not None and not isinstance(query, str):
        raise ValueError('query is not text')
    return {'reply': (reply or '').strip(), 'query': query}


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
            return DialogueTurn(say('okay'))
        if not pending and kind == 'yes' and not asked:
            return DialogueTurn(say('what_to_do'))
        # A "yes" to a question the model asked goes back to the model, which
        # can only turn it into a proposal that needs its own confirmation.
        from core.conversation_log import record
        raw = None
        try:
            self.model_called = True
            length = answer_length(recognition.text)
            raw = self.resolve({'history': list(self.history), 'pending_query': pending,
                'reason': reason, 'answer_length': length, 'recognition': {'text': recognition.text,
                    'confidence': recognition.confidence,
                    'alternatives': [a.text for a in recognition.alternatives]}})
            result = parse_model_reply(raw)
        except Exception as exc:
            # Keep the history, but nothing from a failed turn can be proposed. The
            # raw reply is logged, so the cause can be seen ("I couldn't work out ...").
            record('dialogue_error', error=type(exc).__name__, detail=str(exc)[:200],
                   raw=raw if isinstance(raw, str) else repr(raw)[:2000] if raw is not None else None)
            return DialogueTurn(MODEL_FAILED)
        reply, query = _shorten(result['reply'], _REPLY_LIMIT[length]), result['query']
        reply = without_filler(reply)
        honest = without_action_claims(reply)
        if honest != reply:
            record('dialogue_claim_removed', reply=reply, kept=honest)
            reply = honest
        if query is not None:
            try:
                if len(query) > 400:
                    raise ValueError('Proposal too long')
                self._validate(query)
                return DialogueTurn(reply, proposal=query)
            except ValueError as exc:
                # Not something Jarvis can run ("get today's news"): keep the answer,
                # drop the proposal, instead of failing the whole turn.
                record('dialogue_proposal_rejected', query=query, reason=str(exc))
        if not reply:
            return DialogueTurn(CLAIM_FALLBACK if honest != result['reply'] else MODEL_FAILED)
        self.asked = reply.rstrip().endswith('?')
        return DialogueTurn(reply)
