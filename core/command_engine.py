"""Plain-text understanding and execution, independent of speech delivery."""
from datetime import datetime, timedelta
import random
import re

from config.settings import DEFAULT_LOCATION
from core.command_result import Command, CommandResult
from core.command_services import CommandServices
from core.intent_classifier import route
from core.phrases import say
from core.service_errors import ServiceError

# The alarm intent covers every alarm request; these pick the operation.
_ALARM_CANCEL = re.compile(r"\b(?:cancel|delete|remove|clear|drop|disable|stop|turn\s+off|switch\s+off)\b", re.IGNORECASE)
_ALARM_LIST = re.compile(r"^\W*(?:what|which|list|show|tell|read|check|any|do\s+i\s+have|have\s+i\s+got|are\s+there)\b",
                         re.IGNORECASE)

# Timer intents and the action name CommandServices.timer_action expects.
TIMER_ACTIONS = {
    "start_timer": "set", "pause_timer": "pause", "resume_timer": "resume",
    "cancel_timer": "cancel", "cancel_all_timers": "cancel_all",
    "timer_status": "status", "add_timer_time": "add_time", "remove_timer_time": "remove_time",
    "pomodoro": "pomodoro",
}


_SET_ALARM = re.compile(r"\b(?:set|create|add|make)\s+(?:(?:a|an|another|new)\s+)*alarm\b|\bwake\s+me\b", re.IGNORECASE)
_TIME_WORDS = re.compile(r"\d|\b(?:today|tonight|tomorrow|morning|evening|afternoon|noon|midnight|monday|tuesday|"
                         r"wednesday|thursday|friday|saturday|sunday|a\.?m|p\.?m|every|daily)\b", re.IGNORECASE)


def _from_alarm_words(query):
    """'nearest set an alarm' (a misheard "Jarvis"): the words before "set an alarm"
    are neither the label nor a time, unless they contain a time."""
    match = _SET_ALARM.search(query)
    if match and match.start() > 0 and not _TIME_WORDS.search(query[:match.start()]):
        return query[match.start():]
    return query


def spoken_clock(moment):
    """'1:10 PM', '9 AM'."""
    return moment.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ')


def spoken_date(moment, today):
    """'Thursday, October 22' (with the year only when it is not this year)."""
    text = f"{moment:%A}, {moment:%B} {moment.day}"
    return text if moment.year == today.year else f"{text}, {moment.year}"


# "don't cancel the tea timer", "not the timer": never cancels anything.
_DONT_CANCEL = re.compile(r"\b(?:do\s*n['’]?t|do\s+not|never|not)\s+(?:to\s+)?(?:cancel|stop|delete|remove|end|kill)\b"
                          r"|\bnot\s+the\s+(?:\w+\s+){0,2}timers?\b", re.IGNORECASE)


def understand_query(query, services, default_location=DEFAULT_LOCATION):
    """Parse without executing actions. Intent comes from the routing table."""
    routed = route(query)
    intent, lower = routed.intent, query.lower()
    args = dict(routed.fields)
    if intent == "create_reminder":
        args = services.extract_reminder_info(query)
    elif intent == "alarm":
        if _ALARM_CANCEL.search(query):
            args = {"operation": "delete", "when_text": query}
        elif _ALARM_LIST.search(query):
            args = {"operation": "list"}
        else:
            args = dict(services.extract_reminder_info(_from_alarm_words(query)), kind="alarm", operation="create")
    elif intent == "delete_reminder":
        args["when_text"] = query
    elif intent == "snooze_reminder":
        from core.reminder_parser import snooze_minutes
        args.update(minutes=snooze_minutes(query), when_text=query)
    elif intent in TIMER_ACTIONS:
        args = dict(services.extract_timer_info(query), action=TIMER_ACTIONS[intent])
    elif intent == "weather":
        # Advice questions ("should I wear a jacket?") get one short sentence; the full
        # report is for when it is asked for.
        detailed = any(k in lower for k in ["tell me about", "detail", "full", "everything", "more"])
        context = None
        if any(k in lower for k in ["umbrella", "will it rain", "is it raining", "going to rain"]):
            context = "umbrella"
        elif any(k in lower for k in ["should i go", "can i go", "go outside", "go out"]):
            context = "go_outside"
        elif any(k in lower for k in ["should i wear", "what should i wear", "what to wear", "jacket", "coat", "sweater"]):
            context = "clothing"
        elif any(k in lower for k in ["how cold", "how hot", "is it cold", "is it hot", "is it warm"]):
            context = "temperature"
        args = {"city": args["city"] or default_location, "detailed": detailed, "question_context": context}
    elif intent == "forecast":
        args = {"city": args["city"] or default_location}
    return Command(intent, query, args)


def execute_command(command, services, *, now=datetime.now, choose=random.choice):
    """Execute once and return immediate responses; never deliver them.

Direct callers handle exceptions. execute_query supplies the public error
boundary. Clock and response choice can be fixed for deterministic tests.
"""
    intent, query, args = command.intent, command.query, command.arguments

    def reply(*messages, status="handled", **kwargs):
        return CommandResult(status, intent, tuple(messages), **kwargs)

    def action_reply(action):
        # Legacy callers consider a spoken domain failure handled. Preserve
        # that contract while giving new callers the actual failure status.
        if action.pending:
            return reply(*action.messages, status="pending",
                         pending_action=action.pending_action or "choose_reminder",
                         legacy_handled=True, data={"args": dict(args)})
        return reply(*action.messages, status="handled" if action.succeeded else "error",
                     legacy_handled=True, data={"undo": action.undo} if action.undo else {})

    if intent == "alarm" and args.get("operation") == "delete":
        return action_reply(services.delete_reminder(None, args["when_text"], kind="alarm"))
    if intent == "alarm" and args.get("operation") == "list":
        return action_reply(services.list_reminders(kind="alarm"))
    if intent in ("reminder", "create_reminder", "alarm"):
        task, due, question = args.get('task'), args.get('due'), args.get('question')
        if due is not None and not task and args.get('kind', 'reminder') != 'alarm':
            # A reminder needs something to remind about; the time is kept for the answer.
            return reply(say("ask_reminder_task"), status="pending", pending_action="reminder_task",
                         data={"args": dict(args)})
        if due is not None:
            return action_reply(services.reminder(args))
        if question:
            # Ambiguous time: keep the whole request so the answer can complete it.
            return reply(question, status="pending", pending_action="reminder_time",
                         data={"task": task, "query": query})
        if task:
            return reply(say("ask_alarm_time") if intent == "alarm" else say("ask_reminder_time"),
                         status="pending",
                         pending_action="reminder_time", data={"task": task})
        return reply(say("reminder_unclear"), status="error")
    if intent == "list_reminders":
        return action_reply(services.list_reminders())
    if intent == "delete_reminder":
        return action_reply(services.delete_reminder(args.get("target"), args.get("when_text", "")))
    if intent == "snooze_reminder":
        return action_reply(services.snooze_reminder(args.get("target"), args.get("minutes", 10),
                                                     args.get("when_text", "")))
    if intent in ("weather", "forecast"):
        if not args['city']:
            return reply(say("which_city"))
        response = services.weather(**args) if intent == "weather" else services.forecast(args['city'])
        services.set_context(topic=intent, city=args['city'], query=query, response=response)
        return reply(response)
    if intent == "youtube":
        url = services.youtube(query)
        topic = args['topic']
        if url:
            if not services.open_url(url):
                return reply(say("no_browser"), status="error")
            return reply(say("playing", topic=topic) if topic else say("opening_youtube"))
        return reply(say("youtube_not_found", topic=topic or "that video"), status="error")
    if intent == "time":
        return reply(say("time", time=spoken_clock(now())))
    if intent == "date":
        lower = query.lower()
        today = now()
        day = lambda offset: spoken_date(today + timedelta(days=offset), today)  # noqa: E731
        # "day after tomorrow" contains "tomorrow", so it must be checked first.
        if "day after tomorrow" in lower:
            return reply(say("date_day_after", date=day(2)))
        if "tomorrow" in lower:
            return reply(say("date_tomorrow", date=day(1)))
        if "yesterday" in lower:
            return reply(say("date_yesterday", date=day(-1)))
        return reply(say("date_today", date=day(0)))
    if intent == "google":
        if not services.open_url("https://www.google.com"):
            return reply(say("no_browser"), status="error")
        return reply(say("opening_google"))
    if intent in ("cancel_timer", "cancel_all_timers") and _DONT_CANCEL.search(query):
        return reply(say("wont_cancel"))
    if intent == "timer" or intent in TIMER_ACTIONS:
        action = args['action']
        seconds = (args.get('duration') or (None, None))[0]
        if action in ("set", "add_time") and seconds is not None and seconds <= 0:
            return reply(say("timer_zero"), status="error",
                         error="invalid_duration")
        if action == "add_time" and not seconds:
            return reply(say("add_how_much"))
        if action == "remove_time" and not seconds:
            return reply(say("remove_how_much"))
        return action_reply(services.timer_action(action, query, args))
    if intent == "thank":
        return reply(services.thanks(choose))
    if intent == "what you are doing":
        return reply(choose([
            "Just here, ready to assist you, boss.",
            "Monitoring the system. Let me know if you need anything.",
            "Keeping an eye on things. What can I do for you?",
        ]))
    return reply(services.chat(query))


_default_services = CommandServices()


def execute_query(query, services=None, *, now=datetime.now, choose=random.choice):
    """Public text boundary. No speech imports or delivery and no action retries.

Real services may use network/storage. Errors may follow partial side effects;
an error result does not imply rollback. Reuse services for active timer state.
"""
    if not isinstance(query, str) or not query.strip():
        return CommandResult("error", "unknown", ("Please provide a command.",), error="invalid_input")
    services = services if services is not None else _default_services
    intent = "unknown"
    try:
        follow_up = services.follow_up(query)
        if follow_up:
            return CommandResult("handled", "follow_up", (follow_up,))
        intent = route(query).intent
        command = understand_query(query, services)
        return execute_command(command, services, now=now, choose=choose)
    except Exception as exc:
        return _error_result(exc, intent)


def run_command(command, services=None, *, now=datetime.now, choose=random.choice):
    """Execute an already parsed Command (e.g. one the user confirmed) with the
same error boundary as execute_query. Its arguments are used as they are; the
query is never parsed again.
"""
    services = services if services is not None else _default_services
    try:
        return execute_command(command, services, now=now, choose=choose)
    except Exception as exc:
        return _error_result(exc, command.intent)


def _error_result(exc, intent):
    if isinstance(exc, ServiceError):
        # A provider failed or timed out; its message is written to be spoken.
        return CommandResult("error", intent, (str(exc),), error="ServiceError")
    return CommandResult("error", intent,
                         ("I'm sorry, I couldn't complete that command.",),
                         error=type(exc).__name__)
