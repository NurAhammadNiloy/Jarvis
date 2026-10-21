import os
import random
import re
from google.cloud import texttospeech
from config.credentials import credentials
from utils.audio_utils import play_audio

# Initialize the client
client = texttospeech.TextToSpeechClient(credentials=credentials)

def create_expressive_ssml(
    text,
    emotion="neutral",
    emphasis_level="moderate",
    break_time="300ms",
    keyword_emphasis=None,
    question_phrases=None
):
    """Create expressive SSML with dynamic emphasis and prosody."""
    if keyword_emphasis is None:
        keyword_emphasis = []
    if question_phrases is None:
        question_phrases = ["?", "Would you", "Can you", "What", "Why", "How"]

    # Emotion-based adjustments
    emotion_settings = {
        "neutral": {"pitch": "0%", "rate": "95%", "volume": "medium"},
        "calm": {"pitch": "-2%", "rate": "90%", "volume": "soft"},
        "curious": {"pitch": "+5%", "rate": "100%", "volume": "medium"},
        "excited": {"pitch": "+10%", "rate": "105%", "volume": "loud"},
        "urgent": {"pitch": "+8%", "rate": "110%", "volume": "medium"},
    }
    pitch = emotion_settings[emotion]["pitch"]
    rate = emotion_settings[emotion]["rate"]
    volume = emotion_settings[emotion]["volume"]

    # Split text into sentences for dynamic handling
    phrases = re.split(r"(?<=[.?!])\s*", text)
    ssml_parts = []

    for phrase in phrases:
        if not phrase.strip():
            continue

        # Detect if it's a question
        if any(phrase.strip().lower().startswith(q.lower()) for q in question_phrases):
            phrase = (
                f"<prosody pitch='+10%' rate='95%'>{phrase.strip()}</prosody>"
                f"<break time='{break_time}'/>"
            )
        else:
            # Apply general emphasis and prosody
            for keyword in keyword_emphasis:
                phrase = re.sub(
                    rf"(?i)\b{re.escape(keyword)}\b",
                    f"<emphasis level='{emphasis_level}'>{keyword}</emphasis>",
                    phrase
                )
            phrase = (
                f"<prosody pitch='{pitch}' rate='{rate}' volume='{volume}'>"
                f"{phrase.strip()}</prosody>"
                f"<break time='{break_time}'/>"
            )

        ssml_parts.append(phrase)

    # Combine into SSML with overall adjustments
    ssml_content = f"<speak>{''.join(ssml_parts)}</speak>"
    return ssml_content


def synthesize_speech_expressive(
    text,
    use_ssml=False,
    emotion="neutral",
    emphasis_level="moderate",
    break_time="300ms",
    keyword_emphasis=None,
    voice_name="en-US-Wavenet-D",  # Choose expressive voice
    language_code="en-US",
    sample_rate_hertz=24000,
    pitch_adjustment=0.0,
    speaking_rate=1.0
):
    """Generate expressive speech using SSML or plain text with dynamic adjustments."""
    try:
        if use_ssml:
            ssml_text = create_expressive_ssml(
                text, emotion, emphasis_level, break_time, keyword_emphasis
            )
            input_text = texttospeech.SynthesisInput(ssml=ssml_text)
        else:
            input_text = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
            ssml_gender=texttospeech.SsmlVoiceGender.MALE
        )

        audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        sample_rate_hertz=sample_rate_hertz,
        pitch=pitch_adjustment,
        speaking_rate=speaking_rate,
        effects_profile_id=["wearable-class-device"]
        )


        response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
        audio_file = f"temp_output_{random.randint(1000, 9999)}.mp3"

        with open(audio_file, "wb") as out:
            out.write(response.audio_content)

        play_audio(audio_file)

        # Clean up temporary file
        os.remove(audio_file)

    except Exception as e:
        print(f"Error synthesizing speech: {e}")


# Test the function with expressive SSML
if __name__ == "__main__":
    # Example 1: Neutral Update
    test_text = (
        "Good morning, Boss. Here is your update: "
        "You have 3 meetings scheduled today, starting at 10 AM. "
        "Would you like me to remind you 15 minutes before each one?"
    )
    synthesize_speech_expressive(
        text=test_text,
        use_ssml=True,
        emotion="neutral",
        emphasis_level="moderate",
        break_time="300ms",
        keyword_emphasis=["update", "meetings", "remind"],
        voice_name="en-US-Wavenet-C",
        language_code="en-US"
    )

    # Example 2: Calm Alert
    calm_text = (
        "The room temperature has increased to 30 degrees Celsius. "
        "This is higher than usual. Would you like me to turn on the air conditioning?"
    )
    synthesize_speech_expressive(
        text=calm_text,
        use_ssml=True,
        emotion="calm",
        emphasis_level="moderate",
        break_time="300ms",
        keyword_emphasis=["temperature", "air conditioning"],
        voice_name="en-US-Wavenet-C",
        language_code="en-US"
    )

    # Example 3: Curious Query
    curious_text = (
        "I noticed you’ve been sitting for a while. "
        "Would you like me to set a reminder for a quick break?"
    )
    synthesize_speech_expressive(
        text=curious_text,
        use_ssml=True,
        emotion="curious",
        emphasis_level="moderate",
        break_time="300ms",
        keyword_emphasis=["reminder", "break"],
        voice_name="en-US-Wavenet-C",
        language_code="en-US"
    )
