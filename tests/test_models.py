"""Tests for parsing of the LAMAX Connect payloads.

The backend is loosely typed - numbers arrive as strings, fields go missing,
and empty strings stand in for nulls - so parsing must never raise.
"""

from __future__ import annotations

import pytest

from custom_components.lamax_connect.lamax import Device, GeoFence, Location, TrackPoint


def test_location_from_empty_payload() -> None:
    """A response with no position fields yields empty values, not an error."""
    location = Location.from_json({})

    assert location.latitude is None
    assert location.longitude is None
    assert location.battery is None
    assert location.accuracy == 0
    assert location.steps == 0
    assert location.updated_at is None


@pytest.mark.parametrize("bad", ["", "n/a", None, {}])
def test_location_tolerates_unparsable_coordinates(bad: object) -> None:
    """Junk in the coordinate fields is treated as 'unknown'."""
    location = Location.from_json({"lat": bad, "lng": bad, "step": bad})

    assert location.latitude is None
    assert location.longitude is None
    assert location.steps == 0


def test_device_falls_back_to_imei_for_name() -> None:
    """A watch with no name is identified by its IMEI."""
    device = Device.from_json({"imei": "123", "name": ""})

    assert device.name == "123"
    assert device.unique_id == "123"
    assert device.firmware == ""


def test_geofence_defaults_to_enabled() -> None:
    """Missing toggles default to enabled, matching the app's behaviour."""
    fence = GeoFence.from_json({"id": 1, "fenceName": "School"})

    assert fence.enabled is True
    assert fence.notify_on_entry is True
    assert fence.notify_on_exit is True
    assert fence.radius == 0


def test_trackpoint_without_timestamp() -> None:
    """A track point with no upload time has no recorded timestamp."""
    point = TrackPoint.from_json({"lat": "1.0", "lng": "2.0"})

    assert point.recorded_at is None
    assert point.latitude == pytest.approx(1.0)
