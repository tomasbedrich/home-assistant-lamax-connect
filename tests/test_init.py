"""Tests for setting up and unloading the LAMAX Connect integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.lamax_connect.const import DEFAULT_SCAN_INTERVAL, DOMAIN
from custom_components.lamax_connect.lamax import LamaxAuthError, LamaxConnectionError

from .conftest import TEST_IMEI


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads, creates a device, and unloads cleanly."""
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, TEST_IMEI)})
    assert device is not None
    assert device.name == "Junior"
    assert device.serial_number == TEST_IMEI

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Rejected credentials put the entry into the reauth state."""
    mock_client.login.side_effect = LamaxAuthError(24, "bad")

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_setup_connection_failure_retries(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A backend outage leaves the entry in the retry state."""
    mock_client.login.side_effect = LamaxConnectionError("down")

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    ("entity_id", "expected_state"),
    [
        ("device_tracker.junior", "not_home"),
        ("sensor.junior_battery", "100"),
        ("sensor.junior_steps", "9474"),
        ("sensor.junior_calories", "387"),
        ("sensor.junior_distance", "6.78"),
        ("sensor.junior_heart_rate", "93"),
        ("sensor.junior_blood_oxygen", "99"),
    ],
)
async def test_entities_created(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    entity_id: str,
    expected_state: str,
) -> None:
    """The expected entities exist with values from the backend."""
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert state.state == expected_state


async def test_device_tracker_reports_coordinates(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The tracker exposes the GPS position of the watch."""
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get("device_tracker.junior")
    assert state is not None
    assert state.attributes["latitude"] == pytest.approx(50.07553)
    assert state.attributes["longitude"] == pytest.approx(14.437800)
    assert state.attributes["gps_accuracy"] == 10
    assert state.attributes["source_type"] == "gps"


async def test_unchanged_data_does_not_touch_last_changed(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A poll that brings nothing new must not make the entities look fresh.

    Home Assistant skips the write when both state and attributes are identical,
    so "last changed" keeps telling the truth - as long as nothing in this
    integration puts the poll time into an attribute.
    """
    await setup_entry(hass, mock_config_entry)
    before = {
        entity_id: (state.last_changed, state.last_updated)
        for entity_id in ("device_tracker.junior", "sensor.junior_battery")
        if (state := hass.states.get(entity_id))
    }

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    await hass.async_block_till_done()

    assert mock_client.async_get_snapshots.await_count > 1
    for entity_id, stamps in before.items():
        state = hass.states.get(entity_id)
        assert (state.last_changed, state.last_updated) == stamps, entity_id


async def test_stale_readings_carry_their_own_timestamp(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Readings that go stale are dated by a sensor, not a buried attribute.

    Home Assistant's own "last changed" only says when it polled, so a reading
    taken weeks ago looks fresh without these.
    """
    await setup_entry(hass, mock_config_entry)

    for entity_id, epoch in (
        ("sensor.junior_heart_rate_measured", 1785747669),
        ("sensor.junior_blood_oxygen_measured", 1784733205),
        # The battery rides along with the position report, so this dates it too.
        ("sensor.junior_location_updated", 1786950041),
    ):
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} was not created"
        assert state.state == datetime.fromtimestamp(epoch, tz=UTC).isoformat(), entity_id


async def test_missing_health_leaves_sensors_unknown(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device,
    location,
) -> None:
    """A failed health lookup yields unknown sensors, not bogus zeroes."""
    from custom_components.lamax_connect.lamax import DeviceSnapshot

    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, None, ())
    }
    await setup_entry(hass, mock_config_entry)

    for entity_id in (
        "sensor.junior_steps",
        "sensor.junior_heart_rate",
        "sensor.junior_blood_oxygen",
    ):
        assert hass.states.get(entity_id).state == "unknown", entity_id


async def test_charging_sentinel_is_not_a_percentage(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device,
    health,
    messages,
) -> None:
    """A charging watch reports charging, not a 255% battery."""
    from custom_components.lamax_connect.lamax import DeviceSnapshot, Location

    charging = Location.from_json({"lat": "50.07553", "lng": "14.4378", "Electricity": 255})
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, charging, health, messages)
    }
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.junior_charging").state == "on"
    assert hass.states.get("sensor.junior_battery").state == "unknown"


async def test_battery_percentage_is_reported(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A discharging watch reports its level and charging off."""
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.junior_charging").state == "off"
    assert hass.states.get("sensor.junior_battery").state == "100"


async def test_coarse_fix_does_not_move_the_tracker(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device,
    health,
    messages,
) -> None:
    """A cell tower estimate is not a position, however fresh it is."""
    from custom_components.lamax_connect.lamax import DeviceSnapshot, Location

    coarse = Location.from_json(
        {"lat": "50.07553", "lng": "14.4378", "locationType": 1, "accuracy": 2000}
    )
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, coarse, health, messages)
    }
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get("device_tracker.junior")
    assert state.state == "unknown"
    assert "latitude" not in state.attributes
