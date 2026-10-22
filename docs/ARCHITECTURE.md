# JARVIS target architecture

Status: plan, 22 October 2026. Nothing in this document is implemented yet
unless it says **exists**. It turns [VISION.md](VISION.md) into a design that grows out
of today's code; [ROADMAP.md](ROADMAP.md) orders the work.

Legend used throughout: **exists** (in the repository today), **extend** (exists,
changes), **new** (to be written).

---

## 1. Hardware baseline and what it allows

Measured on 22 October 2026 (`Get-CimInstance`, `nvidia-smi`):

| Part | Value |
|---|---|
| Machine | ASUS TUF Gaming F15 FX506HC (laptop) |
| CPU | Intel Core i5-11400H, 6 cores / 12 threads, 2.7 GHz base |
| RAM | 16 GB DDR4-3200 (2 × 8 GB); **2.0 GB free** at measurement time with Chrome and VS Code open |
| GPU | NVIDIA GeForce RTX 3050 Laptop, **4 GB VRAM** (4096 MiB; 2045 MiB already in use by the desktop, browser and editor), compute capability 8.6, driver 581.08 |
| Second GPU | Intel UHD Graphics (integrated) |
| Disks | NVMe SSDs. Free: **C: 15.2 GB**, D: 182 GB, E: 127 GB, F: 48 GB |
| OS | Windows 11 Home Single Language, build 26300, 64-bit |
| Python | 3.12.6 (project virtualenv `env/`) |

### Verdict

The estimates below come from model sizes and memory bandwidth (RTX 3050 Laptop
≈ 190 GB/s; dual-channel DDR4-3200 ≈ 40–50 GB/s usable). They are **not measured
on this machine**. Phase 5 starts with measuring them (ROADMAP task 5.1).

| Local model | Fits? | Expected speed | Conversational? |
|---|---|---|---|
| 3B, 4-bit (≈ 2 GB) | Entirely in VRAM, with a 4k context | ≈ 30–60 tokens/s, first token < 0.5 s | **Yes**, for short tasks |
| 4B, 4-bit (≈ 2.5 GB) | In VRAM only if the desktop leaves ≥ 3 GB free (today it leaves ~2 GB) | ≈ 25–45 tokens/s | Yes, if VRAM is free |
| 7–8B, 4-bit (≈ 4.7–5 GB) | No; split between GPU and CPU | ≈ 5–12 tokens/s, first token 2–4 s for a 1,500-token agent prompt | **No** for live speech; fine for background jobs |
| 14B, 4-bit (≈ 9 GB) | No; mostly CPU, and RAM is tight | ≈ 2–4 tokens/s | No |

**Local LLMs are practical here only at the 3–4B size, and only for small,
well-defined jobs.** Examples: rewriting a misheard request, classifying a message,
summarizing a conversation for memory, a short offline answer. A 3–4B model is not
a reliable central agent. Multi-step tool calling and planning at that size fail
noticeably more often than a frontier cloud model, and this laptop cannot run
anything larger at speaking speed. So, on this hardware:

- **The cloud model stays the main brain** for the agent (planning, tool use,
  open questions).
- **"Local-first" applies to everything around it:**
  - the wake word, voice detection and (probably) speech recognition;
  - memory storage and search, and embeddings;
  - the fast-path commands, which already run locally;
  - privacy-sensitive summaries;
  - an offline fallback.
- A bigger GPU (≥ 12 GB VRAM) would change this verdict. The model router
  (section 8) is built so that only its routing table changes when that happens.

**Speech fits alongside.**
- **Wake word and voice detection:** openWakeWord and Silero VAD are tiny ONNX
  models that need a few percent of one CPU core.
- **Recognition:** faster-whisper `small.en` / `distil-small.en` at int8 on the
  CPU should transcribe a 3-second command in roughly 0.4–1 s. That is in the
  range of today's Google median of 0.95 s (logs, 22 Oct). On the GPU,
  `large-v3-turbo` at int8 needs about 1.5–2.5 GB of VRAM, which competes with
  a local LLM.
- **Plan:** recognition on the CPU first; the GPU only if the benchmark shows a
  clear accuracy gain.
- **Text-to-speech:** Piper or Kokoro run on the CPU at or above real time. The
  exact numbers are uncertain until measured (task 5.4).

**Practical constraints**
- **C: has 15 GB free.** Ollama stores models in the user profile by default, so
  point `OLLAMA_MODELS` at D: or E:.
- **VRAM:** with 2 GB of VRAM taken by the desktop, a local LLM needs browser
  hardware acceleration off or a 3B model.
- **Battery:** on battery the GPU throttles, so local-model speed must be
  measured plugged in and on battery.

---

## 2. Principles

Kept from Phase 1, because they work (see `docs/voice-session-2026-10-22.md` and
the git history of `core/assistant.py`):

1. **Act first, offer undo; don't confirm.**
   - Clear, reversible actions run at once and "undo" reverses them for 60 s
     (`UNDO_WINDOW_SECONDS`, `Assistant._undo_last`).
   - Jarvis asks only when interpretations disagree on the action itself, as a
     short either/or (`Assistant._plan`, `AwaitingChoice`).
2. **Only executors may claim actions.** The model's words never say something
   was done. `core/dialogue.py` removes claim sentences in code
   (`without_action_claims`). The new agent keeps that rule and tightens it
   (section 4.4).
3. **One "what am I waiting for" state** (`core/conversation_state.py`), checked
   before routing and before any model.
4. **Short, natural, varied replies from one file** (`core/phrases.py`).
   - Fewer words also means less echo on speakers.
5. **Everything observable.**
   - Every decision is an event in `logs/conversation.jsonl`
     (`core/conversation_log.py`).
   - The live transcript (`core/live_transcript.py`) shows it.
   - Every new component logs its decisions the same way.
6. **Modular and replaceable.**
   - Speech, models, memory and tools sit behind small Python interfaces.
   - No framework is added without a concrete need it meets better than ~200
     lines of our own code.
7. **Evolve, don't rewrite.**
   - The voice pipeline, router, state machine, reminder engine and command
     boundary stay.
   - New components are added beside them.

---

## 3. Component map

```
            microphone                                                    speakers
                │                                                            ▲
   ┌────────────▼─────────────┐                               ┌──────────────┴───────────┐
   │ 4.1 Voice input          │                               │ 4.1 Voice output          │
   │ VAD → wake word → STT    │                               │ phrases / agent reply →   │
   │ (+ barge-in, echo gate)  │                               │ TTS → cancellable player  │
   └────────────┬─────────────┘                               └──────────────▲───────────┘
                │ Recognition                                                │ text
   ┌────────────▼─────────────────────────────────────────────────────────────┴───────────┐
   │ Assistant (orchestrator, core/assistant.py)                                            │
   │   4.3 Conversation state ─► 4.2 Fast-path router + planner ─► executor ─► reply        │
   │                     │ not a known command / compound / open question                   │
   │                     ▼                                                                  │
   │   4.4 Central agent  ◄──► 4.6 Memory (retrieve / update)                               │
   │        │  tool calls                                                                   │
   │        ▼                                                                               │
   │   4.9 Permission gate ─► 4.5 Tool layer (reminders, timers, weather, search, files…)   │
   │                                                                                        │
   │   4.7 Model router (local small model / cloud model) — used by agent, memory, repair   │
   └────────────────────────────────────────────────────────────────────────────────────────┘
                ▲  events (time, changes, results)
   ┌────────────┴─────────────┐
   │ 4.8 Scheduler / events   │  reminders, alarms, routines, monitors (core/reminder_manager.py grows into it)
   └──────────────────────────┘
```

### Today → target

| Target component | Exists today | Status |
|---|---|---|
| Voice input | `voice_capture.py` (WebRTC VAD, endpointing), `voice_runtime.py` (capture, recognition and barge-in threads; speakers-mode echo filter), `voice_recognition.py` (free Google web API via `speech_recognition`), `voice_policy.py` (wake-word text check, confidence gate) | extend |
| Voice output | `speech_synthesis.py` (Google Cloud TTS Wavenet), `speech_output.py` (cancellable `SpeechController`) | extend |
| Fast-path router | `intent_classifier.py` (ordered regex `RULES`), `command_engine.py` (`understand_query`, `execute_command`), `Assistant._plan` (act/ask) | keep, small extensions |
| Conversation state | `conversation_state.py` (`Idle`, `AwaitingConfirmation`, `AwaitingChoice`, `AwaitingSlot`) | keep; add an "agent task" state |
| Central agent | `dialogue.py` (one model call, no tools, proposes a command) + `chatgpt_service.py` (`openai==0.28`, `gpt-4o`, JSON mode) | **new**, replaces the dialogue's model call |
| Tool layer | `command_services.py` (`CommandServices` adapters), `command_result.py` (`Command`, `CommandResult`, `ActionResult.undo`) | extend: wrap as tools |
| Memory | `memory_manager.py` and `data/memory.db` (legacy, **not used by the running assistant**); `conversation.jsonl` (raw events) | **new** |
| Model router | none (OpenAI hard-coded in `chatgpt_service.py`) | **new** |
| Scheduler / events | `reminder_manager.py` (`ReminderService`: one thread, SQLite `data/reminders.db`, wakes at the earliest due time, at most every 60 s, catches up missed reminders) | extend into a general scheduler |
| Permission system | act-first + undo policy in `assistant.py`; `READ_ONLY_INTENTS` in `intent_classifier.py`; `_NOT_UNDOABLE` | **new**, generalizing these |

---

## 4. Components

Each component gets: what it does, what it builds on, what's new, and its
interface. Interfaces are Python `Protocol`s or dataclasses. Names match existing
code where one exists.

### 4.1 Voice I/O

**Does:** turns room audio into `Recognition`s addressed to Jarvis, and Jarvis's
text into interruptible speech.

**Builds on (exists):**
- `MicrophoneFrames`: 16 kHz, 20 ms frames, via `sounddevice`.
- `Endpointer`: 1.4 s silence, pre-roll, playback marks for speakers mode.
- `ContinuousListener`: three threads.
- `handle_final`: the speakers-mode filter.
- `Recognition` / `Hypothesis`.
- `SpeechController`: queue, cancel and the input-wait hold.
- `speech_chunks`: sentence chunking.

**New:**
- **On-device wake word.** In passive mode, no audio leaves the machine until the
  wake word fires.
  - Today every utterance goes to Google: on 22 October 325 of 577 final
    recognitions (56%) came back "unrecognized", nearly all background sound.
  - Detection runs on the raw frame stream in the capture thread.
  - On a hit it marks the utterance as addressed, so no transcript prefix check
    is needed; a misheard "nervous" or "Punjabi" no longer matters.
- **Better VAD:** Silero VAD replaces or backs up WebRTC VAD in the `Endpointer`.
  The aim is fewer utterances held open by noise and a shorter endpoint silence.
- **Pluggable recognizer:** `Recognizer` implementations for faster-whisper
  (local) and Google Cloud Speech-to-Text v2 (phrase hints). The current
  `GoogleRecognizer` stays as a baseline.
- **Local barge-in.** "Jarvis" or "stop" while Jarvis speaks is caught on-device
  and stops playback within ~0.3 s.
  - Today it is a cloud partial recognition every 0.8 s over a 1.8 s window
    (`barge_interval_ms`, `barge_window_ms`), which you hear as 2–4 s.
- **Local TTS later** (Phase 5): a `Synthesizer` implementation for Kokoro or
  Piper beside `GoogleSynthesizer`.

**Interfaces:**

```python
class Recognizer(Protocol):            # exists implicitly: GoogleRecognizer.__call__
    def __call__(self, pcm: bytes, *, partial: bool = False,
                 hints: Sequence[str] = ()) -> Recognition: ...

class WakeWordDetector(Protocol):      # new
    def process(self, frame: bytes) -> WakeEvent | None: ...   # 20 ms int16 frames
    def reset(self) -> None: ...

@dataclass(frozen=True)
class WakeEvent:                       # new
    keyword: str        # 'jarvis', 'stop'
    score: float
    frame_index: int    # where in the stream; lets the endpointer start the utterance there

class Synthesizer(Protocol):           # exists implicitly: GoogleSynthesizer.__call__
    def __call__(self, text: str, **options) -> PCMClip: ...
```

`Recognition` gains one field, `source: str`, e.g. `'google-web'`,
`'faster-whisper'` or `'google-cloud-v2'`. Confidence thresholds then become
per-source (see the risk in section 9).

### 4.2 Fast-path router

**Does:** turns a known command into a `Command` in milliseconds, with no model,
and runs it at once (or asks an either/or).

**Builds on (exists):**
- `intent_classifier.RULES` and `route()`;
- `command_engine.understand_query` / `execute_command` / `run_command`;
- `reminder_parser.parse_reminder`;
- `Assistant._plan` (compares recognition alternatives by `_signature`) and
  `Assistant._carry_out`.

**New:**
- **Agent fallback replaces model proposals.** A route of `chat`, an incomplete
  parse, or a compound request ("set a timer and remind me…") goes to the agent
  (4.4). Today it goes to `Dialogue.turn`, whose only output is reply text or one
  proposed command.
- **Rule growth stops.** Phase 1 said "leave for the agent": open-ended
  follow-ups, marking reminders done, music and browser control. The router keeps
  the commands it has and gains rules only when a logged session shows a frequent,
  unambiguous phrasing failing.
- **Each intent maps to a tool.** That way the fast path and the agent run the
  same executor code (4.5), and the agent can call "set a timer" without a second
  implementation.

**Interface:** unchanged: `route(text) -> Route`,
`understand_query(text, services) -> Command`,
`run_command(command, services) -> CommandResult`.

### 4.3 Conversation state

**Does:** decides first whether an utterance answers something Jarvis asked.

**Builds on (exists):**
- `ConversationState` with `Idle`, `AwaitingConfirmation(command, prompt)`,
  `AwaitingChoice(options, cues, prompt)`,
  `AwaitingSlot(intent, slot, query, prompt, command)`;
- `answer_kind`, `answer_reliable`, `strip_echoed_prompt`;
- the 120 s expiry.

**New:**
- **`AwaitingApproval(tool_call, readback, grant_offer)`** for permission tier 1
  (section 6). It is like `AwaitingConfirmation`, but holds a tool call instead of
  a `Command`. It also accepts "yes, and always for this" (a grant) and "no".
- **`AgentTask(task_id, question)`.** The agent asked a question in the middle of
  a multi-step task, and the answer resumes that task, not a fresh turn.
- **The state check gets a full transcript.** Today an `AwaitingSlot('time')` can
  capture an unrelated sentence that happens to contain a time (a Phase 1 known
  issue). The fix: before filling the slot, use the router check that
  `_fill_task` / `_fill_timer` / `_fill_reminder` already apply. A sentence that
  routes to a different command is a new request.

**Interface:** unchanged: `check(recognition, text) -> Answer | None`,
`confirm`, `choose`, `await_slot`, `clear`. New: `await_approval(...)` and
`await_agent(...)`.

### 4.4 Central agent

**Does:** handles everything the fast path can't:
- understands the request in context;
- retrieves memory;
- plans;
- calls tools (through the permission gate);
- checks the results;
- answers.

**Builds on:**
- `core/dialogue.py`. Kept: recent-turn history, the `_DETAIL` → answer-length
  rule, `parse_model_reply` robustness, `without_filler`, and
  `without_action_claims`. Kept but generalized: the `_validate` idea ("a proposal
  must be a supported, non-negated command").
- `chatgpt_service.resolve_dialogue`, whose prompt has the style rules and the
  "never claim an action" rule.

**New:** `core/agent/` with one agent loop. It is a **single agent with native
tool calling**, not a framework and not several agents:

```
turn(request, context):
    memories = memory.retrieve(request, context)                  # 4.6, ≤ ~1.5k tokens
    messages = system_prompt + recent_turns + memories + request
    for step in range(MAX_STEPS):                                 # 4 steps by default
        response = models.chat(messages, tools=tool_specs, task='agent')
        if not response.tool_calls: break
        for call in response.tool_calls:
            decision = permissions.check(call, context)           # 4.9
            if decision is ASK:   return pause(call)              # AwaitingApproval; resumes later
            if decision is DENY:  result = ToolResult.refused(...)
            else:                 result = tools.run(call)        # executor; verifies itself
            journal.append(call, result)                          # evidence for the reply
            messages += [response, result.for_model()]
    reply = compose(response.text, journal)                       # claims only from evidence
    memory.observe(turn, journal)                                 # 4.6 update (async)
```

**Guarantees** (each one a test):

1. **The reply may claim only actions in this turn's journal with
   `succeeded=True`.** The `without_action_claims` filter stays as the last line
   of defence. The composer first states the journal's executed actions in
   `phrases.py` wording ("Pasta timer, 25 minutes."). The model's free text adds
   only information, never the action report.
2. **Step and time limits.**
   - At most `MAX_STEPS` model calls and ~8 s per voice turn.
   - If longer work is needed, it becomes a background task that reports later
     (scheduler, 4.8).
3. **Tool results are data, never instructions.** Text from web pages, files or
   e-mail cannot raise permissions: a tool call that the user's own request does
   not justify is tier 1 by default (section 6).
4. **"Know / remember / verified" labelling.** Each fact in the context carries
   its source:
   - `memory` with a date;
   - `tool` with a timestamp and source name;
   - none, meaning model knowledge.

   The prompt requires saying which one applies when it matters ("You told me
   last Tuesday…", "According to Yle this morning…", "I believe…, but I haven't
   checked").
5. **Fast replies first.** If the first model response is slower than ~1.5 s, a
   one-word acknowledgement plays ("Checking."), short to limit echo.

**Interface:**

```python
@dataclass(frozen=True)
class AgentTurn:
    reply: str                       # what to say (already claim-checked)
    journal: tuple[ToolOutcome, ...] # what ran, with results
    pending: AgentPause | None       # an approval or a question that resumes the task

class Agent(Protocol):
    def turn(self, request: str, context: TurnContext) -> AgentTurn: ...
    def resume(self, pause: AgentPause, answer: str) -> AgentTurn: ...
```

`TurnContext` holds:
- the `Recognition`: text, alternatives and confidence, so the agent can repair a
  mishearing the way `Dialogue` does today;
- the recent turns;
- the pending conversation state;
- the clock.

### 4.5 Tool layer

**Does:** the only code that changes the world. Every action, from the fast path
or the agent, runs here and returns evidence.

**Builds on (exists):**
- `CommandServices`: weather, forecast, YouTube, `open_url`, reminders, timers,
  chat.
- `ActionResult(messages, succeeded, pending, pending_action, undo)`.
- `CommandResult`.
- Reminder soft delete and `undo` closures.
- Timer undo (`_timer_undo`, `restore_timers`).
- `execute_command` as the dispatch for the fast path.

**New:** a registry of `ToolSpec`s. The first tools wrap existing services, so
they are tested code with a JSON schema in front:

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                        # 'reminders.create', 'web.search'
    description: str                 # for the model, one or two sentences
    parameters: dict                 # JSON schema
    tier: Tier                       # SAFE / APPROVAL / NEVER, default for this tool (section 6)
    run: Callable[[dict, ToolContext], ToolResult]
    undoable: bool                   # documented; the result carries the undo itself

@dataclass(frozen=True)
class ToolResult:
    succeeded: bool
    summary: str                     # short fact for the model: "created reminder #42 due 2026-10-23T09:00+03:00"
    spoken: tuple[str, ...] = ()     # phrases.py wording for the user, as ActionResult.messages today
    data: Mapping[str, Any] = {}     # structured result (rows, search hits with URLs and dates)
    undo: Callable[[], None] | None = None
    verified: bool = False           # the executor re-read the state after acting (see 'Verify')
    error: str | None = None
```

**Verify** happens in the executor, not in the model: after acting, the tool
re-reads the state.
- `reminders.create` reads back the row and checks status `pending` and the due
  time.
- `timers.start` checks the timer is in `active_timers()`.
- `files.write` re-reads the file's hash.

The model gets the verified summary. A failed verification is a failed result.

**First tools, in order:**
1. **Existing commands as tools.** Reminders (create, list, delete, snooze, and a
   new `complete` for "mark it done"), alarms, timers, weather, forecast,
   time/date, `youtube.play`, `browser.open`.
2. **`web.search` and `news.headlines`.** Live information is the most-requested
   missing capability.
3. **`media.control`** (play/pause/next via Windows media keys). The Phase 1 "stop
   the music" reply stops being an apology.
4. **`memory.search` / `memory.remember` / `memory.forget`** (Phase 4).
5. **Later (Phase 6):**
   - `files.*`, scoped to granted folders;
   - `documents.*`;
   - `browser.*` automation;
   - `calendar.*`;
   - university LMS;
   - optionally MCP servers (section 10).

### 4.6 Memory

See section 7 for the design. Component summary:

**Builds on:**
- SQLite, as `reminder_store.py` already uses it well (short connections, aware
  datetimes stored as UTC, never-reused ids).
- `logs/conversation.jsonl` as the raw source of truth for what was said and done.
- `core/memory_manager.py` and `data/memory.db` are **not** built on. They are
  unused by the assistant, store raw query/response pairs without structure, and
  are replaced.

**New:** `core/memory/`: store (`data/memory.db`, new schema), extractor,
retriever, consolidator, and a CLI for viewing and editing.

```python
class Memory(Protocol):
    def retrieve(self, query: str, context: TurnContext, budget_tokens: int = 1500) -> list[MemoryHit]: ...
    def observe(self, turn: AgentTurn | FastPathTurn) -> None: ...        # queues extraction; never blocks speech
    def remember(self, text: str, kind: str, **fields) -> MemoryItem: ...  # explicit "remember that ..."
    def forget(self, item_id: int | None = None, query: str | None = None) -> int: ...
    def correct(self, item_id: int, new_content: str) -> MemoryItem: ...
```

### 4.7 Model router

**Does:** picks which model answers a task, by fixed rules (section 8), and
meters cost. The choice is never left to a model.

**Builds on:** `chatgpt_service.py`, which today hard-codes `openai==0.28`,
`gpt-4o` and an 8–10 s timeout.

**New:** `core/models/`:
- a `ChatModel` interface;
- providers: OpenAI (current SDK), Ollama (local), optionally another cloud
  provider;
- the routing table;
- a usage ledger (tokens and cost per call in SQLite, rolled up per day and
  month).

```python
class ChatModel(Protocol):
    name: str                         # 'openai:<model>', 'ollama:qwen3:4b'
    local: bool
    def chat(self, messages, *, tools=None, json=False, max_tokens=..., timeout=...) -> ModelResponse: ...

class ModelRouter:
    def choose(self, task: str, *, sensitivity: str = 'normal', needs_tools: bool = False,
               long_answer: bool = False) -> list[ChatModel]: ...   # ordered: first choice, then fallbacks
```

### 4.8 Scheduler and event system

**Does:**
- fires anything time-based: reminders, alarms, repeating alarm rings, routines;
- polls monitors (e.g. "tell me if the assignment page changes");
- turns events into either a spoken notification or an agent run.

**Builds on (exists):** `ReminderService`.
- One daemon thread waits on a condition until the earliest due time, at most
  `MAX_WAIT_SECONDS = 60`.
- `_changed()` wakes it.
- Reminders missed while Jarvis was off are announced once at startup
  (`LATE_AFTER`).
- Recurrence is handled by `next_occurrence`.
- Everything is in `data/reminders.db`.

**New:**
- The same thread and database gain a `jobs` table: id, kind, trigger, payload,
  next_run, status, last_result, owner routine.
- Job kinds: `reminder`, `alarm_ring` (repeat until stopped), `routine`,
  `monitor`, `agent_task`. Reminders keep their existing table and code path;
  `jobs` sits beside it.
- **Events:** `jobs` firing, tool results from background runs, and Jarvis start
  and stop. Each event goes through one `on_event(event)`. It decides whether to:
  - run a routine (permission-checked as if the user had asked);
  - queue a notification;
  - wake the agent.
- **Notification policy** (proactive without being intrusive):
  - urgency levels;
  - quiet hours;
  - at most N unprompted interjections per hour;
  - speak only when you were active recently, otherwise hold for the next
    interaction or the startup summary (`ReminderService.startup_summary` already
    does this for reminders).
- Timers stay in memory as today (`SmartTimerManager.timers`). Persisting them is
  a small, separate change, if wanted.

```python
@dataclass(frozen=True)
class Event:
    kind: str                 # 'job_due', 'monitor_changed', 'tool_finished', 'startup'
    payload: Mapping[str, Any]
    at: datetime

class Scheduler(Protocol):
    def schedule(self, job: JobSpec) -> int: ...
    def cancel(self, job_id: int) -> bool: ...
    def on_event(self, handler: Callable[[Event], None]) -> None: ...
```

### 4.9 Permission system

See section 6 for the design. Component summary:

**Builds on:**
- the act-first + undo policy (`Assistant._plan`, `_undo_last`, `_last_action`,
  `_NOT_UNDOABLE`, the one-time "Say undo to bring it back." hint);
- `READ_ONLY_INTENTS`;
- the confidence gate (`ConfidenceGate`, which refuses to act on unclear audio);
- the negation rule in `_plan`.

**New:** `core/permissions.py`:
- the tier table per tool;
- `check(call, context) -> ALLOW | ASK | DENY` with a reason;
- grant and routine storage in `data/permissions.db`;
- an audit event per decision.

```python
class Decision(Enum):
    ALLOW = 'allow'; ASK = 'ask'; DENY = 'deny'

class PermissionPolicy(Protocol):
    def check(self, call: ToolCall, context: CallContext) -> tuple[Decision, str]: ...
    def grant(self, tool: str, scope: dict, *, expires: datetime | None, via: str) -> int: ...
    def revoke(self, grant_id: int) -> None: ...
```

`CallContext` says who initiated the call:
- **the user live:** the request was spoken in this turn;
- **a routine:** an approved routine;
- **derived:** the agent decided on its own, or from tool output such as a web
  page.

---

## 5. The request loop

**Listen → Understand → Retrieve Memory → Reason → Plan → Act → Verify →
Respond → Update Memory**, mapped onto code.

| Step | Fast path (known command) | Agent path |
|---|---|---|
| **Listen** | Voice input: VAD → on-device wake word (passive) or active window → recognizer → `Recognition` (text, confidence, alternatives, source). `handle_final` echo filter. | same |
| **Understand** | `ConversationState.check` first (answers to questions), then `route()` + `understand_query` → `Command`; `_plan` compares alternatives → act / either-or. | `route()` says `chat`, or the parse is incomplete or compound → agent. The agent sees the alternatives and repairs mishearings. |
| **Retrieve memory** | skipped (only the recent turns in `Dialogue.history`) | `memory.retrieve(request)`: hybrid search plus time and entity filters |
| **Reason / Plan** | skipped: the rule *is* the plan | model call(s) with tool specs; at most 4 steps per voice turn |
| **Act** | `run_command` → `execute_command` → `CommandServices` (soon: the same tool executors) | each tool call → permission gate → tool executor |
| **Verify** | executor result (`ActionResult.succeeded`), read-back in the executor | read-back in the executor, plus the journal check of what the reply may claim |
| **Respond** | `phrases.say(...)` wording, ≤ 8 words for most actions | journal facts in phrases wording + model text with source labels, claim-filtered |
| **Update memory** | an event in `conversation.jsonl` only; memory extraction later reads these too | `memory.observe(turn)` queued off the speech path |

**Latency budget** (after you stop speaking). Today's measured stages, from the
log on 22 Oct: endpoint silence 1.4 s; recognition median 0.95 s (p90 1.95 s); a
dialogue model call median 1.2 s (p90 2.1 s); synthesis median 0.58 s (p90
1.1 s).

- Fast path target: ≤ 1.5 s to first audio. The changes behind it: a shorter
  endpoint with Silero VAD (~0.8 s), local recognition (~0.5–0.9 s), and
  routing/execution in milliseconds.
- Agent path target: ≤ 3 s to first audio for a one-tool turn; longer turns play
  the one-word acknowledgement.

**Fast-path skip rule:** the agent is skipped when all of these hold:
1. the conversation state has no claim on the utterance;
2. `route()` returns a command intent;
3. the parse is complete (`Assistant._complete`);
4. `_plan` returns `('act', command)`.

This is today's behaviour and stays the default. The agent is also skipped for
`ask` plans: the either/or question is cheaper than a model call.

---

## 6. Permission model

### Tiers

| Tier | Meaning | Today | Examples |
|---|---|---|---|
| **0 · Safe** | Read-only, or reversible within the undo window, local, no cost. **Act first, offer undo.** | exists (act-first policy) | time, weather, search, listing; timers; create, delete (soft), snooze or complete reminders; media keys; opening a web page (not undoable, harmless: `_NOT_UNDOABLE`) |
| **1 · Needs approval** | Irreversible, outward-facing, costly, or touching data not yet granted. **Short readback; "yes" runs it once.** | `AwaitingConfirmation` exists; used today only when alternatives disagree | send an e-mail or message; post anything; delete or overwrite files outside Jarvis's own folder; run a program or shell command; submit a form; spend money; first access to a new data source (a folder, the LMS); any action that only tool output (a web page, an e-mail) suggested |
| **2 · Never** | Refused, whatever the request or grant. | none | payments and money transfers; changing security or system settings; reading or sending credentials, keys or `.env`; deleting Jarvis's own data stores (`data/*.db`, `data/reminders.json`, backups); acting as you towards other people without a readback |

The tier comes from the tool (`ToolSpec.tier`), raised by context:
- a call in `derived` context (from untrusted content) is at least tier 1;
- a call whose arguments exceed a grant's scope is tier 1;
- a call during recognition the gate calls unclear is not acted on (today's
  `ConfidenceGate` behaviour).

The tier is never lowered by the model.

### Approval flow

1. The agent requests a tier-1 tool call. The gate returns `ASK` with a readback
   built from the arguments in code, not the model's prose. This is the same idea
   as `core/command_description.describe_command`, e.g. *"Send Anna: 'I'll be 10
   minutes late'?"*
2. Conversation state → `AwaitingApproval`. "Yes" runs it, "no" drops it, silence
   expires it (120 s, as today).
3. "Yes, always" (or "always for Anna") creates a **grant** after one more short
   readback of its scope ("Always allow messages to Anna?").
4. Long content (an e-mail body, a file list) is shown in the terminal or a local
   page and summarized in speech. Approving a 200-word e-mail by ear alone is not
   enough.

### Stored approvals

All approval data is stored in `data/permissions.db` (SQLite, the same
conventions as `reminder_store.py`).

- **`grants`:**

  | Field | Example or meaning |
  |---|---|
  | id | |
  | tool | `messages.send` |
  | scope (JSON) | `{"to": ["anna@…"]}`, `{"folder": "D:/Uni"}`, `{"max_eur": 0}` |
  | granted_at | |
  | expires_at | nullable |
  | granted_via | voice or ui |
  | use_count, last_used_at | |
  | revoked_at | |

  You can ask for the list ("what have I allowed you to do?") and revoke any
  grant ("stop sending to Anna without asking").
- **`routines`:**

  | Field | Meaning |
  |---|---|
  | id, name | |
  | trigger | time / event / monitor |
  | steps (JSON) | tool calls with parameter bounds |
  | tier_ceiling | |
  | approved_hash | |
  | approved_at | |
  | enabled | |
  | last_run, last_result | |

- **Audit:** every `check()` decision is a `permission_decision` event in
  `conversation.jsonl` (tool, decision, reason, grant id), next to the
  `tool_call` / `tool_result` events.

### Previously authorized routines

A routine is a named, bounded plan, e.g. "every weekday at 8, check the LMS for
new assignments and tell me if anything is due within 3 days". You approve it
once, from its readback. The scheduler runs it **only while**:
- the stored `approved_hash` matches the routine's current definition (any edit
  needs approval again);
- every step's tool is tier 0, or tier 1 and covered by a grant with matching
  scope;
- each run stays inside its bounds: the number of steps, the folders and
  recipients in scope, no spending.

If a run needs anything outside this, the run pauses and becomes a notification.
It never escalates on its own. Results are reported under the notification
policy (4.8).

### Undo, generalized

Act-first + undo stays the default for tier 0. Each tool says how it is undone:
- in memory: timers, `restore_timers`;
- a soft delete: reminders `status='cancelled'`, already;
- the recycle bin or a backup copy for files Jarvis wrote;
- or not at all (`undoable=False`). Then the tool must be tier 1 if it changes
  anything outside Jarvis.

`UNDO_WINDOW_SECONDS` (60 s) stays for voice "undo". The tool journal keeps undo
handles for the last N actions, so "undo the last two" becomes possible later.

---

## 7. Memory design

### What is stored

One SQLite database, `data/memory.db`. The legacy tables there are left unused
and can be deleted with your approval.

| Kind | Example | Key fields |
|---|---|---|
| **fact** | "My thesis supervisor is <name>" | subject, attribute, value |
| **preference** | "Prefers short answers", "Default city Kokkola" | subject, attribute, value |
| **project** | "Thesis on X", status, goal | name, status, summary |
| **decision** | "We decided to use faster-whisper (22 Oct)" | project, decision, reason |
| **task / deadline** | "Data structures assignment 3, due 5 Nov" | project, due_at, status |
| **event** | "Called the landlord about the heater on 20 Oct" | occurred_at, participants |
| **episode** | One conversation session, summarized: topics, decisions, open items | started_at, ended_at, summary, source log range |

Common columns:
- `id`, `kind`, `content` (one sentence);
- `entities` (linked people, projects, places);
- `source`: a conversation event range, a tool result or "user said";
- `created_at`;
- `valid_from` / `valid_to`;
- `status`: active, superseded, disputed or deleted;
- `superseded_by`;
- `confidence`: stated, inferred or verified;
- `last_confirmed_at`;
- `sensitivity`: normal or private.

A `links` table connects related items: same project, caused-by, updates. An FTS5
index and a vector index (sqlite-vec) sit over `content`.

**Never stored:** passwords, API keys, card or ID numbers. A filter runs before
every write. Audio is not stored either, except the labelled test clips you
choose to record for the speech benchmark (ROADMAP 2.3).

### How items get in

1. **Explicit:** "remember that …" → `memory.remember` and a spoken readback of
   what was stored. These are `confidence='stated'`.
2. **Extracted:**
   - When an active conversation ends (the 30 s window closes), an extraction job
     reads that session's turns from `conversation.jsonl`.
   - It proposes candidate items with sources.
   - It runs off the speech path; it uses the local model when good enough,
     otherwise the cloud model, subject to the privacy rules in section 8.
   - Candidates are checked against existing items before writing (below).
   - Inferred items are `confidence='inferred'`.
3. **From tools:** results worth keeping are written with
   `confidence='verified'` and the tool as the source. Examples: an assignment
   list fetched from the LMS, a decision recorded in a document.
4. **Episodes:** each session gets an episode summary. That is what makes "that
   thing we discussed yesterday" answerable: a time filter plus the topic.

### Retrieval

1. **Resolve references from context and time.** "Yesterday", "last week" and
   "two months ago" become a date range. "That thing", "it" and "the project"
   become candidate entities from the recent turns and the latest episodes. A cheap
   model call does this only when the request contains such references.
2. **Hybrid search.**
   - FTS5 keyword match (names, numbers, course codes) plus vector similarity,
     combined by reciprocal rank fusion.
   - Boosted by recency, entity overlap and `status='active'`.
3. **Expand along links**, one hop: the project of a matched decision, the newer
   item that supersedes a match.
4. **Budget:** about 1,500 tokens. Each hit is formatted with its date and
   source, e.g. "[remembered, 14 Oct, you said] …", so the agent can say
   "remember" vs "know".

### Outdated and contradictory items

- **Same subject + attribute, different value:**
  - If the new statement is stated by you, the old item becomes
    `status='superseded'` with `valid_to=now` and `superseded_by`. History is kept;
    retrieval returns only the current value unless asked "what did I say before?"
  - If either side is only inferred, both become `disputed`. Jarvis asks at the
    next natural moment, briefly: *"Is the deadline 5 or 12 November?"*
- **Time-bound items** (deadlines, events) become past automatically after their
  date. They stay searchable, but rank lower for "what's coming up".
- **Staleness:**
  - Facts not confirmed for a long time (e.g. 6 months for preferences, set per
    kind) are presented with their date.
  - The agent is told to verify them with a tool where one exists, before acting
    on them.
- **Nightly consolidation** (scheduler job, local model when good enough):
  - merges duplicates;
  - links new items to projects;
  - closes resolved tasks;
  - writes a short "what changed" log you can read.

### Your control

- **Voice:**
  - "what do you remember about X?" reads the top items with dates;
  - "forget that" / "forget everything about X" deletes;
  - "that's wrong, it's Y" corrects (supersedes).
- **CLI** (Phase 4): `python -m core.memory list | search | show | edit | delete | export`.
  Export is Markdown or JSON.
- **Later:** a local page served on `localhost` for browsing, editing and
  deleting, with the same functions.
- **What "forget" deletes:**
  - It is a **hard delete**: the row, its FTS and vector entries, and the
    mention in episode summaries, which are re-summarized.
  - The deletion is logged without its content.
  - This is unlike reminders, whose soft delete exists for undo. Forgetting is
    about privacy.
- **Private items** never go to a cloud model unless you allow it per request
  (section 8).

---

## 8. Model routing

Routing is a **fixed rule table in code**, so it is predictable and testable; no
model chooses the model. Each task names a first choice and fallbacks.

| Task | First choice | Fallback | Why |
|---|---|---|---|
| Fast-path commands | no model | n/a | Regex + parsers are faster and more reliable |
| Agent turn with tools | cloud | local 3–4B with a warning ("I'm offline, so this may be rough"), and **only tier-0 tools** | Tool calling and planning quality; local is too weak on this GPU |
| Open questions, long answers ("tell me about…") | cloud | local, marked as offline | Quality |
| Repairing a misheard short command | local 3–4B (Phase 5) | cloud | Short prompt, latency, privacy |
| Memory extraction, episode summaries, consolidation | local, if it passes the extraction test set; otherwise cloud with private items removed | queue until available | Background, not latency-bound; privacy |
| Embeddings | local (CPU) | none needed | Cheap, private |
| Anything with `sensitivity='private'` content | local only | ask you ("This needs the cloud model. OK to send it?") | Privacy |

Rules, applied in order:

1. **Privacy.**
   - Items or files marked private, and content from granted private folders, are
     never sent to a cloud model without a tier-1 approval for that request.
   - Raw audio goes only to the recognizer you choose (section 9).
2. **Need.** Tool use, multi-step planning or a long answer means cloud.
3. **Latency.** In a live voice turn, the model must answer within the turn
   budget. If the cloud call times out (8 s today, `request_timeout` in
   `chatgpt_service.py`), the turn falls back once to local or apologizes.
4. **Cost.**
   - A monthly budget (an open question; default in ROADMAP) is tracked in the
     usage ledger.
   - At 80% Jarvis says so once.
   - At 100%, cloud use is limited to tasks you approve, and everything else
     goes local.

**When the cloud is unavailable:** no network, an API error, or the budget is used
up.
- **What still works:** the fast path (timers, reminders and alarms are fully
  local today), memory search, local recognition (once adopted) and local TTS
  (once adopted).
- **Background agent tasks** wait in the scheduler and retry with backoff.
- **Live requests** get the local model with an honest "offline" prefix, or a
  short "I can't do that offline".
- **Not available offline:** weather, search and YouTube need the internet.
  Their tool errors are spoken through `ServiceError` as today.

---

## 9. Speech

### Recognizer: decide by benchmark, expect local faster-whisper

Today's recognizer:
- the free Google web API through `speech_recognition.recognize_google`
  (`core/voice_recognition.py`);
- no phrase hints, no model choice, n-best alternatives with confidence;
- the audio of every utterance, including background noise, goes to Google.

| Option | For | Against |
|---|---|---|
| **faster-whisper, local** (recommended to test first) | No per-minute cost; audio stays local; strong on accented and informal English; `hotwords` / `initial_prompt` can bias towards "Jarvis", command verbs and your reminder names; CPU int8 is feasible (section 1) | No n-best alternatives and no calibrated confidence. The act-first planner (`_plan` compares alternatives) and the `ConfidenceGate` must be recalibrated: confidence from `avg_logprob` / `no_speech_prob`, alternatives empty. Hallucinates on silence or noise, which on-device VAD and the wake word mitigate. GPU use needs CUDA 12 / cuDNN 9 runtime libraries on Windows (extra setup). |
| **Google Cloud Speech-to-Text v2**, phrase hints (`google-cloud-speech` is already in `requirements.txt`) | Returns alternatives and confidence (today's policy keeps working); speech adaptation boosts "Jarvis", yes/no, intent words and names; low latency | Per-minute cost (small once the wake word gates it, see open questions); audio leaves the machine; needs the network |

**Plan:** record a labelled test set from your own voice in your room (ROADMAP
2.3), then measure all three on it: today's API, faster-whisper `small.en` /
`distil-small.en` / `large-v3-turbo`, and Cloud v2 with hints. Pick by:
1. command intent accuracy;
2. wake and command word error rate;
3. latency;
4. cost.

**Expected outcome:** faster-whisper for everything after the wake word, with
Cloud v2 as an optional fallback when local confidence is low. This is not
decided until measured.

### On-device wake word

- **Recommended:** openWakeWord (Apache-2.0, ONNX, CPU).
  - Ships a pretrained "hey jarvis" model.
  - A custom "jarvis" model can be trained from synthetic speech. Training uses
    torch, but on a separate machine or Colab, not in Jarvis's runtime.
- **Alternative:** Picovoice Porcupine.
  - Its built-in "jarvis" keyword is accurate.
  - `pvporcupine==3.0.3` is already in `requirements.txt`, unused.
  - It is proprietary, needs an AccessKey, and is free only under its personal
    tier's terms.
- **"Jarvis" vs "Hey Jarvis":** an open question. Two words give fewer false
  wakes.
- **What the detector does:**
  - In passive mode, nothing is sent to any recognizer until it fires.
  - In the active window (`ACTIVE_WINDOW_SECONDS = 30`), VAD-gated utterances go
    to the recognizer without a wake word, as today.
  - During playback, the wake word (or a dedicated "stop" model) is the barge-in
    signal (below).

### Streaming

- **Recognition:** Phase 2 keeps endpointed utterances, transcribed after the
  silence. That is simpler, works with Whisper, and today's latency is dominated
  by the 1.4 s endpoint and model calls. The endpoint shrinks instead: Silero VAD
  plus ~0.7–0.9 s silence, keeping 1.4 s after a question, where you may pause to
  think.
- **Interruption:** handled on-device by the wake-word stream, not by cloud
  partials.
- **Reply streaming** (Phase 5):
  - model tokens → first complete sentence → TTS, while the rest is generated;
  - `speech_chunks` already splits by sentence;
  - for TTS, short replies make it less important than for long answers.

### Echo handling

Measured problem: Jarvis's own voice through the speakers opens the VAD, mixes
into utterances and causes unrecognized audio (`docs/voice-session-2026-10-22.md`,
Diagnosis). The current mitigation is speakers mode (`ECHO_MODE = "speakers"`,
`handle_final`): during playback and 0.3 s after, only "Jarvis …" or "stop"
counts.

Options, in order of reliability:
1. **A headset.** No echo at all. Recommended for the benchmark recordings even if
   you use speakers day to day.
2. **Acoustic echo cancellation.**
   - The Windows communications audio path, if the laptop's audio driver offers
     echo cancellation, or a software canceller on the PCM stream with the
     playback signal as reference.
   - Python options for software AEC on Windows are immature (an uncertainty to
     test, not a recommendation yet).
3. **Keep speakers mode as the fallback.** With an on-device wake word it gets
   better:
   - "Jarvis" during playback is detected locally and stops playback at once;
   - the rest of the sentence is then recognized cleanly after playback stops.

Stop over speakers currently fires at confidence 0.35 (`stop_confidence`), a
Phase 1 known issue. The local detector replaces that threshold.

---

## 10. Technology choices

One recommendation per choice, with a one-line reason and one alternative. Versions
are deliberately not pinned here; pin them when each is adopted.

| Choice | Recommended | Why | Alternative |
|---|---|---|---|
| Wake word | **openWakeWord** | Open source, CPU, pretrained "hey jarvis", custom words trainable | Porcupine (already in requirements; built-in "jarvis"; proprietary key) |
| Voice activity detection | **Silero VAD** (ONNX) | Much better than WebRTC VAD at telling speech from noise; tiny | Keep `webrtcvad` (exists), tuned |
| Speech recognition | **faster-whisper** (CTranslate2, no torch needed) | Local, accent-robust, int8 CPU, hotwords; MIT | Google Cloud Speech-to-Text v2 with phrase hints |
| Text-to-speech | Keep **Google Cloud TTS** now; test **Kokoro** (Apache-2.0, 82M params) in Phase 5 | Works today (median 0.58 s); Kokoro is the best-sounding small local voice, if CPU speed is fine | Piper (fast on CPU, plainer voice; check its current licence) |
| Local LLM runtime | **Ollama** | One install, model management, OpenAI-style API with tool calls, GPU offload | llama.cpp `llama-server` directly (fewer moving parts, more manual) |
| Local LLM model | a current **3–4B instruct model with tool calling**, 4-bit (e.g. the Qwen 3 4B or Llama 3.2 3B class), chosen by the Phase 5 test set | The only size that fits 4 GB VRAM at speaking speed | The 7–8B class for background jobs only |
| Cloud LLM | Keep **OpenAI** (existing key and code), moved to the current SDK and a current model | No new account, smallest change | Anthropic Claude via the same `ChatModel` interface |
| Agent framework | **None**: our own ~300-line loop on native tool calling | One agent, few tools, custom permission/undo/claim rules that frameworks don't model | PydanticAI, if typed tool plumbing grows painful |
| Tool protocol for external services | Direct Python tools first; **MCP client** support when the first ready-made server is wanted (Phase 6) | Reuse existing MCP servers (filesystem, browser) instead of writing integrations | Plain HTTP APIs per service |
| Memory store | **SQLite + FTS5 + sqlite-vec** | One local file, as the reminder store already uses; keyword and vector search together | LanceDB |
| Embeddings | **fastembed** (ONNX, CPU) with a small English model (e.g. bge-small-en) | No torch, fast on CPU, private | An Ollama embedding model (one runtime, but competes for VRAM) |
| Scheduler | **Extend `ReminderService`** | Already reliable, tested, persistent, catches up after downtime | APScheduler with an SQLite job store |
| Web search | **Brave Search API** | Independent index, simple API, has news and freshness filters; check current pricing | Self-hosted SearXNG (no key, private; scraping can break) |
| Page text extraction | **trafilatura** | Mature main-text extraction for news and articles | readability-lxml |

**Deliberately not adopted:**
- multi-agent frameworks;
- a vector database server;
- LangChain;
- a GUI framework (until the memory page needs one);
- keeping `spaCy` / `torch` / `nltk` / `textblob` / `vosk` in the runtime
  dependencies. Only the unused `utils/nlp_utils.py` imports `spacy` and
  `textblob`. faster-whisper does not need torch. Removal is ROADMAP task 2.1.
