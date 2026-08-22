"""Tests for the LAMAX Connect action platforms (buttons and messaging)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
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
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.lamax_connect.button import (
    LOCATION_POLL_ATTEMPTS,
    LOCATION_POLL_INTERVAL,
)
from custom_components.lamax_connect.lamax import LamaxDeviceOfflineError, LamaxError

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


async def test_locate_button_waits_for_the_watch_to_answer(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device,
    location,
    health,
    messages,
) -> None:
    """Asking is not answering - keep polling until the fix actually changes."""
    from custom_components.lamax_connect.lamax import DeviceSnapshot

    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_snapshots.reset_mock()

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.junior_request_location"},
        blocking=True,
    )
    assert mock_client.async_get_snapshots.await_count == 0

    # The watch stays silent, so the position keeps being re-read.
    await _advance(hass, 2)
    assert mock_client.async_get_snapshots.await_count == 2

    # Once it answers, the polling stops.
    answered = replace(location, updated_at=location.updated_at + timedelta(minutes=5))
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, answered, health, messages)
    }
    await _advance(hass, 1)
    assert mock_client.async_get_snapshots.await_count == 3

    await _advance(hass, 3)
    assert mock_client.async_get_snapshots.await_count == 3


async def test_locate_button_gives_up_on_a_silent_watch(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A watch that never answers must not be polled forever."""
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_snapshots.reset_mock()

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.junior_request_location"},
        blocking=True,
    )
    await _advance(hass, LOCATION_POLL_ATTEMPTS + 3)

    assert mock_client.async_get_snapshots.await_count == LOCATION_POLL_ATTEMPTS


async def _advance(hass: HomeAssistant, intervals: int) -> None:
    """Let the follow-up poller fire the given number of times."""
    for _ in range(intervals):
        async_fire_time_changed(hass, dt_util.utcnow() + LOCATION_POLL_INTERVAL)
        await hass.async_block_till_done()


async def test_offline_watch_is_named_as_such(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """An offline watch is reported as offline, not as a rejected command."""
    await setup_entry(hass, mock_config_entry)
    mock_client.async_find_device.side_effect = LamaxDeviceOfflineError(3)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.junior_find_watch"},
            blocking=True,
        )

    assert err.value.translation_key == "watch_offline"


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
