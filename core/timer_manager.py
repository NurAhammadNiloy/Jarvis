"""
Timer Manager for Jarvis AI Assistant
Handles countdown timers with audio alerts.
"""

import threading
import time
import re
from datetime import datetime, timedelta
from core.speech_synthesis import synthesize_speech

# Active timers storage
active_timers = {}
_timer_id_counter = 0
_lock = threading.Lock()


def parse_duration(text):
    """
    Parse duration from natural language text.
    
    Args:
        text (str): Text containing duration (e.g., "5 minutes", "30 seconds", "1 hour")
        
    Returns:
        tuple: (total_seconds, formatted_duration_str) or (None, None)
    """
    text_lower = text.lower()
    total_seconds = 0
    parts = []
    
    # Pattern to match various duration formats
    patterns = [
        (r'(\d+(?:\.\d+)?)\s*(?:hour|hr|h)s?', 3600),      # hours
        (r'(\d+(?:\.\d+)?)\s*(?:minute|min|m)s?(?!\s*s)', 60),  # minutes (not 'ms')
        (r'(\d+(?:\.\d+)?)\s*(?:second|sec|s)s?', 1),      # seconds
        (r'(\d+)\s*(?:and\s+)?(?:a\s+)?half\s*(?:hour|hr)s?', 1800),  # half hour
        (r'(?:a\s+)?half\s*(?:hour|hr)', 1800),            # "half an hour"
        (r'(?:a\s+)?quarter\s*(?:hour|hr)', 900),          # "quarter hour"
    ]
    
    for pattern, multiplier in patterns:
        matches = re.findall(pattern, text_lower)
        for match in matches:
            if match:
                try:
                    value = float(match) if isinstance(match, str) and match else 1
                    total_seconds += int(value * multiplier)
                except (ValueError, TypeError):
                    pass
    
    # Handle written numbers
    written_numbers = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20,
        'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60
    }
    
    for word, num in written_numbers.items():
        if word in text_lower:
            # Check what unit follows the number
            if re.search(rf'{word}\s*(?:hour|hr)s?', text_lower):
                total_seconds += num * 3600
            elif re.search(rf'{word}\s*(?:minute|min)s?', text_lower):
                total_seconds += num * 60
            elif re.search(rf'{word}\s*(?:second|sec)s?', text_lower):
                total_seconds += num
    
    if total_seconds == 0:
        return None, None
    
    # Format duration string
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    
    formatted = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
    
    return total_seconds, formatted


def set_timer(duration_text, label=None):
    """
    Set a countdown timer.
    
    Args:
        duration_text (str): Duration in natural language (e.g., "5 minutes")
        label (str): Optional label for the timer (e.g., "pasta")
        
    Returns:
        dict: Timer info or None if failed
    """
    global _timer_id_counter
    
    duration_seconds, formatted_duration = parse_duration(duration_text)
    
    if duration_seconds is None or duration_seconds <= 0:
        synthesize_speech("I couldn't understand the timer duration. Please try again.")
        return None
    
    with _lock:
        _timer_id_counter += 1
        timer_id = _timer_id_counter
    
    end_time = datetime.now() + timedelta(seconds=duration_seconds)
    
    timer_info = {
        'id': timer_id,
        'label': label,
        'duration_seconds': duration_seconds,
        'duration_formatted': formatted_duration,
        'start_time': datetime.now(),
        'end_time': end_time,
        'cancelled': False
    }
    
    # Create timer thread
    def timer_callback():
        time.sleep(duration_seconds)
        
        with _lock:
            if timer_id in active_timers and not active_timers[timer_id]['cancelled']:
                del active_timers[timer_id]
                
                if label:
                    synthesize_speech(f"Sir, your {label} timer is complete! {formatted_duration} have passed.")
                else:
                    synthesize_speech(f"Sir, your timer for {formatted_duration} is complete!")
                
                # Play alert sound multiple times
                for _ in range(2):
                    synthesize_speech("Timer alert!", urgent=True)
                    time.sleep(1)
    
    timer_thread = threading.Thread(target=timer_callback, daemon=True)
    timer_thread.start()
    
    timer_info['thread'] = timer_thread
    
    with _lock:
        active_timers[timer_id] = timer_info
    
    # Announce timer set
    if label:
        synthesize_speech(f"Timer set for {formatted_duration} for {label}. I'll alert you when it's done.")
    else:
        synthesize_speech(f"Timer set for {formatted_duration}. I'll alert you when it's done.")
    
    return timer_info


def cancel_timer(timer_id=None, label=None):
    """
    Cancel an active timer.
    
    Args:
        timer_id (int): Timer ID to cancel
        label (str): Timer label to cancel
        
    Returns:
        bool: True if cancelled, False if not found
    """
    with _lock:
        if timer_id:
            if timer_id in active_timers:
                active_timers[timer_id]['cancelled'] = True
                del active_timers[timer_id]
                synthesize_speech(f"Timer {timer_id} cancelled.")
                return True
        elif label:
            for tid, timer in list(active_timers.items()):
                if timer.get('label', '').lower() == label.lower():
                    active_timers[tid]['cancelled'] = True
                    del active_timers[tid]
                    synthesize_speech(f"The {label} timer has been cancelled.")
                    return True
        elif len(active_timers) == 1:
            # Cancel the only active timer
            tid = list(active_timers.keys())[0]
            timer = active_timers[tid]
            active_timers[tid]['cancelled'] = True
            del active_timers[tid]
            if timer.get('label'):
                synthesize_speech(f"The {timer['label']} timer has been cancelled.")
            else:
                synthesize_speech("Timer cancelled.")
            return True
        elif len(active_timers) > 1:
            synthesize_speech("You have multiple timers active. Please specify which one to cancel.")
            return False
    
    synthesize_speech("No active timer found to cancel.")
    return False


def cancel_all_timers():
    """Cancel all active timers."""
    with _lock:
        count = len(active_timers)
        for timer_id in list(active_timers.keys()):
            active_timers[timer_id]['cancelled'] = True
            del active_timers[timer_id]
    
    if count > 0:
        synthesize_speech(f"Cancelled {count} timer{'s' if count != 1 else ''}.")
    else:
        synthesize_speech("No active timers to cancel.")


def get_timer_status(timer_id=None):
    """
    Get status of active timer(s).
    
    Args:
        timer_id (int): Specific timer ID, or None for all timers
        
    Returns:
        list: Timer status information
    """
    with _lock:
        if not active_timers:
            synthesize_speech("You have no active timers.")
            return []
        
        if timer_id and timer_id in active_timers:
            timers_to_check = {timer_id: active_timers[timer_id]}
        else:
            timers_to_check = active_timers.copy()
    
    statuses = []
    for tid, timer in timers_to_check.items():
        remaining = (timer['end_time'] - datetime.now()).total_seconds()
        
        if remaining > 0:
            # Format remaining time
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            seconds = int(remaining % 60)
            
            parts = []
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            if seconds > 0 and hours == 0:  # Only show seconds if less than an hour
                parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
            
            remaining_str = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts)
            
            status = {
                'id': tid,
                'label': timer.get('label'),
                'remaining_seconds': remaining,
                'remaining_formatted': remaining_str
            }
            statuses.append(status)
            
            if timer.get('label'):
                synthesize_speech(f"Your {timer['label']} timer has {remaining_str} remaining.")
            else:
                synthesize_speech(f"Timer has {remaining_str} remaining.")
    
    return statuses


def list_timers():
    """List all active timers."""
    with _lock:
        if not active_timers:
            synthesize_speech("You have no active timers.")
            return []
        
        count = len(active_timers)
        synthesize_speech(f"You have {count} active timer{'s' if count != 1 else ''}.")
        
        for tid, timer in active_timers.items():
            remaining = (timer['end_time'] - datetime.now()).total_seconds()
            if remaining > 0:
                minutes = int(remaining // 60)
                seconds = int(remaining % 60)
                
                if timer.get('label'):
                    synthesize_speech(f"{timer['label']} timer: {minutes} minutes and {seconds} seconds remaining.")
                else:
                    synthesize_speech(f"Timer {tid}: {minutes} minutes and {seconds} seconds remaining.")
        
        return list(active_timers.values())


def extract_timer_info(text):
    """
    Extract timer duration and optional label from text.
    
    Args:
        text (str): User input (e.g., "set a timer for 5 minutes for pasta")
        
    Returns:
        dict: {'duration': str, 'label': str or None}
    """
    text_lower = text.lower()
    
    # Remove command prefixes
    prefixes = [
        r'^(?:please\s+)?set\s+(?:a\s+)?timer\s+(?:for\s+)?',
        r'^(?:please\s+)?start\s+(?:a\s+)?timer\s+(?:for\s+)?',
        r'^timer\s+(?:for\s+)?',
        r'^(?:please\s+)?(?:create|make)\s+(?:a\s+)?timer\s+(?:for\s+)?',
    ]
    
    cleaned = text_lower
    for prefix in prefixes:
        cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE)
    
    # Try to find label (usually after "for" or "called")
    label = None
    label_patterns = [
        r'(?:for|called|named)\s+(?:the\s+)?(.+?)(?:\s+timer)?$',
        r'(.+?)\s+timer$',
    ]
    
    # First, try to extract duration
    duration_pattern = r'(\d+(?:\.\d+)?\s*(?:hour|hr|minute|min|second|sec|h|m|s)s?(?:\s+(?:and\s+)?\d+\s*(?:hour|hr|minute|min|second|sec|h|m|s)s?)*)'
    duration_match = re.search(duration_pattern, cleaned, re.IGNORECASE)
    
    if duration_match:
        duration = duration_match.group(1)
        remaining = cleaned.replace(duration, '').strip()
        
        # Check for label in remaining text
        for pattern in label_patterns:
            label_match = re.search(pattern, remaining, re.IGNORECASE)
            if label_match:
                potential_label = label_match.group(1).strip()
                # Filter out common words
                if potential_label and potential_label not in ['a', 'an', 'the', 'for', 'and', 'to']:
                    label = potential_label
                    break
        
        return {'duration': duration, 'label': label}
    
    # Fallback - use the whole cleaned text as duration
    return {'duration': cleaned, 'label': None}
