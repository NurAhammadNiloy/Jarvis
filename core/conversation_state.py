"""What Jarvis is waiting for. Every utterance is checked against it first.

  idle                                   nothing pending
  awaiting_confirmation(command)         "I have: ... Shall I do that?"
  awaiting_slot(intent, slot)            e.g. "What time should I set the alarm for?"

A confirmation holds the parsed Command, so "yes" executes exactly what was
proposed and never parses it into another question. Answers here are decided
by fixed rules; the model is never asked what "yes" or "stop" means.
"""
from dataclasses import dataclass
import re
import time
from typing import Optional

from core.command_result import Command
from core.conversation_log import record
from core.phrases import PHRASES, say
from core.voice_policy import means_stop, stop_heard, strip_wake_word, words


# --- short answers ------------------------------------------------------------

_YES = {'yes', 'sure', 'ok', 'confirm', 'confirmed', 'correct', 'right', 'absolutely', 'definitely',
        'affirmative', 'do', 'go'}
# "I said yes", "yes I said", "I already said yes": insisting is still yes.
_INSIST = {'i', 'said', 'say', 'already', 'told', 'you', 'have'}
_YES_FILLER = _YES | _INSIST | {'please', 'it', 'that', 'ahead', 'sir', 'jarvis', 'just', 'to', 'exactly', 'fine',
                                'alright', "that's", 'thats'}
_NO = {'no', 'nope', 'nah', 'negative', "don't"}
_NO_FILLER = _NO | _INSIST | {'thanks', 'thank', 'please', 'sir', 'jarvis', 'not', 'that', 'it', 'wait', 'do'}
_NEGATIONS = {'no', 'nope', 'nah', 'not', "don't", 'never', 'negative'}
_AFFIRMATIONS = _YES - {'do', 'go'}  # words that say yes on their own
_CANCEL = {('cancel',), ('never', 'mind'), ('nevermind',), ('forget', 'it'), ('cancel', 'that'),
           ('cancel', 'it')}
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


def answer_reliable(recognition, kind, *prompts):
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
        text = strip_echoed_prompt(alternative.text, *prompts)
        other = answer_kind(text)
        if other != kind and not (kind == 'yes' and other is None and _says_yes(text)):
            return False
    return True


def strip_echoed_prompt(text, *prompts):
    """Drop the end of Jarvis's question when the microphone caught it in front of
    the answer: 'shall I do that yes' after '... Shall I do that?' -> 'yes'."""
    heard = words(text)
    for prompt in prompts:
        asked = words(prompt)
        for size in range(min(len(heard) - 1, len(asked)), 1, -1):
            if heard[:size] == asked[-size:]:
                return ' '.join(heard[size:])
    return text


def _without_wake_word(text):
    addressed = strip_wake_word(text)
    tokens = list(words(addressed if addressed is not None else text))
    if tokens and tokens[0] in _WAKE_VARIANTS:  # 'Yarvis never mind'
        tokens = tokens[1:]
    return ' '.join(tokens)


def means_cancel(text):
    """Stop or cancel (see voice_policy.means_stop), never mind, forget it."""
    return means_stop(text, cancel=True) or answer_kind(_without_wake_word(text)) == 'cancel'


def stop_threshold(recognition):
    """0.5, or 0.35 for a stop heard over Jarvis's own voice (the runtime only lets
    a short stop or "Jarvis ..." through then)."""
    return 0.35 if recognition.playback_id is not None else 0.5


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
class AwaitingChoice:
    """An either/or question, asked only when the recognition alternatives disagree
    on the action itself: "Add 5 minutes to pasta, or a new 5-minute timer?"."""
    options: tuple   # two parsed Commands
    cues: tuple      # per option, the words that pick it ("add", "new", "pasta", ...)
    prompt: str

    def describe(self):
        return 'awaiting choice: ' + ' / '.join(option.query for option in self.options)


_FIRST, _SECOND = {'first', 'former'}, {'second', 'latter', 'other'}


def pick(choice, text):
    """Index of the option an answer picks, or None."""
    tokens = set(words(text))
    if tokens & _FIRST and not tokens & _SECOND:
        return 0
    if tokens & _SECOND and not tokens & _FIRST:
        return 1
    scores = [len(tokens & cues) for cues in choice.cues]
    best = max(scores)
    return scores.index(best) if best and scores.count(best) == 1 else None


@dataclass(frozen=True)
class AwaitingSlot:
    intent: str   # e.g. 'alarm'
    slot: str     # e.g. 'time'
    query: str    # the request so far; the answer completes it
    prompt: str   # the question that was asked
    command: Optional[Command] = None  # already parsed except for this slot (the task)

    def describe(self):
        return f'awaiting {self.slot} for {self.intent.replace("create_", "")}'


IDLE = Idle()
# Asked again after an unclear yes/no. It must not contain "yes": the echo
# filter drops a "yes" heard while Jarvis is saying "yes".
# The confirmation question used until 22 Oct; its echo still turns up in answers.
_OLD_PROMPT = 'Shall I do that?'
REPROMPT = PHRASES['reask'][0]


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

    def choose(self, options, cues, prompt):
        self._set(AwaitingChoice(tuple(options), tuple(cues), prompt), 'asked either/or')

    def await_slot(self, intent, slot, query, prompt, command=None):
        self._set(AwaitingSlot(intent, slot, query, prompt, command), 'asked')

    def clear(self, reason):
        if self._state is not IDLE:
            self._set(IDLE, reason)

    def check(self, recognition, text):
        """Decide an utterance against what is pending; None means 'a new request'."""
        state = self.current
        if state is IDLE:
            return None
        if stop_heard(recognition, stop_threshold(recognition), cancel=True) or (
                answer_kind(_without_wake_word(recognition.text)) == 'cancel' and
                answer_reliable(recognition, 'cancel')):
            self.clear('cancelled')
            return Answer('cancel')
        if recognition.error or recognition.truncated or not text:
            return None
        if isinstance(state, AwaitingSlot):
            return Answer('fill', text=f'{state.query} {text}')
        if isinstance(state, AwaitingChoice):
            return self._check_choice(state, recognition, text)
        answer = strip_echoed_prompt(text, state.prompt, REPROMPT, _OLD_PROMPT)
        kind = answer_kind(answer)
        if kind in ('yes', 'no') and not answer_reliable(recognition, kind, state.prompt, REPROMPT, _OLD_PROMPT):
            return Answer('reply', text=REPROMPT)
        if kind == 'yes':
            self.clear('confirmed')
            return Answer('execute', command=state.command)
        if kind == 'no':
            self.clear('declined')
            return Answer('reply', text=say('declined'))
        return None  # something else: a correction or a new request

    def _check_choice(self, state, recognition, text):
        answer = strip_echoed_prompt(text, state.prompt)
        index = pick(state, answer)
        if index is not None and (recognition.confidence is None or recognition.confidence >= 0.5):
            self.clear('chosen')
            return Answer('execute', command=state.options[index])
        kind = answer_kind(answer)
        if kind == 'no' and answer_reliable(recognition, 'no', state.prompt):
            self.clear('declined')
            return Answer('reply', text=say('declined'))
        if kind == 'yes' or index is None and len(words(answer)) <= 2:
            return Answer('reply', text=say('which_one', question=state.prompt))
        return None  # a new request
