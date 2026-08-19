"""Button platform for LAMAX Connect - locate and ring actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LamaxConfigEntry, LamaxCoordinator
from .entity import LamaxEntity, async_setup_lamax_platform
from .lamax import LamaxClient, LamaxError

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LamaxButtonEntityDescription(ButtonEntityDescription):
    """Describes a LAMAX Connect button."""

    press_fn: Callable[[LamaxClient, str], Awaitable[None]]


BUTTONS: tuple[LamaxButtonEntityDescription, ...] = (
    LamaxButtonEntityDescription(
        key="request_location",
        translation_key="request_location",
        press_fn=lambda client, imei: client.async_request_location_update(imei),
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
        except LamaxError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
