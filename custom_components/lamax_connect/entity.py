"""Base entity and shared platform setup for the LAMAX Connect integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import LamaxConfigEntry, LamaxCoordinator, LamaxDeviceData


class LamaxEntity(CoordinatorEntity[LamaxCoordinator]):
    """Common behaviour for every entity belonging to one watch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LamaxCoordinator, imei: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._imei = imei
        self._attr_unique_id = f"{imei}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, imei)},
            manufacturer=MANUFACTURER,
            name=self.device_data.device.name,
            model=f"Watch (type {self.device_data.device.device_type})",
            sw_version=self.device_data.device.firmware,
            serial_number=imei,
        )

    @property
    def device_data(self) -> LamaxDeviceData:
        """Current data for this watch."""
        return self.coordinator.data[self._imei]

    @property
    def available(self) -> bool:
        """Return True if the watch is still present in the account."""
        return super().available and self._imei in self.coordinator.data


@callback
def async_setup_lamax_platform(
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[LamaxCoordinator, str], Iterable[Entity]],
) -> None:
    """Add entities for every watch, including ones bound after setup.

    ``factory`` builds the platform's entities for a single watch (by IMEI).
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_devices() -> None:
        new = set(coordinator.data) - known
        if not new:
            return
        known.update(new)
        async_add_entities(entity for imei in new for entity in factory(coordinator, imei))

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))
