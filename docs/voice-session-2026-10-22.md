# Voice session analysis — 22 October 2026

Session `77881de3…` in `logs/conversation.jsonl`, 09:49–09:54 local time
(06:49–06:54 UTC). 31 final recognitions, 88 partial (barge-in)
recognitions, 12 spoken replies. Generated from the log with the same event
stream that now drives the live transcript (`core/live_transcript.py`).

## Per-turn table

Columns:

- **Speech len** is the length of the audio the microphone endpointer sent to
  recognition. It includes about 1.4 s of trailing silence and any speaker echo
  or background noise.
- **STT** is the Google recognition call.
- **Routing+model** is the time from the transcript to the dialogue decision.
  It is almost all the ChatGPT call; the regex router takes under 1 ms.
- **TTS** is the Google synthesis call.
- **Held for input** is how long a finished reply waited because the
  microphone still detected speech.
- **End of speech → first audio** runs from the endpoint to the first audio of
  Jarvis's reply. Add about 1.4 s of endpoint silence for the time you
  experienced after your last word.

**Rejected: unaddressed_during_playback** means the utterance overlapped
Jarvis's own speech and did not start with "Jarvis", so it was discarded.

| # | Heard | Conf | Intent | Speech len (s) | Outcome / path | Jarvis reply | STT (s) | Routing+model (s) | TTS (s) | Held for input (s) | End of speech → first audio (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | (unrecognized) | - |  | 1.5 | ignored: no wake word |  | 0.5 |  |  |  |  |
| 2 | (unrecognized) | - |  | 2.5 | rejected: unaddressed_during_playback |  | 0.7 |  |  |  |  |
| 3 | (unrecognized) | - |  | 1.8 | rejected: unaddressed_during_playback |  | 0.5 |  |  |  |  |
| 4 | (unrecognized) | - |  | 1.9 | rejected: unaddressed_during_playback |  | 0.5 |  |  |  |  |
| 5 | (unrecognized) | - |  | 8.2 | rejected: unaddressed_during_playback |  | 1.4 |  |  |  |  |
| 6 | Deli | 0.06 | chat | 3.2 | ignored: no wake word |  | 0.8 |  |  |  |  |
| 7 | (unrecognized) | - |  | 1.8 | ignored: no wake word |  | 0.5 |  |  |  |  |
| 8 | Jarvis | 0.75 | (wake) | 9.1 | wake word | At your service, sir. | 1.1 |  | 0.3 | **6.0** | **7.4** |
| 9 | (unrecognized) | - |  | 7.4 | ignored: unrecognized, reply pending |  | 0.9 |  |  |  |  |
| 10 | (unrecognized) | - |  | 2.7 | rejected: unaddressed_during_playback |  | 0.7 |  |  |  |  |
| 11 | definition | 0.08 | chat | 2.7 | ChatGPT dialogue (low confidence) | Could you clarify what you need a definition for? | 0.8 | 2.2 | 0.5 |  | 3.6 |
| 12 | delete my call Mom reminder | 0.95 | delete_reminder | 10.9 | **rejected: unaddressed_during_playback** |  | 1.9 |  |  |  |  |
| 13 | Jarvis delete my call Mom reminder | 0.87 | delete_reminder | 4.5 | **ChatGPT dialogue (repair in progress)** | I have: delete reminder 'call Mom'. Shall I do that? | 1.2 | 0.8 | 0.5 |  | 2.5 |
| 14 | yes | 0.56 | chat | 6.9 | **rejected: unaddressed_during_playback** |  | 2.3 |  |  |  |  |
| 15 | yes do it | 0.86 | chat | 2.8 | **ChatGPT dialogue (not taken as "yes")** | I have: delete reminder 'call Mom'. Shall I do that? | 0.6 | 1.2 | 0.6 |  | 2.4 |
| 16 | yes please | 0.87 | chat | 6.7 | **rejected: unaddressed_during_playback** |  | 1.4 |  |  |  |  |
| 17 | (unrecognized) | - |  | 2.2 | clarification | I couldn't hear that clearly. Please try again. | 0.6 |  | 0.3 |  | 0.9 |
| 18 | (unrecognized) | - |  | 4.2 | rejected: unaddressed_during_playback |  | 1.5 |  |  |  |  |
| 19 | (unrecognized) | - |  | 1.6 | ignored: unrecognized again |  | 0.4 |  |  |  |  |
| 20 | Jarvis can you delete my call Mom reminder | 0.83 | delete_reminder | 7.7 | **ChatGPT dialogue (repair in progress)** | I have: delete reminder 'call Mom'. Shall I do that? | 2.3 | 0.8 | 0.5 |  | 3.7 |
| 21 | yes please | 0.89 | chat | 7.0 | **rejected: unaddressed_during_playback** |  | 1.3 |  |  |  |  |
| 22 | (unrecognized) | - |  | 1.7 | clarification | I couldn't hear that clearly. Please try again. | 0.5 |  | 0.6 |  | 1.2 |
| 23 | (unrecognized) | - |  | 4.5 | rejected: unaddressed_during_playback |  | 0.8 |  |  |  |  |
| 24 | (unrecognized) | - |  | 2.9 | ignored: unrecognized again |  | 0.5 |  |  |  |  |
| 25 | (unrecognized) | - |  | 1.7 | ignored: unrecognized again |  | 0.4 |  |  |  |  |
| 26 | wake up at 6:30 | 0.20 | chat | 9.5 | ChatGPT dialogue (low confidence) | Would you like to set an alarm for 6:30 AM? | 2.3 | 1.8 | 0.5 | **17.9** | **22.4** |
| 27 | videos of 10 minutes | 0.13 | chat | 22.4 | ChatGPT dialogue (low confidence) | Are you looking for 10-minute videos on YouTube? | 2.2 | 1.1 | 0.4 | 1.0 | 4.8 |
| 28 | set an alarm for 6:30 a.m. | 0.88 | alarm | 3.9 | **rejected: unaddressed_during_playback** |  | 1.1 |  |  |  |  |
| 29 | (unrecognized) | - |  | 3.8 | rejected: unaddressed_during_playback |  | 0.9 |  |  |  |  |
| 30 | (unrecognized) | - |  | 3.0 | clarification | I couldn't hear that clearly. Please try again. | 0.8 |  | 0.5 |  | 1.2 |
| 31 | (unrecognized) | - |  | 10.6 | rejected: unaddressed_during_playback |  | 1.6 |  |  |  |  |

Turns 1–5 happened while Jarvis read out two reminders from January. They
were migrated from `reminders.json` at startup and announced once as missed.
Turns 2–5 are mostly Jarvis hearing itself.

### Stage totals

| Stage | Calls | Median | Max | Total |
|---|---|---|---|---|
| Endpoint silence (fixed) | every turn | 1.4 s | 1.4 s | — |
| Speech recognition (final) | 31 | 0.83 s | 2.34 s | 32.9 s |
| ChatGPT dialogue call | 6 | 1.17 s | 2.25 s | 8.0 s |
| Speech synthesis (replies) | 10 | 0.49 s | 0.64 s | 4.7 s |
| Reply held for "input" | 3 | 6.0 s | **17.9 s** | **24.9 s** |
| End of speech → first audio | 10 | 3.05 s | 22.4 s | 50.1 s |
| Partial barge-in recognitions | 88 | 0.47 s | — | 43 s of cloud calls |

Utterance lengths: median 3.8 s; 11 of 31 were longer than 5 s; the
longest was 22.4 s. A spoken "yes" became 6.7–7.0 s of audio.

## Compared with what you said

Your list arrived with its placeholders unfilled (`[what you said to wake
it]`, …), so this column is my reading of the log. Please correct it.

| Your step | What the log shows | Best reading |
|---|---|---|
| 1. Wake | Turn 6 "Deli" (0.06; alternatives Delhi, jolly, Darby), then turn 8 "Jarvis" (0.75; alternative "Yarvis") | First "Jarvis" misheard as "Deli" and ignored; the second worked |
| 2. Before "definition for?" | Turn 9: 7.4 s unrecognized while "At your service" was held. Turn 10: unrecognized during playback. Turn 11: "definition" (0.08) | Your request was lost: first unrecognized, then a fragment heard as "definition" |
| 3. Delete the reminder | Turn 12 "delete my call Mom reminder" (0.95) **rejected**; turns 13 and 20 "Jarvis (can you) delete my call Mom reminder" (0.87, 0.83) | Heard correctly every time |
| 4. Answers to "Shall I do that?" | "yes" (0.56) rejected; "yes do it" (0.86) not taken as yes; "yes please" (0.87) rejected; "yes please" (0.89) rejected | Heard correctly every time, and never accepted |
| 5. Before the 6:30 alarm question | Turn 26 "wake up at 6:30" (0.20; alternative "wake up") | Probably "wake me up at 6:30" or similar |
| 6. Before the YouTube question | Turn 27 "videos of 10 minutes" (0.13) from 22.4 s of audio; then turn 28 "set an alarm for 6:30 a.m." (0.88) rejected | Probably a repeat of the alarm request, overlapping Jarvis's question |

## Diagnosis

| Problem (turns) | Root cause | Category |
|---|---|---|
| Correct answers thrown away (12, 14, 16, 21) | Jarvis's own voice, played through the speakers, opens the microphone's voice detector before Jarvis finishes. Your answer then becomes part of an utterance that *started* during playback. The whole utterance is tagged as overlapping playback, and `voice_runtime.handle_final` discards tagged utterances unless they start with "Jarvis". You spoke after Jarvis had stopped, but that wasn't considered. | Confirmation handling / echo filter |
| Delete confirmation asked 3 times (13→15→20) | (a) "yes" and both "yes please" were discarded by the filter above. (b) "yes do it" reached the dialogue, but it only accepted exactly "yes", "yes please" or "confirm", so "yes do it" went back to ChatGPT, which proposed the same thing again. (c) Even a matching "yes" needed confidence ≥ 0.8 with no differing alternatives: "yes" at 0.56 (all alternatives "yesss"/"yess") and "yes do it" (alternative "just do it") would both have been refused. | Confirmation handling + threshold |
| "delete reminder" went through the ChatGPT proposal path (13, 20) | The router classified it correctly (`delete_reminder`), but the assistant sends *everything* to the dialogue while `dialogue.repairing` is set. The low-confidence "definition" turn (11) set it, and it stays set until "yes", "cancel" or 2 minutes of silence. So a clear, confident command was handled as a repair. | Routing (state, not the rule table) |
| The proposal would not have deleted anything | ChatGPT phrased it as `delete reminder 'call Mom'`; the target extractor doesn't read quoted names, so the target was empty. Also, no "call mom" reminder was pending: both January ones were announced as missed at startup (09:49) and marked done. | Routing (target extraction) |
| "Would you like to set an alarm for 6:30 AM?" could not be confirmed | ChatGPT asked a yes/no question in free text instead of returning a proposal. With nothing pending, the dialogue answers any "yes" with "What would you like me to do?". | Confirmation handling |
| "wake up at 6:30" not routed as an alarm (26) | The alarm rule only knows "wake me". At 0.20 confidence it went to ChatGPT anyway; a confident "wake up at 6:30" would have gone to chat. | Routing (rule gap) |
| "set an alarm for 6:30 a.m." discarded (28) | You spoke while Jarvis was still asking its question, without saying "Jarvis". Without echo cancellation this can't be told apart from Jarvis hearing itself, so it stays discarded (see recommendations). | Echo / barge-in |
| Request lost after waking (9–11) | 7.4 s of audio came back unrecognized, then a fragment was heard as "definition" (0.08). The long utterance mixes your words with noise and speaker echo. | Misrecognition |
| Low-confidence transcripts (6, 11, 26, 27) and 18 of 31 utterances unrecognized | Long, mixed utterances: the voice detector stays open on speaker echo and background sound (11 utterances > 5 s; a "yes" became 7 s of audio). Google then gets your words buried in Jarvis's own voice or noise. | Misrecognition (audio front end) |
| 6.0 s and 17.9 s of silence before a reply (8, 26) | A finished reply waits until the microphone reports no speech. The voice detector stayed "active" for 6 s and 18 s, so the reply was held with no upper limit. | Latency |

### Where the time goes

The single slowest stage is the **reply being held for "input"**: 24.9 s across
3 turns, 17.9 s at worst, against 8.0 s for all ChatGPT calls together.

On a normal turn, after you stop speaking:

| Stage | Typical time |
|---|---|
| Endpoint silence | 1.4 s |
| Recognition | ~0.8 s (up to 2.3 s for long, noisy utterances) |
| ChatGPT dialogue (when used) | ~1.2 s (up to 2.2 s) |
| Synthesis | ~0.5 s |
| **Total** | about 3–4.5 s on the dialogue path; about 2.7 s on the fast path |

On the fast path, routing and execution take milliseconds. So the dialogue
detour on turns 13 and 20 cost about 1 s each, plus an extra confirmation
round trip.

Misrecognition is a real but secondary problem. Every clearly spoken command
and answer in this session was recognized correctly (0.56–0.95). What failed
was what happened *after* recognition: discarded answers, a too-strict "yes"
and a sticky repair state. The recognition failures (unrecognized audio, 0.06–0.20 transcripts)
trace back to long utterances mixed with speaker echo, i.e. the audio front
end, more than to the speech model.

## Fixes

Each fix has regression tests in `tests/test_voice_session_regressions.py`
built from the exact transcripts, confidences and alternatives above.

| Fix | Files |
|---|---|
| **Answers after Jarvis stops are kept.** The endpointer measures how much speech came after Jarvis's last audible frame. An utterance that overlapped playback is kept when you kept speaking for ≥ 300 ms after Jarvis stopped and the transcript isn't Jarvis's own words. Speech entirely over Jarvis (turn 28) and empty transcripts are still discarded. | `voice_capture.py`, `voice_runtime.py` |
| **Natural confirmations.** "yes do it", "yes please", "go ahead", "sure", "that's right" (and no/cancel variants) are answers. "thank you", "please" and "is that right" are not. | `dialogue.py` |
| **Short-answer threshold.** An answer needs confidence ≥ 0.5 with every alternative meaning the same thing ("yes" 0.56 with "yesss", "yess" now counts), or ≥ 0.8 ignoring alternatives below 0.5. "yes" with a "no" alternative, or below 0.5, still doesn't confirm. | `dialogue.py` |
| **Spelling variants aren't conflicts.** "Jarvis"/"Yarvis" and stretched letters ("yesss", "momm") are ignored when comparing alternatives. Name variants ("Mom"/"Mam") are a *wording* conflict: Jarvis confirms your own words ("I have: delete my call Mom reminder. Shall I do that?") without calling ChatGPT. Meaning conflicts (cancel vs don't cancel, 5 vs 9) still ask you to repeat. | `voice_policy.py`, `assistant.py`, `dialogue.py` |
| **No sticky repair.** A clear, accepted command takes the fast path even while a repair is in progress, and replaces the unfinished request. | `assistant.py` |
| **"Yes" after a model question.** If ChatGPT's last reply was a question, "yes" goes back to it; otherwise a stray "yes" still gets "What would you like me to do?". The prompt now tells the model to propose actions as commands in your words instead of asking in free text. | `dialogue.py`, `chatgpt_service.py` |
| **Quoted reminder names** (`delete reminder 'call Mom'`) are read as the target. | `intent_classifier.py` (field extraction; rule order unchanged) |
| **"wake up at 6:30" is an alarm.** A pattern was added to the existing alarm rule (anchored, so "I wake up at 6:30" stays chat); the parser reads it as morning. | `intent_classifier.py`, `reminder_parser.py` |
| **Latency: replies are held at most 3 s** for a "busy" microphone (previously unlimited: 6.0 s and 17.9 s in this session). | `speech_output.py` |
| **Latency/cost: barge-in recognition only while Jarvis is audible**, not while a reply is being synthesised or held. | `voice_runtime.py` |

The live transcript now also shows why a turn went to the dialogue: low
confidence, similar alternatives, or a repair in progress.

## Recommendations (not implemented)

1. **Stop Jarvis hearing itself.** This is the main source of long utterances,
   unrecognized audio, low confidence and the overlap problem.
   - Simplest: a headset, so the microphone doesn't pick up the speakers.
   - Alternatively, enable acoustic echo cancellation on the input (the
     Windows "communications" processing, or a WebRTC/Speex echo canceller on
     the PCM stream).
   - Or go half-duplex: ignore the microphone during playback except for
     "Jarvis"/"stop".
2. **Recognition settings before switching provider.**
   - Today's recognizer is the free web API behind `speech_recognition`. It has
     no phrase hints and no model choice.
   - `google-cloud-speech` is already installed. Its `speech_contexts` can
     boost "Jarvis", yes/no/cancel, intent words (remind, delete, snooze,
     alarm, timer) and names from your reminders. `latest_short` suits
     commands.
   - A local option is faster-whisper with an initial prompt carrying the same
     words. That also removes network latency, but costs CPU.
3. **Streaming recognition** (Cloud Speech streaming) would deliver the
   transcript as you finish speaking and could end the utterance on the
   provider's end-of-speech signal. That saves most of the ~0.8 s recognition
   step and some of the 1.4 s endpoint silence.
4. **Move provider calls off the conversation loop** (a worker with request
   ids), so a slow ChatGPT or weather call can be superseded by "stop" or a new
   request.
5. **Shorter endpoint for expected short answers.** After "Shall I do that?",
   0.8 s of silence is enough for "yes"; keep 1.4 s for open requests. Measure
   with a headset first.
6. **Voice detector tuning after echo is fixed.** `vad_mode` is 1 (permissive).
   Try 2 with an energy floor, and measure utterance lengths again; this
   session's median was 3.8 s, with 11 of 31 over 5 s.
7. **An on-device wake word** (openWakeWord or Porcupine) would stop sending
   background audio to Google and avoid false starts like "Deli".
8. **Cache fixed phrases** ("At your service, sir.", "I couldn't hear that
   clearly…") to save the ~0.3–0.6 s synthesis call.
