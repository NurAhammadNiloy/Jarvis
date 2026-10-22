# Decisions

Answers to the open questions in [ROADMAP.md](ROADMAP.md#open-questions-your-decisions),
recorded on 22 October 2026. Each one changes only by a new dated entry here.

| # | Question | Decision |
|---|---|---|
| 1 | Monthly cloud budget (LLM + speech + search) | **€15/month hard cap, spoken warning at 80%.** May be raised later. Above the cap, only tasks you approve use the cloud. |
| 2 | Wake phrase | **"Hey Jarvis"** first (pretrained model); a single-word "Jarvis" model only if "Hey Jarvis" feels awkward after a week. *(default accepted)* |
| 3 | Paid cloud speech recognition if it wins the benchmark | **Yes, up to €3/month**, only after the on-device wake word; local faster-whisper preferred when within 2 points of accuracy. *(default accepted)* |
| 4 | Recording labelled audio of your voice for the benchmark | **Yes**, only in `data/speech-tests/` (gitignored), deletable any time, never uploaded. *(default accepted)* |
| 5 | Services to connect, and the course system | **Order: web search (Phase 3) → calendar → course system (Phase 6) → e-mail read-only.** Sending e-mail is always tier 1.<br>**Course system:** courses and assignments are in **Itslearning**, and the timetable is in the **Tuudo** mobile app.<br>**When Phase 6 starts:** investigate how to integrate both: an official API, a calendar/iCal export, notifications, or something else. Do not assume an API exists. |
| 6 | Search provider | **Brave Search API.** *(default accepted)* |
| 7 | Privacy limits for the cloud model | Conversation text may go to the cloud. Memory items and files marked private never go without per-request approval. From documents in granted folders, only the excerpts a request needs. *(default accepted)* |
| 8 | Memory capture | **Automatic capture with a weekly spoken digest, plus explicit "remember that".** Health, money and relationships are stored only on an explicit "remember". |
| 9 | Autonomy ceiling for routines | Tier 0 only (read, check, remind, prepare drafts in Jarvis's folder) until Phase 7 has 2 clean weeks. *(default accepted)* |
| 10 | Microphone setup | **Wired headphones with a built-in microphone, day to day.** `ECHO_MODE = "headset"` is the default. Speakers mode stays available. Task 2.11 (echo) now only needs to check that headset mode has no echo problems; echo cancellation for speakers is no longer a priority. |
| 11 | Cloud LLM provider | **Stay with OpenAI** behind the `ChatModel` interface. *(default accepted)* |
| 12 | Where local models live; GPU sharing | Models on **D:** or inside the project (`OLLAMA_MODELS` for Ollama). Close GPU-heavy apps for local-LLM use. *(default accepted)* |
| 13 | Licence | **MIT.** *(default accepted)* |
| 14 | Languages | **English only** for now; names in other languages as recognizer hints. *(default accepted)* |
| 15 | Encrypting `memory.db` | **Not at first**; revisit before connecting e-mail or documents. *(default accepted)* |
