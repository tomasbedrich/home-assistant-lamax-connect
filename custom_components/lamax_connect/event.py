"""Event platform for LAMAX Connect - messages arriving from a watch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import MSG_KINDS, MSG_TYPE_VOICE, Message

PARALLEL_UPDATES = 0

# Bound on remembered message ids. The backend never deletes delivered
# messages, so without a cap the set would grow for the life of the entry.
_MAX_REMEMBERED = 500


def _attributes(message: Message) -> dict[str, Any]:
    """Build the event payload, omitting fields that do not apply.

    A voice note has no text and a text message has no duration, so neither
    carries the other's always-empty field.
    """
    attributes: dict[str, Any] = {
        "sender_id": message.sender_id,
        "is_group": message.is_group,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
    }
    if message.msg_type == MSG_TYPE_VOICE:
        attributes["duration"] = message.duration
    else:
        attributes["content"] = message.content
    return attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect message events."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [LamaxMessageEvent(coordinator, imei)],
    )


class LamaxMessageEvent(LamaxEntity, EventEntity):
    """Fires when the watch sends a message.

    The backend keeps returning messages it has already delivered, so this
    de-duplicates on the raw payload. Messages already present when Home
    Assistant starts are recorded as seen without firing, so a restart does not
    replay old conversation into automations.
    """

    _attr_translation_key = "message_received"

    def __init__(self, coordinator: LamaxCoordinator, imei: str) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, imei, "message_received")
        self._attr_event_types = [*MSG_KINDS.values(), "unknown"]
        self._seen: set[str] = set()
        self._primed = False

    async def async_added_to_hass(self) -> None:
        """Treat whatever is already queued as history, not as new events."""
        self._remember(self.device_data.messages)
        self._primed = True
        await super().async_added_to_hass()

    def _remember(self, messages: tuple[Message, ...]) -> None:
        if len(self._seen) > _MAX_REMEMBERED:
            self._seen = {message.raw for message in messages}
            return
        self._seen.update(message.raw for message in messages)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire an event for each message we have not seen before."""
        messages = self.device_data.messages
        if self._primed:
            for message in messages:
                if message.raw in self._seen:
                    continue
                self._trigger_event(message.kind, _attributes(message))
        self._remember(messages)
        super()._handle_coordinator_update()
