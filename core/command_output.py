"""Output adapters. Importing this module never initializes audio."""


def speak(text):
    from core.speech_synthesis import synthesize_speech
    return synthesize_speech(text)


def deliver_result(result, output):
    """Delivery failures do not rerun actions."""
    for message in result.messages:
        output(message)


class TextNotifications:
    """Background events are separate from immediate command results."""

    def __init__(self, output=print):
        self.speak = output

    def milestone(self, timer_label, message, remaining_seconds, remaining_fn):
        self.speak(f"{timer_label or 'Timer'} timer: {message}.")

    def completion(self, timer_label, message, category=None):
        self.speak(message)


class VoiceNotifications:
    speak = staticmethod(speak)

    def milestone(self, **kwargs):
        from core.timer_alerts import dispatch_milestone_alert
        dispatch_milestone_alert(**kwargs)

    def completion(self, **kwargs):
        from core.timer_alerts import dispatch_completion_alert
        dispatch_completion_alert(**kwargs)
