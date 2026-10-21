# Voice interaction

## Conversational follow-ups

The live Assistant now owns a `Dialogue` instance. It shares the last 16 user
and assistant messages across general chat, command output and clarification.
General chat, reminder requests and uncertain transcripts use the existing
language model to ask a short targeted question or propose a complete command.
Corrections and spelling can use the retained request details rather than
starting over. Model replies use a validated JSON contract, an 8-second request
timeout and bounded output. This is a text-only abstraction; the model has no
execution tools.

A proposal is read back using its exact command text. Only a clear `yes`,
`yes please` or `confirm` (reported confidence at least 0.8, no conflicting
alternatives) consumes it and calls the existing command boundary once. Missing
or low confidence cannot authorize it. `No` asks what to change; `cancel`,
`never mind` or `forget it` drops the pending dialogue request. Proposals expire
after 120 seconds without a dialogue turn. Invalid model output or provider
failure invalidates the proposal without executing it. Local stop/quiet remains
independent of model requests and does not cancel scheduled domain actions.

This adds a model round trip to conversational repair and reminder understanding.
Its interpretation is probabilistic; mocked tests verify state/execution rules,
not universal language accuracy. The existing reminder parser still interprets
the confirmed text, so its limitations remain. No microphone accuracy or echo
cancellation improvement is implied. Voice recognition can still lose or filter
a turn before it reaches dialogue. Plain-text `execute_query` remains unchanged.
Injected service tests may opt into dialogue using the `dialogue=` argument;
default application construction enables it automatically.

Live text validation reproduced the uncertain Annette/Anna transcript followed
by `Anne, not Annette. A N N E.`: the configured model retained tomorrow at 9 am
and proposed Anne for confirmation. This check did not execute a reminder.

## Conversation diagnostic log

Starting `python main.py` automatically appends to `logs/conversation.jsonl`.
Each line is a JSON event with a UTC timestamp, process-session ID and sequence.
Open it in a text editor or ask Codex to analyze it after a problematic session.
Existing sessions are preserved. The folder is excluded from Git.

The log includes recognized text (including passive listening), confidence and
alternatives, partial interruption recognition, rejected echoes, voice decisions,
executed command text/results, Jarvis's queued responses, playback chunk starts,
cancellation and failures. Queued text is not proof it was heard: check the
corresponding playback ID and completion outcome. Cancelled chunks may have been
partly audible. No raw microphone audio or credentials are logged. Consequently,
transcripts alone cannot establish the words actually spoken; when reporting a
misrecognition, also provide what you intended to say and its approximate time.

Logs are local plain text and grow until removed. Stop Jarvis before deleting or
archiving the file; it will be recreated on next launch. Logging write failures
warn once and do not stop the assistant. Imports and plain-text command execution
do not enable logging; `main()` enables it for the live voice application.

The command boundary remains `execute_query(text, services)`. Microphone capture,
recognition decisions, speech generation and playback live outside it.

## Pipeline

1. `voice_capture.MicrophoneFrames` owns one continuous mono PCM input stream.
2. `voice_capture.Endpointer` consumes WebRTC VAD decisions on 20 ms frames.
   Three voiced frames in a five-frame window start an utterance; 300 ms of
   pre-roll protects initial sounds. An utterance ends after 1.4 seconds of
   continuous non-speech. Shorter pauses stay inside the same recording.
3. `voice_runtime.ContinuousListener` has separate capture, final recognition,
   and interruption workers. Bounded queues prevent unlimited backlog. Lost
   frames and recordings reaching the 60-second safety limit are marked
   incomplete; their tails are drained until silence and never executed.
4. `voice_recognition.GoogleRecognizer` uses the existing Google recognizer.
   It preserves the provider's first transcript, alternatives and actual score.
5. `voice_policy.ConfidenceGate` checks final results before `Assistant` calls
   the unchanged command engine. Partial recognition can only cancel audio.
6. `speech_synthesis.GoogleSynthesizer` produces WAV/PCM; `speech_output` owns
   a single serialized generation/playback worker. Capture continues throughout.

## Recognition and compatibility

There are no phonetic replacements, sentiment rewrites, inferred confidence
scores, or substitutions of a preferred alternative. Negation and control words
are preserved. Wake detection requires a leading, case-insensitive `Jarvis`;
fuzzy aliases have intentionally been removed.

A wake-only utterance (`Jarvis`, including repetitions) requests a greeting in
both passive and active modes. A reported score of at least 0.5 is sufficient
for this harmless attention request; command thresholds remain unchanged.
Repeated unrecognized audio prompts once until recognizable speech arrives and
does not extend the active-session timeout. This prevents repeated noise from
producing a continuous clarification loop.

Reported scores below 0.8 for actions (0.65 for other requests), conflicting
alternatives, incomplete audio, and ambiguous bare controls prompt clarification.
An important request with no score requires an identical full repeat within
20 seconds. Repeating a low-confidence or conflicting result does not authorize
it. Negated actions are blocked because the legacy keyword router cannot safely
interpret them. These thresholds are heuristics, not calibrated probabilities.

Plain-text command behavior and full response text are unchanged. Accepted voice
requests still use the same services. Existing reminder/time follow-up state is
retained; its spoken time answer also passes the confidence gate.

`synthesize_speech()` now returns a `SpeechJob` immediately. Use `job.wait(timeout)`
only where waiting is explicitly needed, and inspect `job.error` after completion.
`stop_speech()` cancels active and queued output. Alert speech and chimes use the
same controller; cancellation affects their audio, not scheduled domain objects.
Responses are split into short synthesis chunks without dropping words. Automatic
sentiment SSML and excessive pauses were removed; long answer text is not silently
summarized. Active speech no longer uses MP3 files, playsound, or FFmpeg.

## Interruption

While a response is active, a separate recognition lane samples up to 1.8 seconds
of recent audio at 800 ms intervals when speech has been detected. This includes
a short word followed by silence. Clear `stop`, `quiet`, and related exact phrases
cancel output; strongly recognized Jarvis-addressed speech can also interrupt.
Partial results never invoke command services. An addressed replacement request
must finish and pass the final confidence gate before execution.

Every response has an identity. Delayed stop results for an old response cannot
cancel a newer response. Cancelling during generation discards the eventual audio.
Playback checks a cancellation event in 20 ms callbacks, with device buffering
adding latency. A cloud synthesis call already underway may continue for its
8-second timeout and delay the next generation. Recognition adds network latency:
the interruption RPC has a 3-second timeout. These are not end-to-end latency
guarantees or measured hardware results.

New output jobs wait while a user utterance is active. The controller serializes
concurrent response and notification submissions and bounds pending jobs to 16.
Full queues fail explicitly. Microphone failures surface to application cleanup;
automatic device reconnection is not implemented.

Audio generation now runs while waiting for input to end; only initial playback
is held. Silent generation is not tagged as speaker overlap. Short sentences are
packed into one synthesis request (up to 240 characters) to avoid extra network
round trips between sentences. New clarification decisions replace old output,
and unrecognized noise does not enqueue clarification behind a pending reply.
Logs separate `synthesis_started`/`synthesis_finished`,
`playback_waiting_for_input`/`playback_input_wait_finished`, and recognition request
duration so future sessions can distinguish provider latency from input waits.

## Limits and live validation

VAD detects speech, not speaker identity. This implementation has no acoustic echo
cancellation. It rejects recognizable response echoes and unaddressed commands
captured over playback, but mixed audio can still confuse recognition. A real
`stop` may be suppressed when that word occurs in the assistant's response.
Prefer `Jarvis, stop` and begin validation with headphones. A wrongly recognized
high-confidence transcript can still pass policy checks. Missing scores may make
the repeat requirement frequent. Pauses longer than 1.4 seconds end an utterance;
no finite silence threshold can infer sentence completion perfectly.

Run isolated checks with:

```powershell
.\env\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
```

The input source, VAD, recognition transport, player, speech controller and clock
are injectable. Tests cover pauses, clipping, scores, alternatives, negation,
interruption during blocked recognition, cancellation during synthesis/playback,
stale response identities, echo filtering, concurrency and device failures.
They do not establish real recognition accuracy or PortAudio duplex compatibility.

Before relying on voice control, test these scenarios with actual Google access:

| Scenario | Check |
| --- | --- |
| Long sentence with 0.5–1.2 s pauses | Initial words and all clauses retained |
| Soft speech, accents and background noise | Accuracy and clarification rate |
| Long response plus `stop` / `Jarvis, stop` | Measure onset-to-silence latency |
| Same tests using speakers instead of headphones | Echo false positives and missed interruptions |
| Negation, pause, resume, yes/no and cancellation | No unintended domain action |
| Speech overlapping notification audio | Serialized audio and safe cancellation |
| Network timeout, unplugged microphone, Ctrl+C | No late playback; clean resource release |

Tune `VoiceConfig` only after collecting results. The next voice-specific step is
measured duplex testing and an echo-cancellation/reference-audio design if speaker
tests show leakage. No recognition-provider migration was made.

Transport references: [WebRTC VAD frame requirements](https://github.com/wiseman/py-webrtcvad),
[Google LINEAR16 WAV encoding](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/AudioEncoding),
and [sounddevice stream API](https://python-sounddevice.readthedocs.io/en/latest/api/).
