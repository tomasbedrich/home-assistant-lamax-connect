"""Binary sensor platform for LAMAX Connect."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import DeviceSnapshot

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LamaxBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a LAMAX Connect binary sensor."""

    value_fn: Callable[[DeviceSnapshot], bool]


BINARY_SENSORS: tuple[LamaxBinarySensorEntityDescription, ...] = (
    LamaxBinarySensorEntityDescription(
        key="location_fix",
        translation_key="location_fix",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(
            data.location
            and data.location.latitude is not None
            and data.location.longitude is not None
        ),
    ),
    LamaxBinarySensorEntityDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda data: bool(data.location and data.location.charging),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect binary sensors."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [
            LamaxBinarySensor(coordinator, imei, description) for description in BINARY_SENSORS
        ],
    )


class LamaxBinarySensor(LamaxEntity, BinarySensorEntity):
    """A boolean reading derived from the watch's last report."""

    entity_description: LamaxBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: LamaxCoordinator,
        imei: str,
        description: LamaxBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, imei, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the current state."""
        return self.entity_description.value_fn(self.device_data)
