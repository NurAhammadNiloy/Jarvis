"""Audio-independent values exchanged by the command boundary."""
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Command:
    intent: str
    query: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandResult:
    # handled means dispatch completed; legacy providers return errors as text.
    status: str
    intent: str
    messages: Tuple[str, ...] = ()
    pending_action: Optional[str] = None
    data: Mapping[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    legacy_handled: Optional[bool] = None

    def legacy_value(self):
        if self.pending_action == "reminder_time":
            return "pending_reminder_time"
        if self.legacy_handled is not None:
            return self.legacy_handled
        return self.status != "error"


@dataclass(frozen=True)
class ActionResult:
    messages: Tuple[str, ...]
    succeeded: bool = True
    pending: bool = False  # the service asked a question (e.g. which reminder)
    pending_action: Optional[str] = None  # what the question is about; default 'choose_reminder'
    # Reverses this action ("undo", "no, that's wrong"); None when it cannot be undone.
    undo: Optional[Callable[[], None]] = field(default=None, compare=False)
