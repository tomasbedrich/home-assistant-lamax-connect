"""Tests for the family chat: sending to the group and receiving messages."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.notify import (
    ATTR_MESSAGE,
    SERVICE_SEND_MESSAGE,
)
from homeassistant.components.notify import (
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.lamax_connect.const import DEFAULT_SCAN_INTERVAL
from custom_components.lamax_connect.lamax import DeviceSnapshot, Message

from .conftest import TEST_D_ID, TEST_IMEI
from .test_init import setup_entry

EVENT_ENTITY = "event.junior_message_received"


def make_message(raw: str, msg_type: int = 1) -> Message:
    """Build a message the way the backend delivers one."""
    parsed = Message.from_json({"msg_content": raw, "msg_type": msg_type})
    assert parsed is not None
    return parsed


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Move past one polling interval."""
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_family_chat_entity_sends_to_the_group(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The family chat entity uses the group endpoint, not the private one."""
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call(
        NOTIFY_DOMAIN,
        SERVICE_SEND_MESSAGE,
        {ATTR_ENTITY_ID: "notify.junior_family_chat", ATTR_MESSAGE: "dinner time"},
        blocking=True,
    )

    mock_client.async_send_group_message.assert_awaited_once_with(
        TEST_IMEI, TEST_D_ID, "dinner time"
    )
    mock_client.async_send_message.assert_not_awaited()


async def test_private_and_family_entities_both_exist(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A watch gets a private notifier and a family chat notifier."""
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("notify.junior_message") is not None
    assert hass.states.get("notify.junior_family_chat") is not None


async def test_existing_messages_do_not_fire_on_startup(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Restarting must not replay old conversation into automations."""
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(EVENT_ENTITY).state == STATE_UNKNOWN


async def test_new_message_fires_event(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device,
    location,
    health,
    messages,
) -> None:
    """A message arriving after startup fires an event with its content."""
    await setup_entry(hass, mock_config_entry)

    incoming = make_message("260819150000_555_1_jsem doma")
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, health, (*messages, incoming))
    }
    await advance(hass, freezer)

    state = hass.states.get(EVENT_ENTITY)
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "text"
    assert state.attributes["content"] == "jsem doma"
    assert state.attributes["sender_id"] == "555"
    assert state.attributes["is_group"] is True
    # Duration only applies to voice notes.
    assert "duration" not in state.attributes


async def test_message_is_not_replayed_on_every_poll(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device,
    location,
    health,
    messages,
) -> None:
    """The backend keeps returning delivered messages; fire each one once."""
    await setup_entry(hass, mock_config_entry)

    incoming = make_message("260819150000_555_1_jsem doma")
    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, health, (*messages, incoming))
    }
    await advance(hass, freezer)
    fired_at = hass.states.get(EVENT_ENTITY).state

    # Same payload again on the next poll.
    await advance(hass, freezer)

    assert hass.states.get(EVENT_ENTITY).state == fired_at


@pytest.mark.parametrize(
    ("raw", "msg_type", "expected_type"),
    [
        ("260819150000_555_1_hi", 1, "text"),
        ("260819150000_555_1_[smile]", 2, "emoji"),
        ("260819150000_555_1_9", 3, "voice"),
        ("260819150000_555_1_hi", 99, "unknown"),
    ],
)
async def test_event_type_per_message_kind(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device,
    location,
    health,
    raw: str,
    msg_type: int,
    expected_type: str,
) -> None:
    """Text, emoji and voice are distinguishable event types."""
    await setup_entry(hass, mock_config_entry)

    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, health, (make_message(raw, msg_type),))
    }
    await advance(hass, freezer)

    assert hass.states.get(EVENT_ENTITY).attributes["event_type"] == expected_type


async def test_voice_event_carries_duration(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device,
    location,
    health,
) -> None:
    """A voice note reports its length, since the audio itself is not fetched."""
    await setup_entry(hass, mock_config_entry)

    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(
            device, location, health, (make_message("260819150000_555_1_9", 3),)
        )
    }
    await advance(hass, freezer)

    state = hass.states.get(EVENT_ENTITY)
    assert state.attributes["duration"] == 9
    # The audio is never fetched, so there is no text to report.
    assert "content" not in state.attributes


async def test_remembered_ids_are_bounded(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    device,
    location,
    health,
) -> None:
    """The de-duplication set cannot grow without bound.

    The backend never deletes delivered messages, so a long-lived entry would
    otherwise accumulate ids forever.
    """
    from custom_components.lamax_connect.event import _MAX_REMEMBERED

    await setup_entry(hass, mock_config_entry)

    flood = tuple(make_message(f"2608191500{i:02d}_555_1_msg{i}") for i in range(60))
    entity = hass.data["entity_components"]["event"].get_entity(EVENT_ENTITY)
    entity._seen = {f"filler-{i}" for i in range(_MAX_REMEMBERED + 1)}

    mock_client.async_get_snapshots.return_value = {
        device.imei: DeviceSnapshot(device, location, health, flood)
    }
    await advance(hass, freezer)

    # Rebuilt from the current poll rather than appended to.
    assert len(entity._seen) == len(flood)
