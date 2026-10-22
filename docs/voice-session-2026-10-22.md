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
