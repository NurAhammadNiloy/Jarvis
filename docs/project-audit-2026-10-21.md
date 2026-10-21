# Jarvis project audit — 21 October 2026

> Snapshot of the project as it stood before the `audit-fixes` branch. Items 1–4
> of "Make it work properly" were fixed afterwards on that branch; everything
> else describes the state at the time of the audit.

The audit was read-and-run only: no files were edited, deleted or committed. The
only effect on the project was 9 lines appended to the gitignored
`logs/conversation.jsonl` by the startup test.

A previous audit exists in `docs/project-audit-2026-10-06.md`. The source code had
not changed since then; its key checks were re-run independently and still held.
This report adds dependency age/security, the uncommitted-work risk, data privacy
and an actual startup run.

---

## 1. Purpose

**Jarvis is a hands-free, voice-controlled desktop assistant for one person on
Windows, modelled on Iron Man's J.A.R.V.I.S.** You say "Jarvis", then ask for
something. It can:

- set timers and reminders
- give the weather
- tell the time and date
- open YouTube or Google
- answer anything else using OpenAI's GPT-4o

It is clearly a personal or learning project, not a product for other people:

- The default city is hardcoded to Kokkola (`config/settings.py:2`).
- The Google credential path pointed at the author's own F: drive
  (`config/credentials.py:4`).
- There are side experiments with a room-sensor service at a private LAN address
  (`utils/api_utils.py:4`, `test_climate_control.py`), which look like a school or
  home IoT project.

The purpose is clear. What is unclear is the scope: the README promises memory,
preferences, reminder management and climate features that the running app does
not have.

## 2. Current state

**The app runs, the isolated tests pass, and the main features are unreliable.**

| Check | Result |
|---|---|
| Project venv `env/` (Python 3.12.6) | Present; `pip check` finds no broken requirements |
| `env\Scripts\python.exe -B -m pytest tests -q` | **145 passed in 3.19 s** |
| `main.py` started for 25 s | Started cleanly, reached passive mode. Background noise triggered one cloud recognition (500 ms, "unrecognized"), correctly ignored |
| API keys / credentials | `.env` has all 5 keys; the Google service-account file exists at the hardcoded F: path. Nothing secret in git history |
| Reminder NLP import | **14.6 s**: `utils/nlp_utils.py:32` loads the `en_core_web_trf` transformer at import, on the first reminder request |
| Bare `pytest` (no path) | Not run on purpose: no pytest config, so it would collect root `test_*.py` scripts that load Whisper, create cloud clients and touch the real DB at import |
| Live OpenAI / weather / YouTube / TTS calls | Not repeated, to avoid API cost. The 6 Oct audit found all four working |

These bugs reproduced with stub services and a fixed clock:

| Input | Result |
|---|---|
| "remind me to call mom **tomorrow** at 9 pm" | Scheduled **today** 21:00 |
| "remind me to pay rent on **December 20** at 9 am" | Scheduled **tomorrow** 09:00 |
| "remind me to take a break **in one hour**" | Time extracted as `"me"`, scheduled for **midnight** |
| "what are my reminders" | Treated as creating a new reminder |
| "update my preference" / "explain runtime errors" | Answers with the **date** / the **time** |
| "tell me about the play Hamlet" | Searches YouTube |
| "weather in Helsinki / Washington / Athens" | City becomes `helski` / `washgton` / `hens` |
| "what's the weather like today?" (README's own example) | City becomes `like today` |
| "day after tomorrow" | Gives tomorrow's date |
| "set an alarm for 7am" | Falls through to ChatGPT; there is no alarm feature |
| "unpause the pasta timer" | Pauses it |
| "twenty five minutes" / "-5 minutes" | 5 minutes / 5 minutes, with label `-5` |
| "open google" when the browser fails | Still says "Opening Google." with status `handled` |

## 3. Strengths (worth keeping)

- **Command boundary.** `core/command_engine.py` separates parsing
  (`understand_query`) from execution (`execute_command`). It returns typed
  `CommandResult`s (`core/command_result.py`), and services can be swapped for
  fakes (`core/command_services.py`). This is the foundation to build on.
- **Voice pipeline.**
  - Capture, voice detection, recognition, confidence policy and speech output are
    separate and testable (`core/voice_capture.py`, `voice_runtime.py`,
    `voice_policy.py`, `speech_output.py`).
  - Speech can be interrupted and cancelled.
  - Stale transcripts can't stop a newer reply (`core/assistant.py:117`).
- **The AI model can't trigger actions directly.** `core/dialogue.py` lets the
  model only *propose* a command. Proposals are checked against an allowlist
  (line 75) and run only after a clear spoken "yes". Most hobby assistants skip
  this.
- **Structured event log.** `core/conversation_log.py` writes thread-safe
  JSON-lines events and never crashes the app if logging fails.
- **Tests and docs for the new design.** 145 fast tests with no hardware or
  network, plus `docs/command-boundary.md` and `docs/voice-interaction.md`.
- **No secrets committed.** Keys load from `.env` through `config/api_keys.py`.

## 4. Weaknesses

### Bugs and broken features

- **Intent routing is plain substring matching** (`core/intent_classifier.py:1-62`),
  checked in order:
  - `"remind"` wins over everything (line 4).
  - `"date"` matches "up*date*" (line 51), `"time"` matches "run*time*" (line 49),
    `"play"` matches any use of the word (line 53), `"continue"` means timer
    (line 26).
- **Reminders lose their date.** The extractor keeps only the time-of-day text.
  `core/command_engine.py:73` passes that string on, `core/reminder_manager.py:43`
  parses it again, and line 47 pushes past times to tomorrow.
- **Reminder lifecycle** (`core/reminder_manager.py`):
  - The `threading.Timer` handles are discarded, so delete/snooze can't cancel an
    alert (lines 84-86, 135-152).
  - Reminders are identified by task text, so completing one completes every
    reminder with the same name (lines 107-112).
  - Recurring reminders aren't restored after their first date passes, because
    the date check wraps both branches (line 31).
  - "Weekly" means every 7 days from now, not on a weekday (line 101).
  - "Hourly" ignores the requested time (line 103).
- **Weather city extraction** uses `str.replace` on fragments like `"in"`, `"at"`
  and `"the"` (`core/command_engine.py:33-34`).
- **Date check order:** "tomorrow" is tested before "day after tomorrow"
  (`core/command_engine.py:97-102`).
- **Timers** (`core/smart_timer.py`):
  - "pause" is matched before "unpause" (lines 917-922).
  - When a named timer isn't found, the command falls back to whichever single
    timer exists (lines 686, 743, 799).
  - A suggested duration asks "Is that okay?" but starts the timer immediately
    (line 436).
  - Elapsed time uses the wall clock (line 83), so changing the system clock
    breaks it.
- **Failures reported as success** (`core/command_engine.py`):
  - Browser failures are ignored (line 105).
  - Weather error strings come back as `handled` (line 85).
  - "status" always replies "All systems are fully operational" (line 108).
- **No network timeouts:**
  - `core/weather_service.py:19, 36, 183, 327, 422-423`
  - `core/chatgpt_service.py:70`
  - YouTube (`core/youtube_service.py:14`)

  Each of these runs synchronously inside `process_recognition`
  (`core/assistant.py:134`), so one slow API freezes the conversation.
- **The model's JSON reply is parsed without JSON mode**
  (`core/chatgpt_service.py:32`). If GPT wraps its reply in a code fence, every
  turn hits the "couldn't work out that follow-up" fallback
  (`core/dialogue.py:86-90`). Found by reading the code, not triggered.

### Unfinished or advertised-but-missing

- **Memory and preferences:** `core/memory_manager.py` is only used by the legacy
  `full_test.py:4`. The running app never stores or reads memory, though the
  README advertises it (lines 33-35, 196-200).
- **Reminder list/delete/snooze** are claimed in the README (line 210). Only
  listing exists, and the router can't reach it.
- **Alarm, climate control, web search:** not implemented.
- **Three separate conversation histories** that don't share state: Dialogue
  history, `_conversation_history` in chatgpt_service, and conversation_context.

### Dependencies

- `requirements.txt` is a `pip freeze` of 139 packages, not a curated list:
  - Several are unused by the app, including `pvporcupine`, `vosk`, `nltk`,
    `matplotlib`, `playsound`, `simpleaudio`, `noisereduce`, `Js2Py`, `pipwin`
    and `dotnet`.
  - Packages the env actually needs are missing, e.g.
    `spacy-curated-transformers` for the README's `en_core_web_trf`. Meanwhile the
    file pins `en_core_web_sm`.
- **`openai==0.28.0` is the legacy 2023 SDK** (latest is 3.x).
  `openai.ChatCompletion` doesn't exist in modern versions, and `gpt-4o` is
  hardcoded (`core/chatgpt_service.py:15`, `:71`).
- Most packages are about two years old. Several pinned versions have published
  security advisories; run `pip-audit` to confirm:
  - `requests` 2.32.3
  - `urllib3` 2.2.3
  - `aiohttp` 3.10.10
  - `Jinja2` 3.1.4
  - `torch` 2.5.1 (the `torch.load` warning appears at startup)
  - `h11` 0.14.0
  - `protobuf` 5.28.3
  - `setuptools` 75.3.0
  - `Js2Py` 0.74 (no fixed version exists)

  Exposure is limited, since this is a local desktop app.

### Security and privacy

- **`data/` isn't gitignored** (`.gitignore`). It contains `memory.db` (260
  conversation rows) and `reminders.json` (personal reminders). One `git add .`
  would commit them.
- **The Google key path is hardcoded and loaded at import**
  (`config/credentials.py:4-5`), so the app crashes on any other machine. `.env`
  already defines `GOOGLE_CLOUD_CREDENTIALS`, but nothing reads it.
- **Every noise is sent to Google.** The wake word is checked *after* cloud
  transcription (`core/assistant.py:50-53`); the startup run showed noise
  triggering a cloud call. That's a privacy and cost concern.
- **Transcripts are logged without limit.** `logs/conversation.jsonl` grows
  forever with no rotation.

### Version control, tests and docs

- **The biggest risk: almost all the good work is uncommitted.** The last commit
  is from Dec 2024. The current changes are about 2,600 lines in 15 tracked files
  plus about 30 untracked files: the whole voice pipeline, command engine, tests
  and docs.
- **The tests pass but miss the real bugs.** They cover the architecture, not the
  reproduced input-to-action failures. There is no regression corpus for
  intents, reminders or cities.
- **No pytest config.** A bare `pytest` imports the root experiment scripts, which
  have side effects:
  - `test_recogination.py:13` loads a Whisper model.
  - `test_memory.py:4` opens the real DB.
- **README problems:** it links a `LICENSE` that doesn't exist (line 230), and its
  clone URL is a placeholder (line 104).

### Confusing structure

- **Dead code alongside live code:**
  - backups: `core/weather_service_backup.py`, `utils/nlp_utils_backup.py`
  - an older timer implementation: `core/timer_manager.py`
  - an empty file: `utils/response_variety.py`
  - legacy `core/intent_handler.py`, used only by `full_test.py`
  - `utils/schedule_utils.py`
- **An oversized NLP module:** `utils/nlp_utils.py` is 1,413 lines, and the app
  uses only `extract_reminder_info` from it.
- **Mixed folder:** experiment scripts sit in the root next to `main.py`.

---

## Recommendations: make it work properly

In priority order:

1. **Protect the work** *(quick fix)*: add `data/` to `.gitignore`, then commit
   the current tree, ideally on a branch.
2. **Make setup portable** *(quick fix)*:
   - Read the credential path from `GOOGLE_CLOUD_CREDENTIALS` in
     `config/credentials.py`.
   - Add a `.env.example`.
   - Add `pytest.ini` with `testpaths = tests`.
3. **Add network timeouts** *(quick fix)* to every `requests` call, the YouTube
   client and `get_chatgpt_response`.
4. **Fix the small parsing bugs** *(quick fix)*:
   - date order ("day after tomorrow" before "tomorrow")
   - "unpause" before "pause"
   - the timer fallback should apply only when no label was given
   - check the `webbrowser.open` return value
   - remove or implement the fake "status" reply
5. **Rewrite intent routing** *(medium)*:
   - Use word-boundary patterns that match the operation first (list/delete
     reminder before create).
   - Extract the city as a span.
   - Add explicit `list/delete/snooze_reminder` and `alarm` intents, or remove
     them.
   - Lock it down with a table-driven regression test built from the inputs in
     section 2.
6. **Rebuild reminder scheduling** *(medium–large)*:
   - Parse the full datetime once and pass the `datetime` object through. Don't
     re-parse the string.
   - Give each reminder a stable ID.
   - Keep timer handles so reminders can be cancelled.
   - Restore recurring reminders correctly, and store them in SQLite rather than
     JSON.
   - Drop the transformer model for a regex + `dateparser` path. This also
     removes the 14.6 s stall.
7. **Upgrade dependencies** *(medium)*:
   - Write a short hand-curated `requirements.txt` from the packages that are
     actually imported.
   - Move to `openai>=1.x` with JSON-mode output.
   - Upgrade the packages with advisories.
   - Run `pip-audit`.
8. **Run slow work off the conversation loop** *(medium)*: do provider calls in a
   worker with a request ID, so "stop" and new requests still work while one is
   pending.
9. **Wire up memory or remove it** *(medium)*: either connect `memory_manager` to
   the dialogue (store exchanges, retrieve relevant ones) or take the claim out
   of the README.
10. **Clean up** *(quick to medium)*:
    - Delete the backups and dead modules.
    - Move the experiment scripts to `experiments/`.
    - Unify the three conversation histories into one session object.
    - Fix the README.
11. **On-device wake word** *(large)*: a local wake-word gate (e.g. openWakeWord or
    Porcupine) so idle audio never leaves the machine.

## Recommendations: possible directions

**A. A reliable personal desk assistant (closest to today).** Narrow scope to
timers, reminders, weather, time/date and chat, and make those dependable.

- Main work: items 1–9 above, plus a spoken-command test corpus and a measured
  success rate.
- Drop the YouTube, Google and climate extras, or keep them as they are.

**B. A privacy-first, offline-capable assistant.** Building on the clean voice
pipeline:

- local wake word
- local speech-to-text (Whisper or Vosk, both already experimented with)
- local TTS (e.g. Piper)
- a local LLM via Ollama, with cloud as an optional fallback

Main work: swap the provider adapters behind the existing interfaces, plus
performance tuning on CPU. The command boundary and dialogue safety design carry
over unchanged.

**C. A voice front-end for a smart room/home.** Turn the climate experiments into
a real feature:

- connect the room-sensor API (`utils/api_utils.py`) or Home Assistant as a
  command service
- add device-control intents with the existing propose → confirm → execute flow

Main work: a device/service registry, a config-driven sensor endpoint instead of
the hardcoded LAN IP, and a confirmation policy for actions with physical effects.

## Recommended next step

Commit the current work first, after adding `data/` to `.gitignore`. At the time
of this audit the best parts of the project existed only on one disk. Then do the
quick fixes (items 2–4) in one sitting. After that, choose a direction: A is the
natural default because it turns what already exists into something you can
trust. Whichever you pick, the first real work is item 5 together with a
table-driven test of the failing phrases in section 2. Intent routing and
reminder parsing are behind most of the bad behaviour, and the architecture
around them is already sound.
