"""Record your voice for wake-word tuning and the speech-recognition benchmark.

    env\\Scripts\\python.exe -B tools\\record_voice.py              (everything, about 9 minutes)
    env\\Scripts\\python.exe -B tools\\record_voice.py --only wake  (one part again: wake, speech, background, commands)
    env\\Scripts\\python.exe -B tools\\record_voice.py --only background --scenario video   (1-2 minutes)
    env\\Scripts\\python.exe -B tools\\record_voice.py --check      (microphone noise and clipping in the recordings)

Parts:
  wake        "Hey Jarvis" 30 times, varied (normal, quick, quiet, tired, farther away)   ~2.5 min
  speech      2 minutes of your normal speech WITHOUT the wake word (read aloud, then talk) ~2 min
  background  1 minute of whatever usually plays around you (optional, press s to skip)   ~1 min
  commands    20 short commands read from a list, saved with the exact text              ~3 min

Scenarios (--only background --scenario NAME): one situation at a time, 90 seconds by default
(--seconds to change): quiet, talking, video, household, or a name of your own. They are
saved in data/voice/background/NAME/ and add to earlier recordings, no --fresh needed.

Everything is stored in data/voice/ (gitignored). Nothing is uploaded or sent anywhere.
Re-running a part adds to it; --fresh deletes that part's old recordings first.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLE_RATE, FRAME_MS = 16000, 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2

WAKE_PROMPTS = (
    ['normally'] * 10 + ['quickly'] * 5 + ['quietly'] * 5 + ['tired, slowly'] * 5
    + ['from a little farther away (lean back or turn your head)'] * 5)

# Read aloud: everyday speech, with words that sound a little like "Hey Jarvis".
SPEECH_TEXT = """\
Hey there, how are you doing today? I think the service was nervous about the harvest.
Travis said the jar of jam is in the garage, next to the jars and the jacket.
Hey, did you check the timetable for the lecture on Thursday?
I have an assignment due next week, and I still need to finish the report.
Can you pass me the charger? Harvey is coming over later, so let's make dinner.
The weather looks cloudy, but it might clear up in the afternoon.
Okay, let's go. Hey, wait for me. Service, nervous, harvest, Davis, Jervis, Marvin.
Now keep talking about anything: your day, your plans, what you are studying.
(Just never say "Hey Jarvis".)"""

COMMANDS = (
    'set a timer for 10 minutes called tea',
    'add 5 minutes to the tea timer',
    'pause the pasta timer',
    'how much time is left on the timer',
    'cancel all timers',
    'remind me to call my mom in 10 minutes',
    'remind me about stand up every Monday at 9 am',
    'set an alarm for 6:30 tomorrow morning',
    'what are my reminders',
    'delete the dentist reminder',
    'snooze it for 10 minutes',
    "what's the weather today",
    'should I wear a jacket',
    "what's the forecast for tomorrow",
    'what time is it',
    "what's the date today",
    'play lofi music on YouTube',
    'tell me about the play Hamlet',
    "what's going on in the universe right now",
    'yes do it',
)


# --- capture (microphone-free, so it can be tested) ------------------------------------------

def read_seconds(frames, seconds):
    """`seconds` of audio from a frame source (MicrophoneFrames or a fake)."""
    audio, needed = bytearray(), int(seconds * 1000 / FRAME_MS)
    while needed > 0:
        try:
            frame = frames.read(timeout=0.1)
        except OverflowError:  # a few frames were lost; keep going
            continue
        if frame is not None:
            audio += frame
            needed -= 1
    return bytes(audio)


def voiced_ms(audio, vad):
    return sum(1 for i in range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES)
               if vad(audio[i:i + FRAME_BYTES])) * FRAME_MS


def read_utterance(frames, vad, wait_seconds=6, silence_ms=1200, max_seconds=10):
    """One spoken utterance: from the first speech to `silence_ms` of silence, with
    0.3 s before it. None if nothing was said within `wait_seconds`."""
    before, audio, silent, waited = [], bytearray(), 0, 0
    while True:
        frame = read_seconds(frames, FRAME_MS / 1000)
        speaking = vad(frame)
        if not audio:
            before = (before + [frame])[-15:]
            waited += FRAME_MS
            if speaking:
                audio += b''.join(before)
            elif waited >= wait_seconds * 1000:
                return None
            continue
        audio += frame
        silent = 0 if speaking else silent + FRAME_MS
        if silent >= silence_ms or len(audio) >= max_seconds * SAMPLE_RATE * 2:
            return bytes(audio)


# --- storage ----------------------------------------------------------------------------

def write_wav(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(SAMPLE_RATE)
        clip.writeframes(audio)
    return path


def next_path(folder, prefix):
    """folder/prefix_NNN.wav after the existing ones."""
    numbers = [int(p.stem.rsplit('_', 1)[-1]) for p in folder.glob(f'{prefix}_*.wav') if p.stem.rsplit('_', 1)[-1].isdigit()]
    return folder / f'{prefix}_{max(numbers, default=0) + 1:03d}.wav'


def add_to_manifest(folder, path, text):
    with open(folder / 'manifest.jsonl', 'a', encoding='utf-8') as manifest:
        manifest.write(json.dumps({'file': path.name, 'text': text,
                                   'recorded_at': datetime.now().isoformat(timespec='seconds')}) + '\n')


def clip_note(audio):
    """A warning when a clip clipped (too loud for the microphone level)."""
    import numpy as np
    from core.wake_word import audio_levels
    clipped = audio_levels(np.frombuffer(audio, dtype=np.int16))['clipped']
    return f', CLIPPED ({clipped} samples): lower the mic level' if clipped else ''


def check(voice_dir):
    """Microphone health of the recordings so far, per part: noise floor, loudest moment,
    and which clips clipped."""
    import statistics
    from core.wake_word import NOISY_FLOOR_DB, audio_levels, read_wav
    lines = []
    for part in ('wake', 'speech', 'background', 'commands'):
        clips = sorted((Path(voice_dir) / part).rglob('*.wav'))
        if not clips:
            lines.append(f'{part}: no recordings')
            continue
        levels = {clip.relative_to(Path(voice_dir) / part).as_posix(): audio_levels(read_wav(clip)) for clip in clips}
        clipped = [name for name, level in levels.items() if level['clipped']]
        floor = statistics.median(level['noise_floor_db'] for level in levels.values())
        lines.append(f'{part}: {len(clips)} clips, noise floor {floor:.0f} dBFS, loudest '
                     f"{max(level['loudest_db'] for level in levels.values()):.0f} dBFS, "
                     + (f"clipped in {len(clipped)}: {', '.join(clipped[:5])}{' ...' if len(clipped) > 5 else ''}"
                        if clipped else 'no clipping'))
        if clipped:
            lines.append('  warning: lower the microphone level (Windows Settings > System > Sound > Input volume) '
                         f'and record this part again with --only {part} --fresh.')
        if part != 'background' and floor > NOISY_FLOOR_DB:
            lines.append(f'  warning: the noise floor is high for a headset (above {NOISY_FLOOR_DB} dBFS): hiss, hum '
                         'or fan noise on the mic. Check the plug, or lower the mic boost.')
    return lines


def clear(folder):
    for path in list(folder.glob('*.wav')) + list(folder.glob('manifest.jsonl')):
        path.unlink()


# --- the parts ----------------------------------------------------------------------------

def record_wake(frames, vad, folder, score=None, prompts=WAKE_PROMPTS, wait=input):
    print(f'\nPart 1: say "Hey Jarvis" {len(prompts)} times, the way the prompt says. Each time you have 3 seconds.')
    wait('Press Enter to start. ')
    number = 0
    while number < len(prompts):
        print(f'  ({number + 1}/{len(prompts)}) "Hey Jarvis", {prompts[number]}... ', end='', flush=True)
        audio = read_seconds(frames, 3)
        if voiced_ms(audio, vad) < 200:
            print("I didn't hear you; again.")
            continue
        path = write_wav(next_path(folder, 'hey_jarvis'), audio)
        print('saved' + (f', plain-model score {score(audio):.2f}' if score else '') + clip_note(audio), f'({path.name})')
        number += 1
        read_seconds(frames, 0.7)


def record_speech(frames, folder, seconds=120, chunk=10, wait=input):
    print(f'\nPart 2: {seconds // 60} minutes of your normal speech, WITHOUT "Hey Jarvis".')
    print('Read this aloud at your normal pace, then keep talking about anything:\n')
    print(SPEECH_TEXT, '\n')
    wait('Press Enter and start reading. ')
    for start in range(0, seconds, chunk):
        write_wav(next_path(folder, 'speech'), read_seconds(frames, chunk))
        print(f'  {start + chunk} of {seconds} s', end='\r', flush=True)
    print('\n  done.')


def record_background(frames, folder, seconds=60, wait=input, scenario=None):
    """Background sound as negatives. With a scenario, one situation (folder/<scenario>/),
    added to what is there; without, the optional part 3 of a full recording."""
    from core.wake_word import SCENARIOS
    if scenario:
        folder = folder / scenario
        print(f'\nScenario "{scenario}": {seconds} seconds of {SCENARIOS.get(scenario, scenario)}.')
        print("Stay quiet yourself (don't say \"Hey Jarvis\"). This teaches the tuning what is NOT you.")
        wait('Set it up, then press Enter to record. ')
    else:
        print(f'\nPart 3: {seconds} seconds of what usually plays around you (a video, music, TV, people talking).')
        print("Start it now and stay quiet. This teaches the tuning what is NOT you saying the wake word.")
        if wait('Press Enter to record, or type s and Enter to skip. ').strip().lower() == 's':
            print('  skipped.')
            return
    for start in range(0, seconds, 10):
        write_wav(next_path(folder, 'background'), read_seconds(frames, 10))
        print(f'  {start + 10} of {seconds} s', end='\r', flush=True)
    print('\n  done.')


def record_commands(frames, vad, folder, commands=COMMANDS, wait=input):
    print(f'\nPart 4: read {len(commands)} commands aloud, exactly as written, without "Hey Jarvis".')
    print('Speak when the command appears; it stops after you pause.')
    wait('Press Enter to start. ')
    number = 0
    while number < len(commands):
        text = commands[number]
        print(f'  ({number + 1}/{len(commands)}) "{text}"  ', end='', flush=True)
        audio = read_utterance(frames, vad)
        if audio is None:
            print("I didn't hear you; again.")
            continue
        path = write_wav(next_path(folder, 'command'), audio)
        add_to_manifest(folder, path, text)
        print(f'saved ({path.name}, {len(audio) / (SAMPLE_RATE * 2):.1f} s){clip_note(audio)}')
        number += 1
        read_seconds(frames, 0.5)


def main():
    from core.voice_capture import MicrophoneFrames, VoiceConfig, create_vad
    from core.wake_word import VOICE_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', choices=['wake', 'speech', 'background', 'commands'])
    parser.add_argument('--scenario', help='with --only background: the situation (quiet, talking, video, household, '
                        'or your own name); adds to earlier recordings of it')
    parser.add_argument('--seconds', type=int, default=None, help='length of a background recording (default 60; 90 for a scenario)')
    parser.add_argument('--fresh', action='store_true', help="delete the chosen parts' old recordings first")
    parser.add_argument('--check', action='store_true', help='check the recordings for mic noise and clipping (no recording)')
    parser.add_argument('--device', default=None, help='input device name or index (default: the system microphone)')
    args = parser.parse_args()
    if args.check:
        for line in check(VOICE_DIR):
            print(line)
        return
    if args.scenario and args.only != 'background':
        parser.error('--scenario goes with --only background')
    scenario = None
    if args.scenario:
        from core.wake_word import scenario_name
        scenario = scenario_name(args.scenario)
    parts = [args.only] if args.only else ['wake', 'speech', 'background', 'commands']
    folders = {part: VOICE_DIR / part for part in parts}
    if scenario:
        folders['background'] = VOICE_DIR / 'background' / scenario
    if args.fresh:
        for folder in folders.values():
            if folder.exists():
                clear(folder)

    device = int(args.device) if args.device and args.device.isdigit() else args.device
    config = VoiceConfig(input_device=device, vad_mode=2)
    vad = create_vad(config)
    score = None
    if 'wake' in parts:
        score = _plain_score()
    print(f'Recording to {VOICE_DIR} (local only). Use your usual microphone, as you would with Jarvis.')
    with MicrophoneFrames(config) as frames:
        read_seconds(frames, 0.5)  # let the microphone settle
        if 'wake' in parts:
            record_wake(frames, vad, folders['wake'], score)
        if 'speech' in parts:
            record_speech(frames, folders['speech'])
        if 'background' in parts:
            record_background(frames, VOICE_DIR / 'background' if scenario else folders['background'],
                              seconds=args.seconds or (90 if scenario else 60), scenario=scenario)
        if 'commands' in parts:
            record_commands(frames, vad, folders['commands'])
    print('')
    for line in check(VOICE_DIR):
        print(line)
    print('\nAll done. Next: env\\Scripts\\python.exe -B tools\\train_wake_verifier.py')


def _plain_score():
    """The plain model's peak score for a clip, shown while recording (just for information)."""
    import numpy as np
    from core.wake_word import clip_frames, load_model
    model = load_model()
    return lambda audio: max((s for s, _ in clip_frames(model, np.frombuffer(audio, dtype=np.int16))), default=0.0)


if __name__ == '__main__':
    started = time.monotonic()
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. What was recorded so far is kept.')
    print(f'({(time.monotonic() - started) / 60:.1f} minutes)')
