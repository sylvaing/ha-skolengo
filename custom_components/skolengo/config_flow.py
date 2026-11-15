"""Config flow for the Skolengo integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_SCHOOL, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_SCHOOL): str})


class SkolengoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Skolengo."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the school to search for."""
        if user_input is not None:
            # TODO(#3): search the school, then sign in through EduConnect (#2).
            return self.async_abort(reason="not_implemented")

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
