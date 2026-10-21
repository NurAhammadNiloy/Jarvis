from unittest.mock import Mock

import pytest

from core.dialogue import Dialogue
from core.voice_policy import Recognition, Hypothesis
from core.assistant import Assistant
from core.command_services import CommandServices
from core.command_result import ActionResult


def test_name_repair_retains_request_and_requires_confirmation_once():
    resolver = Mock(side_effect=[
        {'reply': 'Who should I remind you to call?', 'query': None},
        {'reply': 'Ready.', 'query': 'remind me to call Anne tomorrow at 9 am'},
    ])
    dialogue = Dialogue(resolver, clock=lambda: 0)
    first = dialogue.turn(Recognition('remind me to call Annette tomorrow at 9 am', .85,
        (Hypothesis('remind me to call Anna tomorrow at 9 am', .84),)), reason='conflicting names')
    assert first.reply == 'Who should I remind you to call?'
    assert not first.query
    dialogue.observe('assistant', first.reply)
    corrected = dialogue.turn(Recognition('Anne, not Annette. A N N E.', .95))
    assert not corrected.query
    assert 'call Anne tomorrow at 9 am' in corrected.reply
    context = resolver.call_args.args[0]
    assert 'tomorrow at 9 am' in context['history'][0]['text']
    assert context['history'][-1]['text'] == 'Anne, not Annette. A N N E.'
    confirmed = dialogue.turn(Recognition('yes', .95))
    assert confirmed.query == 'remind me to call Anne tomorrow at 9 am'
    assert not dialogue.turn(Recognition('yes', .95)).query
    assert resolver.call_count == 2


@pytest.mark.parametrize('confirmation', [Recognition('yes', .3), Recognition('yes'),
    Recognition('yes', .95, (Hypothesis('no', .9),))])
def test_weak_or_conflicting_confirmation_never_executes(confirmation):
    dialogue = Dialogue(Mock(return_value={'reply': 'Ready', 'query': 'set a timer for 5 minutes'}), clock=lambda: 0)
    dialogue.turn(Recognition('a five minute timer', .9))
    assert not dialogue.turn(confirmation).query


def test_cancel_and_expiration_invalidate_proposal():
    now = [0]
    dialogue = Dialogue(Mock(return_value={'reply': 'Ready', 'query': 'set a timer for 5 minutes'}), clock=lambda: now[0])
    dialogue.turn(Recognition('timer', .9))
    dialogue.turn(Recognition('never mind', .9))
    assert dialogue.pending is None
    dialogue.turn(Recognition('timer', .9))
    now[0] = 121
    assert not dialogue.turn(Recognition('yes', .9)).query
    assert dialogue.pending is None


@pytest.mark.parametrize('response', [None, {'reply': 'done', 'query': 'delete all files'},
    {'reply': 'done', 'query': "don't cancel all timers"}])
def test_malformed_or_unsafe_model_proposals_cannot_execute(response):
    dialogue = Dialogue(Mock(return_value=response), clock=lambda: 0)
    assert not dialogue.turn(Recognition('something', .9)).query
    assert dialogue.pending is None


def test_provider_failure_preserves_history_but_invalidates_proposal():
    resolver = Mock(side_effect=[{'reply': 'Ready', 'query': 'set a timer for 5 minutes'}, TimeoutError()])
    dialogue = Dialogue(resolver, clock=lambda: 0)
    dialogue.turn(Recognition('timer', .9))
    assert dialogue.turn(Recognition('actually ten minutes', .9)).reply
    assert dialogue.pending is None
    assert dialogue.history[-1]['text'] == 'actually ten minutes'


def test_assistant_routes_confirmed_repair_through_existing_boundary():
    resolver = Mock(side_effect=[
        {'reply': 'Who should I remind you to call?', 'query': None},
        {'reply': 'Ready', 'query': 'remind me to call Anne tomorrow at 9 am'},
    ])
    services = Mock(spec=CommandServices)
    services.follow_up.return_value = None
    services.extract_reminder_info.return_value = dict(task='call Anne', time='tomorrow at 9 am', recurring=False, interval=None)
    services.reminder.return_value = ActionResult(('Reminder set.',))
    speech, output = Mock(), Mock()
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: 0,
        dialogue=Dialogue(resolver, clock=lambda: 0))
    assistant.process_recognition(Recognition('set a reminder for me', .9))
    assistant.process_recognition(Recognition('Anne tomorrow at 9 am', .9))
    services.reminder.assert_not_called()
    assistant.process_recognition(Recognition('yes', .95))
    services.reminder.assert_called_once_with('call Anne', 'tomorrow at 9 am', False, None)
    assistant.process_recognition(Recognition('yes', .95))
    services.reminder.assert_called_once()
    assert any(h['text'] == 'Reminder set.' for h in assistant.dialogue.history)
