"""Voice orchestration around the unchanged speech-independent command boundary."""
from dataclasses import replace
import random
import time

from core.command_result import Command
from core.command_engine import execute_query, run_command, understand_query
from core.command_output import VoiceNotifications, deliver_result
from core.command_services import CommandServices
from core.conversation_state import ConversationState, stop_threshold
from core.voice_policy import ConfidenceGate, VoiceDecision, stop_heard, strip_wake_word, words
from core.conversation_log import record
from core.intent_classifier import READ_ONLY_INTENTS, route


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
        wake_only = bool(words(recognition.text)) and set(words(recognition.text)) == {'jarvis'}
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
            self.output(random.choice(['At your service, sir.', 'How can I help, sir?']))
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
            prompt = "I couldn't hear that. " + self.state.current.prompt
            record('voice_decision', decision='clarify', reason='unrecognized_audio', text='', prompt=prompt)
            self.output(prompt)
            return True
        if recognition.text and not recognition.error:
            self._recognition_failure_prompted = False
        # What Jarvis is waiting for decides first, before routing or the model.
        handled = self._answer_pending(recognition, text)
        if handled is not None:
            return handled
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
        decision = self.gate.assess(recognition, text=text)
        if (self.dialogue is not None and decision.kind == 'clarify' and decision.reason in ('wording', 'meaning')
                and route(text).intent == 'chat'):
            # Alternatives that differ in a word ('send' / 'see', 'not' / 'knot') matter when an
            # action could follow. Plain conversation (a 'yes' or 'not' in it makes the gate
            # cautious) cannot execute anything and the model sees the alternatives, so it is
            # answered normally instead of being labelled "unclear audio".
            decision = VoiceDecision('accept', text=text)
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
            self.output('Cancelled.')
        elif answer.kind == 'reply':
            self.output(answer.text)
        else:
            self._run(answer.command)
        return True

    def _fill_slot(self, recognition, text, state, completed):
        """Try the answer as the missing slot; only if that fails is it a new request."""
        if state.slot == 'task':
            return self._fill_task(recognition, text, state)
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
            self.output("I'm not sure I heard that. " + state.prompt)
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
        return 'When should I remind you?' if args.get('task') else None

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
        prompt = f"I have: {query.rstrip('.!?')}. Shall I do that?"
        self.state.confirm(command, prompt)
        return prompt

    def _dialogue_turn(self, recognition, text, decision, intent):
        started = time.monotonic()
        turn = None
        if decision.reason == 'wording' and intent != 'chat':
            # Alternatives differ only in wording ('call Mom' / 'call Mam'):
            # confirm the user's own words; no model call needed.
            trigger = 'similar alternatives'
            try:
                turn = self.dialogue.propose(text)
            except ValueError:
                turn = None
        if turn is None:
            trigger = 'unclear audio' if decision.kind == 'clarify' else 'conversation'
            pending = getattr(self.state.current, 'command', None)
            turn = self.dialogue.turn(replace(recognition, text=text), pending=pending.query if pending else None,
                                      reason=decision.prompt if decision.kind == 'clarify' else 'conversation')
        dialogue_ms = round((time.monotonic() - started) * 1000)
        command = self._understand(turn.proposal) if turn.proposal else None
        if command is not None and command.intent in READ_ONLY_INTENTS and self._understood(command):
            # Looking something up changes nothing, so no second confirmation.
            self.active_conversation = True
            self.last_active_time = self.clock()
            self.speech.stop()
            record('dialogue_turn', reply='', proposal=turn.proposal, duration_ms=dialogue_ms,
                   model_called=self.dialogue.model_called, trigger=trigger, ran_read_only=True)
            self.state.clear('read-only proposal')
            self._run(command)
            return True
        reply = ((self._propose(turn.proposal) if turn.proposal else None) or turn.reply or
                 "I couldn't work out that request. Could you say it again?")
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
        if result.pending_action == 'reminder_task':
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
