"""
Smart Timer Alert System for Jarvis AI Assistant
Provides non-interrupting, accurate timer notifications.

Strategy:
- If Jarvis is free: Normal voice announcement
- If Jarvis is busy + milestone: Visual + beep (skip voice - it would be stale)
- If Jarvis is busy + completion: Wait, then announce (completion is always accurate)
"""

import threading
import time
from typing import Optional, Callable
from enum import Enum
from dataclasses import dataclass


class AlertPriority(Enum):
    LOW = 1        # 5+ minutes remaining
    MEDIUM = 2     # 1-5 minutes remaining
    HIGH = 3       # 30 seconds - 1 minute
    CRITICAL = 4   # < 30 seconds or completion


@dataclass 
class AlertResult:
    """Result of dispatching an alert."""
    visual_shown: bool = False
    audio_played: bool = False
    voice_spoken: bool = False
    skipped: bool = False
    reason: str = ""


class SmartAlertDispatcher:
    """
    Central dispatcher for timer alerts.
    Chooses the optimal alert method based on system state.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
    
    def dispatch_milestone(
        self,
        timer_label: Optional[str],
        message: str,
        remaining_seconds: float,
        remaining_fn: Callable[[], float]
    ) -> AlertResult:
        """
        Dispatch a milestone alert (e.g., "10 seconds remaining").
        
        Args:
            timer_label: Name of the timer (e.g., "Pasta")
            message: The milestone message
            remaining_seconds: Seconds remaining when milestone triggered
            remaining_fn: Function to get current remaining time
        """
        from core.speech_synthesis import is_speaking, synthesize_speech
        from utils.visual_alerts import visual_timer_alert
        from utils.audio_utils import play_audio_cue
        
        result = AlertResult()
        label = timer_label or "Timer"
        priority = self._get_priority(remaining_seconds)
        
        is_busy = is_speaking()
        
        if not is_busy:
            # Jarvis is free - do normal voice announcement
            if label and label != "Timer":
                announcement = f"{label} timer: {message}."
            else:
                announcement = f"Timer: {message}."
            synthesize_speech(announcement)
            result.voice_spoken = True
            return result
        
        # Jarvis is busy - use visual + audio cue instead
        # (Voice would be stale by the time speech finishes)
        visual_timer_alert(label, message, int(remaining_seconds))
        result.visual_shown = True
        
        # Play appropriate audio cue
        if priority == AlertPriority.CRITICAL:
            play_audio_cue('warning', volume=0.5)
        elif priority == AlertPriority.HIGH:
            play_audio_cue('milestone', volume=0.4)
        else:
            play_audio_cue('subtle', volume=0.3)
        result.audio_played = True
        
        result.reason = "Visual+audio used (voice would be stale)"
        return result
    
    def dispatch_completion(
        self,
        timer_label: Optional[str],
        message: str,
        category: Optional[str] = None
    ) -> AlertResult:
        """
        Dispatch a timer completion alert.
        Completion alerts always use voice (they're always accurate).
        """
        from core.speech_synthesis import synthesize_speech
        from utils.visual_alerts import show_visual_alert
        from utils.audio_utils import play_audio_cue
        
        result = AlertResult()
        label = timer_label or "Timer"
        
        # Always show visual immediately
        show_visual_alert(f"{label.upper()} COMPLETE!", 'complete')
        result.visual_shown = True
        
        # Play completion chime
        play_audio_cue('complete', volume=0.5)
        result.audio_played = True
        
        # The shared output worker serializes speech and supports cancellation.
        synthesize_speech(message)
        result.voice_spoken = True
        
        return result
    
    def _get_priority(self, remaining_seconds: float) -> AlertPriority:
        """Determine alert priority based on remaining time."""
        if remaining_seconds <= 30:
            return AlertPriority.CRITICAL
        elif remaining_seconds <= 60:
            return AlertPriority.HIGH
        elif remaining_seconds <= 300:
            return AlertPriority.MEDIUM
        else:
            return AlertPriority.LOW


# Global dispatcher instance
_dispatcher = None

def get_dispatcher() -> SmartAlertDispatcher:
    """Get or create the global alert dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = SmartAlertDispatcher()
    return _dispatcher


def dispatch_milestone_alert(
    timer_label: str,
    message: str, 
    remaining_seconds: float,
    remaining_fn: Callable[[], float]
) -> AlertResult:
    """Dispatch a milestone alert through the smart system."""
    return get_dispatcher().dispatch_milestone(
        timer_label, message, remaining_seconds, remaining_fn
    )


def dispatch_completion_alert(
    timer_label: str,
    message: str,
    category: str = None
) -> AlertResult:
    """Dispatch a completion alert through the smart system."""
    return get_dispatcher().dispatch_completion(
        timer_label, message, category
    )
