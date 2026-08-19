"""Data update coordinator for the LAMAX Connect integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .lamax import Device, LamaxAuthError, LamaxClient, LamaxError, Location

_LOGGER = logging.getLogger(__name__)

type LamaxConfigEntry = ConfigEntry[LamaxCoordinator]


@dataclass(frozen=True, slots=True)
class LamaxDeviceData:
    """Everything known about one watch after an update."""

    device: Device
    location: Location | None


class LamaxCoordinator(DataUpdateCoordinator[dict[str, LamaxDeviceData]]):
    """Fetches the bound watches and their last known positions."""

    config_entry: LamaxConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: LamaxConfigEntry, client: LamaxClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, LamaxDeviceData]:
        """Fetch devices and positions from the LAMAX backend."""
        try:
            devices = await self.client.async_get_devices_with_location()
        except LamaxAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except LamaxError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        return {
            imei: LamaxDeviceData(device=device, location=location)
            for imei, (device, location) in devices.items()
        }
