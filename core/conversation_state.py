"""What Jarvis is waiting for. Every utterance is checked against it first.

  idle                                   nothing pending
  awaiting_confirmation(command)         "I have: ... Shall I do that?"
  awaiting_slot(intent, slot)            e.g. "What time should I set the alarm for?"

A confirmation holds the parsed Command, so "yes" executes exactly what was
proposed and never parses it into another question. Answers here are decided
by fixed rules; the model is never asked what "yes" or "stop" means.
"""
from dataclasses import dataclass, replace
import re
import time
from typing import Optional

from core.command_result import Command
from core.conversation_log import record
from core.voice_policy import STOP_PHRASES, strip_wake_word, words


# --- short answers ------------------------------------------------------------

_YES = {'yes', 'sure', 'ok', 'confirm', 'confirmed', 'correct', 'right', 'absolutely', 'definitely',
        'affirmative', 'do', 'go'}
_YES_FILLER = _YES | {'please', 'it', 'that', 'ahead', 'sir', 'jarvis', 'just', 'to', 'exactly', 'fine',
                      'alright', "that's", 'thats'}
_NO = {'no', 'nope', 'nah', 'negative', "don't"}
_NO_FILLER = _NO | {'thanks', 'thank', 'you', 'please', 'sir', 'jarvis', 'not', 'that', 'it', 'wait', 'do'}
_NEGATIONS = {'no', 'nope', 'nah', 'not', "don't", 'never', 'negative'}
_AFFIRMATIONS = _YES - {'do', 'go'}  # words that say yes on their own
_CANCEL = {('cancel',), ('never', 'mind'), ('nevermind',), ('forget', 'it'), ('cancel', 'that'),
           ('cancel', 'it')}
_STOP_WORDS = {'stop', 'stopped', 'stops', 'stopping', 'stahp', 'please'}
_WAKE_VARIANTS = {'jarvis', 'yarvis', 'jervis', 'javis'}


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


def _says_yes(text):
    tokens = {_normalize(t) for t in words(text)}
    return bool(tokens & _AFFIRMATIONS) and not tokens & _NEGATIONS


def answer_reliable(recognition, kind, prompt=''):
    """Short answers score low (Google gave 'yes' 0.56), so >= 0.5 is enough when no
    alternative contradicts it. An alternative that still says yes ('shall I do that
    yes do it') is no contradiction; 'no' or a yes-less guess is. From 0.8 up,
    alternatives scored below 0.5 are ignored."""
    confidence = recognition.confidence
    if recognition.error or recognition.truncated or confidence is None or confidence < 0.5:
        return False
    for alternative in recognition.alternatives:
        if confidence >= 0.8 and alternative.confidence is not None and alternative.confidence < 0.5:
            continue
        text = strip_echoed_prompt(alternative.text, prompt)
        other = answer_kind(text)
        if other != kind and not (kind == 'yes' and other is None and _says_yes(text)):
            return False
    return True


def strip_echoed_prompt(text, prompt):
    """Drop the end of Jarvis's question when the microphone caught it in front of
    the answer: 'shall I do that yes' after '... Shall I do that?' -> 'yes'."""
    heard, asked = words(text), words(prompt)
    for size in range(min(len(heard) - 1, len(asked)), 1, -1):
        if heard[:size] == asked[-size:]:
            return ' '.join(heard[size:])
    return text


def _stop_words(text):
    addressed = strip_wake_word(text)
    tokens = list(words(addressed if addressed is not None else text))
    if tokens and tokens[0] in _WAKE_VARIANTS:  # 'Yarvis stop'
        tokens = tokens[1:]
    return tokens


def means_stop(text):
    """'stop', 'Jarvis stop', and how recognition spells it ('stopped', 'stahp')."""
    tokens = _stop_words(text)
    return tuple(tokens) in STOP_PHRASES or (
        any(t != 'please' for t in tokens) and all(t in _STOP_WORDS for t in tokens))


def means_cancel(text):
    return means_stop(text) or answer_kind(' '.join(_stop_words(text))) == 'cancel'


def heard_as(recognition, meaning):
    """The primary transcript and every alternative worth considering mean the
    same thing. Cancelling is harmless, so 0.5 is enough."""
    if recognition.error or recognition.truncated or not recognition.text:
        return False
    if recognition.confidence is not None and recognition.confidence < 0.5:
        return False
    return meaning(recognition.text) and all(
        meaning(a.text) for a in recognition.alternatives if a.confidence is None or a.confidence >= 0.5)


# --- the state ------------------------------------------------------------------

@dataclass(frozen=True)
class Idle:
    def describe(self):
        return 'idle'


@dataclass(frozen=True)
class AwaitingConfirmation:
    command: Command  # parsed once; "yes" executes exactly this
    prompt: str

    def describe(self):
        return f'awaiting confirmation: {self.command.query}'


@dataclass(frozen=True)
class AwaitingSlot:
    intent: str   # e.g. 'alarm'
    slot: str     # e.g. 'time'
    query: str    # the request so far; the answer completes it
    prompt: str   # the question that was asked

    def describe(self):
        return f'awaiting {self.slot} for {self.intent.replace("create_", "")}'


IDLE = Idle()


@dataclass(frozen=True)
class Answer:
    """What an utterance means for the pending state; None from check() = a new request."""
    kind: str                         # cancel / execute / reply / fill
    command: Optional[Command] = None  # execute
    text: str = ''                     # reply: what to say; fill: the completed request


class ConversationState:
    def __init__(self, clock=time.monotonic, timeout=120):
        self.clock, self.timeout = clock, timeout
        self._state, self._since = IDLE, clock()

    @property
    def current(self):
        if self._state is not IDLE and self.clock() - self._since > self.timeout:
            self._set(IDLE, 'expired')
        return self._state

    @property
    def pending(self):
        return self.current is not IDLE

    def _set(self, state, reason):
        self._state, self._since = state, self.clock()
        record('conversation_state', state=state.describe(), reason=reason)

    def confirm(self, command, prompt):
        self._set(AwaitingConfirmation(command, prompt), 'proposed')

    def await_slot(self, intent, slot, query, prompt):
        self._set(AwaitingSlot(intent, slot, query, prompt), 'asked')

    def clear(self, reason):
        if self._state is not IDLE:
            self._set(IDLE, reason)

    def check(self, recognition, text):
        """Decide an utterance against what is pending; None means 'a new request'."""
        state = self.current
        if state is IDLE:
            return None
        if heard_as(recognition, means_cancel):
            self.clear('cancelled')
            return Answer('cancel')
        if recognition.error or recognition.truncated or not text:
            return None
        if isinstance(state, AwaitingSlot):
            return Answer('fill', text=f'{state.query} {text}')
        answer = strip_echoed_prompt(text, state.prompt)
        kind = answer_kind(answer)
        if kind in ('yes', 'no') and not answer_reliable(recognition, kind, state.prompt):
            # Never put "yes" in this prompt: the echo filter would drop your next "yes".
            prompt = "Sorry, I didn't catch that. Should I go ahead?"
            self._set(replace(state, prompt=prompt), 'asked again')
            return Answer('reply', text=prompt)
        if kind == 'yes':
            self.clear('confirmed')
            return Answer('execute', command=state.command)
        if kind == 'no':
            self.clear('declined')
            return Answer('reply', text="Okay, I won't do that.")
        return None  # something else: a correction or a new request
