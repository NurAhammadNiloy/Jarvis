"""Concurrency and playback contract tests; all devices/providers are fake."""
import io
import threading
import types
import wave
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest

from core.speech_output import PCMClip, SoundDevicePlayer, SpeechController, speech_chunks
from core.speech_synthesis import create_dynamic_ssml


CLIP = PCMClip(b'\0' * 960, 24000)


def test_cancel_during_generation_discards_late_audio_and_pending_jobs():
    entered, release = threading.Event(), threading.Event()
    def generate(text, **kwargs):
        entered.set()
        assert release.wait(2)
        return CLIP
    player = Mock()
    output = SpeechController(generate, player)
    try:
        first = output.submit('Long response.')
        assert entered.wait(1)
        second = output.submit('Queued reminder.')
        assert output.stop(expected_id=first.id)
        assert second.done.is_set() and second.cancelled.is_set()
        assert not output.is_speaking()
        release.set()
        assert first.wait(1)
        player.play.assert_not_called()
    finally:
        release.set()
        output.close()


def test_cancel_active_playback_and_recover_for_next_response():
    playing = threading.Event()
    played = []
    def play(clip, cancelled):
        played.append(clip)
        if len(played) == 1:
            playing.set()
            assert cancelled.wait(2)
    output = SpeechController(lambda text: CLIP, types.SimpleNamespace(play=play))
    try:
        first = output.submit('First')
        assert playing.wait(1)
        output.stop()
        assert first.wait(1)
        second = output.submit('Second')
        assert second.wait(1)
        assert len(played) == 2
        assert not output.is_speaking()
    finally:
        output.close()


def test_old_interruption_cannot_cancel_new_speech():
    entered = threading.Event()
    def play(clip, cancelled):
        entered.set()
        cancelled.wait(2)
    output = SpeechController(lambda text: CLIP, types.SimpleNamespace(play=play))
    try:
        first = output.submit('First')
        assert entered.wait(1)
        output.stop()
        assert first.wait(1)
        entered.clear()
        second = output.submit('Second')
        assert entered.wait(1)
        assert not output.stop(expected_id=first.id)
        assert not second.cancelled.is_set()
    finally:
        output.close()


def test_generating_and_playing_exceptions_clear_busy_state():
    synth = Mock(side_effect=[RuntimeError('provider failed'), CLIP, CLIP])
    player = Mock()
    player.play.side_effect = [RuntimeError('device failed'), None]
    output = SpeechController(synth, player)
    try:
        jobs = [output.submit('First'), output.submit('Second'), output.submit('Third')]
        assert output.wait(2)
        assert isinstance(jobs[0].error, RuntimeError)
        assert isinstance(jobs[1].error, RuntimeError)
        assert jobs[2].error is None
        assert not output.is_speaking()
    finally:
        output.close()


def test_new_output_waits_for_user_endpoint_and_priority_cancels_old_queue():
    player = Mock()
    output = SpeechController(lambda text: CLIP, player)
    try:
        output.set_input_active(True)
        first = output.submit('Old')
        second = output.submit('New', priority=True)
        assert first.cancelled.is_set()
        player.play.assert_not_called()
        output.set_input_active(False)
        assert second.wait(1)
        player.play.assert_called_once()
    finally:
        output.close()


def test_concurrent_alerts_share_one_playback_owner():
    calls = []
    output = SpeechController(lambda text: CLIP, types.SimpleNamespace(play=lambda clip, cancel: calls.append(threading.get_ident())))
    try:
        threads = [threading.Thread(target=output.submit, args=(str(i),)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        assert output.wait(2)
        assert len(calls) == 10
        assert len(set(calls)) == 1
    finally:
        output.close()


def test_response_is_chunked_without_dropping_words():
    text = 'This is a sentence. ' * 80
    chunks = speech_chunks(text)
    assert len(chunks) > 1 and max(map(len, chunks)) <= 240
    assert ' '.join(chunks).split() == text.split()


def test_short_multisentence_reply_uses_one_synthesis_request():
    text = 'Loud and clear, sir. How can I assist you today?'
    synth = Mock(return_value=CLIP)
    output = SpeechController(synth, Mock())
    try:
        assert output.submit(text).wait(1)
        synth.assert_called_once_with(text)
    finally:
        output.close()


@pytest.mark.parametrize('cancel', [False, True])
def test_generation_runs_during_input_but_playback_waits(cancel):
    generated = threading.Event()
    def synth(text):
        generated.set()
        return CLIP
    player = Mock()
    output = SpeechController(synth, player)
    output.set_input_active(True)
    try:
        job = output.submit('Ready before the user finishes.')
        assert generated.wait(1)
        player.play.assert_not_called()
        assert not output.snapshot().audible
        if cancel:
            job.cancel()
        else:
            output.set_input_active(False)
        assert job.wait(1)
        assert player.play.call_count == (0 if cancel else 1)
    finally:
        output.close()


def test_ssml_escapes_plain_response_text():
    text = 'Tom & Jerry say 2 < 3. <audio src="x" />'
    assert ET.fromstring(create_dynamic_ssml(text)).text == text
    assert list(ET.fromstring(create_dynamic_ssml(text))) == []


def test_linear16_wav_header_is_decoded_before_playback():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(CLIP.data)
    assert PCMClip.from_wav(buffer.getvalue()) == CLIP


class CallbackAbort(Exception):
    pass


class CallbackStop(Exception):
    pass


def test_device_callback_honors_stop_and_zeroes_output():
    cancel = threading.Event()
    stream = Mock()
    params = {}
    def factory(**kwargs):
        params.update(kwargs)
        return stream
    def start():
        cancel.set()
        data = bytearray(960)
        with pytest.raises(CallbackAbort):
            params['callback'](data, 480, None, None)
        assert data == b'\0' * 960
        params['finished_callback']()
    stream.start.side_effect = start
    backend = types.SimpleNamespace(RawOutputStream=factory, CallbackAbort=CallbackAbort, CallbackStop=CallbackStop)
    SoundDevicePlayer(backend=backend).play(CLIP, cancel)
    stream.close.assert_called_once()
    assert params['blocksize'] == 480


def test_cancelled_audio_never_opens_device():
    backend = Mock()
    cancelled = threading.Event()
    cancelled.set()
    SoundDevicePlayer(backend=backend).play(CLIP, cancelled)
    backend.RawOutputStream.assert_not_called()
