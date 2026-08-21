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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import DeviceSnapshot

PARALLEL_UPDATES = 0

# Not Home Assistant constants - there is no device class for heart rate or
# for dietary calories.
BEATS_PER_MINUTE = "bpm"
KILOCALORIES = "kcal"


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
        # Battery rides along with the position report, so it is exactly as old
        # as the fix - see the "location_updated" sensor for that age.
        value_fn=lambda data: data.location.battery if data.location else None,
    ),
    LamaxSensorEntityDescription(
        key="steps",
        translation_key="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="steps",
        value_fn=lambda data: data.health.steps if data.health else None,
    ),
    LamaxSensorEntityDescription(
        key="calories",
        translation_key="calories",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=KILOCALORIES,
        value_fn=lambda data: data.health.calories if data.health else None,
    ),
    LamaxSensorEntityDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=2,
        value_fn=lambda data: data.health.distance_km if data.health else None,
    ),
    LamaxSensorEntityDescription(
        key="heart_rate",
        translation_key="heart_rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=BEATS_PER_MINUTE,
        value_fn=lambda data: data.health.heart_rate if data.health else None,
    ),
    LamaxSensorEntityDescription(
        key="blood_oxygen",
        translation_key="blood_oxygen",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.health.blood_oxygen if data.health else None,
    ),
    # Heart rate and blood oxygen are only captured when a measurement is taken
    # on the watch, so a reading can be weeks old while the sensor above looks
    # freshly polled. Each one therefore gets its own timestamp next to it.
    LamaxSensorEntityDescription(
        key="heart_rate_measured",
        translation_key="heart_rate_measured",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.health.heart_rate_at if data.health else None,
    ),
    LamaxSensorEntityDescription(
        key="blood_oxygen_measured",
        translation_key="blood_oxygen_measured",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.health.blood_oxygen_at if data.health else None,
    ),
    # The watch only reports its position when asked, so the last fix - and the
    # battery reading that rides with it - can be days old while Home Assistant
    # keeps showing the tracker as "home". This is that age.
    LamaxSensorEntityDescription(
        key="location_updated",
        translation_key="location_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
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
