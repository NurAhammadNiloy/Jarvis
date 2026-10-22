from dataclasses import asdict
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.command_result import ActionResult, Command
from core.conversation_state import ConversationState
from core.dialogue import Dialogue
from core.reminder_parser import parse_reminder
from core.voice_policy import Recognition, Hypothesis
from core.assistant import Assistant
from core.command_services import CommandServices

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo('Europe/Helsinki'))


def test_name_repair_retains_request_and_only_proposes():
    resolver = Mock(side_effect=[
        {'reply': 'Who should I remind you to call?', 'query': None},
        {'reply': 'Ready.', 'query': 'remind me to call Anne tomorrow at 9 am'},
    ])
    dialogue = Dialogue(resolver, clock=lambda: 0)
    first = dialogue.turn(Recognition('remind me to call Annette tomorrow at 9 am', .85,
        (Hypothesis('remind me to call Anna tomorrow at 9 am', .84),)), reason='conflicting names')
    assert first.reply == 'Who should I remind you to call?'
    assert not first.proposal
    dialogue.observe('assistant', first.reply)
    corrected = dialogue.turn(Recognition('Anne, not Annette. A N N E.', .95))
    assert corrected.proposal == 'remind me to call Anne tomorrow at 9 am'
    context = resolver.call_args.args[0]
    assert 'tomorrow at 9 am' in context['history'][0]['text']
    assert context['history'][-1]['text'] == 'Anne, not Annette. A N N E.'
    assert resolver.call_count == 2


TIMER = Command('start_timer', 'set a timer for 5 minutes', {})


@pytest.mark.parametrize('confirmation', [Recognition('yes', .3), Recognition('yes'),
    Recognition('yes', .95, (Hypothesis('no', .9),))])
def test_weak_or_conflicting_confirmation_never_executes(confirmation):
    state = ConversationState(clock=lambda: 0)
    state.confirm(TIMER, 'I have: set a timer for 5 minutes. Shall I do that?')
    assert state.check(confirmation, confirmation.text).kind == 'reply'
    assert state.current.command == TIMER


def test_cancel_and_expiration_invalidate_proposal():
    now = [0]
    state = ConversationState(clock=lambda: now[0])
    state.confirm(TIMER, 'Shall I do that?')
    assert state.check(Recognition('never mind', .9), 'never mind').kind == 'cancel'
    assert not state.pending
    state.confirm(TIMER, 'Shall I do that?')
    now[0] = 121
    assert state.check(Recognition('yes', .9), 'yes') is None
    assert not state.pending


@pytest.mark.parametrize('response', [None, {'reply': 'done', 'query': 'delete all files'},
    {'reply': 'done', 'query': "don't cancel all timers"}])
def test_malformed_or_unsafe_model_proposals_are_never_proposed(response):
    dialogue = Dialogue(Mock(return_value=response), clock=lambda: 0)
    assert not dialogue.turn(Recognition('something', .9)).proposal


def test_provider_failure_preserves_history_but_proposes_nothing():
    resolver = Mock(side_effect=[{'reply': 'Ready', 'query': 'set a timer for 5 minutes'}, TimeoutError()])
    dialogue = Dialogue(resolver, clock=lambda: 0)
    dialogue.turn(Recognition('timer', .9))
    turn = dialogue.turn(Recognition('actually ten minutes', .9))
    assert turn.reply and not turn.proposal
    assert dialogue.history[-1]['text'] == 'actually ten minutes'


def mock_services():
    services = Mock(spec=CommandServices)
    services.follow_up.return_value = None
    services.extract_reminder_info.side_effect = lambda query: asdict(parse_reminder(query, NOW))
    return services


def test_assistant_routes_confirmed_repair_through_existing_boundary():
    resolver = Mock(side_effect=[
        {'reply': 'Who should I remind you to call?', 'query': None},
        {'reply': 'Ready', 'query': 'remind me to call Anne tomorrow at 9 am'},
    ])
    services = mock_services()
    services.reminder.return_value = ActionResult(('Reminder set.',))
    speech, output = Mock(), Mock()
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0,
        dialogue=Dialogue(resolver, clock=lambda: 0))
    assistant.process_recognition(Recognition('set a reminder for me', .9))  # nothing to parse: the model asks
    services.reminder.assert_not_called()
    assistant.process_recognition(Recognition('Anne tomorrow at 9 am', .9))  # the proposal runs (act first)
    services.reminder.assert_called_once_with(asdict(parse_reminder('remind me to call Anne tomorrow at 9 am', NOW)))
    assistant.process_recognition(Recognition('yes', .95))
    services.reminder.assert_called_once()
    assert any(h['text'] == 'Reminder set.' for h in assistant.dialogue.history)


PROPOSALS = [('delete my dentist reminder', 'delete_reminder', 'Delete the dentist reminder?'),
             ('snooze that reminder', 'snooze_reminder', 'Snooze the reminder for 10 minutes?'),
             ('set an alarm for 7am', 'reminder', 'Set an alarm for tomorrow at 7 AM?')]


def proposing(query):
    return Dialogue(Mock(return_value={'reply': 'Ready', 'query': query}), clock=lambda: 0)


@pytest.mark.parametrize('query, method, readback', PROPOSALS)
def test_clear_conversation_proposals_run_at_once(query, method, readback):
    services = mock_services()
    getattr(services, method).return_value = ActionResult(('Done.',))
    output = Mock()
    assistant = Assistant(Mock(), Mock(), services, output, clock=lambda: 0, dialogue=proposing(query))
    assistant.process_recognition(Recognition('something about that', .9))
    getattr(services, method).assert_called_once()
    output.assert_called_with('Done.')


@pytest.mark.parametrize('query, method, readback', PROPOSALS)
def test_proposals_from_unclear_audio_are_read_back_first(query, method, readback):
    services = mock_services()
    getattr(services, method).return_value = ActionResult(('Done.',))
    output = Mock()
    assistant = Assistant(Mock(), Mock(), services, output, clock=lambda: 0, dialogue=proposing(query))
    assistant.process_recognition(Recognition('Jarvis something', .3))   # unclear audio
    output.assert_called_with(readback)
    getattr(services, method).assert_not_called()
    assistant.process_recognition(Recognition('yes', .95))
    getattr(services, method).assert_called_once()


@pytest.mark.parametrize('text, method', [('delete my dentist reminder', 'delete_reminder'),
                                          ('snooze that reminder', 'snooze_reminder')])
def test_reminder_operations_run_directly_without_the_model(text, method):
    resolver = Mock()
    services = Mock(spec=CommandServices)
    services.follow_up.return_value = None
    getattr(services, method).return_value = ActionResult(('Done.',))
    output = Mock()
    assistant = Assistant(Mock(), Mock(), services, output, clock=lambda: 0,
        dialogue=Dialogue(resolver, clock=lambda: 0))
    assistant.process_recognition(Recognition(text, .95))
    resolver.assert_not_called()
    getattr(services, method).assert_called_once()
    output.assert_called_once_with('Done.')


# --- "I couldn't work out that follow-up" (22 Oct, 13:13-13:25) ----------------------------
# Cause: the reply was parsed with json.loads without JSON mode, and any problem with
# the reply - including a proposal Jarvis cannot run, like "get today's news" - threw
# the whole turn away. Now JSON mode is used, parsing is tolerant, an unusable
# proposal is dropped while the answer is kept, and the raw reply is logged.

NEWS_ANSWER = "I can't look up live news, but I can tell you about recent trends in general."


@pytest.mark.parametrize('raw', [
    '```json\n{"reply": "Paused.", "query": "pause the timer"}\n```',
    'Sure! {"reply": "Paused.", "query": "pause the timer"}',
    '{"reply": "Paused.", "query": "pause the timer", "confidence": "high"}',
    {'reply': 'Paused.', 'query': 'pause the timer'},
], ids=['code fence', 'prose around it', 'extra key', 'dict'])
def test_model_replies_are_parsed_robustly(raw):
    dialogue = Dialogue(Mock(return_value=raw), clock=lambda: 0)
    assert dialogue.turn(Recognition('pause the timer', 0.88)).proposal == 'pause the timer'


def test_missing_or_empty_query_is_no_proposal():
    for raw in ('{"reply": "Hello."}', '{"reply": "Hello.", "query": ""}', '{"reply": "Hello.", "query": "null"}'):
        turn = Dialogue(Mock(return_value=raw), clock=lambda: 0).turn(Recognition('hi', 0.9))
        assert turn.reply == 'Hello.' and not turn.proposal


def test_an_unusable_proposal_keeps_the_answer(monkeypatch):
    events = []
    monkeypatch.setattr('core.conversation_log.record', lambda event, **fields: events.append((event, fields)))
    raw = '{"reply": "%s", "query": "get today\'s news"}' % NEWS_ANSWER
    turn = Dialogue(Mock(return_value=raw), clock=lambda: 0).turn(Recognition("give me today's news", 0.84))
    assert turn.reply == NEWS_ANSWER and not turn.proposal
    assert ('dialogue_proposal_rejected', {'query': "get today's news", 'reason': 'Unsupported proposal'}) in events


def test_an_unparseable_reply_is_logged_raw(monkeypatch):
    events = []
    monkeypatch.setattr('core.conversation_log.record', lambda event, **fields: events.append((event, fields)))
    turn = Dialogue(Mock(return_value='I think you want to pause it.'), clock=lambda: 0).turn(
        Recognition('Falls the pasta timer', 0.6))
    assert turn.reply == "Sorry, I lost my train of thought. Say that again?" and not turn.proposal
    (event, fields), = [e for e in events if e[0] == 'dialogue_error']
    assert fields['raw'] == 'I think you want to pause it.' and fields['error'] == 'ValueError'


def test_dialogue_requests_json_mode():
    import json as _json
    from unittest.mock import patch
    from core import chatgpt_service
    reply = {'choices': [{'message': {'content': _json.dumps({'reply': 'Fine.', 'query': None})}}]}
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create', return_value=reply) as create:
        raw = chatgpt_service.resolve_dialogue({'history': []})
    assert create.call_args.kwargs['response_format'] == {'type': 'json_object'}
    assert _json.loads(raw) == {'reply': 'Fine.', 'query': None}


def test_an_over_long_reply_is_cut_at_a_sentence():
    long_reply = 'One sentence here. ' * 40
    turn = Dialogue(Mock(return_value={'reply': long_reply, 'query': None}), clock=lambda: 0).turn(
        Recognition('what is it', 0.9))
    assert len(turn.reply) <= 500 and turn.reply.endswith('.')
