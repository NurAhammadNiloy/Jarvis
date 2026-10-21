"""Voice input tests with synthetic frames and provider responses, no hardware."""
from dataclasses import replace
import pytest

from core.voice_capture import Endpointer, VoiceConfig
from core.voice_policy import ConfidenceGate, Hypothesis, Recognition, can_interrupt, strip_wake_word
from core.voice_recognition import (parse_google_result, interpret_with_context,
    keyword_verification, match_short_utterance, select_best_question_form)


@pytest.mark.parametrize('text', ['not good', 'not great', "don't cancel it", 'pause',
    'stop', 'continue', 'yes', 'no', 'cancel', 'delete', 'jar of coffee', 'What is Paris?'])
def test_transcripts_are_not_rewritten(text):
    assert interpret_with_context(text, ['good', 'stop']) == text
    assert keyword_verification(text, ['Jarvis']) == text
    assert select_best_question_form(text, ['Where is Paris?']) == text
    assert match_short_utterance(text) is None


def test_missing_confidence_is_unknown_and_primary_order_preserved():
    result = parse_google_result({'alternative': [{'transcript': 'not good'}, {'transcript': 'good', 'confidence': 0.99}]})
    assert result.text == 'not good'
    assert result.confidence is None
    assert result.alternatives == (Hypothesis('good', 0.99),)


@pytest.mark.parametrize('result', [{}, [], {'alternative': []}])
def test_empty_recognition_is_not_invented(result):
    assert parse_google_result(result).error == 'unrecognized'


def test_exact_wake_word_preserves_command():
    assert strip_wake_word('Jarvis, do not cancel my timer') == 'do not cancel my timer'
    assert strip_wake_word('jar of coffee') is None
    assert strip_wake_word('please do not say Jarvis') is None


@pytest.mark.parametrize('confidence', [0.1, 0.6, 0.79])
def test_weak_action_is_not_accepted(confidence):
    assert ConfidenceGate(lambda: 0).assess(Recognition('cancel all timers', confidence)).kind == 'clarify'


def test_missing_action_confidence_requires_matching_repeat_with_expiry():
    now = [0]
    gate = ConfidenceGate(lambda: now[0])
    utterance = Recognition('set a timer for 5 minutes')
    assert gate.assess(utterance).kind == 'clarify'
    assert gate.assess(utterance).kind == 'accept'
    assert gate.assess(utterance).kind == 'clarify'
    now[0] = 21
    assert gate.assess(utterance).kind == 'clarify'
    assert gate.assess(Recognition('set a timer for 10 minutes')).kind == 'clarify'


@pytest.mark.parametrize('primary,alternative', [('cancel timer', "don't cancel timer"),
    ('yes', 'no'), ('pause timer', 'resume timer'), ('set timer for 5 minutes', 'set timer for 9 minutes')])
def test_conflicting_important_hypotheses_require_clarification(primary, alternative):
    result = Recognition(primary, 0.99, (Hypothesis(alternative),))
    assert ConfidenceGate(lambda: 0).assess(result).kind == 'clarify'


@pytest.mark.parametrize('text', ["don't cancel the timer", 'pause', 'delete'])
def test_legacy_router_cannot_act_on_negation_or_ambiguous_targets(text):
    assert ConfidenceGate(lambda: 0).assess(Recognition(text, 0.99)).kind == 'clarify'


@pytest.mark.parametrize('text', ['do not play music', 'continue explaining'])
def test_conversation_is_not_mistaken_for_an_action(text):
    from core.intent_classifier import classify_intent
    assert classify_intent(text) == 'chat'
    assert ConfidenceGate(lambda: 0).assess(Recognition(text, 0.99)).kind == 'accept'


@pytest.mark.parametrize('text', ['stop', 'quiet', 'Jarvis, stop', 'please stop'])
def test_explicit_stop_can_cancel_speech_without_authorizing_other_actions(text):
    result = Recognition(text, 0.9)
    assert can_interrupt(result)
    assert ConfidenceGate(lambda: 0).assess(result).kind == 'stop'


@pytest.mark.parametrize('text', ["don't stop", "Jarvis don't stop", 'stop timer', 'pause timer', 'cancel all timers'])
def test_partial_actions_are_not_speech_controls(text):
    assert not can_interrupt(Recognition(text, 0.99))


def test_output_echo_is_not_an_interruption():
    assert not can_interrupt(Recognition('stop', 0.99, playback_text='You can tell me to stop.'))
    assert can_interrupt(Recognition('Jarvis stop', 0.99, playback_text='The weather is nice.'))


def frames(endpoint, count, voiced, marker=1):
    results = []
    for _ in range(count):
        result = endpoint.push(bytes([marker]) * endpoint.config.frame_bytes, voiced)
        if result:
            results.append(result)
    return results


def test_natural_pause_does_not_end_recording_and_preroll_is_kept():
    endpoint = Endpointer()
    frames(endpoint, 10, False, 0)
    frames(endpoint, 20, True, 1)
    assert frames(endpoint, 50, False, 0) == []  # One-second pause, previously cut off.
    assert endpoint.active
    frames(endpoint, 20, True, 2)
    result = frames(endpoint, 70, False, 0)
    assert len(result) == 1
    assert result[0].pcm.startswith(b'\0' * 640)
    assert bytes([1]) * 640 in result[0].pcm and bytes([2]) * 640 in result[0].pcm
    assert not result[0].truncated


def test_wake_command_can_run_longer_than_five_seconds():
    endpoint = Endpointer()
    assert frames(endpoint, 400, True) == []
    assert endpoint.active
    assert len(frames(endpoint, 70, False)) == 1


def test_safety_limit_never_executes_cutoff_tail():
    endpoint = Endpointer(replace(VoiceConfig(), max_utterance_ms=2000))
    result = frames(endpoint, 120, True)
    assert len(result) == 1 and result[0].truncated
    assert endpoint.draining
    assert frames(endpoint, 50, True) == []
    assert frames(endpoint, 70, False) == []
    assert not endpoint.draining
    assert ConfidenceGate(lambda: 0).assess(Recognition('cancel', truncated=True)).kind == 'clarify'


def test_isolated_click_and_silence_do_not_become_utterances():
    endpoint = Endpointer()
    assert frames(endpoint, 2, True) == []
    assert frames(endpoint, 100, False) == []


def test_bad_frame_size_is_rejected():
    with pytest.raises(ValueError):
        Endpointer().push(b'broken', True)
