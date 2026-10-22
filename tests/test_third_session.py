"""Regressions from the third 22 Oct 2026 voice session (runs 6a7258d4 and 26c7df06).

Transcripts, confidences and alternatives are copied exactly from
logs/conversation.jsonl; the clock is frozen at 11:24:42 Helsinki.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core import conversation_log
from core.assistant import Assistant
from core.command_services import CommandServices
from core.conversation_log import record, record_recognition
from core.dialogue import Dialogue
from core.live_transcript import LiveTranscript
from core.speech_output import SpeechSnapshot
from core.voice_capture import AudioUtterance, VoiceConfig
from core.voice_policy import Hypothesis, Recognition
from core.voice_runtime import ContinuousListener


def heard(text, confidence, *alternatives, playback_id=None):
    return Recognition(text, confidence, tuple(Hypothesis(t, c) for t, c in alternatives), playback_id=playback_id)


PHONE = heard('how to check the phone please', 0.33169705,                                   # 26c7df06 72
              ('how to check the phone number', 0.32207173), ('how to check the phone minutes', 0.361873),
              ('how to check the phone', 0.37607941), ('hHow to check the phone please', 0.33169705))
SUPERMAN = heard('who won against Superman', 0.12673612, ('who won against the game', 0.16716181))  # 81
STOP_JARVIS = heard('Jarvis stop Jarvis', 0.77225667,                                         # 411
                    ('Jarvis stopped Jarvis', 0.77225667), ('Jarvis top Jarvis', 0.65541339),
                    ('Yarvis stop Jarvis', 0.77225667), ('Jarvis stop Yarvis', 0.77225667), playback_id=14)
STOP_STOP = heard('Jarvis stop Jarvis stop', 0.73329186,                                      # 6a7258d4 248
                  ('Jarvis stop Jarvis stopped', 0.73329186), ('Jarvis stop Yarvis stop', 0.73329186),
                  ('Yarvis stop Jarvis stop', 0.73329198), ('stop Jarvis stop', 0.69436294), playback_id=10)
WEAK_STOP = heard('Jarvis stop', 0.64726031, ('Jarvis stopped', 0.64726031),                 # 6a7258d4 219
                  ('Jarvis stahp', 0.64726037), ('Yarvis stop', 0.64726031), ('Jarvis stoppe', 0.64726037),
                  playback_id=9)
GENESIS = heard('Genesis stop', 0.40416569, ('Galaxy stop', 0.5173704),                       # 366
                ('Genesis stopped', 0.40416569), ('Genesys stop', 0.40416569), ('Genisys stop', 0.40416569),
                playback_id=13)
ALARM_FROM = heard('set an alarm from 2 minutes from now', 0.97113955)                        # 33
I_SAID = heard('I said Jarvis set an alarm for 2 minutes from now', 0.89875638,              # 6a7258d4 71
               ('Ice Age Jarvis set an alarm for 2 minutes from now', 0.83718908),
               ('I said Yarvis set an alarm for 2 minutes from now', 0.89875638),
               ('Ice Age Yarvis set an alarm for 2 minutes from now', 0.83718908))
SET_ALARM = heard('Jarvis set an alarm', 0.79171795, ('Yarvis set an alarm', 0.79171795),     # 126
                  ('Jerry set an alarm', 0.7678414), ('Jervis set an alarm', 0.78505975),
                  ('service set an alarm', 0.8261044))
IN_TWO_MINUTES = heard('in 2 minutes', 0.70887375)                                            # 150
BANGLADESH = heard('Jarvis tell me the history of Bangladesh', 0.93009281,                   # 333
                   ('Yarvis tell me the history of Bangladesh', 0.93009281))
BANGLADESH_REPLY = 'Bangladesh gained independence from Pakistan in 1971 after a liberation war.'
NOISE = Recognition(error='unrecognized')                                                     # 336

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 11, 24, 42, tzinfo=TZ)

# Fails on the code as it was during the session; removed as each step fixes it.
baseline = pytest.mark.xfail(strict=True, reason='baseline: fails before the fix')


@pytest.fixture
def jarvis(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    reminders = ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=lambda: NOW)
    services = CommandServices(Mock(), reminders=reminders, now=lambda: NOW)
    resolver = Mock(return_value={'reply': 'Could you clarify?', 'query': None})
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = False
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0,
                          dialogue=Dialogue(resolver, clock=lambda: 0))
    return SimpleNamespace(
        hear=assistant.process_recognition, assistant=assistant, resolver=resolver, output=output, speech=speech,
        said=lambda: [call.args[0] for call in output.call_args_list],
        stored=lambda: [(r.kind, r.text, r.due) for r in reminders.store.pending()])


# --- low confidence without the wake word ---------------------------------------------

@pytest.mark.parametrize('overheard', [PHONE, SUPERMAN], ids=['phone 0.33', 'Superman 0.13'])
def test_weak_speech_without_wake_word_is_ignored_when_nothing_is_pending(jarvis, overheard):
    assert not jarvis.hear(overheard)  # active mode: no wake word needed, but 0.5 confidence is
    jarvis.output.assert_not_called()
    jarvis.resolver.assert_not_called()


# --- stop -------------------------------------------------------------------------------

@pytest.mark.parametrize('stop', [pytest.param(STOP_JARVIS, marks=baseline), pytest.param(STOP_STOP, marks=baseline),
                                  WEAK_STOP, pytest.param(GENESIS, marks=baseline)],
                         ids=['Jarvis stop Jarvis', 'Jarvis stop Jarvis stop', 'Jarvis stop 0.65', 'Genesis stop'])
def test_stop_heard_over_jarvis_stops_without_the_model(jarvis, stop):
    jarvis.hear(stop)
    jarvis.speech.stop.assert_called_with(expected_id=stop.playback_id)
    jarvis.resolver.assert_not_called()
    jarvis.output.assert_not_called()


def speakers_listener(recognition):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot(13, BANGLADESH_REPLY, True)
    listener = ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: recognition, speech,
                                  VoiceConfig(echo_mode='speakers'))
    return listener, speech


@baseline
@pytest.mark.parametrize('stop', [GENESIS, STOP_JARVIS, WEAK_STOP], ids=['Genesis stop', 'Jarvis stop Jarvis', 'Jarvis stop 0.65'])
def test_short_stop_during_playback_interrupts_in_speakers_mode(stop):
    listener, speech = speakers_listener(stop)
    result = listener.handle_final(AudioUtterance(b'pcm', playback_id=stop.playback_id, playback_text=BANGLADESH_REPLY))
    assert result is not None and result.text == stop.text
    speech.stop.assert_called_once_with(expected_id=stop.playback_id)


@baseline
def test_short_stop_interrupts_from_a_partial_recognition_too():
    listener, speech = speakers_listener(GENESIS)
    speech.stop.return_value = True
    assert listener.handle_interruption(AudioUtterance(b'pcm', playback_id=13, playback_text=BANGLADESH_REPLY))
    speech.stop.assert_called_once_with(expected_id=13)


# --- alarms --------------------------------------------------------------------------------

@baseline
def test_alarm_without_a_real_label_has_none(jarvis):
    jarvis.hear(ALARM_FROM)
    assert jarvis.said() == ['Alarm set for today at 11:26 AM.']
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


@baseline
def test_words_before_jarvis_are_not_the_alarm_label(jarvis):
    jarvis.hear(I_SAID)          # alternatives differ ('I said' / 'Ice Age'): confirmed first
    jarvis.hear(heard('yes', 0.6191988))
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


@baseline
def test_slot_answer_that_parses_is_accepted_at_0_5(jarvis):
    jarvis.hear(SET_ALARM)
    assert jarvis.said() == ['What time should I set the alarm for?']
    jarvis.hear(IN_TWO_MINUTES)
    assert jarvis.said()[-1] == 'Alarm set for today at 11:26 AM.'
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


# --- the terminal --------------------------------------------------------------------------

def test_reply_is_printed_on_the_line_of_the_utterance_that_caused_it(jarvis):
    # The listener logs the next (unrecognized) utterance before ChatGPT has answered.
    jarvis.resolver.return_value = {'reply': BANGLADESH_REPLY, 'query': None}
    jobs = iter(range(13, 20))

    def speak(text):
        job = next(jobs)
        record('speech_queued', role='jarvis', text=text, playback_id=job)
        record('playback_chunk_started', playback_id=job, text=text)
    jarvis.output.side_effect = speak
    lines = []
    printer = LiveTranscript(out=lines.append)
    conversation_log.add_listener(printer)
    try:
        record_recognition(BANGLADESH)
        record_recognition(NOISE)
        jarvis.hear(BANGLADESH)
        jarvis.hear(NOISE)
        record_recognition(heard('Jarvis', 0.71452725))  # whatever comes next flushes the rest
    finally:
        conversation_log.remove_listener(printer)
    bangladesh = [line for line in lines if 'history of Bangladesh' in line]
    noise = [line for line in lines if '(unrecognized)' in line]
    assert len(bangladesh) == 1 and bangladesh[0].endswith(f'Jarvis: "{BANGLADESH_REPLY}"')
    assert len(noise) == 1 and 'Jarvis:' not in noise[0] and noise[0].startswith('You (ignored')


# --- active listening window -----------------------------------------------------------

def window_assistant(now, speaking=lambda: False):
    speech = Mock()
    speech.is_speaking.side_effect = speaking
    listener = Mock()
    listener.is_capturing = False
    assistant = Assistant(listener, speech, Mock(spec=CommandServices), Mock(), clock=lambda: now[0])
    return assistant, listener


def test_active_window_is_ten_seconds_from_settings():
    from config import settings
    assert settings.ACTIVE_WINDOW_SECONDS == 10
    now = [0]
    assistant, listener = window_assistant(now)
    ticks = []

    def listen(timeout):
        ticks.append(now[0])
        now[0] += 1
    listener.listen.side_effect = listen
    assistant.listen_for_command()
    assert not assistant.active_conversation and ticks[-1] == 10
    assert assistant.window_state() == 'passive'


def test_window_starts_when_jarvis_stops_speaking_and_stays_open_while_waiting():
    now = [0]
    assistant, listener = window_assistant(now, speaking=lambda: now[0] < 30)
    assistant.state.await_slot('alarm', 'time', 'set an alarm', 'What time should I set the alarm for?')
    clears = {45: lambda: assistant.state.clear('test')}

    def listen(timeout):
        now[0] += 1
        clears.get(now[0], lambda: None)()
    listener.listen.side_effect = listen
    assistant.listen_for_command()
    assert now[0] == 55  # talking until 30, pending until 45 (last seen at 44), then the 10 s window


def test_passive_mode_is_announced(capsys):
    assistant, listener = window_assistant([0])
    listener.listen.return_value = Recognition('Jarvis', 0.9)
    assistant.wait_for_wake_word()
    assert capsys.readouterr().out.splitlines()[0] == '[Passive mode]'


def test_weak_speech_is_still_heard_while_an_answer_is_pending(jarvis):
    jarvis.hear(SET_ALARM)
    jarvis.hear(heard('in 2 minutes', 0.45))  # pending: not ignored, but too weak to set the alarm
    assert jarvis.said()[-1] == "I'm not sure I heard that. What time should I set the alarm for?"


def test_transcript_line_shows_the_window(jarvis):
    lines = []
    printer = LiveTranscript(out=lines.append)
    conversation_log.add_listener(printer)
    try:
        jarvis.hear(SUPERMAN)
    finally:
        conversation_log.remove_listener(printer)
    assert lines == ['You (ignored: low confidence, no wake word): "who won against Superman"  conf 0.13 | passive']
