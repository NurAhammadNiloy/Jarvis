"""Audio compatibility helpers routed through the single cancellable output owner."""
import array
import math
import os
import sys
from core.speech_output import PCMClip


def play_audio(audio_file):
    """Legacy file player for the voice experiments; removes the file afterward.

    Active TTS uses PCM directly and needs neither temporary files nor FFmpeg.
    The experiment-only MP3 path lazily uses pydub's existing decoder.
    """
    from core.speech_synthesis import get_speech_controller
    try:
        if str(audio_file).lower().endswith('.wav'):
            with open(audio_file, 'rb') as source:
                clip = PCMClip.from_wav(source.read())
        else:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_file).set_sample_width(2)
            clip = PCMClip(audio.raw_data, audio.frame_rate, audio.channels)
        job = get_speech_controller().submit('', clip=clip)
        job.wait()
        if job.error:
            raise job.error
        return job
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)


def play_audio_cue(cue_type='milestone', volume=0.4):
    """Chimes share queue ownership/cancellation with voice; no overlapping players."""
    from core.speech_synthesis import get_speech_controller
    frequencies, duration = {
        'subtle': ([880], 0.1), 'milestone': ([660], 0.15),
        'warning': ([600, 800], 0.2), 'complete': ([523, 659, 784], 0.4),
        'urgent': ([800, 600, 800, 600], 0.5),
    }.get(cue_type, ([660], 0.15))
    rate = 24000
    count = int(rate * duration)
    segment = max(1, count // len(frequencies))
    samples = array.array('h')
    volume = max(0, min(volume, 1))
    for i in range(count):
        frequency = frequencies[min(i // segment, len(frequencies) - 1)]
        envelope = min(1, (i % segment) / 240, (segment - i % segment) / 240)
        samples.append(int(math.sin(2 * math.pi * frequency * i / rate) * envelope * volume * 32767))
    if sys.byteorder != 'little':
        samples.byteswap()
    return get_speech_controller().submit('', clip=PCMClip(samples.tobytes(), rate))
