"""
🚀 Smart Timer System for Jarvis AI Assistant
A futuristic, intelligent timer with advanced features.

Features:
- Natural language understanding ("couple minutes", "half an hour")
- Named timers with smart labeling
- Progress announcements at intervals
- Pomodoro mode (work/break cycles)
- Timer chaining (do X after Y)
- Pause/Resume functionality
- Learning user patterns
- Contextual suggestions
- Multi-sensory alerts
- Time remaining queries
"""

from core.phrases import say
import threading
import time
import re
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

# Foreground responses and background notifications have separate outputs.
# The compatibility default imports speech only when it is actually delivered.
from core.command_output import speak as synthesize_speech, VoiceNotifications


class TimerState(Enum):
    """Timer states for lifecycle management."""
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AlertStyle(Enum):
    """Different alert styles for various contexts."""
    GENTLE = "gentle"      # Soft reminder
    STANDARD = "standard"  # Normal alert
    URGENT = "urgent"      # Important, can't miss
    SILENT = "silent"      # No audio, just log


@dataclass
class SmartTimer:
    """Represents an intelligent timer with advanced features."""
    id: int
    duration_seconds: int
    label: Optional[str] = None
    state: TimerState = TimerState.RUNNING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    pause_time: Optional[datetime] = None
    elapsed_before_pause: float = 0.0
    alert_style: AlertStyle = AlertStyle.STANDARD
    announce_intervals: bool = True
    chain_next: Optional[Dict] = None  # Timer to start after this one
    category: Optional[str] = None  # cooking, work, exercise, etc.
    
    # Internal
    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _announced_milestones: set = field(default_factory=set)
    
    @property
    def end_time(self) -> Optional[datetime]:
        if self.started_at and self.state == TimerState.RUNNING:
            remaining = self.duration_seconds - self.elapsed_before_pause
            return self.started_at + timedelta(seconds=remaining)
        return None
    
    @property
    def remaining_seconds(self) -> float:
        if self.state == TimerState.PAUSED:
            return self.duration_seconds - self.elapsed_before_pause
        elif self.state == TimerState.RUNNING and self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds() + self.elapsed_before_pause
            return max(0, self.duration_seconds - elapsed)
        return 0
    
    @property
    def progress_percent(self) -> float:
        if self.duration_seconds == 0:
            return 100.0
        elapsed = self.duration_seconds - self.remaining_seconds
        return min(100.0, (elapsed / self.duration_seconds) * 100)


class SmartTimerManager:
    """
    Intelligent timer manager with futuristic features.
    Manages multiple timers with smart scheduling and alerts.
    """
    
    def __init__(self, notifications=None):
        self.notifications = notifications or VoiceNotifications()
        self.timers: Dict[int, SmartTimer] = {}
        self._id_counter = 0
        self._lock = threading.Lock()
        
        # User pattern learning
        self.usage_history: List[Dict] = []
        self.common_durations: Dict[str, int] = {}  # label -> most common duration
        self.history_file = "data/timer_history.json"
        
        # Pomodoro settings
        self.pomodoro_work_duration = 25 * 60  # 25 minutes
        self.pomodoro_break_duration = 5 * 60  # 5 minutes
        self.pomodoro_long_break = 15 * 60     # 15 minutes
        self.pomodoro_count = 0
        # What the last operation changed, for undo: [(timer, remaining seconds, state before)].
        self.last_affected = []

        # Load history
        self._load_history()
    
    def _load_history(self):
        """Load timer usage history for pattern learning."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.usage_history = data.get('history', [])
                    self.common_durations = data.get('common_durations', {})
        except Exception as e:
            print(f"Could not load timer history: {e}")
    
    def _save_history(self):
        """Save timer usage history."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump({
                    'history': self.usage_history[-100:],  # Keep last 100
                    'common_durations': self.common_durations
                }, f)
        except Exception as e:
            print(f"Could not save timer history: {e}")
    
    def _record_usage(self, label: Optional[str], duration: int, category: Optional[str]):
        """Record timer usage for pattern learning."""
        self.usage_history.append({
            'label': label,
            'duration': duration,
            'category': category,
            'timestamp': datetime.now().isoformat(),
            'hour': datetime.now().hour
        })
        
        # Update common durations
        if label:
            label_key = label.lower()
            if label_key not in self.common_durations:
                self.common_durations[label_key] = duration
            else:
                # Average with existing (weighted towards recent)
                self.common_durations[label_key] = int(
                    0.7 * duration + 0.3 * self.common_durations[label_key]
                )
        
        self._save_history()
    
    @classmethod
    def parse_duration(cls, text: str) -> tuple:
        """
        Advanced natural language duration parsing.
        Understands complex expressions like "a couple minutes", "half an hour".
        
        Returns: (seconds, formatted_string), or (None, None) when no duration
        is given. A zero or negative duration returns (seconds, None) so
        callers can reject it rather than mistake it for a missing one.
        """
        text_lower = _words_to_digits(text.lower().strip())
        total_seconds = 0
        found = False
        
        # Handle special expressions first
        special_patterns = [
            (r'(?:a\s+)?couple\s*(?:of\s+)?(?:minute|min)s?', 2 * 60),
            (r'(?:a\s+)?few\s*(?:minute|min)s?', 3 * 60),
            (r'(?:a\s+)?couple\s*(?:of\s+)?(?:second|sec)s?', 2),
            (r'(?:a\s+)?few\s*(?:second|sec)s?', 3),
            (r'(?:a\s+)?couple\s*(?:of\s+)?(?:hour|hr)s?', 2 * 3600),
            (r'(?:a\s+)?few\s*(?:hour|hr)s?', 3 * 3600),
            (r'half\s*(?:an?\s+)?(?:hour|hr)', 30 * 60),
            (r'quarter\s*(?:of\s+)?(?:an?\s+)?(?:hour|hr)', 15 * 60),
            (r'(?:an?\s+)?(?:hour|hr)\s+(?:and\s+)?(?:a\s+)?half', 90 * 60),
            (r'(?:a\s+)?moment', 30),  # "a moment" = 30 seconds
            (r'(?:a\s+)?bit', 60),     # "a bit" = 1 minute
            (r'(?:a\s+)?while', 5 * 60), # "a while" = 5 minutes
        ]
        
        for pattern, seconds in special_patterns:
            if re.search(pattern, text_lower):
                total_seconds += seconds
                found = True
                text_lower = re.sub(pattern, '', text_lower)
        
        # Numeric patterns (spelled-out numbers are already digits). A sign
        # is kept only when it is not part of a range such as "2-3".
        numeric_patterns = [
            (r'(?<![\w-])(-?\d+(?:\.\d+)?)\s*(?:hour|hr|h)s?', 3600),
            (r'(?<![\w-])(-?\d+(?:\.\d+)?)\s*(?:minute|min|m)(?:ute)?s?(?!\s*s)', 60),
            (r'(?<![\w-])(-?\d+(?:\.\d+)?)\s*(?:second|sec|s)(?:ond)?s?', 1),
        ]

        for pattern, multiplier in numeric_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                try:
                    total_seconds += int(float(match) * multiplier)
                    found = True
                except (ValueError, TypeError):
                    pass
        
        if not found:
            return None, None
        if total_seconds <= 0:
            return total_seconds, None
        
        return total_seconds, cls._format_duration(total_seconds)
    
    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format seconds into human-readable duration."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if secs > 0 and hours == 0:  # Don't mention seconds if hours are involved
            parts.append(f"{secs} second{'s' if secs != 1 else ''}")
        
        if len(parts) == 0:
            return "0 seconds"
        elif len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        else:
            return f"{', '.join(parts[:-1])}, and {parts[-1]}"
    
    def _format_remaining(self, seconds: float) -> str:
        """Format remaining time in a natural way."""
        if seconds <= 0:
            return "complete"
        
        seconds = int(seconds)
        
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            if secs > 0 and mins < 5:
                return f"{mins} minute{'s' if mins != 1 else ''} and {secs} second{'s' if secs != 1 else ''}"
            return f"{mins} minute{'s' if mins != 1 else ''}"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            if mins > 0:
                return f"{hours} hour{'s' if hours != 1 else ''} and {mins} minute{'s' if mins != 1 else ''}"
            return f"{hours} hour{'s' if hours != 1 else ''}"
    
    def _detect_category(self, label: Optional[str], text: str) -> Optional[str]:
        """Auto-detect timer category from label or context."""
        search_text = f"{label or ''} {text}".lower()
        
        categories = {
            'cooking': ['cook', 'bake', 'boil', 'pasta', 'rice', 'egg', 'tea', 'coffee', 
                       'food', 'oven', 'microwave', 'steak', 'chicken', 'pizza'],
            'work': ['work', 'focus', 'meeting', 'call', 'presentation', 'deadline',
                    'pomodoro', 'task', 'project'],
            'exercise': ['exercise', 'workout', 'plank', 'stretch', 'rest', 'sets',
                        'running', 'gym', 'yoga', 'meditation'],
            'break': ['break', 'relax', 'rest', 'nap', 'sleep'],
            'reminder': ['remind', 'remember', 'check', 'pill', 'medicine', 'laundry']
        }
        
        for category, keywords in categories.items():
            if any(kw in search_text for kw in keywords):
                return category
        
        return None
    
    @staticmethod
    def _extract_label(text: str) -> Optional[str]:
        """Timer label without a leading "to" / "for": "to drink coffee" -> "Drink Coffee"."""
        label = SmartTimerManager._extract_raw_label(text)
        if label:
            words = label.split()
            while words and words[0].lower() in ('to', 'for'):
                words.pop(0)
            label = ' '.join(words) or None
        return label

    @staticmethod
    def _extract_raw_label(text: str) -> Optional[str]:
        """Extract timer label from natural language."""
        text_lower = text.lower()
        
        # Common conversational phrases to strip from the beginning
        strip_phrases = [
            'jarvis ', 'hey jarvis ', 'ok jarvis ',
            'can you ', 'could you ', 'would you ', 'will you ',
            'please ', 'kindly ', 'i need you to ', 'i want you to ',
            'go ahead and ', 'now '
        ]
        
        for phrase in strip_phrases:
            if text_lower.startswith(phrase):
                text_lower = text_lower[len(phrase):]
        
        # Duration words to exclude from labels
        duration_words = [
            'second', 'seconds', 'sec', 'secs', 's',
            'minute', 'minutes', 'min', 'mins', 'm',
            'hour', 'hours', 'hr', 'hrs', 'h',
            'half', 'quarter', 'couple', 'few', 'bit', 'moment', 'while',
            'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
            'eleven', 'twelve', 'fifteen', 'twenty', 'thirty', 'forty', 'fifty', 'sixty',
            'timer', 'timers', 'set', 'start', 'create', 'for', 'of', 'a', 'an', 'the', 'my', 'please',
            'can', 'could', 'would', 'will', 'you', 'me', 'i', 'jarvis'
        ]
        
        # An explicit name wins: "certain timer for 25 minutes called pasta" is Pasta.
        match = re.search(r'\b(?:called|named)\s+(?:my\s+|the\s+)?(.+?)$', text_lower)
        if match:
            label_words = [w for w in match.group(1).split() if w not in duration_words and not w.isdigit()]
            if label_words:
                return ' '.join(label_words).title()

        # Pattern: "set a {label} timer for {duration}"
        match = re.search(r'(?:set|start|create)\s+(?:a\s+)?(.+?)\s+timer\s+(?:for|of)', text_lower)
        if match:
            label = match.group(1).strip()
            # Check if it's not a duration word
            if label and label not in duration_words and not label.isdigit():
                # Further clean up
                label_words = [w for w in label.split() if w not in duration_words]
                if label_words:
                    return ' '.join(label_words).title()
        
        # Pattern: "{label} timer for {duration}"
        match = re.search(r'^(.+?)\s+timer\s+(?:for|of)', text_lower)
        if match:
            label = match.group(1).strip()
            label_words = [w for w in label.split() if w not in duration_words]
            if label_words:
                return ' '.join(label_words).title()
        
        # Pattern: "timer for {duration} for {label}" or "timer called/named {label}"
        match = re.search(r'timer\s+(?:for\s+.+?\s+)?(?:for|called|named)\s+(?:my\s+)?(?:the\s+)?(.+?)$', text_lower)
        if match:
            label = match.group(1).strip()
            label_words = [w for w in label.split() if w not in duration_words and not w.isdigit()]
            if label_words:
                return ' '.join(label_words).title()
        
        # Look for common timer labels in the text
        common_labels = [
            'pasta', 'rice', 'eggs', 'tea', 'coffee', 'noodles', 'chicken', 'steak', 'pizza',
            'pomodoro', 'work', 'break', 'nap', 'meditation', 'workout', 'plank', 'stretch',
            'laundry', 'oven', 'microwave', 'bake', 'boil'
        ]
        
        for label in common_labels:
            if label in text_lower:
                return label.title()
        
        return None
    
    def suggest_duration(self, label: str) -> Optional[int]:
        """Suggest duration based on learned patterns."""
        label_key = label.lower()
        
        # Check learned patterns
        if label_key in self.common_durations:
            return self.common_durations[label_key]
        
        # Default suggestions for common activities
        defaults = {
            'tea': 3 * 60,
            'coffee': 4 * 60,
            'eggs': 6 * 60,
            'pasta': 10 * 60,
            'rice': 15 * 60,
            'nap': 20 * 60,
            'break': 5 * 60,
            'pomodoro': 25 * 60,
            'meditation': 10 * 60,
            'plank': 60,
            'stretch': 5 * 60,
        }
        
        for key, duration in defaults.items():
            if key in label_key:
                return duration
        
        return None
    
    def create_timer(
        self,
        text: str,
        label: Optional[str] = None,
        chain_to: Optional[Dict] = None,
        alert_style: AlertStyle = AlertStyle.STANDARD,
        announce_intervals: bool = True,
        respond=synthesize_speech,
    ) -> Optional[SmartTimer]:
        """
        Create an intelligent timer from natural language.
        
        Examples:
            "set a timer for 5 minutes"
            "set a pasta timer for 10 minutes"
            "timer for a couple minutes"
            "remind me in half an hour"
        """
        # Parse duration
        duration_seconds, duration_str = self.parse_duration(text)
        
        # Auto-extract label if not provided
        if not label:
            label = self._extract_label(text)
        
        # If no duration found, try to suggest based on label
        if duration_seconds is None and label:
            suggested = self.suggest_duration(label)
            if suggested:
                duration_seconds = suggested
                duration_str = self._format_duration(suggested)
                # The announcement below says what was set; "undo" reverses it.
        
        if duration_seconds is None or duration_seconds <= 0:
            respond(say('timer_no_duration'))
            return None
        
        # Detect category
        category = self._detect_category(label, text)
        
        # Create timer
        with self._lock:
            self._id_counter += 1
            timer = SmartTimer(
                id=self._id_counter,
                duration_seconds=duration_seconds,
                label=label,
                alert_style=alert_style,
                announce_intervals=announce_intervals,
                chain_next=chain_to,
                category=category,
                started_at=datetime.now()
            )
            self.timers[timer.id] = timer
        
        # Record for learning
        self._record_usage(label, duration_seconds, category)
        
        # Start timer thread
        self._start_timer_thread(timer)
        self.last_affected = [(timer, timer.remaining_seconds, TimerState.RUNNING)]
                
        # Announce
        self._announce_timer_set(timer, duration_str, respond=respond)
        
        return timer
    
    def _announce_timer_set(self, timer: SmartTimer, duration_str: str, respond=synthesize_speech):
        """Announce timer creation with style."""
        if timer.label:
            respond(say('timer_set', name=timer.label.lower(), duration=duration_str))
        else:
            respond(say('timer_set_plain', duration=duration_str))
    
    def _start_timer_thread(self, timer: SmartTimer):
        """Start the timer monitoring thread."""
        def run_timer():
            milestones = self._calculate_milestones(timer.duration_seconds)
            
            while timer.state == TimerState.RUNNING:
                if timer._stop_event.wait(timeout=1):
                    break
                
                remaining = timer.remaining_seconds
                
                # Check for milestone announcements
                if timer.announce_intervals:
                    for milestone_seconds, message in milestones:
                        if (milestone_seconds not in timer._announced_milestones and 
                            remaining <= milestone_seconds + 1 and remaining >= milestone_seconds - 1):
                            timer._announced_milestones.add(milestone_seconds)
                            self._announce_milestone(timer, message, remaining)
                            break
                
                # Check if timer is done
                if remaining <= 0:
                    self._complete_timer(timer)
                    break
            
        timer._thread = threading.Thread(target=run_timer, daemon=True)
        timer._thread.start()
    
    def _calculate_milestones(self, duration: int) -> List[tuple]:
        """Calculate announcement milestones based on duration."""
        milestones = []
        
        # Always announce 10 seconds
        if duration > 15:
            milestones.append((10, "10 seconds left"))
        
        # 30 seconds for timers > 1 min
        if duration >= 90:
            milestones.append((30, "30 seconds left"))
        
        # 1 minute for timers > 2 min
        if duration >= 150:
            milestones.append((60, "1 minute left"))
        
        # Halfway point for timers > 4 minutes
        if duration >= 240:
            halfway = duration // 2
            milestones.append((halfway, "halfway there"))
        
        # 5 minutes for timers > 10 min
        if duration >= 600:
            milestones.append((300, "5 minutes left"))
        
        return sorted(milestones, key=lambda x: -x[0])
    
    def _announce_milestone(self, timer: SmartTimer, message: str, remaining: float):
        """Announce a timer milestone using smart alert system."""
        
        self.notifications.milestone(
            timer_label=timer.label,
            message=message,
            remaining_seconds=remaining,
            remaining_fn=lambda: timer.remaining_seconds
        )
    
    def _complete_timer(self, timer: SmartTimer):
        """Handle timer completion with smart alerts."""
        
        timer.state = TimerState.COMPLETED
        
        # Build completion message
        if timer.label:
            message = say('timer_done', name=timer.label.lower())
        else:
            message = say('timer_done_plain')
        
        # Use smart alert system (handles visual, audio, and voice)
        self.notifications.completion(
            timer_label=timer.label,
            message=message,
            category=timer.category
        )
        
        # Handle chained timer
        if timer.chain_next:
            self._start_chained_timer(timer)
        
        # Cleanup
        with self._lock:
            if timer.id in self.timers:
                del self.timers[timer.id]
    
    def _start_chained_timer(self, completed_timer: SmartTimer):
        """Start the next timer in a chain."""
        chain = completed_timer.chain_next
        if chain:
            self.notifications.speak(say('timer_next'))
            self.create_timer(
                text=f"{chain.get('duration', '5 minutes')}",
                label=chain.get('label'),
                announce_intervals=chain.get('announce_intervals', True),
                respond=self.notifications.speak
            )
    
    def pause_timer(self, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> bool:
        """Pause a running timer."""
        timer = self._find_timer(timer_id, label)
        
        if not timer and (timer_id or label):
            # A specific timer was requested: never act on a different one.
            respond(say('timer_not_found', what=f"a {label.lower()} timer" if label else 'that timer'))
            return False

        # No timer was named: use the only running timer, if there is one
        if not timer:
            with self._lock:
                running_timers = [t for t in self.timers.values() if t.state == TimerState.RUNNING]
                if len(running_timers) == 1:
                    timer = running_timers[0]
                elif len(running_timers) > 1:
                    respond(say('timer_which', verb='pause'))
                    return False
                else:
                    respond(say('timer_none_to', verb='pause'))
                    return False
        
        if timer.state != TimerState.RUNNING:
            respond(say('timer_not_running'))
            return False
        
        self.last_affected = [(timer, timer.remaining_seconds, TimerState.RUNNING)]
        timer.state = TimerState.PAUSED
        timer.pause_time = datetime.now()
        timer.elapsed_before_pause += (timer.pause_time - timer.started_at).total_seconds()
        timer._stop_event.set()
        
        remaining = self._format_remaining(timer.remaining_seconds)
        respond(say('timer_paused', name=(timer.label or 'timer').lower(), left=remaining))
        
        return True
    
    def resume_timer(self, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> bool:
        """Resume a paused timer."""
        timer = self._find_timer(timer_id, label)
        
        if not timer and (timer_id or label):
            # A specific timer was requested: never act on a different one.
            respond(say('timer_not_found', what=f"a {label.lower()} timer" if label else 'that timer'))
            return False

        # No timer was named: use the only paused timer, if there is one
        if not timer:
            with self._lock:
                paused_timers = [t for t in self.timers.values() if t.state == TimerState.PAUSED]
                if len(paused_timers) == 1:
                    timer = paused_timers[0]
                elif len(paused_timers) > 1:
                    respond(say('timer_which', verb='resume'))
                    return False
                else:
                    respond(say('timer_none_to', verb='resume'))
                    return False
        
        if timer.state != TimerState.PAUSED:
            respond(say('timer_not_paused'))
            return False
        
        self.last_affected = [(timer, timer.remaining_seconds, TimerState.PAUSED)]
        timer.state = TimerState.RUNNING
        timer.started_at = datetime.now()
        timer._stop_event.clear()
        
        # Restart the timer thread
        self._start_timer_thread(timer)
        
        remaining = self._format_remaining(timer.remaining_seconds)
        respond(say('timer_resumed', left=remaining))
        
        return True
    
    def cancel_timer(self, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> bool:
        """Cancel a timer."""
        timer = self._find_timer(timer_id, label)
        
        if not timer and (timer_id or label):
            # A specific timer was requested: never act on a different one.
            respond(say('timer_not_found', what=f"a {label.lower()} timer" if label else 'that timer'))
            return False

        if not timer:
            # No timer was named: cancel the only one, if there is one
            with self._lock:
                if len(self.timers) == 1:
                    timer = list(self.timers.values())[0]
                elif len(self.timers) > 1:
                    respond(say('timer_which', verb='cancel'))
                    return False
                else:
                    respond(say('no_timers'))
                    return False
        
        self.last_affected = [(timer, timer.remaining_seconds, timer.state)]
        timer.state = TimerState.CANCELLED
        timer._stop_event.set()

        with self._lock:
            if timer.id in self.timers:
                del self.timers[timer.id]
        
        if timer.label:
            respond(say('timer_cancelled', name=timer.label.lower()))
        else:
            respond(say('timer_cancelled_plain'))
        
        return True
    
    def cancel_all_timers(self, respond=synthesize_speech) -> int:
        """Cancel all active timers."""
        with self._lock:
            count = len(self.timers)
            self.last_affected = [(t, t.remaining_seconds, t.state) for t in self.timers.values()]
            for timer in self.timers.values():
                timer.state = TimerState.CANCELLED
                timer._stop_event.set()
            self.timers.clear()
        
        if count == 0:
            respond(say('no_timers'))
        elif count == 1:
            respond(say('timer_cancelled_plain'))
        else:
            respond(say('timers_all_cancelled', count=count))
        
        return count
    
    def get_status(self, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> Optional[str]:
        """Get status of a timer or all timers."""
        if timer_id or label:
            timer = self._find_timer(timer_id, label)
            if timer:
                return self._format_timer_status(timer)
            respond(say('timer_not_found', what='that timer'))
            return None
        
        # Get all timers status
        with self._lock:
            if not self.timers:
                response = say('no_timers')
                respond(response)
                return response
            
            if len(self.timers) == 1:
                timer = list(self.timers.values())[0]
                status = self._format_timer_status(timer)
                respond(status)
                return status
            
            # Multiple timers
            statuses = []
            for timer in self.timers.values():
                remaining = self._format_remaining(timer.remaining_seconds)
                if timer.label:
                    statuses.append(f"{timer.label.lower()}, {remaining}")
                else:
                    statuses.append(f"timer {timer.id}, {remaining}")

            response = say('timer_status_many', count=len(self.timers), list='; '.join(statuses))
            respond(response)
            return response
    
    def _format_timer_status(self, timer: SmartTimer) -> str:
        """Format a single timer's status."""
        remaining = self._format_remaining(timer.remaining_seconds)
        progress = int(timer.progress_percent)
        
        if timer.state == TimerState.PAUSED:
            return say('timer_status_paused', name=(timer.label or 'the timer').lower(), left=remaining)
        if timer.label:
            return say('timer_status', name=timer.label.lower(), left=remaining)
        return say('timer_status_plain', left=remaining)
    
    def _find_timer(self, timer_id: Optional[int], label: Optional[str]) -> Optional[SmartTimer]:
        """Find a timer by ID or label."""
        with self._lock:
            if timer_id and timer_id in self.timers:
                return self.timers[timer_id]
            
            if label:
                label_lower = label.lower()
                for timer in self.timers.values():
                    if timer.label and timer.label.lower() == label_lower:
                        return timer
            
            return None
    
    def add_time(self, seconds: int, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> bool:
        """Add time to an existing timer."""
        timer = self._find_timer(timer_id, label)
        
        if not timer and (timer_id or label):
            # A specific timer was requested: never act on a different one.
            respond(say('timer_not_found', what=f"a {label.lower()} timer" if label else 'that timer'))
            return False

        if not timer:
            with self._lock:
                if len(self.timers) == 1:
                    timer = list(self.timers.values())[0]
                else:
                    respond(say('timer_not_found', what='that timer'))
                    return False
        
        self.last_affected = [(timer, timer.remaining_seconds, timer.state)]
        timer.duration_seconds += seconds
        added_str = self._format_duration(seconds)
        
        if timer.label:
            respond(say('time_added', duration=added_str, name=timer.label.lower()))
        else:
            respond(say('time_added_plain', duration=added_str))
        
        return True
    
    def remove_time(self, seconds: int, timer_id: Optional[int] = None, label: Optional[str] = None, respond=synthesize_speech) -> bool:
        """Take time off a timer (never cancels it: if that is more than what is left, nothing changes)."""
        timer = self._find_timer(timer_id, label)

        if not timer and (timer_id or label):
            respond(say('timer_not_found', what=f"a {label.lower()} timer" if label else 'that timer'))
            return False

        if not timer:
            with self._lock:
                if len(self.timers) == 1:
                    timer = list(self.timers.values())[0]
                elif len(self.timers) > 1:
                    respond(say('timer_which', verb='take time off'))
                    return False
                else:
                    respond(say('no_timers'))
                    return False

        if timer.remaining_seconds <= seconds:
            respond(say('remove_too_much', left=self._format_remaining(timer.remaining_seconds),
                        name=(timer.label or 'the timer').lower()))
            return False

        self.last_affected = [(timer, timer.remaining_seconds, timer.state)]
        timer.duration_seconds -= seconds
        removed_str = self._format_duration(seconds)
        if timer.label:
            respond(say('time_removed', duration=removed_str, name=timer.label.lower()))
        else:
            respond(say('time_removed_plain', duration=removed_str))
        return True

    def restore_timers(self, snapshots):
        """Undo a cancel: put timers back with the time they had left."""
        for old, remaining, state in snapshots:
            timer = SmartTimer(id=old.id, duration_seconds=old.duration_seconds, label=old.label,
                               alert_style=old.alert_style, announce_intervals=old.announce_intervals,
                               chain_next=old.chain_next, category=old.category, started_at=datetime.now(),
                               elapsed_before_pause=old.duration_seconds - remaining,
                               state=TimerState.PAUSED if state == TimerState.PAUSED else TimerState.RUNNING)
            timer._announced_milestones = set(old._announced_milestones)
            with self._lock:
                self.timers[timer.id] = timer
            if timer.state == TimerState.RUNNING:
                self._start_timer_thread(timer)

    def active_timers(self):
        """Running or paused timers, for "which timer?" answers."""
        with self._lock:
            return list(self.timers.values())

    def start_pomodoro(self, work_duration: Optional[int] = None, break_duration: Optional[int] = None, respond=synthesize_speech):
        """Start a Pomodoro work session."""
        work = work_duration or self.pomodoro_work_duration
        break_dur = break_duration or self.pomodoro_break_duration
        
        self.pomodoro_count += 1
        is_long_break = self.pomodoro_count % 4 == 0
        
        break_time = self.pomodoro_long_break if is_long_break else break_dur
        break_label = "long break" if is_long_break else "short break"
        
        # Create work timer that chains to break timer
        self.create_timer(
            text=f"{work // 60} minutes",
            label=f"Pomodoro {self.pomodoro_count}",
            chain_to={
                'duration': f"{break_time // 60} minutes",
                'label': break_label
            },
            alert_style=AlertStyle.STANDARD,
            respond=respond
        )
        
        respond(say('pomodoro_started', number=self.pomodoro_count, work=work // 60, rest=break_time // 60,
                    kind=break_label))


# ============================================================================
# Global instance and convenience functions
# ============================================================================

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        _manager = SmartTimerManager()
    return _manager


def set_timer(text: str, label: str = None) -> Optional[SmartTimer]:
    """Set a new smart timer."""
    return _get_manager().create_timer(text, label)


def pause_timer(label: str = None):
    """Pause a timer."""
    return _get_manager().pause_timer(label=label)


def resume_timer(label: str = None):
    """Resume a paused timer."""
    return _get_manager().resume_timer(label=label)


def cancel_timer(label: str = None):
    """Cancel a timer."""
    return _get_manager().cancel_timer(label=label)


def cancel_all_timers():
    """Cancel all timers."""
    return _get_manager().cancel_all_timers()


def get_timer_status(label: str = None):
    """Get timer status."""
    return _get_manager().get_status(label=label)


def add_time(duration_text: str, label: str = None):
    """Add time to a timer."""
    seconds, _ = SmartTimerManager.parse_duration(duration_text)
    if seconds:
        return _get_manager().add_time(seconds, label=label)
    return False


def start_pomodoro():
    """Start a Pomodoro session."""
    _get_manager().start_pomodoro()


_UNIT_WORDS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
    'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
    'nineteen': 19,
}
_TENS_WORDS = {
    'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
}
_NUMBER_WORDS = re.compile(
    r'\b(?:(minus|negative)\s+)?(?:({tens})(?:[\s-]+({digits}))?|({units}))\b'.format(
        tens='|'.join(_TENS_WORDS),
        digits='one|two|three|four|five|six|seven|eight|nine',
        units='|'.join(sorted(_UNIT_WORDS, key=len, reverse=True))))


def _words_to_digits(text: str) -> str:
    """'twenty five' -> '25', 'minus five' -> '-5', 'minus 5' -> '-5'."""
    def number(match):
        if match.group(2):
            value = _TENS_WORDS[match.group(2)] + (_UNIT_WORDS[match.group(3)] if match.group(3) else 0)
        else:
            value = _UNIT_WORDS[match.group(4)]
        return ('-' if match.group(1) else '') + str(value)
    text = _NUMBER_WORDS.sub(number, text)
    return re.sub(r'\b(?:minus|negative)\s+(?=\d)', '-', text)


def extract_timer_info(text: str) -> dict:
    """Timer label and duration from natural language. The action (start,
    pause, ...) is decided by the intent router, not here."""
    return {
        'label': SmartTimerManager._extract_label(text),
        'duration': SmartTimerManager.parse_duration(text)
    }
