"""Sensor platform for LAMAX Connect."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import DeviceSnapshot

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LamaxSensorEntityDescription(SensorEntityDescription):
    """Describes a LAMAX Connect sensor."""

    value_fn: Callable[[DeviceSnapshot], int | float | datetime | None]


SENSORS: tuple[LamaxSensorEntityDescription, ...] = (
    LamaxSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.location.battery if data.location else None,
    ),
    LamaxSensorEntityDescription(
        key="steps",
        translation_key="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="steps",
        value_fn=lambda data: data.steps,
    ),
    LamaxSensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.location.updated_at if data.location else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect sensors."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [
            LamaxSensor(coordinator, imei, description) for description in SENSORS
        ],
    )


class LamaxSensor(LamaxEntity, SensorEntity):
    """A sensor reading derived from the watch's last report."""

    entity_description: LamaxSensorEntityDescription

    def __init__(
        self,
        coordinator: LamaxCoordinator,
        imei: str,
        description: LamaxSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, imei, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | datetime | None:
        """Return the current value."""
        return self.entity_description.value_fn(self.device_data)
