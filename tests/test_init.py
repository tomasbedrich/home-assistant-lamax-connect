"""Tests for setting up and unloading the LAMAX Connect integration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lamax_connect.const import DOMAIN
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
        ("binary_sensor.junior_location_fix", "on"),
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


async def test_health_sensors_expose_measurement_time(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Stale readings carry the time they were actually captured."""
    await setup_entry(hass, mock_config_entry)

    heart_rate = hass.states.get("sensor.junior_heart_rate")
    assert heart_rate is not None
    assert heart_rate.attributes["measured_at"] == (
        datetime.fromtimestamp(1785747669, tz=UTC).isoformat()
    )

    # Battery is a live reading and has no measurement timestamp.
    assert "measured_at" not in hass.states.get("sensor.junior_battery").attributes


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
        device.imei: DeviceSnapshot(device, location, None)
    }
    await setup_entry(hass, mock_config_entry)

    for entity_id in (
        "sensor.junior_steps",
        "sensor.junior_heart_rate",
        "sensor.junior_blood_oxygen",
    ):
        assert hass.states.get(entity_id).state == "unknown", entity_id
