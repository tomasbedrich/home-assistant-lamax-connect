"""Exceptions raised by the LAMAX Connect client."""

from __future__ import annotations


class LamaxError(Exception):
    """Base error. Carries the backend's numeric code and message."""

    def __init__(self, code: int, msg: str = "") -> None:
        """Initialize the error."""
        super().__init__(f"LAMAX API error {code}: {msg}" if msg else f"LAMAX API error {code}")
        self.code = code
        self.msg = msg


class LamaxAuthError(LamaxError):
    """Credentials rejected (code 24) or session expired (code 25)."""


class LamaxConnectionError(LamaxError):
    """The backend could not be reached, or returned an undecodable response."""

    def __init__(self, msg: str) -> None:
        """Initialize the error."""
        super().__init__(-1, msg)
