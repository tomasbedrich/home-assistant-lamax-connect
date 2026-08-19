"""Notify platform for LAMAX Connect - send messages to a watch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.notify import (
    NotifyEntity,
    NotifyEntityDescription,
    NotifyEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import LamaxClient, LamaxError

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LamaxNotifyEntityDescription(NotifyEntityDescription):
    """Describes a LAMAX Connect notify entity."""

    send_fn: Callable[[LamaxClient, str, int, str], Awaitable[str]]


NOTIFIERS: tuple[LamaxNotifyEntityDescription, ...] = (
    LamaxNotifyEntityDescription(
        key="notify",
        translation_key="message",
        send_fn=lambda client, imei, d_id, message: client.async_send_message(imei, d_id, message),
    ),
    LamaxNotifyEntityDescription(
        key="family_chat",
        translation_key="family_chat",
        send_fn=lambda client, imei, d_id, message: client.async_send_group_message(
            imei, d_id, message
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect notify entities."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [
            LamaxNotifyEntity(coordinator, imei, description) for description in NOTIFIERS
        ],
    )


class LamaxNotifyEntity(LamaxEntity, NotifyEntity):
    """Sends a message to the watch, shown in its chat app."""

    _attr_supported_features = NotifyEntityFeature(0)
    entity_description: LamaxNotifyEntityDescription

    def __init__(
        self,
        coordinator: LamaxCoordinator,
        imei: str,
        description: LamaxNotifyEntityDescription,
    ) -> None:
        """Initialize the notify entity."""
        super().__init__(coordinator, imei, description.key)
        self.entity_description = description

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message to the watch.

        Anything past the watch's 30 character limit is trimmed; the client
        logs a warning when that happens.
        """
        try:
            await self.entity_description.send_fn(
                self.coordinator.client,
                self._imei,
                self.device_data.device.d_id,
                message,
            )
        except LamaxError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_message_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # Pick up anything the watch replies with sooner than the next poll.
        await self.coordinator.async_request_refresh()
