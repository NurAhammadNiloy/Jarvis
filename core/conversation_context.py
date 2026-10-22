"""
Conversation Context Manager for Jarvis AI Assistant.

Tracks conversation context to enable natural follow-up responses.
For example, after giving a weather forecast, if user says "yes" or 
"tell me more", Jarvis understands the context.
"""

from core.phrases import say
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

@dataclass
class ConversationState:
    """Tracks the current conversation state."""
    last_topic: Optional[str] = None  # weather, forecast, timer, reminder, etc.
    last_city: Optional[str] = None   # For weather-related follow-ups
    last_query: Optional[str] = None  # What user asked
    last_response: Optional[str] = None  # What Jarvis said
    last_time: datetime = field(default_factory=datetime.now)
    pending_action: Optional[str] = None  # Action waiting for confirmation
    pending_data: Dict[str, Any] = field(default_factory=dict)  # Data for pending action
    
    def is_expired(self, timeout_seconds: int = 60) -> bool:
        """Check if context has expired."""
        return (datetime.now() - self.last_time).total_seconds() > timeout_seconds
    
    def clear(self):
        """Clear the conversation state."""
        self.last_topic = None
        self.last_city = None
        self.last_query = None
        self.last_response = None
        self.pending_action = None
        self.pending_data = {}


# Global conversation state
_state = ConversationState()


def set_context(topic: str, city: str = None, query: str = None, 
                response: str = None, pending_action: str = None,
                pending_data: dict = None):
    """Update the conversation context."""
    global _state
    _state.last_topic = topic
    _state.last_time = datetime.now()
    
    if city:
        _state.last_city = city
    if query:
        _state.last_query = query
    if response:
        _state.last_response = response
    if pending_action:
        _state.pending_action = pending_action
    if pending_data:
        _state.pending_data = pending_data


def get_context() -> ConversationState:
    """Get the current conversation context."""
    global _state
    if _state.is_expired():
        _state.clear()
    return _state


def clear_context():
    """Clear the conversation context."""
    global _state
    _state.clear()


def has_pending_action() -> bool:
    """Check if there's a pending action waiting for confirmation."""
    global _state
    return _state.pending_action is not None and not _state.is_expired()


def get_follow_up_response(user_input: str, *, weather=None, forecast=None,
                           cancel_timers=None) -> Optional[str]:
    """
    Generate a response for follow-up inputs based on context.
    
    Returns None if no contextual response is appropriate.
    Only handles short follow-up responses, not full queries.
    """
    global _state
    
    if _state.is_expired():
        return None
    
    user_lower = user_input.lower().strip()
    
    # Only handle SHORT follow-up responses (less than 4 words typically)
    # Full queries like "what is the weather" should go to normal processing
    word_count = len(user_lower.split())
    if word_count > 4:
        return None  # This is a full query, not a follow-up
    
    # Skip if it looks like a new query (contains question words with other content)
    query_patterns = ["what is", "what's", "how is", "tell me", "show me", "play", 
                      "set a", "create", "open", "search", "weather", "forecast", "timer"]
    if any(pattern in user_lower for pattern in query_patterns):
        return None  # This is a new query, not a follow-up
    
    # Handle yes/no responses
    is_yes = user_lower in ["yes", "yeah", "yep", "sure", "okay", "ok", "please", "go ahead", "yes please", "sure thing"]
    is_no = user_lower in ["no", "nope", "nah", "not really", "never mind", "cancel", "no thanks"]
    
    # Handle "tell me more" type responses
    wants_more = any(phrase in user_lower for phrase in ["tell me more", "more details", "more info", "elaborate", "what else", "anything else"])
    
    # Context-specific follow-ups
    if _state.last_topic == "forecast":
        if is_yes or wants_more:
            if weather is None:
                from core.weather_service import get_weather as weather
            city = _state.last_city or "Kokkola"
            # Give current weather as follow-up
            response = weather(city, detailed=True)
            clear_context()
            return response
        elif is_no:
            clear_context()
            return say('okay')
    
    elif _state.last_topic == "weather":
        if wants_more or "forecast" in user_lower:
            if forecast is None:
                from core.weather_service import get_forecast as forecast
            city = _state.last_city or "Kokkola"
            response = forecast(city)
            clear_context()
            return response
        elif is_yes:
            clear_context()
            return say('glad')
        elif is_no:
            clear_context()
            return say('okay')
    
    elif _state.last_topic == "timer":
        if is_yes and _state.pending_action == "confirm_cancel":
            # Confirm timer cancellation
            if cancel_timers is None:
                from core.smart_timer import cancel_all_timers as cancel_timers
            cancel_timers()
            clear_context()
            return say('all_timers_cancelled')
        elif is_no and _state.pending_action:
            clear_context()
            return say('timers_keep_running')
    
    elif _state.last_topic == "youtube":
        if is_yes or wants_more:
            clear_context()
            return say('play_what')
        elif is_no:
            clear_context()
            return say('enjoy')
    
    # Generic follow-ups
    if is_yes:
        # User said yes but we don't have specific context
        return None  # Let it go to ChatGPT
    elif is_no:
        clear_context()
        return say('okay')
    elif wants_more:
        clear_context()
        return say('more_about_what')
    
    return None  # No contextual response, proceed normally


def handle_thanks(choose=None) -> str:
    """Handle thank you responses based on context."""
    global _state
    
    from core.phrases import PHRASES
    import random
    clear_context()
    return (choose or random.choice)(PHRASES['thanks'])
