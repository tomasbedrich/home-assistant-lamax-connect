"""Device tracker platform for LAMAX Connect - the watch position."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import Location

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
    def force_update(self) -> bool:
        """Only write the state when the position actually changed.

        TrackerEntity forces every write, because a push-based tracker is
        expected to keep re-reporting the same position. This one is polled
        through the coordinator, so forcing it would reset "last changed" every
        five minutes and make a days-old fix look like it had just arrived.
        """
        return False

    @property
    def _fix(self) -> Location | None:
        """Return the last report, unless it is only a cell tower estimate.

        A tower fix can be kilometres off - the app offers to let the user drag
        such a marker to the right place - and Home Assistant matches zones
        against the accuracy circle, so it would report the watch as home from
        the far side of town. WiFi fixes are kept: this hardware reports them
        accurate to tens of metres.
        """
        location = self.device_data.location
        return location if location and not location.is_coarse else None

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the watch."""
        fix = self._fix
        return fix.latitude if fix else None

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the watch."""
        fix = self._fix
        return fix.longitude if fix else None

    @property
    def location_accuracy(self) -> int:
        """Return the accuracy of the position in meters."""
        fix = self._fix
        return fix.accuracy if fix else 0
