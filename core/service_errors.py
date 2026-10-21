"""Failure signal shared by network-backed services and the command boundary."""


class ServiceError(Exception):
    """A provider failed. str(exc) is a short message that is safe to speak."""
