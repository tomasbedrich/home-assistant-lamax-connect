"""Config flow for the LAMAX Connect integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import CONF_COUNTRY, CONF_LOGIN_TYPE, DOMAIN
from .lamax import (
    LOGIN_TYPE_EMAIL,
    LOGIN_TYPE_PHONE,
    LamaxAuthError,
    LamaxClient,
    LamaxError,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
        vol.Required(CONF_LOGIN_TYPE, default=LOGIN_TYPE_EMAIL): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=LOGIN_TYPE_EMAIL, label="Email"),
                    SelectOptionDict(value=LOGIN_TYPE_PHONE, label="Phone"),
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_COUNTRY): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        )
    }
)


class LamaxConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the LAMAX Connect config flow."""

    VERSION = 1

    async def _async_validate(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Try to log in. Returns a dict of form errors, empty when valid."""
        client = LamaxClient(async_get_clientsession(self.hass))
        try:
            await client.login(
                data[CONF_USERNAME],
                data[CONF_PASSWORD],
                data.get(CONF_LOGIN_TYPE, LOGIN_TYPE_EMAIL),
                data.get(CONF_COUNTRY),
            )
        except LamaxAuthError:
            return {"base": "invalid_auth"}
        except LamaxError as err:
            _LOGGER.debug("Cannot connect to LAMAX backend: %s", err)
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error validating LAMAX credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication after the stored credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password and verify it."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(reauth_entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={CONF_USERNAME: reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing the account details without removing the entry."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_validate(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or dict(reconfigure_entry.data)
            ),
            errors=errors,
        )
