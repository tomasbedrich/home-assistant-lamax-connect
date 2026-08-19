"""Diagnostics support for LAMAX Connect."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import LamaxConfigEntry

# The IMEI and exact coordinates identify a child's watch and its position.
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "imei",
    "serial_number",
    "latitude",
    "longitude",
    "description",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LamaxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "host": coordinator.client.host,
        "devices": [
            async_redact_data(
                {
                    "device": asdict(data.device),
                    "location": asdict(data.location) if data.location else None,
                },
                TO_REDACT,
            )
            for data in coordinator.data.values()
        ],
    }
