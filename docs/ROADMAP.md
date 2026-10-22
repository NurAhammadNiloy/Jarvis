# JARVIS roadmap

Status: plan, 22 October 2026. It orders the work for [VISION.md](VISION.md); the
design it builds is in [ARCHITECTURE.md](ARCHITECTURE.md). Phases 2 and 3 are
broken into tasks of about one work session each. Later phases are outlines, to be
detailed when the phase before them is done.

Every phase ends with something that works better in daily use. Every task keeps
the full test suite green (`env\Scripts\python.exe -B -m pytest -q`; 729 tests
on 22 Oct).

---

## Changes to the phase order, and why

| Vision phase | Roadmap phase | Change |
|---|---|---|
| 1 Strengthen the foundation | **1 Foundation** (done) | Its leftover cleanup moves into Phase 2. |
| part of 4 (speech recognition) | **2 Hearing reliably** | **New, pulled forward.** The 22 Oct logs show recognition is the main weakness:<br>• the wake word is misheard ("nervous", "Punjabi", "service", "there is"), so commands are silently ignored (87 `no_wake_word` ignores that day);<br>• 56% of what is sent to Google is background noise (325 of 577 final recognitions came back "unrecognized");<br>• stop takes 2–4 s.<br>An agent that mishears you is worse than a regex that mishears you, so this comes first. |
| 2 Agentic intelligence | **3 Central agent and first tools** | Same goal, with two additions:<br>• **permissions v1**, because the first new tools are designed against it;<br>• **web search / news**, the most-requested missing capability. |
| 3 Persistent memory | **4 Memory** | Unchanged. It comes after the agent, because retrieval needs a consumer that can use it and extraction needs a model interface. The agent phase already logs every tool call, so memory can be backfilled from the logs. |
| 4 Local AI and natural communication | **5 Local models and natural voice** | Narrowed: speech recognition moved to Phase 2. What remains is local LLM routing, local TTS, reply streaming and offline mode. The hardware sets the limits: a 4 GB GPU means 3–4B local models only (ARCHITECTURE section 1). |
| 5 Real-world task execution | **6 Computer and services** | Unchanged in substance. It depends on Phase 3 permissions. |
| 6 Proactive behaviour | **7 Proactive** | Unchanged, but simple scheduler pieces arrive earlier: repeating alarm ring in Phase 3, the nightly memory job in Phase 4. |
| 7 Digital coworker | **8 Digital coworker** | Unchanged. |

---

## Phase 1 — Foundation (done)

Done on `main`, as of 22 October 2026:
- audit fixes;
- the regex intent router (`core/intent_classifier.py`);
- the reminder and alarm engine on SQLite (`core/reminder_store.py`,
  `core/reminder_manager.py`);
- one conversation state (`core/conversation_state.py`);
- act-first with undo;
- speakers mode;
- the active listening window (30 s);
- live transcripts;
- natural replies in `core/phrases.py`.

See `docs/voice-session-2026-10-22.md` and the git history.

**Lessons that shape the plan:**
- **Hearing is the bottleneck**, not understanding.
  - Most failed turns on 22 Oct started with a misheard wake word, background
    noise, or a misheard word ("add" → "at", "Hamlet" → "helmet").
  - The router and parsers mostly did the right thing with what they were given.
- **Live information is the most-requested missing capability.**
- **Some things should not get more regex: they are agent work.** Open-ended
  follow-ups, marking reminders done by voice, repeating alarm rings, and
  music/browser control.

**Carried into Phase 2:**
- dependency upgrade (task 2.1, 2.2);
- moving slow API calls off the conversation loop (2.12);
- dead-code cleanup (2.1);
- README/LICENSE (2.14);
- the known small issues (2.13; stop over speakers in 2.10).

---

## Phase 2 — Hearing reliably

**Goal:** Jarvis hears "Jarvis" and the command that follows reliably and stops
within half a second, and nothing reaches the cloud until you address it.

**Deliverables:**
- a cleaned dependency set;
- the current OpenAI SDK;
- a labelled speech test set and benchmark harness;
- an on-device wake word;
- Silero VAD;
- local and cloud recognizers behind one interface, chosen by measurement;
- on-device barge-in and stop;
- an echo decision;
- network calls off the conversation loop;
- the four known small issues fixed;
- an accurate README and LICENSE.

**Phase done when** (one 30-minute live session over speakers, at least 40
addressed commands, checked against the log):
- wake word missed ≤ 1 in 20;
- intent correct ≥ 95% of addressed commands;
- 0 recognizer calls in passive mode without a wake event;
- median stop latency ≤ 0.5 s;
- the full test suite passes.

**Risks:**
- **Whisper gives no alternatives or calibrated confidence.** The act-first
  planner and the confidence gate rely on both, so recalibration (2.9) may take
  longer than one session.
- **Wake word choice.** openWakeWord's pretrained model is "hey jarvis", and a
  custom single-word "jarvis" model may give more false wakes.
- **Echo cancellation on Windows** may not be practical. Speakers mode then stays.

**Dependencies:** the decisions on wake phrase, speech budget and audio recording
(open questions 2–4).

| # | Task (≈ one session) | Done when |
|---|---|---|
| 2.1 | **Dependency cleanup.**<br>• Split `requirements.txt` into runtime and dev.<br>• Remove unused heavy packages: `spacy`, `en_core_web_sm`, `torch`, `nltk`, `textblob`, `vosk`, `Js2Py`, `matplotlib`, `pipwin`, `dotnet`, `ffmpeg` (the PyPI stub), and others no runtime module imports. Verify first with an import scan. faster-whisper does not need torch, so torch can go.<br>• Move the modules the running app never imports (`core/intent_handler.py`, `core/timer_manager.py`, `core/weather_service_backup.py`, `core/memory_manager.py`, `utils/nlp_utils*.py`, `utils/response_variety.py`, `utils/schedule_utils.py`, `utils/text_utils.py`, `utils/api_utils.py`, root `test_*.py`, `full_test.py`, `populate_memory.py`, `clear_memory.py`) out of the tree, after checking each with you.<br>• Run `pip-audit` and upgrade packages with advisories. | A fresh virtualenv installs from the runtime file; `python main.py` starts; the full suite passes; `pip-audit` reports no unresolved high-severity advisory (or each one is written down with a reason). |
| 2.2 | **OpenAI SDK upgrade.** `openai==0.28` → the current 1.x client in `core/chatgpt_service.py` (`resolve_dialogue`, `get_chatgpt_response`), with the same prompts, JSON mode and timeouts. The model name becomes a setting. | Tests pass with the updated mocks; a live check of 5 dialogue turns behaves as before. |
| 2.3 | **Speech test set and harness.**<br>• A recording script prompts phrases and saves WAV plus the expected text to `data/speech-tests/` (gitignored). Phrases come from the logs: wake words that were misheard, "add 5 minutes to the tea timer", "Hamlet", yes/no/cancel, stop, reminders with times, names.<br>• Also record 30 minutes of background (TV, music, a video call).<br>• A benchmark script runs any `Recognizer` or `WakeWordDetector` over the set and reports: word error rate, intent match (`route` + `understand_query` against the expected text), wake hits and misses, false wakes per hour, and latency. | ≥ 150 labelled clips (≥ 50 starting with "Jarvis", ≥ 30 short answers, ≥ 20 "stop") and 30 min of background audio; the harness prints a report table. |
| 2.4 | **Baseline:** run today's recognizer (free Google web API) and today's text wake check over the set. Write `docs/speech-benchmark.md`. | The baseline numbers are committed; every later speech change is compared against them. |
| 2.5 | **On-device wake word** (openWakeWord, behind a setting).<br>• The capture thread scores each frame.<br>• In passive mode, an utterance is only recognized after a wake event.<br>• The event is logged as `wake_detected`.<br>• In the active window, nothing changes. | On the set: misses ≤ 5%, false wakes ≤ 1 per hour of background; in a 30-min live run, no recognizer calls in passive mode without a wake event. |
| 2.6 | **Silero VAD** in the `Endpointer` (behind a setting), with endpoint silence 0.8 s (1.4 s after a question). | On the set: no clipped words at pauses ≤ 0.6 s; live: "unrecognized" falls from 56% to < 10% of recognitions; fast-path time to reply drops by ≥ 0.4 s. |
| 2.7 | **faster-whisper recognizer** (CPU int8; `small.en`, `distil-small.en`; `large-v3-turbo` on GPU if the CUDA libraries install cleanly).<br>• Hotwords: "Jarvis", the command verbs, and the names in your reminders and timers.<br>• Confidence comes from `avg_logprob` / `no_speech_prob`.<br>• `Recognition.source` is set. | Benchmark rows for each model size, with latency. |
| 2.8 | **Google Cloud Speech-to-Text v2 recognizer** with phrase hints (only if open question 3 allows it). | Its benchmark row, with an estimated monthly cost at your usage. |
| 2.9 | **Choose and recalibrate.** Pick the recognizer from 2.4–2.8. Set per-source thresholds in `ConfidenceGate` and the 0.5 action floor in `_plan`, and decide how `_plan` works when there are no alternatives. Update the regression tests that encode Google confidences. | Intent accuracy on the set ≥ 95% and better than the baseline; false actions on noise = 0; the full suite passes. |
| 2.10 | **On-device barge-in and stop.**<br>• A wake event or a local "stop" during playback stops speech at once. The local "stop" is either a custom openWakeWord model or the local recognizer on short barge-in windows.<br>• This replaces the cloud partials (`barge_interval_ms` 800, `barge_window_ms` 1800) and the 0.35 stop threshold over speakers. | Over speakers, 20 trials: median ≤ 0.5 s from the end of "stop" to `speech_cancel_requested`; 0 false stops in 30 min of Jarvis speaking. |
| 2.11 | **Echo.** Test the headset; the Windows communications-mode echo cancellation, if the driver offers it; and speakers mode with the new wake word. Measure each on 20 overlapped answers. | A decision with numbers in `docs/speech-benchmark.md`; `ECHO_MODE` default set from it. |
| 2.12 | **Slow calls off the conversation loop.** Weather, YouTube and model calls run on a worker. The loop keeps handling "stop", "undo" and new commands; a newer request supersedes a stale result. | A test with an 8 s fake weather call shows a "stop" handled within 0.1 s, and no stale reply after a newer command. |
| 2.13 | **Known small issues**, each with a regression test from a logged transcript:<br>• relative times are anchored at proposal, not confirmation (keep the relative expression and resolve it when the request runs);<br>• a pending "What time?" slot captures an unrelated sentence that contains a time (route the answer first, as `_fill_task` does);<br>• "not the tea timer" alone starts a timer (a negation never starts a timer). | Three new tests pass; the old ones still pass. |
| 2.14 | **README and LICENSE.**<br>• The README lists current commands, setup (including the wake word and recognizer) and the speakers/headset choice.<br>• Add the LICENSE file the README already links to, with MIT as it states (open question 13). | The README matches the code; the LICENSE exists. |

---

## Phase 3 — Central agent and first tools

**Goal:** anything the fast path can't handle goes to one central agent. It plans,
calls tools through a permission gate, checks the results, and answers with
sources, starting with live web and news.

**Deliverables:**
- the `ChatModel` interface and usage ledger;
- a tool registry wrapping today's commands, with read-back verification;
- permissions v1 (tiers, approvals, grants);
- the agent loop replacing `Dialogue`'s model call;
- `web.search` and `news.headlines`;
- media keys;
- marking reminders done;
- repeating alarm rings;
- open-ended follow-ups;
- an agent evaluation set.

**Phase done when:**
- **Tools:** on the evaluation set (40 requests), the right tool and arguments in
  ≥ 90%.
- **Claims:** 0 replies claiming an action that isn't in the journal.
- **Approvals:** 0 tier-1 calls run without approval.
- **News:** "what's going on in the universe now" / "latest news about X"
  answered with a dated, named source in ≥ 8 of 10 live trials.
- **Latency:** median time to first audio ≤ 3 s for one-tool agent turns.
- **Fast path:** no slower than at the end of Phase 2.

**Risks:**
- **Latency:** each tool round trip adds about 1–2 s.
- **Prompt injection** from web pages, mitigated by the derived-context rule.
- **Search API cost and terms.**
- **Scope creep:** keep the tool list to the one in this phase.

**Dependencies:**
- Phase 2.2 (SDK);
- the search provider decision (open question 6);
- the cloud budget (open question 1).

| # | Task (≈ one session) | Done when |
|---|---|---|
| 3.1 | **Models interface.** `core/models/`: the `ChatModel` protocol, an OpenAI provider (tools, JSON mode, timeouts), and a usage ledger (tokens and estimated cost per call, in SQLite). `chatgpt_service` calls go through it. | Tests with a fake model; the ledger shows a day's spend; behaviour unchanged. |
| 3.2 | **Tool registry.** `ToolSpec`, `ToolResult`, with existing commands as tools (`reminders.*`, `alarms.*`, `timers.*`, `weather.*`, `time`, `date`, `youtube.play`, `browser.open`), delegating to `CommandServices`. The fast path keeps `execute_command` and the `CommandResult` interface, and calls the same executors. | Every tool has a JSON schema and a test; the full suite passes unchanged. |
| 3.3 | **Read-back verification** in the reminder, alarm and timer executors: after acting, re-read the state; a mismatch is a failed result. | A test with a store that silently drops writes reports failure and Jarvis says so. |
| 3.4 | **Permissions v1.**<br>• `core/permissions.py`: the tier table, `check()`, the `derived`-context rule, and `data/permissions.db` (grants).<br>• `AwaitingApproval` in the conversation state.<br>• Readback built from the arguments in code.<br>• `permission_decision` log events. | Tests: a tier-1 call never runs without "yes"; a grant covers only its scope; a derived call is raised to tier 1; tier 2 is refused even with a grant. |
| 3.5 | **Agent loop v1.**<br>• `core/agent/` replaces `Dialogue.turn`'s model call for chat, unparsed and compound requests.<br>• It keeps the recognition repair context (alternatives) and the prompt style from `resolve_dialogue`.<br>• At most 4 steps; "Checking." after 1.5 s.<br>• The composer states journal facts in `phrases.py` wording; `without_action_claims` stays as a backstop. | Scripted tests with a fake model:<br>• a claimed action without a tool call is removed;<br>• a failed tool is reported as failed;<br>• an approval pause resumes correctly;<br>• the old dialogue regression tests still pass. |
| 3.6 | **`web.search` and `news.headlines`** (Brave Search API by default), plus `web.read` (fetch and extract with trafilatura) as a tier-0 tool. Spoken answers name the source and its age ("BBC, two hours ago"). | 10 live questions (5 news, 5 current facts): ≥ 8 answered with a dated source; on no results or an error, Jarvis says so and doesn't guess. |
| 3.7 | **`media.control`** (Windows media keys: play/pause/next/previous). "Stop the music" and "pause YouTube" use it instead of the current "I can't control YouTube playback yet." | A manual test pauses and resumes YouTube in the browser; tests for the routing. |
| 3.8 | **Reminders and alarms:**<br>• a `reminders.complete` tool ("I did it", "mark the dentist one done");<br>• alarm rings repeat (every 30 s for up to 5 min) until "stop" or "snooze", as an `alarm_ring` job in the extended scheduler. | Tests for both; a live alarm keeps ringing until stopped. |
| 3.9 | **Open-ended follow-ups** through the agent with recent turns: "and tomorrow?" after weather; "what about the second one?" after a list; "tell me more". | 10 scripted follow-up cases, ≥ 9 correct against the live model. |
| 3.10 | **Agent evaluation set.**<br>• 40 text requests with the expected tool calls, arguments and outcome. Sources: the logs, the vision examples, and failure cases (ambiguous, unsupported, injection attempts in fake web pages).<br>• It runs against the live model with tools in dry-run mode and writes a report. | The report meets the phase "done when" numbers; it is re-run after every agent change. |

---

## Phase 4 — Memory (outline)

**Goal:** Jarvis remembers what matters across weeks, says where a memory came
from, keeps it current, and lets you see, correct and delete it.

**Deliverables:**
- `data/memory.db` with the schema in ARCHITECTURE section 7;
- `memory.remember`, `memory.forget` and `memory.search` tools;
- per-session episode summaries;
- extraction of facts, decisions, tasks and preferences after each session;
- hybrid retrieval (FTS5 + sqlite-vec + recency + links) in the agent loop;
- contradiction handling (supersede vs dispute);
- a nightly consolidation job;
- the memory CLI;
- a backfill from `logs/conversation.jsonl`.

**Done when:**
- **Retrieval:** on a 30-question test set built from real sessions ("what did we
  decide about X", "when is assignment 3 due", "what was that thing yesterday",
  "what's my default city"), ≥ 27 correct, each with a date and source.
- **Forgetting:** "Forget X" removes X from every search result and episode (test).
- **Corrections:** a corrected fact is never returned in its old value (test).
- **Extraction:** precision ≥ 90%, judged by you on 50 extracted items.
- **Speed:** retrieval adds ≤ 300 ms to an agent turn.

**Risks:**
- noisy extraction filling memory with trivia;
- private content sent to the cloud during extraction (routing rule: private
  stays local);
- wrong reference resolution ("that thing").

**Dependencies:** Phase 3 (agent, model router); open questions 7 and 8.

## Phase 5 — Local models and natural voice (outline)

**Goal:** routine language work and speech run on this laptop where they're good
enough, and the conversation flows faster and more naturally.

**Deliverables:**
- **5.1 Measure local LLMs**: Ollama with models on D:/E:; 3B and 4B candidates;
  tokens/s, first token and VRAM, plugged in and on battery.
- An Ollama provider in `core/models/`.
- A local model for misheard-command repair and memory extraction, where it passes
  their test sets.
- An offline mode.
- **5.4 Local TTS trial**: Kokoro vs Piper vs Google; latency and your rating.
- Reply streaming: the first sentence is spoken while the rest is generated.
- Smoother turn-taking, with a semantic end of turn if the measurements justify it.

**Done when:**
- **Offline:** with the network off, the fast path, memory search and local
  answers work, and Jarvis says it's offline.
- **Local tasks:** each passes its test set (repair ≥ 90% of the cloud model's
  score).
- **Speed:** first audio for long answers ≤ 1.5 s after the model starts.
- **Cost:** cloud spend down ≥ 30% from the Phase 3 ledger at similar usage.

**Risks:**
- 4 GB of VRAM shared with the desktop and possibly Whisper;
- 3–4B quality;
- local TTS speed on the CPU.

**Dependencies:** Phases 2–4; the hardware (ARCHITECTURE section 1).

## Phase 6 — Computer and services (outline)

**Goal:** Jarvis prepares real results from your files, browser and services
under the permission model.

**Deliverables:**
- **Files:** `files.*` limited to granted folders; writes go to Jarvis's own
  output folder unless approved.
- **Documents:** `documents.*` (read and create notes and plans).
- **Browser:** automation through Playwright, or a browser MCP server.
- **Services:** calendar; the university LMS (open question 5); MCP client support
  for ready-made servers.
- **Long content:** approval readbacks shown on screen.

**Done when:**
- **Vision example:** "check my university assignments, find what's unfinished,
  organize everything by deadline, and prepare a plan for this week" produces a
  correct plan document from the real LMS in 3 consecutive weekly runs (deadlines
  match the LMS).
- **Approvals:** every tier-1 action was approved.
- **Audit:** the audit log is complete.

**Risks:**
- LMS access (API vs scraping, login with MFA);
- browser automation is brittle;
- prompt injection from documents and pages.

## Phase 7 — Proactive (outline)

**Goal:** Jarvis notices what needs attention and acts within what you've
authorized, without being intrusive.

**Deliverables:**
- **Scheduler:** the general jobs table and event handler.
- **Monitors:** LMS changes, deadlines approaching, tasks idle.
- **Routines** with approved hashes and grants.
- **Notification policy:** urgency, quiet hours, at most N interjections per hour,
  speaking only when you're present.
- **Morning and evening briefings** if wanted.

**Done when:**
- **Safety:** 2 weeks of routines with 0 unauthorized actions.
- **Volume:** ≤ 5 unprompted interjections a day on average.
- **Usefulness:** you rate ≥ 80% of the proactive notices useful (a quick
  "useful / not useful" voice reply after each).
- **Deadlines:** a missed-deadline test scenario is caught 3 days ahead.

**Risks:** annoyance; false alarms from monitors; routines drifting from what you
approved, mitigated by the hash check.

## Phase 8 — Digital coworker (outline)

**Goal:** Jarvis carries multi-day tasks: it plans them, works on them in the
background, checks progress, recovers from failures, and reports.

**Deliverables:**
- persistent agent tasks with checkpoints and resumable state;
- a task board you can query by voice ("what are you working on?");
- failure detection and retry/escalation;
- progress reports;
- specialized sub-agents only where measurement shows the single agent failing.

**Done when:**
- **Completion:** a 3-day task (e.g. "keep my thesis reading list up to date and
  summarize new papers each morning") runs to completion with ≤ 2 interventions
  from you.
- **Recovery:** an injected tool failure is detected and recovered or escalated
  (test).

**Risks:** cost of long-running model use; trust in background work without
oversight.

---

## Where the Phase 1 leftovers go

| Item | Task |
|---|---|
| Dependency upgrade (openai SDK, advisories, unused spaCy/torch; torch is not needed by faster-whisper) | 2.1, 2.2 |
| Slow API calls off the conversation loop | 2.12 |
| Dead-code cleanup | 2.1 |
| README / LICENSE | 2.14 |
| Relative times anchored at proposal, not confirmation | 2.13 |
| Pending "What time?" slot captures an unrelated sentence with a time | 2.13 |
| Stop at 0.35 confidence over speakers | 2.10 |
| "not the tea timer" alone starts a timer | 2.13 |
| Open-ended follow-ups | 3.9 (agent) |
| Marking reminders done by voice | 3.8 (agent tool) |
| Repeating alarm ring | 3.8 (scheduler job) |
| Music / browser control | 3.7 (media keys); browser automation in Phase 6 |

---

## Open questions (your decisions)

**Decided on 22 October 2026; see [DECISIONS.md](DECISIONS.md).** Changes from the
defaults below:
- the microphone is wired headphones with a mic (headset mode);
- the course system is Itslearning, with the timetable in Tuudo; integration
  options are to be investigated in Phase 6.

The table is kept as the record of what was asked.

Each one has the default I'd use if you don't decide otherwise.

| # | Question | Recommended default |
|---|---|---|
| 1 | **Monthly cloud budget** (LLM + speech + search) | **€15/month** hard cap, with a spoken warning at 80%. Above the cap, only tasks you approve use the cloud. |
| 2 | **Wake phrase:** "Jarvis" or "Hey Jarvis" | **"Hey Jarvis"** first (pretrained, fewer false wakes); train a single-word "Jarvis" model only if you find it awkward after a week. |
| 3 | **May speech go to a paid cloud recognizer** (Google Cloud STT v2) if it wins the benchmark? | **Yes, up to €3/month**, only after the on-device wake word, with local faster-whisper preferred when within 2 points of accuracy. |
| 4 | **Record labelled audio of your voice** for the speech benchmark | **Yes**, stored only in `data/speech-tests/` (gitignored), deletable any time, never uploaded. |
| 5 | **Which services to connect, in which order** (which LMS does your university use: Moodle, Canvas, other? Google or Outlook calendar? e-mail?) | **Web search (Phase 3) → calendar → LMS (Phase 6) → e-mail read-only.** Sending e-mail is always tier 1. |
| 6 | **Search provider** | **Brave Search API**; SearXNG if you prefer no third-party key. |
| 7 | **Privacy limits for the cloud model** | Conversation text: yes. Memory items and files marked private: never without per-request approval. Documents from granted folders: only excerpts needed for the request. |
| 8 | **Memory capture:** automatic extraction or only explicit "remember that" | **Automatic for normal items, with a weekly spoken digest** ("This week I learned 12 things; want to hear them?"). Health, money and relationships are kept only when you say "remember". |
| 9 | **Autonomy ceiling for routines** | Tier 0 only (read, check, remind, prepare drafts in Jarvis's folder). Nothing sent, deleted or submitted without you, until Phase 7 has 2 clean weeks. |
| 10 | **Microphone setup** | Keep **speakers** day to day; use a **headset for the benchmark recordings**; revisit after task 2.11. |
| 11 | **Cloud LLM provider** | **Stay with OpenAI** (current key) behind the `ChatModel` interface; reconsider only if the evaluation set shows a clear gap. |
| 12 | **Where local models live and GPU sharing** | Models on **D:** (`OLLAMA_MODELS`); accept closing GPU-heavy apps (or turning off browser hardware acceleration) for local-LLM use. |
| 13 | **Licence** | **MIT**, as the README already states. |
| 14 | **Languages** | **English only** for now; names in other languages added as recognizer hints. |
| 15 | **Encrypting `memory.db`** | **No** at first (Windows account protection); revisit before connecting e-mail or documents. |
