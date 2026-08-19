"""Constants for the LAMAX Connect integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lamax_connect"

CONF_LOGIN_TYPE: Final = "login_type"
CONF_COUNTRY: Final = "country"

MANUFACTURER: Final = "LAMAX"

# The backend is cloud polling and the watches report on their own schedule,
# so there is nothing to gain from polling faster than this.
DEFAULT_SCAN_INTERVAL: Final = 300
