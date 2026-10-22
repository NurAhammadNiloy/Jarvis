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

# On-device wake word: "Hey Jarvis" (plain "Jarvis" is not reliable), detected on the CPU
# by openWakeWord. While Jarvis is passive, nothing is sent to cloud speech recognition
# until it fires. None = the old check for "Jarvis" in the cloud transcript.
WAKE_WORD_ENGINE = "openwakeword"

# 0-1. Higher: fewer false wake-ups, more missed wake words. Lower: the opposite.
# 0.5 is openWakeWord's recommended default; measure with tools/measure_wake_word.py.
WAKE_WORD_THRESHOLD = 0.5

# Personal tuning to your voice: record with tools/record_voice.py, then train with
# tools/train_wake_verifier.py (stored in data/voice/, never uploaded). Used once trained;
# False = the plain model only.
WAKE_WORD_PERSONAL = True

# The personal tuning decides from this plain-model score up (lower = it judges more of
# what you say; your weakest real "Hey Jarvis" peaked at 0.08).
WAKE_WORD_VERIFIER_GATE = 0.05

# After the wake word or a finished exchange (once Jarvis stops speaking), Jarvis
# listens without the wake word for this long, then returns to passive mode.
ACTIVE_WINDOW_SECONDS = 30

# The same, when Jarvis's last reply ended with a question (you may need to think).
QUESTION_WINDOW_SECONDS = 30

# "undo" / "no, that's wrong" / "cancel that" reverses the last action for this long.
UNDO_WINDOW_SECONDS = 60
