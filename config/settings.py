"""Settings usable without cloud credentials or audio services."""
DEFAULT_LOCATION = "Kokkola"

# Upper bound, in seconds, for any single call to an external network service.
NETWORK_TIMEOUT_SECONDS = 10

# IANA zone for reminders and alarms, e.g. "Europe/Helsinki". None = system zone.
TIMEZONE = None

# Print one line per heard utterance (what Jarvis heard, how it was handled, timings).
SHOW_TRANSCRIPTS = True
