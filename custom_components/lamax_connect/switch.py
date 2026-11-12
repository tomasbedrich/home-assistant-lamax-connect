"""Switch platform for LAMAX Connect."""

from __future__ import annotations

from datetime import timedelta
import logging
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
SCAN_INTERVAL = timedelta(minutes=5)

_LOGGER = logging.getLogger(__name__)


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
    """Allows cell-tower (LBS) positioning; off leaves only GPS and WiFi.

    Disabled by default: the tracker already ignores LBS fixes, and not every
    watch supports the setting. It polls on its own rather than through the
    coordinator, so nobody pays a request per poll for an entity they never use.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "lbs_location"

    @property
    def should_poll(self) -> bool:
        """Poll the setting, unlike the coordinator-backed entities."""
        return True

    async def async_added_to_hass(self) -> None:
        """Read the setting right away instead of after the first scan interval."""
        await super().async_added_to_hass()
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Read the current setting."""
        device = self.device_data.device
        try:
            self._attr_is_on = await self.coordinator.client.async_get_lbs_enabled(
                device.d_id, self._imei
            )
        except LamaxError as err:
            _LOGGER.debug("No LBS setting for %s: %s", self._imei, err)
            self._attr_is_on = None

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
