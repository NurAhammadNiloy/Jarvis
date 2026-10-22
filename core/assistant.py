"""Voice orchestration around the unchanged speech-independent command boundary."""
from dataclasses import replace
import random
import re
import time

from core.command_result import Command
from core.command_engine import execute_query, run_command, understand_query
from core.command_output import VoiceNotifications, deliver_result
from core.command_services import CommandServices
from core.conversation_state import ConversationState, stop_threshold
from core.voice_policy import ConfidenceGate, VoiceDecision, stop_heard, strip_wake_word, words
from core.conversation_log import record
from core.intent_classifier import READ_ONLY_INTENTS, route
from core.phrases import say


class Assistant:
    def __init__(self, listener=None, speech=None, services=None, output=None,
                 clock=time.monotonic, dialogue=None):
        if dialogue is None and services is None:
            from core.dialogue import Dialogue
            dialogue = Dialogue(clock=clock)
        self.dialogue = dialogue
        if speech is None:
            from core.speech_synthesis import get_speech_controller
            speech = get_speech_controller()
        if listener is None:
            from core.voice_recognition import get_listener
            listener = get_listener(speech)
        if output is None:
            from core.speech_synthesis import synthesize_speech
            output = synthesize_speech
        self.listener, self.speech = listener, speech
        self._turn_uid = None
        self._asked_question = False

        def reply(text):
            # Marks this as the reply to the utterance being handled, so the
            # transcript never mistakes an alarm going off for it.
            record('assistant_reply', uid=self._turn_uid, text=text)
            self._asked_question = text.rstrip().endswith('?')
            if self.dialogue is not None:
                self.dialogue.observe('assistant', text)
            return output(text)
        self.output = reply
        self.services = services if services is not None else CommandServices(VoiceNotifications())
        self.clock = clock
        self.gate = ConfidenceGate(clock)
        self.state = ConversationState(clock)
        from config.settings import ACTIVE_WINDOW_SECONDS, QUESTION_WINDOW_SECONDS
        self.active_conversation = False
        self.answer_window, self.question_window = ACTIVE_WINDOW_SECONDS, QUESTION_WINDOW_SECONDS
        self.last_active_time = clock()
        self._recognition_failure_prompted = False
        from config.settings import UNDO_WINDOW_SECONDS
        self.undo_window = UNDO_WINDOW_SECONDS
        self._last_action = None  # (undo function or None, when, intent, query) of the last change
        self._undo_hint_given = False  # "Say undo to bring it back." is said once per session

    def process_recognition(self, recognition, passive=False):
        """Only final, accepted transcripts may reach execute_query."""
        if recognition is None:
            return False
        record('turn_started', uid=recognition.uid, text=recognition.text, confidence=recognition.confidence,
               error=recognition.error, truncated=recognition.truncated)
        self._turn_uid = recognition.uid
        try:
            return self._process(recognition, passive)
        finally:
            self._turn_uid = None
            record('turn_finished', uid=recognition.uid, window=self.window_state())

    @property
    def conversation_timeout(self):
        """Seconds to listen without the wake word: longer after a question."""
        return self.question_window if self._asked_question else self.answer_window

    def window_state(self):
        """'active 10s' (time left to speak without the wake word) or 'passive'."""
        if not self.active_conversation:
            return 'passive'
        if self.speech.is_speaking() or self.state.pending:
            return f'active, {self.conversation_timeout:.0f}s after ' + (
                'reply' if self.speech.is_speaking() else 'your answer')
        left = self.conversation_timeout - (self.clock() - self.last_active_time)
        return f'active {max(0, left):.0f}s'

    def _process(self, recognition, passive):
        if recognition.error and recognition.error.startswith('microphone_'):
            raise RuntimeError('Microphone capture failed: ' + recognition.error)
        if recognition.error == 'said_over_jarvis':
            # Heard clearly over Jarvis's question (speakers mode): not acted on, but the
            # window stays open so you can repeat it.
            record('voice_decision', decision='ignore', reason='said_over_jarvis', text=recognition.text)
            if self.active_conversation:
                self.last_active_time = self.clock()
            return False
        addressed = strip_wake_word(recognition.text)
        if passive and addressed is None:
            record('voice_decision', decision='ignore', reason='no_wake_word', text=recognition.text)
            return False
        text = addressed if addressed is not None else recognition.text
        # Wake-only speech is an attention request in either conversation mode.
        # Repetitions are not a command, and must never reach the domain router.
        wake_only = bool(words(recognition.text)) and (set(words(recognition.text)) == {'jarvis'} or
                                                         addressed is not None and not words(addressed))
        if wake_only and not recognition.error and not recognition.truncated:
            # This lower threshold only authorizes a greeting, never an action.
            if recognition.confidence is not None and recognition.confidence < 0.5:
                record('voice_decision', decision='ignore', reason='weak_wake_word', text=text)
                return False
            record('voice_decision', decision='wake', text=recognition.text)
            self._recognition_failure_prompted = False
            self.active_conversation = True
            self.last_active_time = self.clock()
            self.speech.stop()
            self.output(say('greeting'))
            return True
        if recognition.error == 'unrecognized':
            # Background noise must not speak or extend the session. Only when
            # Jarvis is waiting for an answer is it worth saying so, once.
            if not self.state.pending:
                record('voice_decision', decision='ignore', reason='unrecognized_nothing_pending', text='')
                return False
            if self.speech.is_speaking():
                record('voice_decision', decision='ignore', reason='unrecognized_while_response_pending', text='')
                return False
            if self._recognition_failure_prompted:
                record('voice_decision', decision='ignore', reason='repeated_unrecognized_audio', text='')
                return False
            self._recognition_failure_prompted = True
            prompt = say('not_heard_then', question=self.state.current.prompt)
            record('voice_decision', decision='clarify', reason='unrecognized_audio', text='', prompt=prompt)
            self.output(prompt)
            return True
        if recognition.text and not recognition.error:
            self._recognition_failure_prompted = False
        # What Jarvis is waiting for decides first, before routing or the model.
        handled = self._answer_pending(recognition, text)
        if handled is not None:
            return handled
        if _MEDIA_CONTROL.search(text) and not recognition.error:
            # "stop the music", "pause YouTube": Jarvis can open YouTube but not control it.
            record('voice_decision', decision='media_control', text=text)
            self.speech.stop()
            self.active_conversation = True
            self.last_active_time = self.clock()
            self.output(say('no_media_control'))
            return True
        if stop_heard(recognition, stop_threshold(recognition)):
            # 'Jarvis stop Jarvis', 'Genesis stop' (0.40, heard over Jarvis): stop.
            record('voice_decision', decision='stop', text=text, playback_id=recognition.playback_id)
            self.speech.stop(expected_id=recognition.playback_id)
            return True
        if (addressed is None and recognition.confidence is not None and recognition.confidence < 0.5
                and not recognition.error and not self.state.pending):
            # Active mode needs no wake word, but then weak, unaddressed speech is
            # more likely a TV or another person than you (nothing is pending here).
            record('voice_decision', decision='ignore', reason='weak_without_wake_word', text=text)
            return False
        if _UNDO.match(text) and not recognition.error:
            return self._undo_last(text)
        if (not recognition.error and not recognition.truncated and route(text).intent == 'remove_timer_time'
                and self._takes_back_added_time(text)):
            return self._undo_last(text)  # "cancel that extra 5 minutes" right after adding them
        decision = self.gate.assess(recognition, text=text)
        if (self.dialogue is not None and decision.kind == 'clarify' and decision.reason in ('wording', 'meaning')
                and route(text).intent == 'chat'):
            # Alternatives that differ in a word ('send' / 'see', 'not' / 'knot') matter when an
            # action could follow. Plain conversation (a 'yes' or 'not' in it makes the gate
            # cautious) cannot execute anything and the model sees the alternatives, so it is
            # answered normally instead of being labelled "unclear audio".
            decision = VoiceDecision('accept', text=text)
        if decision.kind != 'stop' and not recognition.error and not recognition.truncated and text and \
                route(text).intent != 'chat':
            plan = self._plan(recognition, text, decision)
            if plan is not None:
                return self._carry_out(plan, recognition, text)
        if self.dialogue is not None and decision.kind != 'stop' and not recognition.error and not recognition.truncated and text:
            # A clear command takes the fast path; only conversation, requests
            # the parser cannot understand and unclear audio go to the dialogue.
            intent = route(text).intent
            if (decision.kind == 'clarify' or intent == 'chat' or
                    (intent == 'create_reminder' and not self._understood(self._understand(text)))):
                return self._dialogue_turn(recognition, text, decision, intent)
            if decision.kind == 'accept':
                self.dialogue.clear()
            self.dialogue.observe('user', text)
        record('voice_decision', decision=decision.kind, text=text, reason=decision.reason,
               prompt=decision.prompt, playback_id=recognition.playback_id)
        if decision.kind == 'ignore':
            return False
        self.active_conversation = True
        self.last_active_time = self.clock()
        if decision.kind == 'stop':
            # A delayed transcript from old playback must not stop a new reply.
            self.speech.stop(expected_id=recognition.playback_id)
            return True
        if decision.kind == 'clarify':
            # A newer recognized request supersedes old output; do not put
            # another clarification behind a stale response.
            self.speech.stop()
            self.output(decision.prompt)
            return True
        self.speech.stop()  # Supersede queued old responses, not domain actions.
        self.state.clear('superseded')  # a new command replaces an unanswered proposal
        query = decision.text
        self._execute(query, lambda: execute_query(query, self.services))
        return True

    # --- what Jarvis is waiting for ---------------------------------------------

    def _answer_pending(self, recognition, text):
        """Handle an utterance that answers what Jarvis is waiting for; None if it
        is a new request (an unanswered proposal stays available to the model)."""
        state = self.state.current
        answer = self.state.check(recognition, text)
        if answer is None:
            return None
        if answer.kind == 'fill':
            return self._fill_slot(recognition, text, state, answer.text)
        record('pending_answer', state=state.describe(), answer=answer.kind, text=text)
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop(expected_id=recognition.playback_id)
        if answer.kind == 'cancel':
            self.output(say('cancelled'))
        elif answer.kind == 'reply':
            self.output(answer.text)
        else:
            self._run(answer.command)
        return True

    def _fill_slot(self, recognition, text, state, completed):
        """Try the answer as the missing slot; only if that fails is it a new request."""
        if state.slot == 'task':
            return self._fill_task(recognition, text, state)
        if state.slot == 'timer':
            return self._fill_timer(recognition, text, state)
        # An answer that is a request of its own ('cancel the timer') is not a time.
        command = self._understand(completed) if route(text).intent == 'chat' else None
        question = self._time_question(command) if command else None
        if not self._understood(command) or question == state.prompt:
            self.state.clear('new request')
            return None
        record('pending_answer', state=state.describe(), answer='fill', text=text)
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        if not self._clear_slot_answer(recognition, state, command):
            self.output(say('not_sure_then', question=state.prompt))
        elif question:  # progress, e.g. "Did you mean 6 a.m. or p.m.?"
            self.state.await_slot(state.intent, state.slot, completed, question)
            self.output(question)
        else:
            self.state.clear('filled')
            self._run(command)
        return True

    def _fill_task(self, recognition, text, state):
        """The answer names what to be reminded about; the time was already parsed.
        An answer that is only a time (or nothing) is saved as 'Reminder'."""
        from core.reminder_parser import parse_reminder
        if route(text).intent != 'chat' or recognition.error or recognition.truncated:
            self.state.clear('new request')
            return None
        record('pending_answer', state=state.describe(), answer='fill', text=text)
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        try:  # the same words as "remind me to <answer>": time expressions are removed
            task = parse_reminder('remind me to ' + text, self.services.now()).task
        except Exception:
            task = None
        if task is not None and (recognition.confidence or 0) < 0.5:
            task = None
        command = Command(state.command.intent, state.command.query,
                          dict(state.command.arguments, task=task or 'Reminder'))
        self.state.clear('filled')
        self._run(command)
        return True

    def _fill_timer(self, recognition, text, state):
        """"Which timer?" answered by name ("the pasta one", "coffee"), by length
        ("5-minute timer") or by number ("timer 2")."""
        try:
            timers = list(self.services.timers.active_timers())
        except Exception:
            timers = []
        chosen = _match_timers(text, timers)
        if not chosen and route(text).intent != 'chat' and not _TIMER_ANSWER.match(text):
            self.state.clear('new request')
            return None
        record('pending_answer', state=state.describe(), answer='fill', text=text)
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        if len(chosen) != 1 or recognition.confidence is not None and recognition.confidence < 0.5:
            self.output(say('which_timer', timers=_list_timers(timers)))
            return True
        timer = chosen[0]
        self.state.clear('filled')
        self._run(Command(state.command.intent, state.command.query,
                          dict(state.command.arguments, label=timer.label, timer_id=timer.id)))
        return True

    def _clear_slot_answer(self, recognition, state, command):
        """An answer that completes the request is enough from 0.5 ('in 2 minutes'
        0.71), unless a likely alternative completes it differently ('in 3 minutes',
        'at 7 pm' for 'at 7 am')."""
        if recognition.confidence is None or recognition.confidence < 0.5:
            return False
        due = command.arguments.get('due')
        for alternative in recognition.alternatives:
            if alternative.confidence is not None and alternative.confidence < 0.5:
                continue
            other = self._understand(f'{state.query} {alternative.text}')
            if other is not None and other.arguments.get('due') not in (None, due):
                return False
        return True

    def _understand(self, query):
        try:
            return understand_query(query, self.services)
        except Exception:
            return None

    @staticmethod
    def _time_question(command):
        """What to ask when a new reminder or alarm has no usable time yet."""
        args = command.arguments
        if command.intent not in ('create_reminder', 'alarm') or args.get('operation', 'create') != 'create':
            return None
        if args.get('due') is not None:
            return None
        if args.get('question'):
            return args['question']
        if command.intent == 'alarm':
            return say('ask_alarm_time')
        return say('ask_reminder_time') if args.get('task') else None

    @staticmethod
    def _understood(command):
        if command is None:
            return False
        if command.intent != 'create_reminder':
            return True
        args = command.arguments
        return bool(args.get('due') is not None or args.get('question') or args.get('task'))

    def _propose(self, query):
        """Ask before executing a proposal; returns what to say, or None."""
        command = self._understand(query)
        if not self._understood(command):
            return None
        question = self._time_question(command)
        if question:  # ask for the missing time now, not after "yes"
            self.state.await_slot(command.intent, 'time', query, question)
            return question
        prompt = self._describe(command) + '?'
        self.state.confirm(command, prompt)
        return prompt

    # --- act first, undo instead of confirm ---------------------------------------

    def _plan(self, recognition, text, decision):
        """('act', command) when the parsed action is clear, ('ask', [commands]) when the
        recognition alternatives disagree on the action itself, None for the old path
        (negations, unknown confidence, unclear audio, nothing parseable)."""
        if decision.kind == 'clarify' and decision.reason not in ('wording', 'meaning', 'low_confidence'):
            return None  # "I won't act on that", "which timer?", repeat to confirm, ...
        if decision.kind not in ('accept', 'clarify'):
            return None
        if recognition.confidence is not None and recognition.confidence < 0.5:
            return None
        primary = self._understand(text)
        others = []
        for alternative in recognition.alternatives:
            if alternative.confidence is not None and alternative.confidence < 0.5:
                continue
            alt_text = _addressed(alternative.text)
            if set(words(alt_text)) & _NEGATIONS != set(words(text)) & _NEGATIONS:
                return None  # "cancel" vs "don't cancel": never guess
            if route(alt_text).intent != 'chat':
                others.append(self._understand(alt_text))
        if self._complete(primary):
            differing = [c for c in others if self._complete(c) and _signature(c) != _signature(primary)]
            if differing:
                return ('ask', [primary, differing[0]])
            existing = primary.intent == 'start_timer' and self._running_timer_named(
                primary, [text] + [a.text for a in recognition.alternatives])
            if existing and set(words(text)) & _MORE:
                return ('act', _add_time(primary, existing))  # "3 more minutes on coffee": add
            if existing:
                return ('ask', [_add_time(primary, existing), primary])
            return ('act', primary)
        candidates = []
        for command in others:
            if self._complete(command) and all(_signature(command) != _signature(c) for c in candidates):
                candidates.append(command)
        if candidates:
            return ('ask', candidates[:2])
        return None

    def _complete(self, command):
        if not self._understood(command) or command.intent == 'chat':
            return False
        if command.intent in ('start_timer', 'add_timer_time', 'remove_timer_time'):
            return bool((command.arguments.get('duration') or (None,))[0])
        return True

    def _running_timer_named(self, command, texts):
        """An existing timer this "start a timer" request names ("... to Pasta timer"),
        when it could just as well mean "add time to it"."""
        try:
            timers = list(self.services.timers.active_timers())
        except Exception:
            return None
        spoken = {w for text in texts for w in words(text)} | set(words(command.arguments.get('label') or ''))
        for timer in timers:
            label_words = set(words(timer.label or ''))
            if label_words and any(_similar(w, s) for w in label_words for s in spoken):
                return timer.label
        return None

    def _carry_out(self, plan, recognition, text):
        kind, value = plan
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        if self.dialogue is not None:
            self.dialogue.clear()
            self.dialogue.observe('user', text)
        self.state.clear('superseded')
        if kind == 'act':
            record('voice_decision', decision='accept', text=text, reason='act first',
                   playback_id=recognition.playback_id)
            self._run(value)
            return True
        if len(value) == 1:
            prompt = self._describe(value[0]) + '?'
            self.state.confirm(value[0], prompt)
        else:
            prompt = self._either_or(value)
            self.state.choose(value, [_cues(c, self._describe(c), value) for c in value], prompt)
        record('voice_decision', decision='clarify', text=text, reason='alternatives disagree', prompt=prompt)
        self.output(prompt)
        return True

    def _either_or(self, options):
        first, second = options
        if {first.intent, second.intent} == {'add_timer_time', 'start_timer'}:
            add = first if first.intent == 'add_timer_time' else second
            seconds = add.arguments['duration'][0]
            from core.command_description import duration_words
            return (f"Add {duration_words(seconds)} to {add.arguments.get('label', 'the timer').lower()}, "
                    f"or a new {duration_words(seconds, True)} timer?")
        second_text = self._describe(second)
        return f"{self._describe(first)}, or {second_text[:1].lower() + second_text[1:]}?"

    def _takes_back_added_time(self, text):
        """True when this asks to remove time the last action just added (the same amount
        or none given, and the same timer): that is an undo, not a subtraction."""
        last = self._last_action
        if last is None or last[0] is None or last[2] != 'add_timer_time' or self.clock() - last[1] > self.undo_window:
            return False
        from core.smart_timer import extract_timer_info
        added, asked = extract_timer_info(last[3]), extract_timer_info(text)
        if asked['duration'][0] and asked['duration'][0] != added['duration'][0]:
            return False
        return not asked['label'] or (added['label'] or '').lower() == asked['label'].lower()

    def _undo_last(self, text):
        record('voice_decision', decision='undo', text=text)
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        last, self._last_action = self._last_action, None
        if last is None or self.clock() - last[1] > self.undo_window:
            self.output(say('nothing_to_undo'))
            return True
        undo, _, intent, _ = last
        if undo is None:
            self.output(say('cannot_undo'))
            return True
        try:
            undo()
        except Exception as exc:
            record('undo_failed', intent=intent, error=type(exc).__name__)
            self.output(say('undo_failed'))
            return True
        record('undone', intent=intent)
        self.output(say('undone'))
        return True

    def _describe(self, command):
        """What will actually run, from the parsed command (not the transcript)."""
        from core.command_description import describe_command
        try:
            now = self.services.now()
        except Exception:
            now = None
        return describe_command(command, now if hasattr(now, 'tzinfo') else None)

    def _dialogue_turn(self, recognition, text, decision, intent):
        started = time.monotonic()
        turn = None
        if turn is None:
            trigger = 'unclear audio' if decision.kind == 'clarify' else 'conversation'
            pending = getattr(self.state.current, 'command', None)
            turn = self.dialogue.turn(replace(recognition, text=text), pending=pending.query if pending else None,
                                      reason=decision.prompt if decision.kind == 'clarify' else 'conversation')
        dialogue_ms = round((time.monotonic() - started) * 1000)
        command = self._understand(turn.proposal) if turn.proposal else None
        if (command is not None and self._understood(command) and not self._time_question(command)
                and (decision.kind != 'clarify' or command.intent in READ_ONLY_INTENTS)):
            # Act first: the model understood a clear request; "undo" reverses it. After
            # unclear audio only look-ups run directly; anything else is asked first.
            self.active_conversation = True
            self.last_active_time = self.clock()
            self.speech.stop()
            record('dialogue_turn', reply='', proposal=turn.proposal, duration_ms=dialogue_ms,
                   model_called=self.dialogue.model_called, trigger=trigger, ran_proposal=True)
            self.state.clear('proposal run')
            self._run(command)
            return True
        if turn.proposal:
            # The model's words about a proposal are never spoken on their own: if the
            # proposal cannot run, they might describe something that did not happen.
            reply = self._propose(turn.proposal) or say('cannot_work_out')
        else:
            reply = turn.reply or say('cannot_work_out')
        self.active_conversation = True
        self.last_active_time = self.clock()
        self.speech.stop()
        record('dialogue_turn', reply=reply, proposal=turn.proposal or None, duration_ms=dialogue_ms,
               model_called=self.dialogue.model_called, trigger=trigger)
        self.output(reply)
        return True

    def _run(self, command):
        """Execute a parsed command (a confirmed proposal, a filled slot) as it is."""
        self._execute(command.query, lambda: run_command(command, self.services))

    def _execute(self, query, run):
        record('command_started', text=query)
        started = time.monotonic()
        result = run()
        record('command_result', status=result.status, intent=result.intent, messages=list(result.messages),
               pending_action=result.pending_action, duration_ms=round((time.monotonic() - started) * 1000))
        undo = result.data.get('undo') if hasattr(result.data, 'get') else None
        if undo is not None:
            self._last_action = (undo, self.clock(), result.intent, query)
            if _is_removal(result.intent, query) and not self._undo_hint_given and result.messages:
                # The first cancel or delete of the session says how to take it back.
                self._undo_hint_given = True
                result = replace(result, messages=result.messages[:-1] + (f'{result.messages[-1]} {say("undo_hint")}',))
        elif result.status == 'handled' and result.intent in _NOT_UNDOABLE:
            self._last_action = (None, self.clock(), result.intent, query)
        if result.pending_action == 'choose_timer':
            self.state.await_slot(result.intent, 'timer', query, result.messages[-1],
                                  Command(result.intent, query, result.data['args']))
        elif result.pending_action == 'reminder_task':
            self.state.await_slot(result.intent, 'task', query, result.messages[0],
                                  Command(result.intent, query, result.data['args']))
        elif result.pending_action == 'reminder_time':
            # The answer completes this request: "set an alarm" + "2 minutes from now".
            self.state.await_slot(result.intent, 'time',
                                  result.data.get('query') or f"remind me to {result.data['task']}",
                                  result.messages[0])
        deliver_result(result, self.output)

    # --- loops ------------------------------------------------------------------

    def wait_for_wake_word(self):
        print("[Passive mode]")
        while True:
            if self.process_recognition(self.listener.listen(timeout=1), passive=True):
                return

    def listen_for_command(self):
        self.active_conversation = True
        self.last_active_time = self.clock()
        while self.active_conversation:
            self.process_recognition(self.listener.listen(timeout=1))
            if self.speech.is_speaking() or self.state.pending:
                # The window starts when Jarvis stops talking and nothing is awaited.
                self.last_active_time = self.clock()
            elif (not self.listener.is_capturing and
                    self.clock() - self.last_active_time > self.conversation_timeout):
                self.active_conversation = False  # back to passive; wait_for_wake_word says so

    def close(self):
        self.speech.stop()
        self.listener.close()
        self.speech.close()


# --- helpers for acting first --------------------------------------------------------

_UNDO = re.compile(
    r"^\W*(?:no\W+)?(?:undo(?:\s+(?:that|it|this))?|that['’]?s\s+(?:wrong|not\s+right)|that\s+was\s+wrong"
    r"|cancel\s+that|take\s+(?:that|it)\s+back|revert(?:\s+(?:that|it))?)(?:\s+please)?\W*$", re.IGNORECASE)
_NEGATIONS = {'not', 'no', 'never', "don't", 'don’t', "can't", 'cannot', "won't", "didn't"}
# Opening a page or playing a video cannot be taken back.
_NOT_UNDOABLE = {'youtube', 'google'}
# Cancelling or deleting: the first one in a session also says how to undo it.
_REMOVALS = {'cancel_timer', 'cancel_all_timers', 'delete_reminder'}


def _is_removal(intent, query):
    return intent in _REMOVALS or intent == 'alarm' and bool(_ALARM_REMOVAL.search(query))


_ALARM_REMOVAL = re.compile(r"\b(?:cancel|delete|remove|clear|drop)\b", re.IGNORECASE)
_WAKE_LIKE = {'jarvis', 'yarvis', 'jervis', 'javis'}


def _addressed(text):
    """The words after a (misheard) wake word: 'Yarvis pause the timer' -> 'pause the timer'."""
    addressed = strip_wake_word(text)
    if addressed is not None:
        return addressed
    tokens = text.split()
    return ' '.join(tokens[1:]) if tokens and tokens[0].lower().strip(',.') in _WAKE_LIKE else text


def _signature(command):
    """What the action is: the intent plus the amount or time that matters."""
    args = command.arguments
    if command.intent in ('start_timer', 'add_timer_time', 'remove_timer_time'):
        return command.intent, (args.get('duration') or (None,))[0]
    if command.intent in ('create_reminder', 'alarm') and args.get('operation', 'create') == 'create':
        due = args.get('due')
        return command.intent, due.replace(second=0, microsecond=0) if due else None, args.get('recurrence')
    return (command.intent,)


def _similar(a, b):
    from difflib import SequenceMatcher
    return a == b or len(a) > 3 and len(b) > 3 and SequenceMatcher(None, a, b).ratio() >= 0.8


def _add_time(start, label):
    """The "add time to <label>" reading of a "start a timer" request."""
    args = dict(start.arguments, label=label, action='add_time')
    return Command('add_timer_time', f"add {start.query} to {label} timer", args)


# "3 more minutes on the coffee timer" adds to it ("another 5-minute timer" is a new one).
_MORE = {'more', 'extra', 'additional'}
_CUE_WORDS = {'add_timer_time': {'add', 'more', 'extend', 'existing', 'it', 'that', 'same'},
              'start_timer': {'new', 'another', 'separate', 'start', 'fresh', 'second'}}
_COMMON = {'the', 'a', 'an', 'to', 'for', 'or', 'timer', 'of', 'set', 'your'}


def _cues(command, description, options):
    """Words in an answer that pick this option: its own words minus the shared ones."""
    mine = set(words(description)) | _CUE_WORDS.get(command.intent, set())
    shared = set.intersection(*(set(words(o.query)) for o in options)) | _COMMON
    return frozenset(mine - shared)


# --- "which timer?" ---------------------------------------------------------------------

# An answer that is only about a timer ("the 5-minute timer") even though the router
# would call it a new timer request.
_TIMER_ANSWER = re.compile(r"^\W*(?:the\s+)?(?:\w+[\s-]+){0,3}(?:timer|one)\W*$", re.IGNORECASE)


def _match_timers(text, timers):
    """The timers an answer names: by label, by original length, or by number."""
    from core.smart_timer import SmartTimerManager
    spoken = set(words(text))
    by_label = [t for t in timers if t.label and set(words(t.label)) & {w for w in spoken if len(w) > 2}
                or t.label and any(_similar(w, s) for w in words(t.label) for s in spoken)]
    if by_label:
        return by_label
    seconds, _ = SmartTimerManager.parse_duration(text.replace('-', ' '))
    if seconds:
        return [t for t in timers if t.duration_seconds == seconds]
    numbers = {int(w) for w in spoken if w.isdigit()}
    return [t for t in timers if t.id in numbers]


def _list_timers(timers):
    from core.command_description import duration_words
    names = [t.label.lower() if t.label else f"the {duration_words(t.duration_seconds, True)} one" for t in timers]
    return ', '.join(names[:-1]) + ' or ' + names[-1] if len(names) > 1 else ''.join(names)


# "stop the music", "pause YouTube", "skip this song": playback Jarvis cannot control.
_MEDIA_CONTROL = re.compile(
    r"^\W*(?:please\s+)?(?:stop|pause|resume|unpause|skip|mute|unmute|close|turn\s+(?:off|down|up)|next)\b"
    r"(?:\s+(?:the|this|that|my))?\s+(?:music|song|songs|youtube|video|playback|track)\b", re.IGNORECASE)
