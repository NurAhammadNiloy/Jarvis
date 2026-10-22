"""Act first, undo instead of confirm (22 Oct 2026, session 73bc6f3e, 13:10-13:30).

Transcripts, confidences and alternatives are copied exactly from
logs/conversation.jsonl. Jarvis acts when the parsed action is clear, asks one
short question only when the alternatives disagree on the action itself, and
"undo" reverses the last action within 60 s.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.assistant import Assistant
from core.command_services import CommandServices
from core.dialogue import Dialogue
from core.smart_timer import TimerState
from core.voice_policy import Hypothesis, Recognition


def heard(text, confidence, *alternatives):
    return Recognition(text, confidence, tuple(Hypothesis(t, c) for t, c in alternatives))


CERTAIN_TIMER = heard('Jarvis certain timer for 25 minutes called pasta', 0.85859585,                  # 281
                      ('Jarvis set a timer for 25 minutes called pasta', 0.76440674),
                      ('Jarvis setting timer for 25 minutes called pasta', 0.79522562),
                      ('Yarvis certain timer for 25 minutes called pasta', 0.85859585),
                      ('Jarvis certan timer for 25 minutes called pasta', 0.85859585))
PAUSE_PASTA_PASTA = heard('Jarvis pause the pasta pasta timer', 0.54863864,                            # 359
                          ('Jarvis pause the pasta timer', 0.56839347), ('Yarvis pause the pasta pasta timer', 0.54863864),
                          ('Jarvis pause the pastor pasta timer', 0.54953253), ('Yarvis pause the pasta timer', 0.56839347))
FALLS = heard('Jarvis Falls the pasta timer', 0.60215652,                                               # 394
              ('Jarvis for the pasta timer', 0.59426165), ('Jarvis fals the pasta timer', 0.60215652),
              ('Jarvis pause the pasta timer', 0.61430538), ('Jarvis fohls the pasta timer', 0.60215652))
UNPAUSE = heard('unpause the pasta timer', 0.76869005, ('unpause the timer', 0.91051418))                # 484
ADD_FIVE = heard('Jarvis at 5 minutes to pass the timer', 0.91591626,                                   # 578
                 ('Jarvis at 5 minutes to Pasta timer', 0.84043896), ('Jarvis at 5 minutes to Paz the timer', 0.91591626),
                 ('Yarvis at 5 minutes to pass the timer', 0.91591626), ('Yarvis at 5 minutes to Pasta timer', 0.84043896))
MORE_COFFEE = heard('Jarvis said more 3 minutes on coffee timer', 0.84486485,                           # 868
                    ('Jarvis said more 3 minutes on Coffey timer', 0.84486485),
                    ('Jarvis said more 3 minutes on Koffee timer', 0.84486485),
                    ('Jarvis said more 3 minutes on koffi timer', 0.84486485),
                    ('Jarvis said more 3 minutes on coffe timer', 0.84486485))
STANDUP = heard('Jarvis remind me about stand up every Monday at 9:00 a.m.', 0.91510409,               # 1061
                ('Jarvis remind me about the stand up every Monday at 9:00 a.m.', 0.84645349),
                ('Yarvis remind me about stand up every Monday at 9:00 a.m.', 0.91510409),
                ('Yarvis remind me about the stand up every Monday at 9:00 a.m.', 0.84645349))
HINDI = heard('Jarvis play Hindi loafy music on YouTube', 0.88622302,                                  # 1955
              ('Jarvis play Hindi movie music on YouTube', 0.8298558), ('Jarvis play Hindi Lo-Fi music on YouTube', 0.86416525),
              ('Jarvis play Hindi Luffy music on YouTube', 0.87784415), ('Jarvis play hindy loafy music on YouTube', 0.88622302))
GOOGLE = heard('Jarvis open Google', 0.73985928, ('Yarvis open Google', 0.73985928),                    # 2073
               ('Jervis open Google', 0.69338512), ("Jerry's open Google", 0.66576958), ('Janice open Google', 0.64245075))

TZ = ZoneInfo('Europe/Helsinki')
NOW = datetime(2026, 10, 22, 13, 12, 10, tzinfo=TZ)


@pytest.fixture
def jarvis(tmp_path):
    from core.reminder_manager import ReminderService
    from core.reminder_store import ReminderStore
    reminders = ReminderService(ReminderStore(tmp_path / 'r.db', zone=TZ), notify=Mock(), clock=lambda: NOW)
    services = CommandServices(Mock(), reminders=reminders, now=lambda: NOW)
    resolver = Mock(return_value={'reply': 'Could you say that again?', 'query': None})
    speech, output = Mock(), Mock()
    speech.is_speaking.return_value = False
    now = [0.0]
    assistant = Assistant(Mock(), speech, services, output, clock=lambda: now[0],
                          dialogue=Dialogue(resolver, clock=lambda: now[0]))
    yield SimpleNamespace(
        hear=assistant.process_recognition, assistant=assistant, resolver=resolver, now=now,
        said=lambda: [call.args[0] for call in output.call_args_list],
        timers=lambda: {t.label: t for t in services.timers.active_timers()},
        reminders=lambda: [(r.kind, r.text, r.recurrence) for r in reminders.store.pending()])
    services.timers.cancel_all_timers(respond=lambda message: None)


def questions(jarvis):
    return [line for line in jarvis.said() if line.rstrip().endswith('?')]


# --- clear actions run at once ----------------------------------------------------------

def test_misheard_but_clear_timer_starts_at_once(jarvis):
    jarvis.hear(CERTAIN_TIMER)
    assert list(jarvis.timers()) == ['Pasta'] and questions(jarvis) == []


def test_weak_but_clear_pause_and_unpause_run_at_once(jarvis):
    jarvis.hear(CERTAIN_TIMER)
    jarvis.hear(PAUSE_PASTA_PASTA)
    assert jarvis.timers()['Pasta'].state == TimerState.PAUSED
    jarvis.hear(UNPAUSE)
    assert jarvis.timers()['Pasta'].state == TimerState.RUNNING
    assert questions(jarvis) == []


def test_weekly_reminder_runs_at_once(jarvis):
    jarvis.hear(STANDUP)
    assert jarvis.reminders() == [('reminder', 'stand up', 'weekly')] and questions(jarvis) == []


@pytest.mark.parametrize('utterance, intent', [(HINDI, 'youtube'), (GOOGLE, 'google')])
def test_opening_pages_runs_at_once(jarvis, utterance, intent):
    kind, command = jarvis.assistant._plan(utterance, utterance.text[len('Jarvis '):],
                                           jarvis.assistant.gate.assess(utterance, text=utterance.text[len('Jarvis '):]))
    assert kind == 'act' and command.intent == intent


# --- ask only when the alternatives disagree on the action -------------------------------

def test_garbled_primary_with_one_clear_alternative_is_read_back(jarvis):
    jarvis.hear(CERTAIN_TIMER)
    jarvis.hear(FALLS)
    assert jarvis.said()[-1] == 'Pause the pasta timer?'
    jarvis.hear(heard('yes', 0.58290237))
    assert jarvis.timers()['Pasta'].state == TimerState.PAUSED


@pytest.mark.parametrize('answer, added', [('add', True), ('add it', True), ('a new one', False),
                                           ('new timer', False), ('the first', True), ('the second one', False)])
def test_add_or_new_timer_is_one_either_or_question(jarvis, answer, added):
    jarvis.hear(CERTAIN_TIMER)
    pasta = jarvis.timers()['Pasta']
    jarvis.hear(ADD_FIVE)
    assert jarvis.said()[-1] == 'Add 5 minutes to pasta, or a new 5-minute timer?'
    jarvis.hear(heard(answer, 0.8))
    assert (pasta.duration_seconds == 30 * 60) is added
    assert (len(jarvis.timers()) == 2) is not added


def test_more_minutes_on_an_existing_timer_asks_add_or_new(jarvis):
    jarvis.hear(heard('Jarvis set a coffee timer for 5 minutes', 0.92))
    jarvis.hear(MORE_COFFEE)
    assert jarvis.said()[-1] == 'Add 3 minutes to coffee, or a new 3-minute timer?'


def test_alternatives_that_disagree_on_the_amount_are_asked(jarvis):
    jarvis.hear(heard('Jarvis set a timer for 5 minutes', 0.9, ('Jarvis set a timer for 9 minutes', 0.88)))
    assert jarvis.said() == ['Start a new 5-minute timer, or start a new 9-minute timer?']
    jarvis.hear(heard('9 minutes', 0.9))
    assert [t.duration_seconds for t in jarvis.timers().values()] == [540]


def test_session_needs_few_questions(jarvis):
    """The logged commands of this session: at most 1 in 10 needs a question."""
    commands = [CERTAIN_TIMER, PAUSE_PASTA_PASTA, UNPAUSE, ADD_FIVE, STANDUP,
                heard('Jarvis cancel the pasta timer', 0.84393156, ('Jarvis canceled the pasta timer', 0.76506722),
                      ('Jarvis kansal the pasta timer', 0.84393156), ('Yarvis cancel the pasta timer', 0.84393156)),
                heard('Jarvis remind me to drink water in 2 minutes', 0.94539559),
                heard('Jarvis set an alarm', 0.80383801, ('nearest set an alarm', 0.792), ('Yarvis set an alarm', 0.804)),
                heard('Jarvis how much time left', 0.9406274), heard('Jarvis cancel all the timer', 0.93498743),
                heard("Jarvis what's the weather tomorrow", 0.8948077)]
    asked = 0
    for command in commands:
        before = len(jarvis.said())
        jarvis.hear(command)
        new = jarvis.said()[before:]
        asked += any(line.endswith('?') and 'set the alarm for' not in line for line in new)
        jarvis.assistant.state.clear('next command')
    assert asked <= len(commands) // 10   # ADD_FIVE is the one either/or question


# --- undo ----------------------------------------------------------------------------------

@pytest.mark.parametrize('phrase', ['undo', 'undo that', "no, that's wrong", "that's wrong", 'cancel that',
                                    'Jarvis undo'])
def test_undo_reverses_a_new_timer(jarvis, phrase):
    jarvis.hear(CERTAIN_TIMER)
    jarvis.hear(heard(phrase, 0.9))
    assert jarvis.said()[-1] == 'Undone.' and jarvis.timers() == {}


def test_undo_restores_a_paused_and_a_cancelled_timer(jarvis):
    jarvis.hear(CERTAIN_TIMER)
    jarvis.hear(PAUSE_PASTA_PASTA)
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.timers()['Pasta'].state == TimerState.RUNNING
    left = jarvis.timers()['Pasta'].remaining_seconds
    jarvis.hear(heard('Jarvis cancel the pasta timer', 0.84393156))
    assert jarvis.timers() == {}
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.timers()['Pasta'].remaining_seconds == pytest.approx(left, abs=2)


def test_undo_reverses_reminders_deletes_and_snoozes(jarvis):
    jarvis.hear(STANDUP)
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.reminders() == []
    jarvis.hear(heard('Jarvis remind me to drink water in 2 minutes', 0.94539559))
    jarvis.hear(heard('Jarvis delete my drink water reminder', 0.95))
    assert jarvis.reminders() == []
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.reminders() == [('reminder', 'drink water', 'none')]


def test_undo_window_is_60_seconds(jarvis):
    from config import settings
    assert settings.UNDO_WINDOW_SECONDS == 60
    jarvis.hear(CERTAIN_TIMER)
    jarvis.now[0] = 61
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.said()[-1] == "There's nothing to undo." and list(jarvis.timers()) == ['Pasta']


def test_some_actions_cannot_be_undone(jarvis):
    jarvis.assistant._last_action = (None, 0, 'youtube')
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.said()[-1] == "Sorry, I can't undo that."


def test_read_only_questions_do_not_replace_what_undo_reverses(jarvis):
    jarvis.hear(CERTAIN_TIMER)
    jarvis.hear(heard('Jarvis how much time left', 0.9406274))
    jarvis.hear(heard('undo', 0.9))
    assert jarvis.timers() == {}


# --- "Which timer?" answers (seq 632 -> 658) ---------------------------------------------

CANCEL_THE_TIMER = heard('Jarvis cancel the timer', 0.94590157, ('Yarvis cancel the timer', 0.94590157))   # 632
FIVE_MINUTE_TIMER = heard('5-minute timer', 0.6653868, ('5 minute timer', 0.66916543))                     # 658


def two_timers(jarvis):
    jarvis.hear(CERTAIN_TIMER)                                        # Pasta, 25 minutes
    jarvis.hear(heard('Jarvis set a timer for 5 minutes', 0.95))      # unnamed, 5 minutes
    jarvis.hear(heard('Jarvis set a coffee timer for 4 minutes', 0.95))


@pytest.mark.parametrize('answer, left', [
    (FIVE_MINUTE_TIMER, {'Pasta', 'Coffee'}),
    (heard('the pasta one', 0.8), {None, 'Coffee'}),
    (heard('coffee', 0.8), {'Pasta', None}),
    (heard('the coffee timer', 0.8), {'Pasta', None}),
], ids=['5-minute timer', 'the pasta one', 'coffee', 'the coffee timer'])
def test_which_timer_is_answered_by_name_or_length(jarvis, answer, left):
    two_timers(jarvis)
    jarvis.hear(CANCEL_THE_TIMER)
    assert jarvis.said()[-1] == 'You have multiple timers. Which one should I cancel?'
    assert jarvis.assistant.state.current.describe() == 'awaiting timer for cancel_timer'
    jarvis.hear(answer)
    assert set(jarvis.timers()) == left
    jarvis.resolver.assert_not_called()


def test_which_timer_works_for_pause_too(jarvis):
    two_timers(jarvis)
    jarvis.hear(heard('Jarvis pause the timer', 0.9))
    jarvis.hear(heard('the pasta one', 0.8))
    assert jarvis.timers()['Pasta'].state == TimerState.PAUSED
    assert jarvis.timers()['Coffee'].state == TimerState.RUNNING


def test_an_unclear_answer_lists_the_timers(jarvis):
    two_timers(jarvis)
    jarvis.hear(CANCEL_THE_TIMER)
    jarvis.hear(heard('the blue one', 0.8))
    assert jarvis.said()[-1] == 'Which one: pasta, the 5-minute one or coffee?'
    assert len(jarvis.timers()) == 3


def test_a_new_request_instead_of_an_answer_runs(jarvis):
    two_timers(jarvis)
    jarvis.hear(CANCEL_THE_TIMER)
    jarvis.hear(heard('what time is it', 0.95))
    assert jarvis.said()[-1].startswith('The current time is') and len(jarvis.timers()) == 3
