import os
import random
import spacy
from textblob import TextBlob
from google.cloud import texttospeech
from config.credentials import credentials
from utils.audio_utils import play_audio

# ---------------- Init ----------------
client = texttospeech.TextToSpeechClient(credentials=credentials)
nlp = spacy.load("en_core_web_sm")

# Optional audio post FX
try:
    from pydub import AudioSegment
    PYDUB_OK = True
except Exception:
    PYDUB_OK = False


# ---------------- Analyzers (yours, unchanged) ----------------
def analyze_text_context(sentence_text):
    sentiment = TextBlob(sentence_text).sentiment
    polarity = sentiment.polarity

    tone = "neutral"
    emotion = "none"
    if polarity > 0.5:
        tone, emotion = "positive", "happy"
    elif polarity < -0.5:
        tone, emotion = "negative", "concerned"
    elif 0 < polarity <= 0.5:
        tone, emotion = "slightly positive", "encouraging"
    elif -0.5 <= polarity < 0:
        tone, emotion = "slightly negative", "worried"
    return tone, emotion


def analyze_sentence_type(sentence_text):
    t = sentence_text.strip()
    if t.endswith("?"):
        return "question"
    if t.endswith("!"):
        return "exclamation"
    if t.split()[0].lower() in ["please", "do", "execute", "run"]:
        return "command"
    return "statement"


def detect_critical_words(sentence_text, entities):
    critical_keywords = ["warning", "immediate", "critical", "danger", "failure", "caution", "error", "rising"]
    doc = nlp(sentence_text)
    critical_words = set()

    for entity in entities:
        critical_words.add(entity)

    low = sentence_text.lower()
    for word in critical_keywords:
        if word in low:
            critical_words.add(word)

    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"] and token.text.lower() in critical_keywords:
            critical_words.add(token.text)
    return critical_words


def dynamic_break_time(sentence_type, emotion):
    if sentence_type == "question":
        return "420ms"
    if sentence_type == "exclamation":
        return "320ms"
    if emotion == "concerned":
        return "650ms"
    return "480ms"


# ---------------- SSML (clean, human, Google-safe) ----------------
def create_dynamic_ssml(text):
    """
    Human-style SSML:
      - Sentence-level prosody (subtle)
      - Clause-aware micro-pauses (em-dash, ellipsis)
      - % -> “percent”
      - No fillers, no nested-tag issues
    """
    import re, html

    def esc(s: str) -> str:
        return html.escape(s, quote=False)

    def render_percentages(s: str) -> str:
        # 15% -> <say-as>15</say-as> percent
        pat = re.compile(r'(\d+(?:\.\d+)?)%')
        out, last = [], 0
        for m in pat.finditer(s):
            out.append(esc(s[last:m.start()]))
            out.append(f"<say-as interpret-as='cardinal'>{esc(m.group(1))}</say-as> percent")
            last = m.end()
        out.append(esc(s[last:]))
        return "".join(out)

    doc = nlp(text)
    parts = []

    for sent in doc.sents:
        raw = sent.text.strip()
        if not raw:
            continue

        tone, emotion = analyze_text_context(raw)
        s_type = analyze_sentence_type(raw)

        # Calm, human prosody
        pitch, rate, volume = "0%", "98%", "medium"
        if s_type == "question":
            pitch, rate = "+4%", "101%"
        elif s_type == "exclamation":
            pitch, rate = "+3%", "101%"
        elif s_type == "command":
            pitch, rate = "+2%", "100%"

        if emotion == "concerned":
            pitch, rate = "-2%", "97%"
        elif emotion == "happy":
            pitch = "+5%"

        body = render_percentages(raw)
        # gentle breaks for em-dash / ellipsis only (keep commas to the engine)
        body = body.replace("—", "—<break time='160ms'/>").replace("…", "<break time='180ms'/>…")

        parts.append(f"<s><prosody pitch='{pitch}' rate='{rate}' volume='{volume}'>{body}</prosody></s>")
        parts.append(f"<break time='{dynamic_break_time(s_type, emotion)}'/>")

    # long final pause so it feels like waiting for user
    return f"<speak><p>{''.join(parts)}<break time='750ms'/></p></speak>"


# ---------------- Audio post-processing (only mastering) ----------------
def _post_process_audio(audio_path: str):
    """
    Apply light mastering (fade-in/out + slight gain).
    Skips gracefully if pydub not available.
    """
    if not PYDUB_OK:
        return
    try:
        voice = AudioSegment.from_file(audio_path)
        voice = (voice.fade_in(60).fade_out(90)) - 1.0  # soften edges, reduce gain
        voice.export(audio_path, format="mp3")
    except Exception as e:
        print(f"[Note] Post-processing skipped: {e}")


# ---------------- Synthesizer ----------------
def synthesize_dynamic_speech(
    text,
    voice_name="en-US-Wavenet-C",
    language_code="en-US",
    speaking_rate=1.0,
    pitch=0.0
):
    print(f"Generating speech with voice: {voice_name} | Language: {language_code}")
    ssml_text = create_dynamic_ssml(text)
    print("Generated SSML:\n", ssml_text)

    input_text = texttospeech.SynthesisInput(ssml=ssml_text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch,
        effects_profile_id=["wearable-class-device"],
        sample_rate_hertz=24000
    )

    response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    audio_file = f"dynamic_output_{random.randint(1000, 9999)}.mp3"
    with open(audio_file, "wb") as out:
        out.write(response.audio_content)

    _post_process_audio(audio_file)

    try:
        play_audio(audio_file)
    finally:
        try:
            os.remove(audio_file)
        except OSError:
            pass


# ---------------- Test text ----------------
test_text = (
    "Hello boss, it’s Jarvis reporting in. "
    "System check complete—everything is stable, and no major issues were detected. "
    "However, there is one critical update: the database temperature is rising slowly, and if ignored, it could lead to a failure. "
    "CPU usage is at 72%, memory load is steady, and profits have increased by 15%. "
    "Would you like me to activate additional cooling, or should I keep monitoring? "
    "Meanwhile, an external login attempt was flagged on the secure server in Helsinki. "
    "Do you want me to lock it down immediately? "
    "On a brighter note, Centria University just published the quarterly report. "
    "The results are overwhelmingly positive! "
    "Would you like me to prepare a detailed presentation, or just the highlights? "
    "Lastly, the energy grid is stable, but a backup battery warning appeared at 3:45 p.m. "
    "Shall I run a full diagnostic sweep now, boss?"
)

if __name__ == "__main__":
    synthesize_dynamic_speech(
        text=test_text,
        voice_name="en-US-Neural2-F",  # very natural; try Neural2-C for calmer tone
        language_code="en-US",
        speaking_rate=1.0,
    )
