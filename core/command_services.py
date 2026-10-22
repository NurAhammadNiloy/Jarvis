"""Lazy adapters. Construction performs no I/O; real execution can use APIs.

Replace this object in tests. Audio is only used when VoiceNotifications is
explicitly supplied. Reuse an instance to preserve its active timer state.
"""
from core.command_output import TextNotifications
from core.command_result import ActionResult


class CommandServices:
    def __init__(self, notifications=None, now=None):
        self.notifications = notifications or TextNotifications()
        self._timers = None
        if now is None:
            from core.reminder_parser import local_now as now
        self.now = now

    @property
    def timers(self):
        if self._timers is None:
            from core.smart_timer import SmartTimerManager
            self._timers = SmartTimerManager(notifications=self.notifications)
        return self._timers

    def extract_reminder_info(self, query):
        """Task, timezone-aware due datetime, recurrence and kind; no NLP model."""
        from dataclasses import asdict
        from core.reminder_parser import parse_reminder
        return asdict(parse_reminder(query, self.now()))

    def extract_timer_info(self, query):
        from core.smart_timer import extract_timer_info
        return extract_timer_info(query)

    def follow_up(self, query):
        from core.conversation_context import get_follow_up_response
        return get_follow_up_response(
            query, weather=self.weather, forecast=self.forecast,
            cancel_timers=lambda: self.timer_action("cancel_all", query, {}),
        )

    def set_context(self, **kwargs):
        from core.conversation_context import set_context
        set_context(**kwargs)

    def thanks(self, choose):
        from core.conversation_context import handle_thanks
        return handle_thanks(choose=choose)

    def weather(self, city, **kwargs):
        from core.weather_service import get_weather
        return get_weather(city, **kwargs)

    def forecast(self, city):
        from core.weather_service import get_forecast
        return get_forecast(city)

    def chat(self, query):
        from core.chatgpt_service import get_chatgpt_response
        return get_chatgpt_response(query)

    def youtube(self, query):
        from core.youtube_service import search_youtube
        return search_youtube(query)

    def open_url(self, url):
        import webbrowser
        return webbrowser.open(url)

    def reminder(self, request):
        """Schedule a parsed request (see extract_reminder_info)."""
        from core import reminder_manager
        reminder_manager.initialize_reminders(notify=self.notifications.speak)
        messages = []
        # Transitional: the legacy scheduler takes a string. Replaced by the
        # SQLite scheduler, which takes the datetime itself.
        recurring = request['recurrence'] != 'none'
        succeeded = reminder_manager.handle_reminder(
            request['task'], request['due'].strftime('%Y-%m-%d %H:%M:%S'), recurring,
            request['recurrence'] if recurring else None, respond=messages.append,
            notify=self.notifications.speak,
        )
        return ActionResult(tuple(messages), succeeded)

    def list_reminders(self):
        from core import reminder_manager
        reminder_manager.initialize_reminders(notify=self.notifications.speak)
        messages = []
        reminder_manager.get_reminders(respond=messages.append)
        return ActionResult(tuple(messages))

    def timer_action(self, action, query, info):
        messages = []
        kwargs = {"label": info.get("label"), "respond": messages.append}
        manager = self.timers
        if action == "cancel_all":
            manager.cancel_all_timers(respond=messages.append)
            succeeded = True
        elif action == "pomodoro":
            manager.start_pomodoro(respond=messages.append)
            succeeded = True
        elif action == "status":
            status = manager.get_status(**kwargs)
            if status and not messages:
                messages.append(status)
            succeeded = status is not None
        elif action == "add_time":
            succeeded = manager.add_time(info["duration"][0], **kwargs)
        elif action in ("cancel", "pause", "resume"):
            succeeded = getattr(manager, action + "_timer")(**kwargs)
        else:
            succeeded = manager.create_timer(query, **kwargs) is not None
        return ActionResult(tuple(messages), bool(succeeded))
