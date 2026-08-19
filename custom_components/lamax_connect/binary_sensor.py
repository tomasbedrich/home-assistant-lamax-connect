"""Binary sensor platform for LAMAX Connect."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect binary sensors."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [LamaxLocationFixBinarySensor(coordinator, imei)],
    )


class LamaxLocationFixBinarySensor(LamaxEntity, BinarySensorEntity):
    """Whether the backend currently holds a position for the watch."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "location_fix"

    def __init__(self, coordinator: LamaxCoordinator, imei: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, imei, "location_fix")

    @property
    def is_on(self) -> bool:
        """Return True if a position with coordinates is available."""
        location = self.device_data.location
        return bool(location and location.latitude is not None and location.longitude is not None)
