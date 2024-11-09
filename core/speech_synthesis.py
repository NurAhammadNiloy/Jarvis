from google.cloud import texttospeech
from config.credentials import credentials
import random
from utils.audio_utils import play_audio

# Initialize the client
client = texttospeech.TextToSpeechClient(credentials=credentials)

def create_dynamic_ssml(
    text, 
    emphasis_level="moderate", 
    pitch="+5%", 
    break_time="300ms", 
    keyword_emphasis=None
):
    """Create SSML content dynamically with custom emphasis and prosody."""
    if keyword_emphasis is None:
        keyword_emphasis = []

    phrases = text.split(". ")
    ssml_parts = []

    for phrase in phrases:
        if phrase:
            for keyword in keyword_emphasis:
                if keyword.lower() in phrase.lower():
                    phrase = phrase.replace(
                        keyword, f"<emphasis level='strong'>{keyword}</emphasis>"
                    )
            ssml_part = (
                f"<emphasis level='{emphasis_level}'>{phrase}</emphasis>"
                f"<break time='{break_time}'/>"
            )
            ssml_parts.append(ssml_part)

    ssml_content = f"<speak><prosody pitch='{pitch}'>{''.join(ssml_parts)}</prosody></speak>"
    return ssml_content

def synthesize_speech(
    text, 
    use_ssml=False, 
    emphasis_level="moderate", 
    pitch="+5%", 
    break_time="300ms", 
    keyword_emphasis=None,
    voice_name="en-GB-Journey-D",  # Ensure this is included
    language_code="en-GB"
):
    """Generate speech using SSML or plain text with dynamic adjustments."""
    if use_ssml:
        ssml_text = create_dynamic_ssml(
            text, emphasis_level, pitch, break_time, keyword_emphasis
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
        audio_encoding=texttospeech.AudioEncoding.MP3,  # Use LINEAR16 for higher quality if needed
        sample_rate_hertz=24000,
        pitch=0.0,
        speaking_rate=1.0
    )
    
    response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    audio_file = f"output_{random.randint(1000, 9999)}.mp3"
    
    with open(audio_file, "wb") as out:
        out.write(response.audio_content)
    play_audio(audio_file)
