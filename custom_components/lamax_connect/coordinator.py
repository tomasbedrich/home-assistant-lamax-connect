"""Data update coordinator for the LAMAX Connect integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .lamax import DeviceSnapshot, LamaxAuthError, LamaxClient, LamaxError

_LOGGER = logging.getLogger(__name__)

type LamaxConfigEntry = ConfigEntry[LamaxCoordinator]


class LamaxCoordinator(DataUpdateCoordinator[dict[str, DeviceSnapshot]]):
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

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        """Fetch devices, positions and step counts from the LAMAX backend."""
        try:
            return await self.client.async_get_snapshots()
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
