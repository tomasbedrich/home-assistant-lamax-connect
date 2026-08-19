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
    MSG_TYPE_EMOJI,
    MSG_TYPE_TEXT,
    MSG_TYPE_VOICE,
    Device,
    DeviceSnapshot,
    GeoFence,
    Location,
    TrackPoint,
)

__all__ = [
    "ALTERNATE_HOST",
    "DEFAULT_HOST",
    "LOGIN_TYPE_EMAIL",
    "LOGIN_TYPE_PHONE",
    "MSG_TYPE_EMOJI",
    "MSG_TYPE_TEXT",
    "MSG_TYPE_VOICE",
    "Device",
    "DeviceSnapshot",
    "GeoFence",
    "LamaxAuthError",
    "LamaxClient",
    "LamaxConnectionError",
    "LamaxError",
    "Location",
    "TrackPoint",
]
