"""Tests for the LAMAX Connect action platforms (buttons and messaging)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.notify import (
    ATTR_MESSAGE,
    SERVICE_SEND_MESSAGE,
)
from homeassistant.components.notify import (
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lamax_connect.lamax import LamaxError

from .conftest import TEST_D_ID, TEST_IMEI
from .test_init import setup_entry


async def test_send_message(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The notify entity forwards the message to the watch."""
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call(
        NOTIFY_DOMAIN,
        SERVICE_SEND_MESSAGE,
        {ATTR_ENTITY_ID: "notify.junior_message", ATTR_MESSAGE: "Dinner is ready"},
        blocking=True,
    )

    mock_client.async_send_message.assert_awaited_once_with(TEST_IMEI, TEST_D_ID, "Dinner is ready")


async def test_send_message_error_is_surfaced(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A backend failure while sending raises a HomeAssistantError."""
    await setup_entry(hass, mock_config_entry)
    mock_client.async_send_message.side_effect = LamaxError(557, "nope")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            NOTIFY_DOMAIN,
            SERVICE_SEND_MESSAGE,
            {ATTR_ENTITY_ID: "notify.junior_message", ATTR_MESSAGE: "hi"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("entity_id", "method"),
    [
        ("button.junior_request_location", "async_request_location_update"),
        ("button.junior_find_watch", "async_find_device"),
    ],
)
async def test_buttons(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    entity_id: str,
    method: str,
) -> None:
    """Pressing a button calls the matching client method."""
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    getattr(mock_client, method).assert_awaited_once_with(TEST_IMEI)


async def test_button_error_is_surfaced(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A backend failure while pressing raises a HomeAssistantError."""
    await setup_entry(hass, mock_config_entry)
    mock_client.async_find_device.side_effect = LamaxError(557, "nope")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.junior_find_watch"},
            blocking=True,
        )
