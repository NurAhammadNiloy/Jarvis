"""Compatibility entry point for the existing voice conversation loop."""
from core.command_engine import execute_query
from core.command_output import VoiceNotifications, deliver_result, speak
from core.command_services import CommandServices

_voice_services = CommandServices(notifications=VoiceNotifications())


def handle_query(query, *, services=None, output=None):
    """Execute and deliver once; preserve True/False/pending legacy values.

    Text callers use execute_query. Tests can inject services and output.
    """
    result = execute_query(query, services=services if services is not None else _voice_services)
    deliver_result(result, output if output is not None else speak)
    return result.legacy_value()
