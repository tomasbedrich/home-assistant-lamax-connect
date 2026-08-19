"""Tests for the LAMAX Connect coordinator behaviour over time."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.lamax_connect.const import DEFAULT_SCAN_INTERVAL
from custom_components.lamax_connect.lamax import (
    Device,
    DeviceSnapshot,
    LamaxAuthError,
    LamaxError,
)

from .test_init import setup_entry


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Move past one polling interval and let the coordinator run."""
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_entities_go_unavailable_on_update_failure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failing refresh marks entities unavailable, and recovery restores them."""
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get("sensor.junior_battery").state == "100"

    mock_client.async_get_snapshots.side_effect = LamaxError(557, "boom")
    await _advance(hass, freezer)
    assert hass.states.get("sensor.junior_battery").state == STATE_UNAVAILABLE

    mock_client.async_get_snapshots.side_effect = None
    await _advance(hass, freezer)
    assert hass.states.get("sensor.junior_battery").state == "100"


async def test_auth_failure_during_refresh_triggers_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An expired session during polling starts a reauth flow."""
    await setup_entry(hass, mock_config_entry)

    mock_client.async_get_snapshots.side_effect = LamaxAuthError(25, "gone")
    await _advance(hass, freezer)

    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_watch_added_later_creates_entities(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device: Device,
    location,
    health,
) -> None:
    """A watch bound after setup shows up without reloading the entry."""
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get("device_tracker.second") is None

    second = Device.from_json(
        {"imei": "860000000000002", "name": "Second", "d_id": 999, "device_type": 27}
    )
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, health, ()),
        second.imei: DeviceSnapshot(second, location, health, ()),
    }
    await _advance(hass, freezer)

    assert hass.states.get("device_tracker.second") is not None
    assert hass.states.get("device_tracker.junior") is not None
