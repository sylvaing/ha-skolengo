"""Tests for the Skolengo config flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.skolengo.const import CONF_SCHOOL, DOMAIN


async def test_user_flow_scaffold(hass: HomeAssistant) -> None:
    """The user step shows the school form; the scaffold aborts until the login is implemented."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SCHOOL: "Billères"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_implemented"
