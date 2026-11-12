"""Switch platform for LAMAX Connect."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LamaxConfigEntry
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import LamaxError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect switches."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [LamaxLbsSwitch(coordinator, imei, "lbs_location")],
    )


class LamaxLbsSwitch(LamaxEntity, SwitchEntity):
    """Allows cell-tower (LBS) positioning; off leaves only GPS and WiFi."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "lbs_location"

    @property
    def is_on(self) -> bool | None:
        """Return whether LBS positioning is allowed."""
        return self.device_data.lbs_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow LBS positioning."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forbid LBS positioning."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        device = self.device_data.device
        try:
            await self.coordinator.client.async_set_lbs_enabled(device.d_id, self._imei, enabled)
        except LamaxError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
