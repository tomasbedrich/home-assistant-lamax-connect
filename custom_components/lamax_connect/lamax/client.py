"""Async client for the LAMAX Connect ("watchxr") backend.

Reverse engineered from the LAMAX Connect Android app v1.0.17
(``com.ztc.lamax``) and verified against the live backend. Unofficial and
unaffiliated with LAMAX - endpoints may change without notice.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from typing import Any, Final

import aiohttp

from .crypto import decrypt, encrypt
from .exceptions import LamaxAuthError, LamaxConnectionError, LamaxError
from .models import MSG_TYPE_TEXT, Device, GeoFence, Location, TrackPoint

_LOGGER = logging.getLogger(__name__)

DEFAULT_HOST: Final = "elem6.wisskys.com"
ALTERNATE_HOST: Final = "elem6.lagenio.com"

# Static constant the app sends on every request; not a real version string.
_APP_SECRET: Final = "YkMG%4#^4LUIunhg"
_APP_VERSION: Final = "1.0.17"
_TIMEOUT: Final = aiohttp.ClientTimeout(total=30)

# Backend result codes. The API reuses this numeric space per endpoint, so
# success is declared per call rather than globally.
CODE_OK: Final = 0
CODE_OK_ALT: Final = 4
CODE_NO_DATA: Final = 2  # e.g. "no geofences configured" - not an error
CODE_BAD_CREDENTIALS: Final = 24
CODE_SESSION_EXPIRED: Final = 25

LOGIN_TYPE_EMAIL: Final = "1"
LOGIN_TYPE_PHONE: Final = "2"


class LamaxClient:
    """Talks to the LAMAX Connect backend on behalf of one account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        host: str = DEFAULT_HOST,
        language_type: str = "13",
    ) -> None:
        """Initialize the client with an injected aiohttp session."""
        self._session = session
        self._host = host
        self._language_type = language_type
        self.token: str | None = None
        self.u_id: int | None = None

    @property
    def host(self) -> str:
        """Backend host this client talks to."""
        return self._host

    async def _post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        ok_codes: tuple[int, ...] = (CODE_OK, CODE_OK_ALT),
    ) -> dict[str, Any]:
        """POST an encrypted JSON body and return the decrypted response.

        ``ok_codes`` declares which ``code`` values mean success for this
        endpoint.
        """
        payload: dict[str, Any] = {**(body or {}), "version": _APP_SECRET}
        if self.token is not None:
            payload.setdefault("token", self.token)

        url = f"https://{self._host}/watchxr{path}"
        try:
            async with self._session.post(
                url, data=encrypt(json.dumps(payload)), timeout=_TIMEOUT
            ) as response:
                response.raise_for_status()
                raw = await response.text()
        except TimeoutError as err:
            raise LamaxConnectionError(f"Timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise LamaxConnectionError(f"Error calling {path}: {err}") from err

        plaintext = decrypt(raw)
        if plaintext is None:
            raise LamaxConnectionError(f"Undecodable response from {path}")
        try:
            result: dict[str, Any] = json.loads(plaintext)
        except json.JSONDecodeError as err:
            raise LamaxConnectionError(f"Malformed JSON from {path}") from err

        code = int(result.get("code", -1))
        if code in (CODE_BAD_CREDENTIALS, CODE_SESSION_EXPIRED):
            raise LamaxAuthError(code, result.get("msg", ""))
        if code not in ok_codes:
            raise LamaxError(code, result.get("msg", ""))
        return result

    # -- authentication ---------------------------------------------------

    async def login(
        self,
        username: str,
        password: str,
        login_type: str = LOGIN_TYPE_EMAIL,
        country: str | None = None,
    ) -> None:
        """Authenticate and remember the session token.

        ``login_type`` is "1" for email or "2" for phone; ``country`` is the
        dial code without a leading "+" and is only used for phone logins.
        """
        body: dict[str, Any] = {
            "username": username,
            "pwd": password,
            "type": login_type,
            "languageType": self._language_type,
            "app-version": f"Android-LAMAX-{_APP_VERSION}",
        }
        if country:
            body["country"] = country
        result = await self._post("/user/login", body)
        self.token = str(result["token"])
        self.u_id = int(result["u_id"])
        _LOGGER.debug("Logged in as u_id %s", self.u_id)

    # -- devices ----------------------------------------------------------

    async def async_get_devices(self) -> list[Device]:
        """List the watches bound to this account."""
        result = await self._post("/watchAppUser/getbindDeviceListPost")
        return [Device.from_json(item) for item in result.get("deviceList", [])]

    async def async_find_device(self, imei: str) -> None:
        """Make the watch ring so it can be located physically."""
        await self._post("/controllerDevice/findPost", {"imei": imei})

    # -- geolocation ------------------------------------------------------

    async def async_request_location_update(self, imei: str) -> None:
        """Ask the watch to push a fresh GPS fix.

        The fix is not in the response - poll :meth:`async_get_location`
        shortly afterwards.
        """
        await self._post("/controllerDevice/ask/localtionPost", {"imei": imei})

    async def async_get_location(self, d_id: int) -> Location:
        """Return the last position reported by a watch."""
        result = await self._post("/location/getlast/searchPost", {"did": d_id})
        return Location.from_json(result)

    async def async_get_track_history(
        self, d_id: int, start: datetime, end: datetime
    ) -> list[TrackPoint]:
        """Return position history for a watch between two timestamps."""
        fmt = "%Y-%m-%d %H:%M:%S"
        result = await self._post(
            "/location/watchtrackPost",
            {
                "did": d_id,
                "starttime": start.strftime(fmt),
                "endtime": end.strftime(fmt),
                "startTime": start.strftime(fmt),
                "endTime": end.strftime(fmt),
            },
        )
        return [TrackPoint.from_json(item) for item in result.get("List", [])]

    # -- geofences --------------------------------------------------------

    async def async_get_geofences(self, d_id: int) -> list[GeoFence]:
        """Return the geofences configured for a watch."""
        result = await self._post(
            "/security/getwatchfencePost",
            {"did": d_id},
            ok_codes=(CODE_OK, CODE_NO_DATA, CODE_OK_ALT),
        )
        return [GeoFence.from_json(item) for item in result.get("GeoFenceList", [])]

    # -- messaging --------------------------------------------------------

    async def async_send_message(
        self, imei: str, d_id: int, message: str, msg_type: int = MSG_TYPE_TEXT
    ) -> None:
        """Send a text or emoji message to a watch."""
        if self.u_id is None:
            raise LamaxAuthError(CODE_SESSION_EXPIRED, "Not logged in")
        stamp = datetime.now().strftime("%y%m%d%H%M%S")
        await self._post(
            "/rtosWechat/appSendDevice",
            {
                "d_id": d_id,
                "imei": imei,
                "msg_type": msg_type,
                "msg_content": f"{stamp}_{self.u_id}_FFF{imei}_{message}",
            },
        )

    # -- convenience ------------------------------------------------------

    async def async_get_devices_with_location(self) -> dict[str, tuple[Device, Location | None]]:
        """Return every bound watch together with its last known position.

        Locations are fetched concurrently; a watch whose position lookup fails
        is still returned, with ``None`` for the location.
        """
        devices = await self.async_get_devices()
        if not devices:
            return {}

        locations = await asyncio.gather(
            *(self.async_get_location(device.d_id) for device in devices),
            return_exceptions=True,
        )
        result: dict[str, tuple[Device, Location | None]] = {}
        for device, location in zip(devices, locations, strict=True):
            if isinstance(location, BaseException):
                if isinstance(location, LamaxAuthError):
                    raise location
                _LOGGER.debug("No location for %s: %s", device.imei, location)
                result[device.imei] = (device, None)
            else:
                result[device.imei] = (device, location)
        return result
