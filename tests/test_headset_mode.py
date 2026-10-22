"""Headset mode (the default since 22 Oct 2026): the microphone cannot hear Jarvis, so
you can answer or interrupt at any time, also while Jarvis is speaking."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.assistant import Assistant
from core.command_services import CommandServices
from core.dialogue import Dialogue
from core.speech_output import SpeechSnapshot
from core.voice_capture import AudioUtterance, VoiceConfig
from core.voice_policy import Hypothesis, Recognition
from core.voice_runtime import ContinuousListener

EITHER_OR = 'Add 5 minutes to pasta, or a new 5-minute timer?'


def listener(recognition, echo_mode='headset'):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot(7, EITHER_OR, True)
    speech.stop.return_value = True
    return ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: recognition, speech,
                              VoiceConfig(echo_mode=echo_mode))


def during_reply():
    return AudioUtterance(b'pcm', playback_id=7, playback_text=EITHER_OR)


@pytest.mark.parametrize('said', [
    Recognition('a new 5-minute timer', 0.86),          # repeats Jarvis's own words: not echo with a headset
    Recognition('what time is it', 0.9),
    Recognition('stop', 0.7),
])
def test_speaking_during_a_reply_interrupts_it(said):
    jarvis = listener(said)
    assert jarvis.handle_interruption(during_reply())
    jarvis.speech.stop.assert_called_with(expected_id=7)


@pytest.mark.parametrize('said', [Recognition("don't stop", 0.9), Recognition('keep going, do not stop', 0.9),
                                  Recognition('the', 0.4), Recognition(error='unrecognized')])
def test_dont_stop_and_unclear_sound_do_not_interrupt(said):
    assert not listener(said).handle_interruption(during_reply())


def test_over_speakers_only_jarvis_or_stop_interrupts():
    assert not listener(Recognition('a new 5-minute timer', 0.86), 'speakers').handle_interruption(during_reply())
    assert listener(Recognition('stop', 0.7), 'speakers').handle_interruption(during_reply())


def test_an_answer_said_over_the_question_is_kept_and_stops_jarvis():
    jarvis = listener(Recognition('a new 5-minute timer', 0.86))
    result = jarvis.handle_final(during_reply())
    assert result.text == 'a new 5-minute timer' and not result.error
    jarvis.speech.stop.assert_called_with(expected_id=7)


# --- end to end: answering the either/or while Jarvis is still asking it -------------------------

@pytest.fixture
def jarvis():
    services = CommandServices(Mock())
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = True        # Jarvis is still speaking the question
    now = [0.0]
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: now[0],
                          dialogue=Dialogue(Mock(return_value={'reply': 'Sorry?', 'query': None}), clock=lambda: now[0]))
    yield SimpleNamespace(assistant=assistant, speech=speech, said=lambda: [c.args[0] for c in output.call_args_list],
                          timers=lambda: {t.label: t for t in services.timers.active_timers()})
    services.timers.cancel_all_timers(respond=lambda message: None)


def test_answering_the_question_while_jarvis_still_asks_it(jarvis):
    jarvis.assistant.process_recognition(Recognition('Jarvis set a timer for 25 minutes called pasta', 0.9))
    jarvis.assistant.process_recognition(Recognition(
        'Jarvis at 5 minutes to pass the timer', 0.91591626, (Hypothesis('Jarvis at 5 minutes to Pasta timer', 0.84),)))
    assert jarvis.said()[-1] == EITHER_OR
    jarvis.assistant.process_recognition(Recognition('add it', 0.9, playback_id=7, playback_text=EITHER_OR))
    assert jarvis.timers()['Pasta'].duration_seconds == 30 * 60
    jarvis.speech.stop.assert_any_call(expected_id=7)
