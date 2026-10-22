# 🤖 Jarvis - AI Voice Assistant

A sophisticated voice-activated AI assistant inspired by Iron Man's J.A.R.V.I.S., built in Python. Jarvis listens for voice commands, processes natural language, and responds with expressive synthesized speech.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Status](https://img.shields.io/badge/Status-Active-green.svg)

---

## ✨ Features

### Voice Interaction
- **Wake Word Detection** - Say **"Hey Jarvis"**. It is detected on your computer (openWakeWord, on the CPU), so nothing is sent to cloud speech recognition until you say it. Plain "Jarvis" is not used: the model was trained on "Hey Jarvis". Within a conversation (30 s after Jarvis answers, or while it waits for your answer) no wake word is needed.
- **Headset by default** - With wired headphones and a microphone you can answer or interrupt at any time, also while Jarvis is speaking (`ECHO_MODE` in `config/settings.py`; `"speakers"` for loudspeakers).
- **Voice Activity Detection (VAD)** - Continuous capture with 1.4-second silence endpointing
- **Speech Recognition** - Google Speech Recognition with preserved transcripts and clarification for uncertain commands
- **Interruptible Speech** - Queued Google Cloud TTS and cancellable PCM playback; listening continues during responses

See [voice interaction architecture and live-testing limits](docs/voice-interaction.md).

### Supported Commands

| Command | Examples |
|---------|----------|
| **Create reminders** | "Remind me to call mom tomorrow at 9 pm", "Remind me to take a break in one hour", "Remind me to pay rent on December 20 at 9 am" |
| **Recurring reminders** | "Remind me to water plants every day at 8 am", "Remind me about standup every Monday at 9", "Remind me to drink water every hour" |
| **List reminders** | "What are my reminders?" |
| **Delete reminders** | "Delete my dentist reminder", "Delete the call mom reminder tomorrow at 9 pm" |
| **Snooze reminders** | "Snooze it for 10 minutes", "Snooze that reminder" (10 minutes), "Snooze the cat reminder for 20 minutes" |
| **Alarms** | "Set an alarm for 7am", "Wake me up at 6:30", "Set an alarm for 7 AM every day", "Cancel my alarm", "What alarms do I have?" |
| **Timers** | "Set a timer for twenty five minutes", "Pause the pasta timer", "Unpause the pasta timer", "How much time is left?", "Start a pomodoro" |
| **Weather** | "What's the weather like today?", "Weather in Helsinki", "What's the forecast for Athens?" |
| **YouTube** | "Play lofi music on YouTube" |
| **Time** | "What time is it?" |
| **Date** | "What's today's date?", "What's the date day after tomorrow?" |
| **Open Google** | "Open Google" (opens the page; there is no search-results workflow) |
| **General Chat** | Anything else goes to ChatGPT |

### Reminders and Alarms
- **One parse, one datetime** - The time is parsed once (regex plus `dateparser` for calendar dates) into a timezone-aware datetime; no NLP model is loaded.
- **Asks instead of guessing** - Missing times ("remind me to call mom") and ambiguous ones ("at 5" - a.m. or p.m.?) get a question; your answer completes the original request. A bare 7-11 is read as morning and 12 as noon.
- **Stored in SQLite** - `data/reminders.db`; each reminder has a stable id, so two reminders with the same text are independent. On first start, `data/reminders.json` is imported once and left in place.
- **One scheduler** - A single background thread fires reminders on time, survives restarts, and announces anything that fell due while Jarvis was off once at startup.
- **By id** - Delete and snooze act on exactly one reminder; if a name matches several, Jarvis reads them back with their times and asks which one.
- **Time zone** - The system zone by default; set `TIMEZONE` in `config/settings.py` (e.g. `"Europe/Helsinki"`) to override.

### Not Implemented Yet
- **Memory and preferences** - `core/memory_manager.py` exists, but the running assistant does not store or read conversation memory or preferences.
- **Web search**, **climate/room monitoring** and **system status** checks.

---

## 🏗️ Architecture

```
Jarvis/
├── main.py                    # Entry point: starts reminders, then the voice loop
├── core/
│   ├── assistant.py           # Conversation loop, wake word and confidence decisions
│   ├── intent_classifier.py   # Ordered word-boundary routing table
│   ├── command_engine.py      # Understand + execute text commands -> CommandResult
│   ├── command_services.py    # Adapters to weather, YouTube, timers, reminders, chat
│   ├── dialogue.py            # Conversational repair; model proposals need a spoken "yes"
│   ├── reminder_parser.py     # Reminder/alarm text -> timezone-aware datetime
│   ├── reminder_store.py      # SQLite storage (data/reminders.db) + JSON migration
│   ├── reminder_manager.py    # Scheduler thread; create/list/delete/snooze by id
│   ├── smart_timer.py         # Timers and pomodoro
│   ├── voice_*.py             # Capture, VAD, recognition and voice policy
│   ├── speech_synthesis.py    # Text-to-speech with SSML
│   ├── chatgpt_service.py     # OpenAI GPT-4o integration
│   ├── weather_service.py     # OpenWeatherMap integration
│   └── youtube_service.py     # YouTube Data API
├── config/
│   ├── api_keys.py            # API keys from .env
│   ├── credentials.py         # Google Cloud credentials (GOOGLE_CLOUD_CREDENTIALS)
│   └── settings.py            # Default city, network timeout, time zone
├── utils/
│   └── audio_utils.py         # Audio playback
└── data/                      # Runtime data (gitignored): reminders.db, memory.db
```

### Flow
```
Continuous microphone → Frame VAD → Final Google recognition
                                          ↓
                                 Wake / confidence policy
                                          ↓
                              Command engine → Structured result
                                          ↓
                              TTS queue → Cancellable PCM playback

Microphone → Separate interruption recognition → Cancel current speech
Reminder scheduler thread → Spoken reminder or alarm
```

---

## 🔧 Prerequisites

- **Python 3.10+**
- **Microphone** access
- **FFmpeg** (included in `env/ffmpeg/`)

### Required API Keys

| API | Purpose |
|-----|---------|
| OpenAI API | ChatGPT responses |
| OpenWeatherMap API | Weather data |
| YouTube Data API v3 | Video search |
| Google Cloud TTS | Speech synthesis |
| Google Geolocation API | Location detection |

---

## 🚀 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/jarvis.git
cd jarvis
```

### 2. Create Virtual Environment
```bash
python -m venv env

# Windows
.\env\Scripts\activate

# Linux/macOS
source env/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

No spaCy language model download is needed: the running assistant does not use spaCy.

### 4. Configure API Keys

Copy `.env.example` to `.env` in the project root and fill in the values:
```env
OPENAI_API_KEY=your_openai_api_key
YOUTUBE_API_KEY=your_youtube_api_key
WEATHER_API_KEY=your_openweathermap_api_key
GOOGLE_API_KEY=your_google_api_key
GOOGLE_CLOUD_CREDENTIALS=C:/path/to/your-service-account.json
```

Set up Google Cloud credentials:
1. Create a Google Cloud project
2. Enable Text-to-Speech API
3. Create a service account and download the JSON key
4. Set `GOOGLE_CLOUD_CREDENTIALS` in `.env` to the key file's path

---

## 💻 Usage

### Start Jarvis
```bash
python main.py
```

### How It Works
1. Jarvis starts the reminder scheduler and announces any reminders missed while it was off
2. Jarvis listens passively for the wake word **"Hey Jarvis"**
3. Say your command after it, in the same breath or after Jarvis answers
4. Jarvis processes and responds with synthesized speech
5. The conversation stays active for 30 seconds after each reply, then Jarvis returns to passive mode

Measure the wake word in your room with `tools/measure_wake_word.py`.

### Example Commands
```
"Hey Jarvis, what's the weather like?"
"Hey Jarvis, remind me to take a break in 30 minutes"
"Hey Jarvis, what are my reminders?"
"Hey Jarvis, set an alarm for 7am"
"Hey Jarvis, play relaxing music on YouTube"
"Hey Jarvis, what time is it?"
"Hey Jarvis, tell me a joke"
```

---

## 🧪 Testing

Run the isolated tests (no microphone, TTS, API calls or real data files):

```bash
python -B -m pytest -q
```

`pytest.ini` limits collection to `tests/`. Reminder tests use a frozen clock and a temporary database, so nothing waits in real time.

Plain-text execution returns structured results through
`core.command_engine.execute_query()`. See [command boundary documentation](docs/command-boundary.md)
for service injection, output adapters, and compatibility details.

The root-level `test_*.py` and `full_test.py` scripts are older experiments, not part of the suite. They can load models, call external services or write to the real memory database.

---

## 📁 Key Components

### Speech Synthesis
- Escaped SSML with configurable voice, rate and pitch
- Short synthesis chunks preserving the full response text
- Cancellable playback with a shared audio queue
- Continuous microphone capture during output (speaker echo still requires live validation)

### Intent Routing
An ordered table of word-boundary rules in `core/intent_classifier.py`; the first match wins and anything unmatched goes to ChatGPT. Operations on existing things are checked first (snooze/delete/list reminders before creating one, resume before pause).

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Inspired by J.A.R.V.I.S. from Iron Man
- Built with OpenAI, Google Cloud, and open-source libraries
- Thanks to the Python community for excellent packages
