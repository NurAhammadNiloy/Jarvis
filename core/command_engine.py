"""Plain-text understanding and execution, independent of speech delivery."""
from datetime import datetime, timedelta
import random
import re

from config.settings import DEFAULT_LOCATION
from core.command_result import Command, CommandResult
from core.command_services import CommandServices
from core.intent_classifier import classify_intent
from core.service_errors import ServiceError


def understand_query(query, services, default_location=DEFAULT_LOCATION):
    """Parse without executing actions. Existing parsing rules are preserved."""
    intent = classify_intent(query)
    lower = query.lower()
    args = {}
    if intent == "reminder":
        args = services.extract_reminder_info(query)
    elif "what are my reminders" in lower or "tell me my reminders" in lower:
        intent = "list_reminders"
    elif intent == "weather":
        detailed = any(k in lower for k in ["should i", "what should", "wear", "go out", "tell me about", "detailed", "full", "everything", "more"])
        context = None
        if any(k in lower for k in ["should i go", "can i go", "go outside"]):
            context = "go_outside"
        elif any(k in lower for k in ["should i wear", "what should i wear", "what to wear"]):
            context = "clothing"
        elif any(k in lower for k in ["how cold", "how hot", "is it cold", "is it hot", "is it warm"]):
            context = "temperature"
        city = default_location
        if not context:
            city = lower
            for word in ["weather", "what is the", "what's the", "current", "now", "in", "at", "temperature", "outside", "how is the", "tell me", "the", "?"]:
                city = city.replace(word, "")
            city = city.strip() or default_location
        args = {"city": city, "detailed": detailed, "question_context": context}
    elif intent == "forecast":
        city = lower
        for word in ["forecast", "what's", "the", "what", "is", "weather", "for", "of", "about", "in", "tell", "me", "get", "show"]:
            city = re.sub(r'\b' + word + r'\b', '', city)
        args = {"city": ' '.join(re.sub(r'[?.,!]', '', city).split()) or default_location}
    elif intent == "youtube" or "open a video" in lower or "show me a video" in lower:
        intent = "youtube"
        topic = lower
        for word in ["play", "open", "show", "me", "a", "video", "about", "on", "youtube", "the", "song", "music"]:
            topic = re.sub(r'\b' + word + r'\b', '', topic)
        args = {"topic": ' '.join(topic.split()).strip()}
    elif intent == "timer":
        args = services.extract_timer_info(query)
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
        return reply(*action.messages, status="handled" if action.succeeded else "error",
                     legacy_handled=True)

    if intent == "reminder":
        task, time = args['task'], args['time']
        if task and time:
            return action_reply(services.reminder(task, time, args['recurring'], args['interval']))
        if task:
            return reply(f"I heard the task '{task}', but when would you like me to remind you?",
                         status="pending", pending_action="reminder_time", data={"task": task})
        return reply("I couldn't understand the reminder. Please try again with a task and time.", status="error")
    if intent == "list_reminders":
        return action_reply(services.list_reminders())
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
            services.open_url(url)
            return reply(f"Playing {topic} on YouTube." if topic else "Opening YouTube.")
        return reply(f"I couldn't find {topic} on YouTube." if topic else "Couldn't find that video.")
    if intent == "time":
        return reply(f"The current time is {now().strftime('%I:%M %p')}.")
    if intent == "date":
        lower = query.lower()
        if "tomorrow" in lower:
            return reply(f"Tomorrow's date is {(now() + timedelta(days=1)).strftime('%B %d, %Y')}.")
        if "yesterday" in lower:
            return reply(f"Yesterday's date was {(now() - timedelta(days=1)).strftime('%B %d, %Y')}.")
        if "day after tomorrow" in lower:
            return reply(f"The day after tomorrow is {(now() + timedelta(days=2)).strftime('%B %d, %Y')}.")
        return reply(f"Today's date is {now().strftime('%B %d, %Y')}.")
    if intent == "google":
        services.open_url("https://www.google.com")
        return reply("Opening Google.")
    if intent == "status":
        return reply("All systems are fully operational, sir.")
    if intent == "timer":
        action = args['action']
        if action == "add_time" and not (args['duration'] and args['duration'][0]):
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
        intent = classify_intent(query)
        command = understand_query(query, services)
        return execute_command(command, services, now=now, choose=choose)
    except ServiceError as exc:
        # A provider failed or timed out; its message is written to be spoken.
        return CommandResult("error", intent, (str(exc),), error="ServiceError")
    except Exception as exc:
        return CommandResult("error", intent,
                             ("I'm sorry, I couldn't complete that command.",),
                             error=type(exc).__name__)
