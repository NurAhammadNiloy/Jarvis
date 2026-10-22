"""Conservative decisions over provider transcripts. No audio or provider imports."""
from dataclasses import dataclass, field
import itertools
import re
from typing import Optional, Tuple

from core.intent_classifier import classify_intent
from core.phrases import say


@dataclass(frozen=True)
class Hypothesis:
    text: str
    confidence: Optional[float] = None


@dataclass(frozen=True)
class Recognition:
    text: str = ""
    confidence: Optional[float] = None
    alternatives: Tuple[Hypothesis, ...] = ()
    error: Optional[str] = None
    truncated: bool = False
    playback_id: Optional[int] = None
    playback_text: str = ""
    captured_at: Optional[float] = None
    # The on-device detector heard the wake word at the start of this utterance (its
    # score). The text is then addressed to Jarvis even if it lacks "Jarvis".
    wake_score: Optional[float] = None
    # Only when wake_score is set: whether the cloud transcript of the utterance has the
    # wake word, or a word it is misheard as (wake_like); None when unknown (no transcript).
    wake_heard: Optional[bool] = None
    # Identifies one heard utterance in the log (kept by dataclasses.replace).
    uid: int = field(default_factory=itertools.count(1).__next__, compare=False)


def words(text):
    # Normalization is for comparison only. Never rewrite the dispatched text.
    return tuple(re.findall(r"[\w]+(?:['’][\w]+)?", text.lower()))


# A word in front of the wake word that still means something stays in the request.
_KEEP_BEFORE_WAKE = {'no', 'yes', 'not', "don't", 'stop', 'cancel'}


def strip_wake_word(text):
    """The request after "Jarvis" as the first or second word ("hey Jarvis, ...",
    "ok Jarvis ..."), or None when it is not addressed to Jarvis."""
    match = re.match(r"^\s*(?:([\w'’]+)[\s,.:!?-]+)?jarvis\b[\s,.:!?-]*", text, re.IGNORECASE)
    if not match:
        return None
    rest = text[match.end():].strip()
    before = (match.group(1) or '').lower()
    return f"{before} {rest}".strip() if before in _KEEP_BEFORE_WAKE else rest


STOP_PHRASES = {('stop',), ('quiet',), ('silence',), ('stop', 'speaking'),
                ('stop', 'talking'), ('be', 'quiet'), ('please', 'stop'),
                ('please', 'be', 'quiet')}
PROTECTED = {'not', 'no', "don't", 'don’t', 'never', 'without', 'cancel',
             'delete', 'remove', 'clear', 'stop', 'pause', 'resume', 'continue',
             'yes', 'quiet', 'unpause'}
ACTION_INTENTS = {'reminder', 'timer', 'youtube', 'google', 'alarm'}
NEGATION = {'not', 'no', 'never', "don't", 'don’t', 'without'}


def is_stop(text):
    command = strip_wake_word(text)
    return words(command if command is not None else text) in STOP_PHRASES


# How recognition spells "stop" and "cancel": stopped, stoppe, stahp, cancelled.
_STOP_WORD = re.compile(r"st(?:o+p+(?:e|ed|s|ing)?|a+h*p+)")
_CANCEL_WORD = re.compile(r"cancel(?:s|l?ed|l?ing)?")
_NOT = {'not', 'no', 'never', "don't", 'don’t', "can't", 'cannot', "won't", "didn't"}


def means_stop(text, cancel=False):
    """A short utterance (<= 4 words) with "stop" (or "cancel") anywhere in it:
    'Jarvis stop Jarvis', 'Genesis stop' - the other words are wake-word variants
    or mishearings of it. Negated ('don't stop') or with a target ('stop the
    timer', 'cancel my reminder': those are commands) it is not."""
    tokens = words(text)
    if not tokens or len(tokens) > 4 or set(tokens) & _NOT:
        return False
    if not any(_STOP_WORD.fullmatch(t) or (cancel and _CANCEL_WORD.fullmatch(t)) for t in tokens):
        return False
    addressed = strip_wake_word(text)
    return classify_intent(addressed if addressed is not None else text) == 'chat'


def stop_heard(result, threshold, cancel=False):
    """Stopping is harmless, so the primary transcript decides, at `threshold`."""
    if result.error or result.truncated or not result.text:
        return False
    if result.confidence is not None and result.confidence < threshold:
        return False
    return means_stop(result.text, cancel)


def is_echo(text, playback_text):
    heard, spoken = words(text), words(playback_text)
    return bool(heard and spoken and any(spoken[i:i + len(heard)] == heard
                for i in range(len(spoken) - len(heard) + 1)))


_WAKE_VARIANTS = {'jarvis', 'yarvis', 'jervis', 'javis'}
# What the cloud recognizer also made of your "Jarvis" (logs/conversation.jsonl, Oct 2026).
_WAKE_MISHEARD = {'service', 'nervous', 'jersey', 'jarred', 'travis'}


def wake_like(text):
    """Whether a transcript has the wake word, or a word it is often misheard as."""
    from difflib import SequenceMatcher
    for word in words(text):
        word = re.sub(r"([a-z])\1+", r"\1", re.split(r"['’]", word)[0])
        if (word in _WAKE_VARIANTS or word in _WAKE_MISHEARD
                or len(word) >= 4 and SequenceMatcher(None, word, 'jarvis').ratio() >= 0.7):
            return True
    return False


def _comparable(text):
    """Words for comparing hypotheses: stretched letters ('yesss', 'momm') and a
    misheard leading wake word ('Yarvis') do not change what was asked."""
    tokens = [re.sub(r"([a-z])\1+", r"\1", w) for w in words(text)]
    if tokens and tokens[0] in _WAKE_VARIANTS:
        tokens = tokens[1:]
    return tuple(tokens)


def _same_wording(a, b):
    """Spelling variants of the same words ('stretch' / 'strech') are not a
    different request; different names ('Mom' / 'Mam') are."""
    from difflib import SequenceMatcher
    return len(a) == len(b) and all(
        x == y or (not any(c.isdigit() for c in x + y) and SequenceMatcher(None, x, y).ratio() >= 0.85)
        for x, y in zip(a, b))


def conflict_reason(result, important=False):
    """'meaning' if alternatives differ in a protected word or number, 'wording'
    if an important request's alternatives differ only in other words
    (e.g. 'call Mom' / 'call Mam'), else None."""
    primary = _comparable(result.text)
    signature = tuple(w for w in primary if w in PROTECTED or any(c.isdigit() for c in w))
    reason = None
    for alternative in result.alternatives:
        if alternative.confidence is not None and alternative.confidence < 0.5:
            continue
        other = _comparable(alternative.text)
        other_signature = tuple(w for w in other if w in PROTECTED or any(c.isdigit() for c in w))
        if other_signature != signature:
            return 'meaning'
        if important and not _same_wording(other, primary):
            reason = 'wording'
    return reason


def alternatives_conflict(result, important=False):
    return conflict_reason(result, important) is not None


def can_interrupt(result, stop_confidence=0.65, any_speech=False):
    """Partial recognition may only cancel speech, never authorize an action.
    A short stop needs `stop_confidence` (0.35 over loudspeakers, see ECHO_MODE).
    `any_speech` (headset mode, where the microphone cannot hear Jarvis): whatever you
    clearly say interrupts, except "don't stop"."""
    if result.error or result.truncated or not result.text:
        return False
    if not any_speech and is_echo(result.text, result.playback_text):
        return False
    if stop_heard(result, stop_confidence):
        return True
    if result.confidence is not None and result.confidence < 0.65:
        return False
    if any_speech:
        tokens = set(words(result.text))
        return not (tokens & NEGATION and tokens & {'stop', 'talking', 'speaking', 'going'})
    if alternatives_conflict(result, important=True):
        return False
    if set(words(result.text)) & NEGATION:
        return False
    if is_stop(result.text):
        return True
    # Explicit addressing may interrupt, but needs a reported strong score.
    # An incomplete addressed request is never executed from this decision.
    return (strip_wake_word(result.text) is not None and
            result.confidence is not None and result.confidence >= 0.8)


@dataclass(frozen=True)
class VoiceDecision:
    kind: str  # accept, clarify, stop, ignore
    text: str = ""
    prompt: str = ""
    reason: str = ""  # for clarify: 'meaning' / 'wording' conflict, 'low_confidence', ...


class ConfidenceGate:
    def __init__(self, clock, repeat_window=20):
        self.clock = clock
        self.repeat_window = repeat_window
        self._repeat = None

    def assess(self, result, text=None, force_important=False):
        text = result.text.strip() if text is None else text.strip()
        if result.error or result.truncated:
            self._repeat = None
            prompt = say('incomplete') if result.truncated else say('not_heard')
            return VoiceDecision('clarify', prompt=prompt,
                                 reason='incomplete_recording' if result.truncated else result.error)
        if not text:
            return VoiceDecision('ignore')
        if is_stop(text) and can_interrupt(result):
            self._repeat = None
            return VoiceDecision('stop')
        intent = classify_intent(text)
        tokens = words(text)
        important = force_important or intent in ACTION_INTENTS or bool(set(tokens) & PROTECTED)
        conflict = conflict_reason(result, important)
        if conflict:
            self._repeat = None
            return VoiceDecision('clarify', text=text, reason=conflict, prompt=say('repeat_please'))
        if result.confidence is not None and result.confidence < (0.8 if important else 0.65):
            self._repeat = None
            return VoiceDecision('clarify', reason='low_confidence', prompt=say('repeat_please'))
        # Do not let the legacy keyword router turn a negated action into an action.
        if intent in ACTION_INTENTS and set(tokens) & NEGATION:
            self._repeat = None
            return VoiceDecision('clarify', prompt=say('wont_act'))
        # These words have multiple possible targets; do not assume a timer.
        if tokens in {('pause',), ('continue',), ('resume',), ('cancel',), ('delete',)}:
            self._repeat = None
            return VoiceDecision('clarify', prompt=say('control_what', verb=tokens[0]))
        if intent == 'timer' and not any(t in tokens for t in ('timer', 'timers', 'pomodoro', 'minute', 'minutes', 'second', 'seconds', 'hour', 'hours', 'left', 'remaining')):
            self._repeat = None
            return VoiceDecision('clarify', prompt=say('mean_timer'))
        if important and result.confidence is None:
            current = (tokens, self.clock())
            previous = self._repeat
            self._repeat = current
            if not previous or previous[0] != tokens or current[1] - previous[1] > self.repeat_window:
                prompt = say('repeat_to_confirm', text=text if len(text) <= 120 else 'That')
                return VoiceDecision('clarify', prompt=prompt)
        self._repeat = None
        return VoiceDecision('accept', text=text)
