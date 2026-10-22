"""Regressions from the third 22 Oct 2026 voice session (runs 6a7258d4 and 26c7df06).

Transcripts, confidences and alternatives are copied exactly from
logs/conversation.jsonl; the clock is frozen at 11:24:42 Helsinki.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import json
from unittest.mock import patch

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

@pytest.mark.parametrize('stop', [STOP_JARVIS, STOP_STOP, WEAK_STOP, GENESIS],
                         ids=['Jarvis stop Jarvis', 'Jarvis stop Jarvis stop', 'Jarvis stop 0.65', 'Genesis stop'])
def test_stop_heard_over_jarvis_stops_without_the_model(jarvis, stop):
    jarvis.hear(stop)
    jarvis.speech.stop.assert_called_with(expected_id=stop.playback_id)
    jarvis.resolver.assert_not_called()
    jarvis.output.assert_not_called()


@pytest.mark.parametrize('text, stop, cancel', [
    ('stop', True, True), ('Jarvis stop Jarvis', True, True), ('Genesis stop', True, True),
    ('please stop talking', True, True), ('Jarvis stoppe', True, True), ('cancel', False, True),
    ('Jarvis cancel that', False, True),
    ("don't stop", False, False), ('I cannot stop', False, False),         # negated
    ('stop the timer', False, False), ('cancel my dentist reminder', False, False),  # commands
    ('cancel the alarm', False, False),
    ('stop and tell me the time now', False, False),                        # more than 4 words
])
def test_what_counts_as_stop(text, stop, cancel):
    from core.conversation_state import means_cancel
    from core.voice_policy import means_stop
    assert means_stop(text) == stop
    assert means_cancel(text) == cancel


def test_bare_cancel_with_nothing_pending_is_just_acknowledged(jarvis):
    jarvis.hear(heard('cancel', 0.9))
    assert jarvis.said() == ['Okay.']
    jarvis.resolver.assert_not_called()


def speakers_listener(recognition):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot(13, BANGLADESH_REPLY, True)
    listener = ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: recognition, speech,
                                  VoiceConfig(echo_mode='speakers'))
    return listener, speech


@pytest.mark.parametrize('stop', [GENESIS, STOP_JARVIS, WEAK_STOP], ids=['Genesis stop', 'Jarvis stop Jarvis', 'Jarvis stop 0.65'])
def test_short_stop_during_playback_interrupts_in_speakers_mode(stop):
    listener, speech = speakers_listener(stop)
    result = listener.handle_final(AudioUtterance(b'pcm', playback_id=stop.playback_id, playback_text=BANGLADESH_REPLY))
    assert result is not None and result.text == stop.text
    speech.stop.assert_called_once_with(expected_id=stop.playback_id)


def test_short_stop_interrupts_from_a_partial_recognition_too():
    listener, speech = speakers_listener(GENESIS)
    speech.stop.return_value = True
    assert listener.handle_interruption(AudioUtterance(b'pcm', playback_id=13, playback_text=BANGLADESH_REPLY))
    speech.stop.assert_called_once_with(expected_id=13)


# --- alarms --------------------------------------------------------------------------------

def test_alarm_without_a_real_label_has_none(jarvis):
    jarvis.hear(ALARM_FROM)
    assert jarvis.said() == ['Alarm set for today at 11:26 AM.']
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


def test_words_before_jarvis_are_not_the_alarm_label(jarvis):
    jarvis.hear(I_SAID)          # alternatives differ ('I said' / 'Ice Age'): confirmed first
    jarvis.hear(heard('yes', 0.6191988))
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


def test_slot_answer_that_parses_is_accepted_at_0_5(jarvis):
    jarvis.hear(SET_ALARM)
    assert jarvis.said() == ['What time should I set the alarm for?']
    jarvis.hear(IN_TWO_MINUTES)
    assert jarvis.said()[-1] == 'Alarm set for today at 11:26 AM.'
    assert jarvis.stored() == [('alarm', None, NOW + timedelta(minutes=2))]


def test_slot_answer_with_a_different_likely_time_is_asked_again(jarvis):
    jarvis.hear(SET_ALARM)
    jarvis.hear(heard('in 2 minutes', 0.71, ('in 3 minutes', 0.6)))
    assert jarvis.said()[-1] == "I'm not sure I heard that. What time should I set the alarm for?"
    assert jarvis.stored() == []


@pytest.mark.parametrize('request_, label', [
    ('set an alarm from 2 minutes from now', None), ('set an alarm for the 2 minutes from now', None),
    ('set an alarm for the gym in 2 minutes', 'gym'), ('set an alarm in 2 minutes to take the pizza out', 'take the pizza out'),
])
def test_alarm_labels_keep_only_real_words(request_, label):
    from core.reminder_parser import parse_reminder
    assert parse_reminder(request_, NOW).task == label


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


def test_unrecognized_audio_after_an_echo_gets_an_outcome_line():
    # 26c7df06 237/240: echo discarded, the audio after it re-recognized as nothing.
    lines = []
    printer = LiveTranscript(out=lines.append)
    conversation_log.add_listener(printer)
    try:
        speech = Mock()
        speech.snapshot.return_value = SpeechSnapshot()
        results = iter([Recognition(error='unrecognized'), Recognition(error='unrecognized')])
        listener = ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: next(results), speech,
                                      VoiceConfig(echo_mode='speakers'))
        assert listener.handle_final(AudioUtterance(b'all', playback_id=10, playback_text='This is your alarm.',
                                                    after_playback_pcm=b'after')) is None
    finally:
        conversation_log.remove_listener(printer)
    assert lines == ['You (ignored: Jarvis speaking (speakers mode)): "(unrecognized)"  conf - | stt 0.0s',
                     'You (ignored: nothing clear after Jarvis stopped (speakers mode)): "(unrecognized)"  conf -'
                     ' | stt 0.0s']


# --- ChatGPT knows Jarvis's commands (session 5472c258, 12:20) -------------------------

NO_THEY_HAVE = heard('no they have any reminder', 0.78612196, ('now they have any reminder', 0.77071142),
                     ('know they have any reminder', 0.78612196), ('no they have any reminders', 0.60823381))
YES_REMINDERS = heard('yes', 0.57714069, ('yesss', 0.57714069), ('yessss', 0.57714069), ('yess', 0.57714069))


def test_prompt_lists_the_router_commands_and_forbids_saying_they_are_impossible():
    from core import chatgpt_service
    from core.intent_classifier import command_names
    reply = {'choices': [{'message': {'content': json.dumps({'reply': 'Fine.', 'query': None})}}]}
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create', return_value=reply) as create:
        chatgpt_service.resolve_dialogue({'history': []})
    prompt = create.call_args.kwargs['messages'][0]['content']
    assert all(name in prompt for name in command_names()) and 'list reminders' in prompt
    assert 'Never say you cannot do something on this list' in prompt


def test_yes_to_are_you_asking_about_reminders_lists_them_without_a_second_confirmation(jarvis):
    jarvis.resolver.side_effect = [
        {'reply': 'I\'m not sure what you mean. Are you asking if there are any reminders set?', 'query': None},
        {'reply': 'Checking.', 'query': 'do I have any reminders'},
    ]
    jarvis.hear(NO_THEY_HAVE)
    assert jarvis.said()[-1].endswith('Are you asking if there are any reminders set?')
    jarvis.hear(YES_REMINDERS)
    assert jarvis.said()[-1] == 'You have no reminders.'
    assert 'Shall I' not in ' '.join(jarvis.said())
    assert jarvis.resolver.call_args.args[0]['history'][-1]['text'] == 'yes'


def test_changing_proposals_still_need_confirmation(jarvis):
    jarvis.resolver.return_value = {'reply': 'Ok.', 'query': 'delete my dentist reminder'}
    jarvis.hear(heard('Jarvis get rid of the dentist thing', 0.9))
    assert jarvis.said()[-1] == 'I have: delete my dentist reminder. Shall I do that?'


# --- "for <number> <unit>" in reminders (session 5472c258, 12:21) ---------------------

FOR_TWO = heard('set a reminder for 2 minutes', 0.95373708)      # 385, 408 (0.96)


@pytest.mark.parametrize('phrase, task, minutes', [
    ('set a reminder for 2 minutes', None, 2), ('remind me for 5 minutes', None, 5),
    ('remind me for an hour', None, 60),
    ('remind me to run for 30 minutes at 6 pm', 'run for 30 minutes', None),   # another time given: task text
    ('remind me to run for 30 minutes', 'run for 30 minutes', None),
    ('remind me to book a table for 4 at 7 pm', 'book a table for 4', None),   # no unit: task text
    ('remind me to stretch in 2 minutes', 'stretch', 2),
])
def test_for_number_with_unit_is_a_duration_only_when_nothing_else_is_the_task(phrase, task, minutes):
    from core.reminder_parser import parse_reminder
    request = parse_reminder(phrase, NOW)
    assert request.task == task
    if minutes:
        assert request.due == NOW + timedelta(minutes=minutes)
    else:
        assert request.due != NOW + timedelta(minutes=30)  # "for 30 minutes" stayed in the task


def test_reminder_without_a_task_asks_what_to_remind_about(jarvis):
    jarvis.hear(FOR_TWO)
    assert jarvis.said() == ['What should I remind you about?']
    assert jarvis.stored() == []
    jarvis.hear(heard('Jarvis stretch', 0.9))   # addressed, as people do
    assert jarvis.said()[-1] == 'Reminder set for today at 11:26 AM: stretch.'
    assert jarvis.stored() == [('reminder', 'stretch', NOW + timedelta(minutes=2))]


@pytest.mark.parametrize('answer', [heard('in 2 minutes', 0.81), heard('stretch', 0.3), heard('at 5 pm', 0.9)],
                         ids=['only a time', 'unclear (0.3)', 'only a clock time'])
def test_unclear_task_answer_is_saved_as_reminder_never_as_a_time(jarvis, answer):
    jarvis.hear(FOR_TWO)
    jarvis.hear(answer)
    assert jarvis.stored() == [('reminder', 'Reminder', NOW + timedelta(minutes=2))]
    assert 'minutes' not in jarvis.stored()[0][1]


def test_session_exchange_no_longer_saves_the_time_as_the_task(jarvis):
    # Logged: "set a reminder for 2 minutes" -> "When should I remind you?" -> "in 2 minutes"
    # saved "remind me to 2 minutes in 2 minutes" with the task "2 minutes".
    jarvis.hear(FOR_TWO)
    jarvis.hear(heard('in 2 minutes', 0.81))
    assert all(task != '2 minutes' for _, task, _ in jarvis.stored())


def test_task_answer_that_is_a_command_is_a_new_request(jarvis):
    jarvis.hear(FOR_TWO)
    jarvis.hear(heard('what time is it', 0.95))
    assert jarvis.said()[-1].startswith('The current time is') and jarvis.stored() == []


# --- 12:55 session (193aa5d4): flow fixes -----------------------------------------------

EARTH_QUESTION = ("There's always something fascinating happening in the universe. "
                  "Is there a specific topic or event you're curious about?")


def run_window(assistant, listener, now, until):
    ticks = []

    def listen(timeout):
        now[0] += 1
        ticks.append(now[0])
        return None
    listener.listen.side_effect = listen
    assistant.listen_for_command()
    return ticks[-1]


@pytest.mark.parametrize('reply, closes_after', [(EARTH_QUESTION, 20), ('Reminder set for today at 12:58 PM: stretch.', 10)])
def test_window_is_20_seconds_after_a_question_and_10_after_a_statement(reply, closes_after):
    from config import settings
    assert settings.QUESTION_WINDOW_SECONDS == 20
    now = [0]
    assistant, listener = window_assistant(now)
    assistant.output(reply)
    assistant.active_conversation = True
    assert run_window(assistant, listener, now, closes_after) == closes_after + 1  # closes once N s have passed
    assert assistant.window_state() == 'passive'


def test_window_state_shows_the_longer_window_after_a_question():
    now = [0]
    assistant, _ = window_assistant(now)
    assistant.active_conversation = True
    assistant.output(EARTH_QUESTION)
    assert assistant.window_state() == 'active 20s'
    now[0] = 5
    assert assistant.window_state() == 'active 15s'


# --- said over Jarvis's question (193aa5d4 seq 235 / 361) ------------------------------

OVER_QUESTION = heard('no anything related to Earth you can send me', 0.89244109,           # 235
                      ('no anything related to art you can send me', 0.9),
                      ('know anything related to Earth you can send me', 0.89), playback_id=8)
QUESTION_TEXT = ("There's always something fascinating happening in the universe, from stars being born "
                 "to galaxies colliding. Is there a specific topic or event you're curious about?")


def over_jarvis(recognition, playback_text=QUESTION_TEXT, after=None):
    speech = Mock()
    speech.snapshot.return_value = SpeechSnapshot()
    results = iter([recognition] + ([after] if after else []))
    listener = ContinuousListener(Mock(), lambda frame: False, lambda pcm, partial=False: next(results), speech,
                                  VoiceConfig(echo_mode='speakers'))
    utterance = AudioUtterance(b'all', playback_id=8, playback_text=playback_text,
                               after_playback_pcm=b'after' if after else b'')
    return listener.handle_final(utterance)


def test_clear_speech_over_a_question_is_flagged_not_dropped():
    result = over_jarvis(OVER_QUESTION)
    assert result.error == 'said_over_jarvis' and result.text == OVER_QUESTION.text


@pytest.mark.parametrize('recognition, playback_text', [
    (replace(OVER_QUESTION, confidence=0.79), QUESTION_TEXT),                      # not clear enough
    (OVER_QUESTION, 'Reminder set for today at 12:58 PM: stretch.'),               # no question asked
    (replace(OVER_QUESTION, text=QUESTION_TEXT), QUESTION_TEXT),                   # Jarvis's own echo
], ids=['below 0.8', 'no question asked', 'echo'])
def test_other_overlaps_are_still_just_discarded(recognition, playback_text):
    assert over_jarvis(recognition, playback_text) is None


def test_speech_after_jarvis_stopped_is_used_instead_of_flagged():
    result = over_jarvis(OVER_QUESTION, after=heard('no anything related to Earth you can send me', 0.91))
    assert result.error is None and result.text == OVER_QUESTION.text


def test_assistant_keeps_the_window_open_and_stays_quiet(jarvis):
    now = [0]
    assistant = jarvis.assistant
    assistant.clock = lambda: now[0]
    assistant.active_conversation = True
    assistant.last_active_time = 0
    now[0] = 18
    assert not jarvis.hear(replace(OVER_QUESTION, error='said_over_jarvis', playback_id=None))
    assert assistant.last_active_time == 18 and assistant.active_conversation
    jarvis.output.assert_not_called()
    jarvis.resolver.assert_not_called()


def test_transcript_says_to_repeat():
    lines = []
    printer = LiveTranscript(out=lines.append)
    conversation_log.add_listener(printer)
    try:
        assistant = Assistant(Mock(), Mock(), Mock(spec=CommandServices), Mock(), clock=lambda: 0)
        assistant.active_conversation = True
        recognition = replace(OVER_QUESTION, error='said_over_jarvis', playback_id=None)
        record_recognition(recognition)
        assistant.process_recognition(recognition)
    finally:
        conversation_log.remove_listener(printer)
    assert len(lines) == 1 and lines[0].startswith(
        'You (said over Jarvis — please repeat): "no anything related to Earth you can send me"  conf 0.89')


def test_prompt_treats_send_give_show_as_tell_and_admits_missing_live_information():
    from core import chatgpt_service
    reply = {'choices': [{'message': {'content': json.dumps({'reply': 'Fine.', 'query': None})}}]}
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create', return_value=reply) as create:
        chatgpt_service.resolve_dialogue({'history': [
            {'role': 'user', 'text': 'anything related to Earth send me'}]})
    prompt = create.call_args.kwargs['messages'][0]['content']
    assert '"send me", "give me" and "show me" mean "tell me"' in prompt
    assert 'live information Jarvis cannot get (news, current events, web search)' in prompt
    assert 'in one short sentence and offer what you can tell from general knowledge' in prompt


# --- 0.92-0.95 labelled "unclear audio" (193aa5d4 seq 364, 453) ---------------------------

SEND_ME_IN_SHORT = heard('yes you can send me in short', 0.92825669,                           # 364
                         ('yes you can see me in short', 0.91), ('yes you can send me in shortt', 0.93),
                         ('yes you can send me Inn short', 0.93))
SAID_TOLD = heard('Jarvis I said that I was told you about to say not send', 0.91632271,       # 453
                  ('Jarvis I say that I was told you about to say not send', 0.91),
                  ('Jarvis I said that I was told you about to say not sin', 0.88),
                  ('Jarvis I said that I was told you about to say knot send', 0.92))


@pytest.mark.parametrize('utterance', [SEND_ME_IN_SHORT, SAID_TOLD], ids=['yes ... send me', 'told ... not send'])
def test_confident_conversation_is_not_unclear_audio(jarvis, utterance):
    jarvis.hear(utterance)
    assert jarvis.resolver.call_args.args[0]['reason'] == 'conversation'
    assert jarvis.said() == ['Could you clarify?']   # the model's own answer, not a request to repeat


@pytest.mark.parametrize('utterance', [
    heard('Jarvis remind me to call Mom', 0.9, ('Jarvis remind me to call Mam', 0.9)),
    heard('Jarvis cancel all timers', 0.95, ("Jarvis don't cancel all timers", 0.9)),
    heard('Jarvis set an alarm at 7 am', 0.95, ('Jarvis set an alarm at 7 pm', 0.9)),
], ids=['name', 'meaning', 'am/pm'])
def test_requests_that_could_become_actions_still_need_agreement(jarvis, utterance):
    jarvis.hear(utterance)
    assert jarvis.stored() == []
