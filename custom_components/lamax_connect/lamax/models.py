"""Typed views over the LAMAX Connect JSON payloads.

Field names mirror the wire format exactly where practical; the shapes were
confirmed against the live backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# msg_type values used by /rtosWechat/appSendDevice
MSG_TYPE_TEXT = 1
MSG_TYPE_EMOJI = 2
MSG_TYPE_VOICE = 3


type JsonDict = dict[str, Any]


def _as_float(value: Any) -> float | None:
    """Coerce a loosely-typed backend value to a float, or None if unusable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    accuracy: int
    location_type: int
    steps: int
    description: str
    updated_at: datetime | None

    @classmethod
    def from_json(cls, data: JsonDict) -> Location:
        """Build from a /location/getlast/searchPost response."""
        uploadtime = _as_int(data.get("uploadtime"), 0)
        battery = data.get("Electricity")
        return cls(
            latitude=_as_float(data.get("lat")),
            longitude=_as_float(data.get("lng")),
            battery=_as_int(battery) if battery is not None else None,
            accuracy=_as_int(data.get("accuracy")),
            location_type=_as_int(data.get("locationType")),
            steps=_as_int(data.get("step")),
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
