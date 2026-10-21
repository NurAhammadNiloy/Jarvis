"""
Visual Alert System for Jarvis AI Assistant
Non-intrusive terminal notifications that don't interrupt speech.
"""

import threading
import sys

# Try to use colorama for colored output, fall back to plain text
try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        YELLOW = CYAN = GREEN = RED = WHITE = MAGENTA = ""
    class Style:
        RESET_ALL = BRIGHT = ""


class VisualAlertManager:
    """Non-intrusive visual alerts in terminal."""
    
    STYLES = {
        'milestone': (Fore.YELLOW, '⏱️'),
        'warning': (Fore.RED, '⚠️'),
        'complete': (Fore.GREEN, '✅'),
        'info': (Fore.CYAN, 'ℹ️'),
        'timer': (Fore.MAGENTA, '⏰')
    }
    
    def __init__(self):
        self._lock = threading.Lock()
    
    def show_alert(self, message: str, style: str = 'milestone'):
        """Display a visual alert without interrupting audio."""
        color, icon = self.STYLES.get(style, (Fore.WHITE, ''))
        
        with self._lock:
            # Print a visually distinct alert box
            # Calculate border length accounting for emoji width
            text_len = len(message) + 4
            border = "═" * text_len
            print(f"\n{color}╔{border}╗")
            print(f"║ {icon} {message} ║")
            print(f"╚{border}╝{Style.RESET_ALL}")
            sys.stdout.flush()
    
    def show_inline_alert(self, message: str, style: str = 'milestone'):
        """Show a compact inline alert."""
        color, icon = self.STYLES.get(style, (Fore.WHITE, ''))
        
        with self._lock:
            print(f"{color}  {icon} {message}{Style.RESET_ALL}")
            sys.stdout.flush()


# Global instance
_visual_alerts = VisualAlertManager()


def show_visual_alert(message: str, style: str = 'milestone', inline: bool = False):
    """
    Show a visual timer alert in the terminal.
    
    Args:
        message: The alert message
        style: One of 'milestone', 'warning', 'complete', 'info', 'timer'
        inline: If True, show compact inline version
    """
    if inline:
        _visual_alerts.show_inline_alert(message, style)
    else:
        _visual_alerts.show_alert(message, style)


def visual_timer_alert(timer_label: str, message: str, remaining: int = None):
    """Convenience function for timer-specific alerts."""
    if timer_label:
        display = f"{timer_label.upper()}: {message}"
    else:
        display = message
    
    # Choose style based on urgency
    if remaining is not None and remaining <= 10:
        style = 'warning'
    elif remaining is not None and remaining <= 30:
        style = 'timer'
    else:
        style = 'milestone'
    
    show_visual_alert(display, style)
