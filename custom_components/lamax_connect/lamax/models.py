"""Typed views over the LAMAX Connect JSON payloads.

Field names mirror the wire format exactly where practical; the shapes were
confirmed against the live backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# msg_type values used by the /rtosWechat endpoints
MSG_TYPE_TEXT = 1
MSG_TYPE_EMOJI = 2
MSG_TYPE_VOICE = 3

MSG_KINDS = {MSG_TYPE_TEXT: "text", MSG_TYPE_EMOJI: "emoji", MSG_TYPE_VOICE: "voice"}

# The watch silently trims longer messages, so truncate up front and say so
# rather than letting the recipient receive half a sentence unannounced.
#
# The budget is 30 *weighted* units, not characters or bytes: the app's own
# input filter (com.ztc.lamax.ui.inputfilter.ChineseInputFiler) counts CJK and
# a few punctuation blocks as 2 and everything else as 1. Latin text, including
# Czech diacritics, therefore gets the full 30 characters.
MAX_MESSAGE_LENGTH = 30

# Unicode blocks the app's filter charges double, as Java UnicodeBlock ranges.
_DOUBLE_WIDTH_RANGES = (
    (0x2000, 0x206F),  # General Punctuation (curly quotes, dashes, ellipsis)
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFFEF),  # Halfwidth and Fullwidth Forms
)


def _char_width(char: str) -> int:
    """Return the weight the watch's input filter assigns to one character."""
    code = ord(char)
    return 2 if any(low <= code <= high for low, high in _DOUBLE_WIDTH_RANGES) else 1


def message_width(text: str) -> int:
    """Return the weighted length the watch measures a message by."""
    return sum(_char_width(char) for char in text)


def truncate_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> str:
    """Trim text to what the watch will actually accept."""
    used = 0
    for index, char in enumerate(text):
        used += _char_width(char)
        if used > limit:
            return text[:index]
    return text


# Receiver segment of msg_content that marks the shared family conversation
# (a private message addresses the watch as "FFF<imei>" instead).
GROUP_RECEIVER = "1"

# The watch reports 255 in the battery field while charging rather than a
# percentage (LocationFragment shows a charging icon for it).
BATTERY_CHARGING = 255

# locationType of a position report: 1 = LBS (cell tower), 2 = WiFi, anything
# else = GPS (LocationFragment.c1 picks the ic_lbs / ic_wifi / ic_gps icon on
# exactly that). Only the cell tower estimate is treated as untrustworthy here -
# a WiFi fix from this hardware came back accurate to 25 m, while a tower can be
# kilometres out and would still drag Home Assistant's zone matching with it.
LOCATION_TYPE_LBS = 1
LOCATION_TYPE_WIFI = 2


type JsonDict = dict[str, Any]


def _as_float(value: Any) -> float | None:
    """Coerce a loosely-typed backend value to a float, or None if unusable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_epoch_ms(value: Any) -> datetime | None:
    """Parse an epoch-milliseconds field, which may arrive as str or int."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms > 0 else None


def _positive_or_none(value: int | None) -> int | None:
    """Treat 0 as "never measured" - 0 bpm and 0% SpO2 are not real readings."""
    return value if value else None


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a loosely-typed backend value to an int, falling back to default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Device:
    """A watch bound to the account."""

    imei: str
    name: str
    d_id: int
    device_type: int
    firmware: str

    @property
    def unique_id(self) -> str:
        """Stable identifier for this watch."""
        return self.imei

    @classmethod
    def from_json(cls, data: JsonDict) -> Device:
        """Build from a /watchAppUser/getbindDeviceListPost entry."""
        return cls(
            imei=str(data.get("imei", "")),
            name=str(data.get("name") or data.get("imei", "")),
            d_id=_as_int(data.get("d_id")),
            device_type=_as_int(data.get("device_type")),
            # "L36W_A_S90_WC_VE_V001_250801#newoss01#0" -> "L36W_A_S90_WC_VE_V001_250801"
            firmware=str(data.get("dv", "")).split("#")[0],
        )


@dataclass(frozen=True, slots=True)
class Location:
    """A position report from a watch."""

    latitude: float | None
    longitude: float | None
    battery: int | None
    charging: bool
    accuracy: int
    location_type: int
    description: str
    updated_at: datetime | None

    @property
    def is_coarse(self) -> bool:
        """Return True for a cell tower estimate, which can be kilometres off."""
        return self.location_type == LOCATION_TYPE_LBS

    @classmethod
    def from_json(cls, data: JsonDict) -> Location:
        """Build from a /location/getlast/searchPost response."""
        uploadtime = _as_int(data.get("uploadtime"), 0)
        level = _as_int(data.get("Electricity"))
        charging = level == BATTERY_CHARGING
        return cls(
            latitude=_as_float(data.get("lat")),
            longitude=_as_float(data.get("lng")),
            # While charging the field is a sentinel, not a percentage - and 0
            # is not a reading either: a watch flat enough to report 0 % is off
            # and reports nothing at all. It rides along with positions the
            # backend stored without a battery sample.
            battery=level if level and not charging else None,
            charging=charging,
            accuracy=_as_int(data.get("accuracy")),
            location_type=_as_int(data.get("locationType")),
            description=str(data.get("desc", "")),
            updated_at=(datetime.fromtimestamp(uploadtime / 1000, tz=UTC) if uploadtime else None),
        )


@dataclass(frozen=True, slots=True)
class GeoFence:
    """A geofence configured for a watch."""

    id: int
    name: str
    latitude: float | None
    longitude: float | None
    radius: int
    notify_on_entry: bool
    notify_on_exit: bool
    enabled: bool

    @classmethod
    def from_json(cls, data: JsonDict) -> GeoFence:
        """Build from a /security/getwatchfencePost entry."""
        return cls(
            id=_as_int(data.get("id")),
            name=str(data.get("fenceName", "")),
            latitude=_as_float(data.get("lat")),
            longitude=_as_float(data.get("lng")),
            radius=_as_int(data.get("Radius", data.get("radius"))),
            notify_on_entry=bool(_as_int(data.get("entry"), 1)),
            notify_on_exit=bool(_as_int(data.get("exit"), 1)),
            enabled=bool(_as_int(data.get("enable"), 1)),
        )


@dataclass(frozen=True, slots=True)
class TrackPoint:
    """A single point of location history."""

    latitude: float | None
    longitude: float | None
    location_type: int
    recorded_at: datetime | None

    @classmethod
    def from_json(cls, data: JsonDict) -> TrackPoint:
        """Build from a /location/watchtrackPost entry."""
        uploadtime = _as_int(data.get("uploadtime"), 0)
        return cls(
            latitude=_as_float(data.get("lat")),
            longitude=_as_float(data.get("lng")),
            location_type=_as_int(data.get("locationType")),
            recorded_at=(datetime.fromtimestamp(uploadtime / 1000, tz=UTC) if uploadtime else None),
        )


@dataclass(frozen=True, slots=True)
class Health:
    """Activity and health readings from a watch.

    Heart rate and blood oxygen are only recorded when a measurement is taken
    on the watch, so they can be days or weeks old - always pair them with
    their ``*_at`` timestamp. Body temperature and blood pressure exist in the
    payload but read as 0 on the tested hardware, so they are not surfaced.
    """

    steps: int | None
    steps_at: datetime | None
    calories: int | None
    distance_km: float | None
    heart_rate: int | None
    heart_rate_at: datetime | None
    blood_oxygen: int | None
    blood_oxygen_at: datetime | None

    @classmethod
    def from_json(cls, data: JsonDict) -> Health:
        """Build from a /heath/getLastAllByDeviceLocalTimePost response."""
        devicestep = data.get("devicestep")
        calories = data.get("calories")
        return cls(
            steps=_as_int(devicestep) if devicestep not in (None, "") else None,
            steps_at=_as_epoch_ms(data.get("step_time")),
            calories=_as_int(calories) if calories not in (None, "") else None,
            distance_km=_as_float(data.get("km")),
            heart_rate=_positive_or_none(_as_int(data.get("heart_rate"))),
            heart_rate_at=_as_epoch_ms(data.get("heart_rate_system_time")),
            blood_oxygen=_positive_or_none(_as_int(data.get("blood_oxygen"))),
            blood_oxygen_at=_as_epoch_ms(data.get("blood_oxygen_system_time")),
        )


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Everything one poll gathers about a single watch."""

    device: Device
    location: Location | None
    health: Health | None
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True, slots=True)
class Message:
    """A chat message sent from a watch.

    ``raw`` is the untouched ``msg_content`` and is the only stable identity
    the backend offers - it never deletes delivered messages, so clients must
    de-duplicate on it.
    """

    raw: str
    content: str
    msg_type: int
    sender_id: str
    receiver_id: str
    sent_at: datetime | None
    duration: int | None

    @property
    def kind(self) -> str:
        """Return "text", "emoji", "voice", or "unknown"."""
        return MSG_KINDS.get(self.msg_type, "unknown")

    @property
    def is_group(self) -> bool:
        """Return True if this went to the family conversation."""
        return self.receiver_id == GROUP_RECEIVER

    @classmethod
    def from_json(cls, data: JsonDict) -> Message | None:
        """Build from a /rtosWechat/getVoiceListPost entry.

        Returns None for entries that do not carry the expected
        ``<yyMMddHHmmss>_<sender>_<receiver>_<content>`` envelope.
        """
        raw = str(data.get("msg_content", ""))
        parts = raw.split("_", 3)
        if len(parts) < 3:
            return None
        stamp, sender_id, receiver_id = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""

        try:
            # Watch-local wall clock; the payload carries no timezone.
            sent_at = datetime.strptime(stamp, "%y%m%d%H%M%S")
        except ValueError:
            sent_at = None

        msg_type = _as_int(data.get("msg_type"), MSG_TYPE_TEXT)
        duration = None
        content = body
        if msg_type == MSG_TYPE_VOICE:
            # For voice the trailing segment is a length in seconds and the
            # audio itself lives in object storage we do not fetch.
            duration = _as_int(body) or None
            content = ""

        return cls(
            raw=raw,
            content=content,
            msg_type=msg_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            sent_at=sent_at,
            duration=duration,
        )
