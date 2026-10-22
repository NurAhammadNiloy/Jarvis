"""Conservative decisions over provider transcripts. No audio or provider imports."""
from dataclasses import dataclass
import re
from typing import Optional, Tuple

from core.intent_classifier import classify_intent


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


def words(text):
    # Normalization is for comparison only. Never rewrite the dispatched text.
    return tuple(re.findall(r"[\w]+(?:['’][\w]+)?", text.lower()))


def strip_wake_word(text):
    match = re.match(r"^\s*jarvis\b[\s,.:!?-]*", text, re.IGNORECASE)
    return text[match.end():].strip() if match else None


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


def is_echo(text, playback_text):
    heard, spoken = words(text), words(playback_text)
    return bool(heard and spoken and any(spoken[i:i + len(heard)] == heard
                for i in range(len(spoken) - len(heard) + 1)))


_WAKE_VARIANTS = {'jarvis', 'yarvis', 'jervis', 'javis'}


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


def can_interrupt(result):
    """Partial recognition may only cancel speech, never authorize an action."""
    if result.error or result.truncated or not result.text:
        return False
    if is_echo(result.text, result.playback_text):
        return False
    if result.confidence is not None and result.confidence < 0.65:
        return False
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
            prompt = ("That recording was incomplete. Please say the command again."
                      if result.truncated else "I couldn't hear that clearly. Please try again.")
            return VoiceDecision('clarify', prompt=prompt)
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
            return VoiceDecision('clarify', text=text, reason=conflict,
                                 prompt="I heard different possibilities. Please repeat the full request.")
        if result.confidence is not None and result.confidence < (0.8 if important else 0.65):
            self._repeat = None
            return VoiceDecision('clarify', reason='low_confidence',
                                 prompt="I'm not sure I heard that correctly. Please repeat it.")
        # Do not let the legacy keyword router turn a negated action into an action.
        if intent in ACTION_INTENTS and set(tokens) & NEGATION:
            self._repeat = None
            return VoiceDecision('clarify', prompt="I won't act on that. Please tell me explicitly what you want me to do.")
        # These words have multiple possible targets; do not assume a timer.
        if tokens in {('pause',), ('continue',), ('resume',), ('cancel',), ('delete',)}:
            self._repeat = None
            return VoiceDecision('clarify', prompt="Please include what you want me to control.")
        if intent == 'timer' and not any(t in tokens for t in ('timer', 'timers', 'pomodoro', 'minute', 'minutes', 'second', 'seconds', 'hour', 'hours', 'left', 'remaining')):
            self._repeat = None
            return VoiceDecision('clarify', prompt="Do you mean a timer? Please include the target in your request.")
        if important and result.confidence is None:
            current = (tokens, self.clock())
            previous = self._repeat
            self._repeat = current
            if not previous or previous[0] != tokens or current[1] - previous[1] > self.repeat_window:
                prompt = (f"I heard: {text}. Please repeat the full request to confirm."
                          if len(text) <= 120 else "Please repeat the full request to confirm what I heard.")
                return VoiceDecision('clarify', prompt=prompt)
        self._repeat = None
        return VoiceDecision('accept', text=text)
