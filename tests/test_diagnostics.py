"""Tests for LAMAX Connect diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import TEST_IMEI, TEST_PASSWORD, TEST_USERNAME
from .test_init import setup_entry

REDACTED = "**REDACTED**"


async def test_diagnostics_redacts_identifying_data(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Credentials, IMEI and coordinates never appear in diagnostics."""
    await setup_entry(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)

    assert result["entry"]["username"] == REDACTED
    assert result["entry"]["password"] == REDACTED
    assert result["host"] == "elem6.wisskys.com"

    device = result["devices"][0]
    assert device["device"]["imei"] == REDACTED
    assert device["location"]["latitude"] == REDACTED
    assert device["location"]["longitude"] == REDACTED

    # Nothing identifying leaked anywhere else in the payload.
    serialized = str(result)
    assert TEST_IMEI not in serialized
    assert TEST_PASSWORD not in serialized
    assert TEST_USERNAME not in serialized
    assert "50.07553" not in serialized


async def test_diagnostics_without_location(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device,
) -> None:
    """A watch with no position still produces valid diagnostics."""
    mock_client.async_get_devices_with_location.return_value = {device.imei: (device, None)}
    await setup_entry(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)

    assert result["devices"][0]["location"] is None
