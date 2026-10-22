"""Voice orchestration around the unchanged speech-independent command boundary."""
import random
import time

from core.command_engine import execute_query
from core.command_output import VoiceNotifications, deliver_result
from core.command_services import CommandServices
from core.voice_policy import ConfidenceGate, strip_wake_word, words
from core.conversation_log import record
from core.intent_classifier import route


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
        self.listener, self.speech, self.output = listener, speech, output
        if self.dialogue is not None:
            def conversational_output(text):
                self.dialogue.observe('assistant', text)
                return output(text)
            self.output = conversational_output
        self.services = services if services is not None else CommandServices(VoiceNotifications())
        self.clock = clock
        self.gate = ConfidenceGate(clock)
        self.active_conversation = False
        self.conversation_timeout = 120
        self.last_active_time = clock()
        self.pending_reminder = None
        self._recognition_failure_prompted = False

    def process_recognition(self, recognition, passive=False):
        """Only final, accepted transcripts may reach execute_query."""
        if recognition is None:
            return False
        if recognition.error and recognition.error.startswith('microphone_'):
            raise RuntimeError('Microphone capture failed: ' + recognition.error)
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
            # Background noise must not repeatedly speak or extend the session.
            if self.speech.is_speaking():
                record('voice_decision', decision='ignore', reason='unrecognized_while_response_pending', text='')
                return False
            if self._recognition_failure_prompted:
                record('voice_decision', decision='ignore', reason='repeated_unrecognized_audio', text='')
                return False
            self._recognition_failure_prompted = True
            prompt = "I couldn't hear that clearly. Please try again."
            record('voice_decision', decision='clarify', reason='unrecognized_audio', text='', prompt=prompt)
            self.output(prompt)
            return True
        if recognition.text and not recognition.error:
            self._recognition_failure_prompted = False
        decision = self.gate.assess(recognition, text=text,
                                    force_important=self.pending_reminder is not None)
        if self.dialogue is not None and decision.kind != 'stop' and not recognition.error and not recognition.truncated and text:
            # Only new reminders need the dialogue's confirmation; list, delete
            # and snooze run (or refuse) directly.
            if self.dialogue.repairing or decision.kind == 'clarify' or route(text).intent in {'chat', 'create_reminder'}:
                from dataclasses import replace
                turn = self.dialogue.turn(replace(recognition, text=text), reason=(
                    decision.prompt if decision.kind == 'clarify' else 'conversation'))
                self.active_conversation = True
                self.last_active_time = self.clock()
                self.speech.stop()
                record('dialogue_turn', reply=turn.reply, confirmed_query=turn.query)
                if turn.reply:
                    self.output(turn.reply)
                    return True
                # Only the dialogue's deterministic confirmation branch yields
                # an executable query. The model can only create a proposal.
                self.pending_reminder = None
                record('command_started', text=turn.query)
                result = execute_query(turn.query, self.services)
                record('command_result', status=result.status, intent=result.intent,
                       messages=list(result.messages), pending_action=result.pending_action)
                deliver_result(result, self.output)
                return True
            self.dialogue.observe('user', text)
        record('voice_decision', decision=decision.kind, text=text,
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
        query = decision.text
        if self.pending_reminder:
            # The answer completes the original request, which is parsed once.
            query = f"{self.pending_reminder['query']} {query}"
        record('command_started', text=query)
        result = execute_query(query, self.services)
        record('command_result', status=result.status, intent=result.intent, messages=list(result.messages),
               pending_action=result.pending_action)
        if result.pending_action == 'reminder_time':
            self.pending_reminder = {'query': result.data.get('query') or f"remind me to {result.data['task']}"}
        elif result.status != 'error':
            self.pending_reminder = None
        deliver_result(result, self.output)
        return True

    def wait_for_wake_word(self):
        print("[Passive mode - say 'Jarvis' to wake]")
        while True:
            if self.process_recognition(self.listener.listen(timeout=1), passive=True):
                return

    def listen_for_command(self):
        self.active_conversation = True
        self.last_active_time = self.clock()
        while self.active_conversation:
            self.process_recognition(self.listener.listen(timeout=1))
            if (not self.speech.is_speaking() and not self.listener.is_capturing and
                    self.clock() - self.last_active_time > self.conversation_timeout):
                self.active_conversation = False
                self.output("I'm here whenever you need me. Just say 'Jarvis' to wake me up.")

    def close(self):
        self.speech.stop()
        self.listener.close()
        self.speech.close()
