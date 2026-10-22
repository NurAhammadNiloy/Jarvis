"""Intent routing: one ordered table of word-boundary regex rules.

The first matching rule wins and anything unmatched is conversation ("chat").
Order is operation-first: changing or listing an existing thing is checked
before creating one, and specific intents before general ones. Plain regex
only; routing never loads an NLP model.
"""
from dataclasses import dataclass, field
import re
from typing import Any, Mapping

# Optional wake word and politeness in front of an imperative verb.
_LEAD = r"^\W*(?:(?:hey|ok|okay)\s+)?(?:jarvis\W+)?(?:(?:can|could|would|will)\s+you\s+|please\s+)*"
_END = r"\W*$"
_TIMER = r"\b(?:timers?|pomodoros?|countdown)\b"
_UNIT = r"\b(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
_REMINDER = r"\breminders?\b"
_WHATS = r"\bwhat(?:['’]s|\s+is|\s+was)"
_TAKE_OFF = r"\b(?:cancel|remove|delete|take\s+off|take\s+away|subtract|drop|clear|get\s+rid\s+of|undo)\b"
_REMOVE_TIME = (_TAKE_OFF + r".*\b(?:extra|more|additional|added)\b.*" + _UNIT
                + r"|" + _TAKE_OFF + r".*" + _UNIT + r".*\b(?:more|extra|additional)\b"
                + r"|" + _TAKE_OFF + r".*\b(?:extra|additional|added)\s+time\b"
                + r"|\btake\s+(?:off|away)\b.*" + _UNIT
                + r"|\btake\b.*" + _UNIT + r".*\b(?:off|away)\b"
                + r"|\bsubtract\b.*" + _UNIT
                + r"|\b(?:remove|delete|cut)\s+(?:an?\s+|\w+\s+)?\d+[\s-]*" + _UNIT + r"(?![\s-]*(?:timers?|countdown)\b)")

RULES = (
    # intent              pattern (case-insensitive)
    # Reminders: existing ones (snooze, delete, list) before creating one.
    ('snooze_reminder',   _LEAD + r"snooze\b"),
    ('delete_reminder',   _LEAD + r"(?:delete|remove|cancel|clear|drop|forget(?:\s+about)?)\b.*" + _REMINDER),
    ('list_reminders',    _LEAD + r"(?:what|which|list|show|tell|read|check|do\s+i\s+have|have\s+i\s+got|are\s+there)\b.*" + _REMINDER
                          + r"|" + _LEAD + r"(?:my\s+)?reminders" + _END),
    ('create_reminder',   r"\bremind\s+(?:me|us)\b"
                          + r"|" + _LEAD + r"(?:set|create|add|make)\s+(?:(?:a|an|another|new)\s+)*reminder\b"),
    # Alarm before timers: "set an alarm for 30 minutes" is not a timer.
    ('alarm',             r"\balarms?\b|\bwake\s+me\b|" + _LEAD + r"wake\s+up\b"),
    # Taking time off a timer ("cancel that extra 5 minutes", "take off 5 minutes") is not
    # cancelling the timer, so it comes before the cancel rules.
    ('remove_timer_time', _REMOVE_TIME),
    # Timers: cancel-all before cancel, resume before pause (unpause), and
    # every operation before the generic start rule.
    ('cancel_all_timers', r"\b(?:cancel|stop|delete|remove|clear|end)\b.*\ball\b.*" + _TIMER),
    ('cancel_timer',      r"\b(?:cancel|stop|delete|remove|clear|end|kill)\b.*" + _TIMER),
    ('resume_timer',      r"\bunpause\b"
                          + r"|\b(?:resume|continue|restart)\b.*" + _TIMER
                          + r"|" + _LEAD + r"resume(?:\s+(?:it|that|this))?" + _END
                          + r"|\bstart\b.*\b(?:timer|it|that)\b.*\bagain\b"),
    ('pause_timer',       r"\b(?:pause|hold|freeze)\b.*" + _TIMER
                          + r"|" + _LEAD + r"pause(?:\s+(?:it|that|this))?" + _END),
    ('timer_status',      _TIMER + r".*\b(?:status|left|remaining)\b"
                          + r"|\b(?:status|check)\b.*" + _TIMER
                          + r"|\bhow\s+(?:much\s+time|long)\b.*\b(?:left|remaining)\b"
                          + r"|\btime\s+(?:left|remaining)\b"
                          + r"|\b(?:what|which|list|show|any)\b.*\btimers\b"),
    ('add_timer_time',    r"\b(?:add|extend)\b.*" + _TIMER
                          + r"|^(?!.*" + _REMINDER + r").*\b(?:add|extend)\b.*(?:" + _UNIT + r"|\bmore\s+time\b)"),
    ('pomodoro',          r"\bpomodoros?\b"),
    ('start_timer',       _TIMER + r"|\b(?:set|start)\b.*" + _UNIT),
    # Weather: a multi-day question is a forecast.
    ('forecast',          r"\bforecast\b"
                          + r"|\bweather\b.*\b(?:week|weekend|tomorrow|next\s+few\s+days|coming\s+days)\b"
                          + r"|\b(?:week|weekend|tomorrow)['’]?s?\b.*\bweather\b"),
    ('weather',           r"\bweather\b|\btemperature\b(?!\s+of\b)"
                          + r"|\b(?:should|can)\s+i\s+(?:go\s+out(?:side)?|wear)\b|\bgo\s+outside\b"
                          + r"|\bwhat\s+(?:should\s+i|to)\s+wear\b"
                          + r"|\bhow\s+(?:cold|hot|warm)\s+is\s+it\b"
                          + r"|\bis\s+it\s+(?:cold|hot|warm|raining|snowing)\b"),
    # YouTube only for an explicit play request or a YouTube mention:
    # "tell me about the play Hamlet" is conversation.
    ('youtube',           r"\byoutube\b"
                          + r"|" + _LEAD + r"(?:play|put\s+on)\b"
                          + r"|\b(?:open|show\s+me|find)\s+(?:me\s+)?a\s+video\b"),
    ('google',            r"\bopen\s+google\b|" + _LEAD + r"google" + _END),
    # Local time only: "what time is it in Tokyo" is a question for chat.
    ('time',              r"\bwhat\s+time\s+is\s+it\b(?!\s+in\b)"
                          + r"|" + _WHATS + r"\s+the\s+(?:current\s+)?time\b"
                          + r"|\b(?:tell|give)\s+me\s+the\s+time\b|\bcurrent\s+time\b"
                          + r"|" + _LEAD + r"(?:the\s+)?time(?:\s+please)?" + _END),
    ('date',              _WHATS + r"\s+(?:the\s+|(?:today|tomorrow|yesterday)['’]s\s+)?date\b"
                          + r"|\bwhat\s+(?:date|day)\s+is\s+(?:it|today)\b"
                          + r"|\btell\s+me\s+(?:the|today['’]s)\s+date\b"
                          + r"|" + _LEAD + r"(?:the\s+|today['’]s\s+)?date" + _END),
    ('what you are doing', r"\bwhat\s+are\s+you\s+doing\b|\bwhat\s+you\s+are\s+doing\b"),
    ('thank',             r"\bthank(?:s|\s+you)?\b"),
)

_COMPILED = tuple((intent, re.compile(pattern, re.IGNORECASE)) for intent, pattern in RULES)

# Coarse families for the voice policy and dialogue, which only need to know
# whether something is a reminder or timer action.
FAMILIES = {
    'create_reminder': 'reminder', 'delete_reminder': 'reminder', 'snooze_reminder': 'reminder',
    'start_timer': 'timer', 'pause_timer': 'timer', 'resume_timer': 'timer',
    'cancel_timer': 'timer', 'cancel_all_timers': 'timer', 'timer_status': 'timer',
    'add_timer_time': 'timer', 'remove_timer_time': 'timer', 'pomodoro': 'timer',
}


# Conversation, not commands: the router answers these with chat or a fixed reply.
_NOT_COMMANDS = {'thank', 'what you are doing'}
# Every intent the router knows is a command Jarvis can run, and so can be proposed
# by the dialogue; derived from RULES so the two never drift apart.
COMMAND_INTENTS = tuple(intent for intent, _ in RULES if intent not in _NOT_COMMANDS)
# Commands that only look something up; a proposal for one runs without "Shall I do that?".
READ_ONLY_INTENTS = frozenset({'list_reminders', 'timer_status', 'weather', 'forecast', 'time', 'date'})


def command_names():
    """Spoken names of the supported commands, e.g. 'list reminders', for prompts."""
    return [intent.replace('_', ' ') for intent in COMMAND_INTENTS]


@dataclass(frozen=True)
class Route:
    intent: str
    fields: Mapping[str, Any] = field(default_factory=dict)


# --- field extraction -------------------------------------------------------

_PLACE_PREPOSITION = re.compile(r"\b(?:in|at|for)\s+", re.IGNORECASE)
_TRAILING_TIME = re.compile(
    r"\s+(?:today|tonight|tomorrow|now|right\s+now|currently|like|please|"
    r"at\s+the\s+moment|this\s+(?:week|weekend|morning|afternoon|evening)|"
    r"next\s+(?:week|few\s+days)|the\s+(?:week|weekend|next\s+few\s+days))$", re.IGNORECASE)
# "at the office", "for my trip": a leading determiner means it is not a city.
_NOT_A_PLACE = re.compile(r"^(?:the|my|our|your|a|an|this|that|it|me|us)\b", re.IGNORECASE)


def _clean_place(span):
    span = ' ' + re.sub(r"[?!.,;:\"]", ' ', span).strip()
    while True:
        shorter = _TRAILING_TIME.sub('', span)
        if shorter == span:
            break
        span = shorter
    span = ' '.join(span.split())
    if not span or _NOT_A_PLACE.match(span) or _TRAILING_TIME.match(' ' + span):
        return None
    return span.title() if span.islower() or span.isupper() else span


def extract_city(query):
    """City named after in/at/for; the last usable span wins. None if absent."""
    matches = list(_PLACE_PREPOSITION.finditer(query))
    for index in range(len(matches) - 1, -1, -1):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(query)
        city = _clean_place(query[matches[index].end():end])
        if city:
            return city
    return None


_TOPIC_STRIP = (
    re.compile(_LEAD + r"(?:play|put\s+on|open|show\s+me|find|search(?:\s+for)?)\b\s*", re.IGNORECASE),
    re.compile(r"\s+please\W*$", re.IGNORECASE),
    re.compile(r"\s*\b(?:on|in|from|at)\s+youtube\b\W*$|^\W*youtube\b\s*", re.IGNORECASE),
    re.compile(r"^(?:me\s+)?(?:a\s+)?videos?\b\s*(?:about|of|on|for)?\s*|^some\s+", re.IGNORECASE),
)


def extract_topic(query):
    """What to search for on YouTube, without the command words."""
    topic = query.strip()
    for pattern in _TOPIC_STRIP:
        topic = pattern.sub('', topic)
    return ' '.join(re.sub(r"[?!.,;:\"]", ' ', topic).split())


_TARGET_QUOTED = re.compile(r"(?:^|\s)['\"“‘]([^'\"“”‘’]+)['\"”’](?=\W*$|\s)")
_TARGET_AFTER = re.compile(_REMINDER + r"\s+(?:about|for|to|called|named)\s+(.+)", re.IGNORECASE)
_TARGET_BEFORE = re.compile(r"\b(?:delete|remove|cancel|clear|drop|forget(?:\s+about)?|snooze)\s+(.*?)\s*" + _REMINDER,
                            re.IGNORECASE)
_DETERMINERS = re.compile(r"\b(?:my|the|that|this|a|an|all|it|of)\b", re.IGNORECASE)


def extract_reminder_target(query):
    """Which reminder a delete/snooze refers to, or None for 'that'/'it'.

    A duration ("snooze the reminder for 10 minutes") is never the target.
    """
    for pattern in (_TARGET_QUOTED, _TARGET_AFTER, _TARGET_BEFORE):
        match = pattern.search(query)
        if not match:
            continue
        target = ' '.join(_DETERMINERS.sub(' ', re.sub(r"[?!.,;:\"]", ' ', match.group(1))).split())
        if target and not re.search(r"\d|" + _UNIT, target, re.IGNORECASE):
            return target.lower()
    return None


_FIELDS = {
    'weather': lambda q: {'city': extract_city(q)},
    'forecast': lambda q: {'city': extract_city(q)},
    'youtube': lambda q: {'topic': extract_topic(q)},
    'delete_reminder': lambda q: {'target': extract_reminder_target(q)},
    'snooze_reminder': lambda q: {'target': extract_reminder_target(q)},
}


def route(query):
    """Fine-grained intent and the fields the router itself can extract."""
    for intent, pattern in _COMPILED:
        if pattern.search(query):
            extract = _FIELDS.get(intent)
            return Route(intent, extract(query) if extract else {})
    return Route('chat')


def classify_intent(query):
    """Coarse intent family ('reminder', 'timer', 'weather', ..., 'chat')."""
    intent = route(query).intent
    return FAMILIES.get(intent, intent)
