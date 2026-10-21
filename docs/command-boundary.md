# Command execution boundary

The voice entry point is still `core.intent_handler.handle_query(query)`.
Plain-text callers use `core.command_engine.execute_query(query)` and receive
a `CommandResult`; foreground responses are not printed or spoken automatically.

```python
from datetime import datetime
from core.command_engine import execute_query

result = execute_query("what time is it", now=lambda: datetime(2026, 9, 9, 14, 30))
assert result.status == "handled"
assert result.messages == ("The current time is 02:30 PM.",)
```

## Responsibilities

1. `understand_query(query, services)` returns a `Command` with intent and
   arguments. It does not run actions. Existing reminder/timer parsing is
   accessed through replaceable services.
2. `execute_command(command, services)` performs the selected action and returns
   its immediate messages. Clock and response-choice functions can be injected.
3. `execute_query()` preserves the existing contextual-follow-up precedence,
   then understands and executes. It converts ordinary exceptions into error
   results. It does not retry actions or guarantee rollback of partial effects.
4. `deliver_result(result, output)` delivers the returned messages in order.
   The voice wrapper supplies lazy Google TTS delivery. An output failure does
   not cause the command to execute again.

`CommandResult` contains `status`, `intent`, `messages`, `pending_action`,
`data`, and an optional exception type in `error`. Status is:

- `handled`: dispatch completed. Existing weather/chat integrations still return
  provider errors as ordinary text, so this is not a universal success guarantee.
- `pending`: the existing reminder-time question; `data["task"]` contains the task.
- `error`: invalid input, an explicit domain failure, or an execution exception.

`legacy_value()` preserves the `True`, `False`, or `"pending_reminder_time"`
contract consumed by `Assistant`. The old dispatcher treated a timer/reminder
domain failure as handled after announcing it; `legacy_handled` retains that
behavior while text callers can inspect `status == "error"`.

## Services and background events

`CommandServices` lazily imports the existing providers. Constructing it does
not load credentials, NLP models, speech recognition, TTS, or runtime data.
Executing real weather/chat/YouTube commands still uses their respective APIs.
Real reminder parsing still uses the existing spaCy model; audio independence
does not mean all NLP/provider dependencies have been removed.

Reuse a service instance to retain active timers:

```python
from core.command_engine import execute_query
from core.command_output import TextNotifications, deliver_result
from core.command_services import CommandServices

services = CommandServices(notifications=TextNotifications(output=print))
result = execute_query("set a pasta timer for 5 minutes", services)
deliver_result(result, print)
```

Timer milestones, completion events, chained-timer messages and reminder alerts
use the notification adapter independently of the returned foreground result.
Text services default to terminal notifications. The voice wrapper supplies
`VoiceNotifications`, retaining the existing smart visual/audio/voice alerts.

The timer/reminder managers accept response callbacks for immediate messages.
Their legacy direct-call defaults still speak lazily. No global speech function
is patched or redirected to collect command results.

Reminder restoration is now explicit: `main()` calls `initialize_reminders()`
for voice startup. Text services initialize reminders on first reminder action,
using their selected notifier. Importing the reminder module starts no jobs.
Standalone callers wanting restoration must also call `initialize_reminders()`.

Conversation context and reminder storage remain process-wide. This change does
not add isolated user sessions; do not treat different services objects as
independent reminder/conversation runtimes. Timer dictionaries are service-owned.

The default city now lives in `config/settings.py`. `config/credentials.py`
re-exports it for compatibility, without requiring text commands to load a
Google credential file.

## Deterministic tests

```powershell
.\env\Scripts\python.exe -B -m pytest tests/test_command_boundary.py tests/test_command_adapters.py -q -p no:cacheprovider
```

The tests inject fake services, fixed time/response selection, temporary storage,
and controlled scheduling. They test real timer transitions and reminder
callbacks without microphone, TTS, network calls, or modifying `data/`.
A fresh-process check disables third-party site packages and blocks audio/cloud
imports while exercising local commands.

The older root-level `full_test.py` and `test_*.py` experiments were not migrated
in this refactor. Some write real storage or initialize external clients; they
are not the isolated suite above.

## Scope intentionally left for subsequent changes

City/date/duration parsing rules, reminder cancellation and recurrence defects,
wake-word pending-state handling, inactivity timeout behavior, provider error
contracts, and speech synthesis internals have not been redesigned. Named timer
status now reaches output because the adapter includes the previously discarded
returned status text. Other existing response wording and dispatch precedence
are retained.
