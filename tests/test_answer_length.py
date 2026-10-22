"""Short answers by default; up to ~6 sentences when asked for detail; always stoppable."""
import json
import threading
import types
from unittest.mock import Mock, patch

import pytest

from core.dialogue import Dialogue, answer_length
from core.speech_output import PCMClip, SpeechController, speech_chunks
from core.voice_policy import Recognition

# Six sentences, about 800 characters: longer than a short reply may be.
LONG_REPLY = ' '.join([
    'Bangladesh lies on the Bengal delta, one of the most fertile regions in the world.',
    'For centuries it was part of Bengal, ruled by Buddhist, Hindu and later Muslim dynasties.',
    'Under British rule Bengal was partitioned, and in 1947 its eastern half became East Pakistan.',
    'Tensions over language and political power grew, starting with the Bengali Language Movement of 1952.',
    'In 1971 a liberation war led to independence, and Bangladesh became a sovereign nation that December.',
    'Since then it has grown into one of the fastest growing economies in South Asia, despite floods and cyclones.',
])


@pytest.mark.parametrize('text', [
    'Jarvis tell me about black holes', 'Jarvis can you tell me about Finland',      # 22 Oct session
    'Jarvis tell me the history of Bangladesh', 'Jarvis tell me the full story of Bangladesh',
    'explain how vaccines work', 'describe the moon landing in detail', 'tell me more',
])
def test_asking_for_detail_allows_a_long_answer(text):
    assert answer_length(text) == 'long'


@pytest.mark.parametrize('text', ['what is the capital of France', 'how are you', 'who won the match'])
def test_other_questions_get_a_short_answer(text):
    assert answer_length(text) == 'short'


def test_long_answer_is_accepted_only_when_detail_was_asked_for():
    resolver = Mock(return_value={'reply': LONG_REPLY, 'query': None})
    dialogue = Dialogue(resolver, clock=lambda: 0)
    assert dialogue.turn(Recognition('Jarvis tell me the full story of Bangladesh', 0.95)).reply == LONG_REPLY
    assert resolver.call_args.args[0]['answer_length'] == 'long'
    short = dialogue.turn(Recognition('what about Bangladesh', 0.95))
    assert resolver.call_args.args[0]['answer_length'] == 'short'
    assert short.reply != LONG_REPLY  # over the short limit: not spoken as is


@pytest.mark.parametrize('length, tokens, sentences', [('short', 250, 'one or two short'), ('long', 450, 'up to six')])
def test_prompt_and_token_budget_follow_the_requested_length(length, tokens, sentences):
    from core import chatgpt_service
    reply = {'choices': [{'message': {'content': json.dumps({'reply': 'Fine.', 'query': None})}}]}
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create', return_value=reply) as create:
        chatgpt_service.resolve_dialogue({'answer_length': length, 'history': []})
    kwargs = create.call_args.kwargs
    assert kwargs['max_tokens'] == tokens
    assert sentences in kwargs['messages'][0]['content']


def test_a_long_answer_is_spoken_in_chunks_and_stop_cuts_it_short():
    chunks = speech_chunks(LONG_REPLY)
    assert len(chunks) >= 3 and ' '.join(chunks) == LONG_REPLY
    synthesized, first_playing = [], threading.Event()
    audible_between_chunks = []

    def play(clip, cancelled):
        first_playing.set()
        assert cancelled.wait(2)  # plays until stopped

    output = SpeechController(lambda text, **kw: synthesized.append(text) or PCMClip(b'\0' * 960, 24000),
                              types.SimpleNamespace(play=play))
    try:
        job = output.submit(LONG_REPLY)
        assert first_playing.wait(1)
        audible_between_chunks.append(output.snapshot().audible)
        assert output.stop(expected_id=job.id)
        assert job.wait(1)
    finally:
        output.close()
    assert synthesized == chunks[:1]  # the rest is never synthesized or played
    assert audible_between_chunks == [True]


def test_jarvis_stays_audible_while_the_next_chunk_is_synthesized():
    seen, release = [], threading.Event()

    def synthesize(text, **kw):
        if seen:  # second chunk: Jarvis has spoken the first one
            seen.append(output.snapshot().audible)
            release.set()
        else:
            seen.append(None)
        return PCMClip(b'\0' * 960, 24000)

    output = SpeechController(synthesize, types.SimpleNamespace(play=lambda clip, cancelled: None))
    try:
        assert output.submit(LONG_REPLY).wait(2)
    finally:
        output.close()
    assert release.is_set() and seen[1] is True
    assert not output.snapshot().audible
