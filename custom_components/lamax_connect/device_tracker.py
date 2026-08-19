"""Device tracker platform for LAMAX Connect - the watch position."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
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
    """Set up the LAMAX Connect device trackers."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [LamaxDeviceTracker(coordinator, imei)],
    )


class LamaxDeviceTracker(LamaxEntity, TrackerEntity):
    """Reports the last known GPS position of a watch."""

    _attr_name = None

    def __init__(self, coordinator: LamaxCoordinator, imei: str) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator, imei, "tracker")

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the tracker."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the watch."""
        location = self.device_data.location
        return location.latitude if location else None

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the watch."""
        location = self.device_data.location
        return location.longitude if location else None

    @property
    def location_accuracy(self) -> int:
        """Return the accuracy of the position in meters."""
        location = self.device_data.location
        return location.accuracy if location else 0
