"""Unofficial async client for the LAMAX Connect kids' GPS watch backend.

This package is self-contained and has no Home Assistant imports, so it can be
extracted into a standalone PyPI package later without changes.
"""

from .client import (
    ALTERNATE_HOST,
    DEFAULT_HOST,
    LOGIN_TYPE_EMAIL,
    LOGIN_TYPE_PHONE,
    LamaxClient,
)
from .exceptions import LamaxAuthError, LamaxConnectionError, LamaxError
from .models import (
    GROUP_RECEIVER,
    MAX_MESSAGE_LENGTH,
    MSG_KINDS,
    MSG_TYPE_EMOJI,
    MSG_TYPE_TEXT,
    MSG_TYPE_VOICE,
    Device,
    DeviceSnapshot,
    GeoFence,
    Health,
    Location,
    Message,
    TrackPoint,
    message_width,
    truncate_message,
)

__all__ = [
    "ALTERNATE_HOST",
    "DEFAULT_HOST",
    "GROUP_RECEIVER",
    "LOGIN_TYPE_EMAIL",
    "LOGIN_TYPE_PHONE",
    "MAX_MESSAGE_LENGTH",
    "MSG_KINDS",
    "MSG_TYPE_EMOJI",
    "MSG_TYPE_TEXT",
    "MSG_TYPE_VOICE",
    "Device",
    "DeviceSnapshot",
    "GeoFence",
    "Health",
    "LamaxAuthError",
    "LamaxClient",
    "LamaxConnectionError",
    "LamaxError",
    "Location",
    "Message",
    "TrackPoint",
    "message_width",
    "truncate_message",
]
