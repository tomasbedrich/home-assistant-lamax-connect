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
from .models import (
    GROUP_RECEIVER,
    MAX_MESSAGE_LENGTH,
    MSG_TYPE_TEXT,
    Device,
    DeviceSnapshot,
    GeoFence,
    Health,
    Location,
    Message,
    TrackPoint,
    truncate_message,
)

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
        self._credentials: tuple[str, str, str, str | None] | None = None
        self._login_lock = asyncio.Lock()
        # Bumped on every successful login so concurrent requests that race a
        # session expiry only trigger a single re-login between them.
        self._session_generation = 0

    @property
    def host(self) -> str:
        """Backend host this client talks to."""
        return self._host

    async def _post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        ok_codes: tuple[int, ...] = (CODE_OK,),
    ) -> dict[str, Any]:
        """POST an encrypted JSON body and return the decrypted response.

        ``ok_codes`` declares which ``code`` values mean success for this
        endpoint - the API reuses the same numeric space for different meanings
        per endpoint, so only codes actually observed as success are accepted.

        The backend allows only one session per account, so a login elsewhere
        (typically the phone app) silently invalidates our token. That surfaces
        as ``code 25``; we re-login once and retry rather than failing.
        """
        generation = self._session_generation
        try:
            return await self._post_once(path, body, ok_codes=ok_codes)
        except LamaxAuthError as err:
            if err.code != CODE_SESSION_EXPIRED or self._credentials is None:
                raise
            _LOGGER.debug("Session expired on %s, re-authenticating", path)
            await self._async_relogin(generation)
            return await self._post_once(path, body, ok_codes=ok_codes)

    async def _async_relogin(self, generation: int) -> None:
        """Re-establish the session, unless another task already did."""
        async with self._login_lock:
            if self._session_generation != generation:
                _LOGGER.debug("Session already refreshed by another request")
                return
            assert self._credentials is not None
            username, password, login_type, country = self._credentials
            await self.login(username, password, login_type, country)

    async def _post_once(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        ok_codes: tuple[int, ...] = (CODE_OK,),
    ) -> dict[str, Any]:
        """Perform a single request without retrying."""
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
        _LOGGER.debug("%s -> code %s", path, code)
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
        result = await self._post_once("/user/login", body)
        self.token = str(result["token"])
        self.u_id = int(result["u_id"])
        self._credentials = (username, password, login_type, country)
        self._session_generation += 1
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

    async def async_get_health(self, d_id: int, imei: str) -> Health:
        """Return the latest activity and health readings for a watch.

        This one endpoint carries steps, calories, distance, heart rate and
        blood oxygen. Note the ``step`` field of the *location* response is
        unrelated and always "0" - the real counter is ``devicestep`` here.
        """
        result = await self._post(
            "/heath/getLastAllByDeviceLocalTimePost", {"did": d_id, "imei": imei}
        )
        return Health.from_json(result)

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
            ok_codes=(CODE_OK, CODE_NO_DATA),
        )
        return [GeoFence.from_json(item) for item in result.get("GeoFenceList", [])]

    # -- messaging --------------------------------------------------------

    async def async_send_message(
        self, imei: str, d_id: int, message: str, msg_type: int = MSG_TYPE_TEXT
    ) -> str:
        """Send a private message to a watch. Returns the text actually sent."""
        return await self._async_send(
            "/rtosWechat/appSendDevice", imei, d_id, f"FFF{imei}", message, msg_type
        )

    async def async_send_group_message(
        self, imei: str, d_id: int, message: str, msg_type: int = MSG_TYPE_TEXT
    ) -> str:
        """Send a message to the family conversation.

        Returns the text actually sent, which may be truncated.
        """
        return await self._async_send(
            "/rtosWechat/appSendGroupMsg", imei, d_id, GROUP_RECEIVER, message, msg_type
        )

    async def _async_send(
        self,
        path: str,
        imei: str,
        d_id: int,
        receiver: str,
        message: str,
        msg_type: int,
    ) -> str:
        """Post a chat message, truncating it the way the watch would."""
        if self.u_id is None:
            raise LamaxAuthError(CODE_SESSION_EXPIRED, "Not logged in")

        text = truncate_message(message)
        if text != message:
            _LOGGER.warning(
                "Message truncated to the watch limit of %s units: %r -> %r",
                MAX_MESSAGE_LENGTH,
                message,
                text,
            )

        stamp = datetime.now().strftime("%y%m%d%H%M%S")
        await self._post(
            path,
            {
                "d_id": d_id,
                "imei": imei,
                "msg_type": msg_type,
                "msg_content": f"{stamp}_{self.u_id}_{receiver}_{text}",
            },
        )
        return text

    async def async_get_messages(self, d_id: int) -> list[Message]:
        """Return messages sent from a watch.

        The backend keeps returning delivered messages, so callers must
        de-duplicate on :attr:`Message.raw`. Live delivery in the official app
        goes over RongCloud IM; this is the polling fallback.
        """
        result = await self._post(
            "/rtosWechat/getVoiceListPost",
            {"did": d_id},
            ok_codes=(CODE_OK, CODE_NO_DATA),
        )
        parsed = (Message.from_json(item) for item in result.get("chaMsgList", []))
        return [message for message in parsed if message is not None]

    # -- convenience ------------------------------------------------------

    async def async_get_snapshots(self) -> dict[str, DeviceSnapshot]:
        """Return every bound watch with its last position and step count.

        Per-watch lookups run concurrently. A watch whose position or health
        lookup fails is still returned, with ``None`` for the missing part, so
        one flaky reading never hides the whole account.
        """
        devices = await self.async_get_devices()
        if not devices:
            return {}

        # _async_snapshot absorbs per-reading failures itself and only lets an
        # expired session through, so anything raised here is worth surfacing.
        snapshots = await asyncio.gather(*(self._async_snapshot(device) for device in devices))
        return {snapshot.device.imei: snapshot for snapshot in snapshots}

    async def _async_snapshot(self, device: Device) -> DeviceSnapshot:
        """Gather the per-watch readings, tolerating individual failures."""
        location_result, health_result, messages_result = await asyncio.gather(
            self.async_get_location(device.d_id),
            self.async_get_health(device.d_id, device.imei),
            self.async_get_messages(device.d_id),
            return_exceptions=True,
        )
        for value in (location_result, health_result, messages_result):
            if isinstance(value, LamaxAuthError):
                raise value

        location: Location | None = None
        if isinstance(location_result, BaseException):
            _LOGGER.debug("No location for %s: %s", device.imei, location_result)
        else:
            location = location_result

        health: Health | None = None
        if isinstance(health_result, BaseException):
            _LOGGER.debug("No health data for %s: %s", device.imei, health_result)
        else:
            health = health_result

        messages: tuple[Message, ...] = ()
        if isinstance(messages_result, BaseException):
            _LOGGER.debug("No messages for %s: %s", device.imei, messages_result)
        else:
            messages = tuple(messages_result)

        return DeviceSnapshot(device, location, health, messages)
