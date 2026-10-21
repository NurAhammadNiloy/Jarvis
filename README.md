# 🤖 Jarvis - AI Voice Assistant

A sophisticated voice-activated AI assistant inspired by Iron Man's J.A.R.V.I.S., built in Python. Jarvis listens for voice commands, processes natural language, and responds with expressive synthesized speech.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Status](https://img.shields.io/badge/Status-Active-green.svg)

---

## ✨ Features

### Voice Interaction
- **Wake Word Detection** - Requires a leading "Jarvis"
- **Voice Activity Detection (VAD)** - Continuous capture with 1.4-second silence endpointing
- **Speech Recognition** - Google Speech Recognition with preserved transcripts and clarification for uncertain commands
- **Interruptible Speech** - Queued Google Cloud TTS and cancellable PCM playback; listening continues during responses

See [voice interaction architecture and live-testing limits](docs/voice-interaction.md).

### Supported Commands

| Command | Example |
|---------|---------|
| **Reminders** | "Remind me to call mom at 5pm" |
| **Weather** | "What's the weather like today?" |
| **YouTube** | "Play lofi music on YouTube" |
| **Time** | "What time is it?" |
| **Date** | "What's today's date?" |
| **Web Search** | "Open Google" |
| **General Chat** | Any question (falls back to ChatGPT) |

### Advanced Capabilities
- **Contextual Reminders** - Natural language date/time parsing with recurring support
- **Memory System** - SQLite-based conversation history with short-term and long-term storage
- **User Preferences** - Persistent settings across sessions
- **Speech Output** - Short synthesis chunks and serialized speech/chime playback

---

## 🏗️ Architecture

```
Jarvis/
├── main.py                    # Entry point
├── core/
│   ├── assistant.py           # Main conversation loop & wake word detection
│   ├── intent_classifier.py   # Keyword-based intent classification
│   ├── intent_handler.py      # Routes intents to handlers
│   ├── voice_recognition.py   # Speech-to-text with VAD
│   ├── speech_synthesis.py    # Text-to-speech with SSML
│   ├── chatgpt_service.py     # OpenAI GPT-4o integration
│   ├── weather_service.py     # OpenWeatherMap integration
│   ├── youtube_service.py     # YouTube Data API
│   ├── memory_manager.py      # SQLite conversation storage
│   └── reminder_manager.py    # Reminder scheduling
├── config/
│   ├── api_keys.py            # API key configuration
│   └── credentials.py         # Google Cloud credentials
├── utils/
│   ├── audio_utils.py         # Audio playback
│   ├── nlp_utils.py           # Entity extraction (spaCy)
│   └── text_utils.py          # Text processing
└── data/
    └── memory.db              # SQLite database
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

# Download spaCy language model
python -m spacy download en_core_web_trf
```

### 4. Configure API Keys

Create a `.env` file in the project root:
```env
OPENAI_API_KEY=your_openai_api_key
YOUTUBE_API_KEY=your_youtube_api_key
WEATHER_API_KEY=your_openweathermap_api_key
GOOGLE_API_KEY=your_google_api_key
```

Set up Google Cloud credentials:
1. Create a Google Cloud project
2. Enable Text-to-Speech API
3. Create a service account and download the JSON key
4. Update the path in `config/credentials.py`

---

## 💻 Usage

### Start Jarvis
```bash
python main.py
```

### How It Works
1. Jarvis listens passively for the wake word **"Jarvis"**
2. Once activated, speak your command
3. Jarvis processes and responds with synthesized speech
4. Conversation stays active for 2 minutes before returning to passive mode

### Example Commands
```
"Jarvis, what's the weather like?"
"Jarvis, remind me to take a break in 30 minutes"
"Jarvis, play relaxing music on YouTube"
"Jarvis, what time is it?"
"Jarvis, tell me a joke"
```

---

## 🧪 Testing

Run the isolated command-boundary and voice tests (no microphone, TTS, or API calls):

```bash
python -B -m pytest tests -q -p no:cacheprovider
```

Plain-text execution returns structured results through
`core.command_engine.execute_query()`. See [command boundary documentation](docs/command-boundary.md)
for service injection, output adapters, and compatibility details.

The older integration suite below is not isolated and can write to the real
memory database or invoke external services:
```bash
pytest full_test.py
```

Individual test files:
- `test_memory.py` - Memory system tests
- `test_climate_control.py` - Climate control tests
- `test_voice_recogination.py` - Voice recognition tests

---

## 📁 Key Components

### Memory Manager
- **Short-term memory**: Last 5 conversations (in-memory)
- **Long-term memory**: SQLite database for conversation history
- **User preferences**: Persistent settings storage
- **Session data**: Temporary state management

### Speech Synthesis
- Escaped SSML with configurable voice, rate and pitch
- Short synthesis chunks preserving the full response text
- Cancellable playback with a shared audio queue
- Continuous microphone capture during output (speaker echo still requires live validation)

### Intent Classification
Keyword-based classification with support for:
- Reminder management (set, list, delete, snooze)
- Weather queries
- YouTube playback
- Time and date queries
- General conversation (ChatGPT fallback)

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
