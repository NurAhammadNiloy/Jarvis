"""Network calls carry the shared timeout and failures surface as error results."""
from unittest.mock import Mock, patch

import pytest
import requests

from config.settings import NETWORK_TIMEOUT_SECONDS
from core.command_engine import execute_query
from core.service_errors import ServiceError


def services(**overrides):
    fake = Mock()
    fake.follow_up.return_value = None
    fake.extract_reminder_info.return_value = {}
    for name, value in overrides.items():
        setattr(fake, name, value)
    return fake


def test_timeout_constant_is_positive():
    assert NETWORK_TIMEOUT_SECONDS > 0


def test_weather_request_has_timeout_and_timeout_is_a_service_error():
    from core import weather_service
    with patch.object(weather_service.requests, 'get', side_effect=requests.exceptions.Timeout) as get:
        with pytest.raises(ServiceError, match='too long'):
            weather_service.get_weather('Kokkola')
    assert get.call_args.kwargs['timeout'] == NETWORK_TIMEOUT_SECONDS


def test_forecast_request_has_timeout_and_timeout_is_a_service_error():
    from core import weather_service
    with patch.object(weather_service.requests, 'get', side_effect=requests.exceptions.Timeout) as get:
        with pytest.raises(ServiceError, match='too long'):
            weather_service.get_forecast('Kokkola')
    assert get.call_args.kwargs['timeout'] == NETWORK_TIMEOUT_SECONDS


def test_weather_http_error_is_a_service_error():
    from core import weather_service
    with patch.object(weather_service.requests, 'get', return_value=Mock(status_code=404)):
        with pytest.raises(ServiceError, match="couldn't find"):
            weather_service.get_weather('Nowhere')


def test_chat_request_has_timeout_and_timeout_is_a_service_error():
    import openai
    from core import chatgpt_service
    with patch.object(chatgpt_service.openai.ChatCompletion, 'create',
                      side_effect=openai.error.Timeout('slow')) as create:
        with pytest.raises(ServiceError, match='too long'):
            chatgpt_service.get_chatgpt_response('hello')
    assert create.call_args.kwargs['request_timeout'] == NETWORK_TIMEOUT_SECONDS


def test_youtube_timeout_is_a_service_error():
    from core import youtube_service
    search = Mock()
    search.search.return_value.list.return_value.execute.side_effect = TimeoutError
    with patch.object(youtube_service, 'youtube', search):
        with pytest.raises(ServiceError, match='too long'):
            youtube_service.search_youtube('lofi')


def test_youtube_client_is_built_with_a_timeout():
    from core import youtube_service
    assert youtube_service.youtube._http.timeout == NETWORK_TIMEOUT_SECONDS


@pytest.mark.parametrize('query, attr', [
    ("what's the weather in Oslo", 'weather'),
    ('give me the forecast for Oslo', 'forecast'),
    ('tell me a story', 'chat'),
    ('play lofi on youtube', 'youtube'),
])
def test_provider_timeout_gives_a_failed_result_with_a_spoken_message(query, attr):
    message = 'The service took too long to respond. Please try again.'
    fake = services(**{attr: Mock(side_effect=ServiceError(message))})
    result = execute_query(query, fake)
    assert result.status == 'error'
    assert result.messages == (message,)
    assert result.legacy_value() is False
