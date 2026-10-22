"""Plain-text understanding and execution, independent of speech delivery."""
from datetime import datetime, timedelta
import random
import re

from config.settings import DEFAULT_LOCATION
from core.command_result import Command, CommandResult
from core.command_services import CommandServices
from core.intent_classifier import route
from core.service_errors import ServiceError

# The alarm intent covers every alarm request; these pick the operation.
_ALARM_CANCEL = re.compile(r"\b(?:cancel|delete|remove|clear|drop|disable|stop|turn\s+off|switch\s+off)\b", re.IGNORECASE)
_ALARM_LIST = re.compile(r"^\W*(?:what|which|list|show|tell|read|check|any|do\s+i\s+have|have\s+i\s+got|are\s+there)\b",
                         re.IGNORECASE)

# Timer intents and the action name CommandServices.timer_action expects.
TIMER_ACTIONS = {
    "start_timer": "set", "pause_timer": "pause", "resume_timer": "resume",
    "cancel_timer": "cancel", "cancel_all_timers": "cancel_all",
    "timer_status": "status", "add_timer_time": "add_time", "pomodoro": "pomodoro",
}


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
            args = dict(services.extract_reminder_info(query), kind="alarm", operation="create")
    elif intent == "delete_reminder":
        args["when_text"] = query
    elif intent == "snooze_reminder":
        from core.reminder_parser import snooze_minutes
        args.update(minutes=snooze_minutes(query), when_text=query)
    elif intent in TIMER_ACTIONS:
        args = dict(services.extract_timer_info(query), action=TIMER_ACTIONS[intent])
    elif intent == "weather":
        detailed = any(k in lower for k in ["should i", "what should", "wear", "go out", "tell me about", "detailed", "full", "everything", "more"])
        context = None
        if any(k in lower for k in ["should i go", "can i go", "go outside"]):
            context = "go_outside"
        elif any(k in lower for k in ["should i wear", "what should i wear", "what to wear"]):
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
            return reply(*action.messages, status="pending", pending_action="choose_reminder",
                         legacy_handled=True)
        return reply(*action.messages, status="handled" if action.succeeded else "error",
                     legacy_handled=True)

    if intent == "alarm" and args.get("operation") == "delete":
        return action_reply(services.delete_reminder(None, args["when_text"], kind="alarm"))
    if intent == "alarm" and args.get("operation") == "list":
        return action_reply(services.list_reminders(kind="alarm"))
    if intent in ("reminder", "create_reminder", "alarm"):
        task, due, question = args.get('task'), args.get('due'), args.get('question')
        if due is not None and not task and args.get('kind', 'reminder') != 'alarm':
            # A reminder needs something to remind about; the time is kept for the answer.
            return reply("What should I remind you about?", status="pending", pending_action="reminder_task",
                         data={"args": dict(args)})
        if due is not None:
            return action_reply(services.reminder(args))
        if question:
            # Ambiguous time: keep the whole request so the answer can complete it.
            return reply(question, status="pending", pending_action="reminder_time",
                         data={"task": task, "query": query})
        if task:
            return reply("When should I remind you?", status="pending",
                         pending_action="reminder_time", data={"task": task})
        return reply("I couldn't understand the reminder. Please try again with a task and time.", status="error")
    if intent == "list_reminders":
        return action_reply(services.list_reminders())
    if intent == "delete_reminder":
        return action_reply(services.delete_reminder(args.get("target"), args.get("when_text", "")))
    if intent == "snooze_reminder":
        return action_reply(services.snooze_reminder(args.get("target"), args.get("minutes", 10),
                                                     args.get("when_text", "")))
    if intent in ("weather", "forecast"):
        if not args['city']:
            return reply("I couldn't determine your location. Please tell me the city for the weather update.")
        response = services.weather(**args) if intent == "weather" else services.forecast(args['city'])
        services.set_context(topic=intent, city=args['city'], query=query, response=response)
        return reply(response)
    if intent == "youtube":
        url = services.youtube(query)
        topic = args['topic']
        if url:
            if not services.open_url(url):
                return reply("I found the video but couldn't open your browser.", status="error")
            return reply(f"Playing {topic} on YouTube." if topic else "Opening YouTube.")
        return reply(f"I couldn't find {topic} on YouTube." if topic else "Couldn't find that video.",
                     status="error")
    if intent == "time":
        return reply(f"The current time is {now().strftime('%I:%M %p')}.")
    if intent == "date":
        lower = query.lower()
        # "day after tomorrow" contains "tomorrow", so it must be checked first.
        if "day after tomorrow" in lower:
            return reply(f"The day after tomorrow is {(now() + timedelta(days=2)).strftime('%B %d, %Y')}.")
        if "tomorrow" in lower:
            return reply(f"Tomorrow's date is {(now() + timedelta(days=1)).strftime('%B %d, %Y')}.")
        if "yesterday" in lower:
            return reply(f"Yesterday's date was {(now() - timedelta(days=1)).strftime('%B %d, %Y')}.")
        return reply(f"Today's date is {now().strftime('%B %d, %Y')}.")
    if intent == "google":
        if not services.open_url("https://www.google.com"):
            return reply("I couldn't open your browser.", status="error")
        return reply("Opening Google.")
    if intent == "timer" or intent in TIMER_ACTIONS:
        action = args['action']
        seconds = (args.get('duration') or (None, None))[0]
        if action in ("set", "add_time") and seconds is not None and seconds <= 0:
            return reply("A timer needs a duration greater than zero.", status="error",
                         error="invalid_duration")
        if action == "add_time" and not seconds:
            return reply("How much time would you like to add?")
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
