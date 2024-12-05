from google.cloud import texttospeech
from config.credentials import credentials
import random
from utils.audio_utils import play_audio
import spacy
from textblob import TextBlob


# Initialize the client
client = texttospeech.TextToSpeechClient(credentials=credentials)

# Load the spaCy NLP model
nlp = spacy.load("en_core_web_trf")


def analyze_text_context(sentence_text):
    """
    Analyze the context of a sentence to determine tone, emotion, and sentiment.
    """
    sentiment = TextBlob(sentence_text).sentiment
    polarity = sentiment.polarity  # Determines positive or negative sentiment
    subjectivity = sentiment.subjectivity  # Determines fact vs. opinion

    # Default tone and emotion
    tone = "neutral"
    emotion = "none"

    # Adjust based on sentiment polarity
    if polarity > 0.5:
        tone = "positive"
        emotion = "happy"
    elif polarity < -0.5:
        tone = "negative"
        emotion = "concerned"
    elif 0 < polarity <= 0.5:
        tone = "slightly positive"
        emotion = "encouraging"
    elif -0.5 <= polarity < 0:
        tone = "slightly negative"
        emotion = "worried"

    return tone, emotion


def analyze_sentence_type(sentence_text):
    """
    Determine the type of sentence (question, command, exclamation, or statement).
    """
    if sentence_text.endswith("?"):
        return "question"
    elif sentence_text.endswith("!"):
        return "exclamation"
    elif sentence_text.split()[0].lower() in ["please", "do", "execute", "run"]:
        return "command"
    else:
        return "statement"


def detect_critical_words(sentence_text, entities):
    """
    Detect critical/emergency words in the sentence based on context and predefined keywords.
    """
    critical_keywords = ["warning", "immediate", "critical", "danger", "failure", "caution", "error", "rising"]

    # Analyze the sentence with spaCy
    doc = nlp(sentence_text)
    critical_words = set()

    # Add named entities for emphasis
    for entity in entities:
        critical_words.add(entity)

    # Add predefined critical keywords
    for word in critical_keywords:
        if word.lower() in sentence_text.lower():
            critical_words.add(word)

    # Include only impactful nouns and proper nouns
    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"] and token.text.lower() in critical_keywords:
            critical_words.add(token.text)

    return critical_words


def dynamic_break_time(sentence_type, emotion):
    """
    Determine appropriate break time based on sentence type and emotion.
    """
    if sentence_type == "question":
        return "400ms"
    elif sentence_type == "exclamation":
        return "300ms"
    elif emotion == "concerned":
        return "700ms"
    else:
        return "500ms"


def create_dynamic_ssml(text):
    """
    Generate SSML with fine-grained dynamic adjustments for human-like speech.
    """
    doc = nlp(text)
    ssml_parts = []

    for sentence in doc.sents:
        sentence_text = sentence.text.strip()
        entities = {ent.text: ent.label_ for ent in sentence.ents}

        # Detect critical/emergency words
        critical_words = detect_critical_words(sentence_text, entities)

        # Analyze sentence context and type
        tone, emotion = analyze_text_context(sentence_text)
        sentence_type = analyze_sentence_type(sentence_text)

        # Default prosody settings for the sentence
        sentence_pitch = "0%"
        sentence_rate = "95%"
        sentence_volume = "medium"
        sentence_break_time = dynamic_break_time(sentence_type, emotion)

        # Adjust prosody based on sentence type and emotion
        if sentence_type == "question":
            sentence_pitch = "+8%"
            sentence_rate = "100%"
        elif sentence_type == "exclamation":
            sentence_pitch = "+10%"
            sentence_rate = "105%"
            sentence_volume = "medium-loud"
        elif sentence_type == "command":
            sentence_pitch = "+5%"
        elif emotion == "happy":
            sentence_pitch = "+10%"
            sentence_rate = "100%"
            sentence_volume = "medium-loud"
        elif emotion == "concerned":
            sentence_pitch = "-5%"
            sentence_rate = "90%"
            sentence_volume = "medium-soft"

        # Build SSML for critical/emergency words and handle contractions
        words = sentence_text.split()
        phrase_ssml_parts = []
        i = 0

        while i < len(words):
            word = words[i]

            # Handle contractions (e.g., "What 's" -> "What's")
            if i < len(words) - 1 and words[i + 1] in ["'s", "'ve", "'ll", "'re", "n't"]:
                word = word + words[i + 1]
                i += 1  # Skip the next word (part of the contraction)

            # Apply emphasis only to critical/emergency words
            if word.lower() in critical_words:
                word_ssml = f"<prosody pitch='+10%' rate='100%'>{word}</prosody>"
            else:
                word_ssml = word

            phrase_ssml_parts.append(word_ssml)
            i += 1

        # Combine words into a sentence-level prosody
        phrase_text = " ".join(phrase_ssml_parts)
        sentence_ssml = (
            f"<prosody pitch='{sentence_pitch}' rate='{sentence_rate}' volume='{sentence_volume}'>"
            f"{phrase_text}</prosody>"
        )
        ssml_parts.append(sentence_ssml)
        ssml_parts.append(f"<break time='{sentence_break_time}'/>")

    # Combine all sentences into the final SSML output
    return f"<speak>{''.join(ssml_parts)}</speak>"

def synthesize_speech(
    text,
    voice_name="en-US-Wavenet-C",
    language_code="en-US",
    speaking_rate=1.1,
    pitch=0.0
):
    """
    Generate expressive speech using Google Cloud TTS with dynamic SSML.
    """
    print(f"Generating speech with voice: {voice_name} | Language: {language_code}")

    # Generate dynamic SSML
    ssml_text = create_dynamic_ssml(text)
    print("Generated SSML:")
    print(ssml_text)

    input_text = texttospeech.SynthesisInput(ssml=ssml_text)

    # Configure voice
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    )

    # Audio configuration
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch,
        effects_profile_id=["wearable-class-device"],
        sample_rate_hertz=24000
    )

    # Generate audio
    response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    audio_file = f"Output_{random.randint(1000, 9999)}.mp3"
    
    with open(audio_file, "wb") as out:
        out.write(response.audio_content)
    play_audio(audio_file)
