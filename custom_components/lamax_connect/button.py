"""Button platform for LAMAX Connect - locate and ring actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import LamaxClient, LamaxDeviceOfflineError, LamaxError

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)


# Asking is not answering: the watch has to wake up, get a fix and upload it,
# and the backend has nothing new until it does. The app keeps its refresh
# button disabled for 60 s and re-reads the position afterwards, so do the same
# here - poll until the fix actually changes rather than once at a guessed
# moment. This costs cloud requests, not watch battery.
LOCATION_POLL_INTERVAL = timedelta(seconds=20)
LOCATION_POLL_ATTEMPTS = 9


@dataclass(frozen=True, kw_only=True)
class LamaxButtonEntityDescription(ButtonEntityDescription):
    """Describes a LAMAX Connect button."""

    press_fn: Callable[[LamaxClient, str], Awaitable[None]]
    # Set for commands the watch answers asynchronously, with a new position.
    awaits_fix: bool = False


BUTTONS: tuple[LamaxButtonEntityDescription, ...] = (
    LamaxButtonEntityDescription(
        key="request_location",
        translation_key="request_location",
        press_fn=lambda client, imei: client.async_request_location_update(imei),
        awaits_fix=True,
    ),
    LamaxButtonEntityDescription(
        key="find_watch",
        translation_key="find_watch",
        press_fn=lambda client, imei: client.async_find_device(imei),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LamaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LAMAX Connect buttons."""
    async_setup_lamax_platform(
        entry,
        async_add_entities,
        lambda coordinator, imei: [
            LamaxButton(coordinator, imei, description) for description in BUTTONS
        ],
    )


class LamaxButton(LamaxEntity, ButtonEntity):
    """A one-shot command sent to the watch."""

    entity_description: LamaxButtonEntityDescription

    def __init__(
        self,
        coordinator: LamaxCoordinator,
        imei: str,
        description: LamaxButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, imei, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command to the watch."""
        try:
            await self.entity_description.press_fn(self.coordinator.client, self._imei)
        except LamaxDeviceOfflineError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="watch_offline",
            ) from err
        except LamaxError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if self.entity_description.awaits_fix:
            self._await_fix()

    @callback
    def _await_fix(self) -> None:
        """Keep polling until the watch reports a new position, or give up."""
        asked_after = self._reported_at
        attempts = 0

        async def _poll(_now: datetime) -> None:
            nonlocal attempts
            attempts += 1
            await self.coordinator.async_refresh()
            if self._reported_at != asked_after:
                _LOGGER.debug("The watch answered the locate request")
                cancel()
            elif attempts >= LOCATION_POLL_ATTEMPTS:
                _LOGGER.debug(
                    "The watch did not report a position within %s of being asked",
                    LOCATION_POLL_ATTEMPTS * LOCATION_POLL_INTERVAL,
                )
                cancel()

        cancel = async_track_time_interval(self.hass, _poll, LOCATION_POLL_INTERVAL)
        self.async_on_remove(cancel)

    @property
    def _reported_at(self) -> datetime | None:
        """Return when the watch last reported a position."""
        location = self.device_data.location
        return location.updated_at if location else None
