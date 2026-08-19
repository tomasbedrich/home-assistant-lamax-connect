"""Notify platform for LAMAX Connect - send messages to a watch."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import LamaxError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect notify entities."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [LamaxNotifyEntity(coordinator, imei)],
    )


class LamaxNotifyEntity(LamaxEntity, NotifyEntity):
    """Sends a text message to the watch, shown in its chat app."""

    _attr_translation_key = "message"
    _attr_supported_features = NotifyEntityFeature(0)

    def __init__(self, coordinator: LamaxCoordinator, imei: str) -> None:
        """Initialize the notify entity."""
        super().__init__(coordinator, imei, "notify")

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a text message to the watch."""
        try:
            await self.coordinator.client.async_send_message(
                self._imei, self.device_data.device.d_id, message
            )
        except LamaxError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_message_failed",
                translation_placeholders={"error": str(err)},
            ) from err
