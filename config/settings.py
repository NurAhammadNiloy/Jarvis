"""Settings usable without cloud credentials or audio services."""
DEFAULT_LOCATION = "Kokkola"

# Upper bound, in seconds, for any single call to an external network service.
NETWORK_TIMEOUT_SECONDS = 10

# IANA zone for reminders and alarms, e.g. "Europe/Helsinki". None = system zone.
TIMEZONE = None

# Print one line per heard utterance (what Jarvis heard, how it was handled, timings).
SHOW_TRANSCRIPTS = True

# "headset": the microphone does not hear Jarvis (wired headphones with a mic), so you
# can answer or interrupt at any time, also while Jarvis is speaking.
# "speakers": the microphone hears Jarvis, so while it speaks and for 0.3 s after,
# only speech starting with "Jarvis" or "stop" counts; the rest is discarded.
ECHO_MODE = "headset"

# After the wake word or a finished exchange (once Jarvis stops speaking), Jarvis
# listens without the wake word for this long, then returns to passive mode.
ACTIVE_WINDOW_SECONDS = 30

# The same, when Jarvis's last reply ended with a question (you may need to think).
QUESTION_WINDOW_SECONDS = 30

# "undo" / "no, that's wrong" / "cancel that" reverses the last action for this long.
UNDO_WINDOW_SECONDS = 60
