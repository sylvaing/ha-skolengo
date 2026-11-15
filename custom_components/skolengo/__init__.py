"""The Skolengo integration.

Unofficial integration for the Skolengo school ENT (Kosmos), used by many French regional ENTs.
Entities and cards are tracked in the GitHub issues.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Account, SkolengoAuthError, SkolengoClient, SkolengoError, Tokens
from .config_flow import school_from_dict
from .const import CONF_SCHOOL, CONF_TOKENS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []


@dataclass(slots=True)
class SkolengoData:
    """Runtime data of a config entry."""

    client: SkolengoClient
    account: Account


type SkolengoConfigEntry = ConfigEntry[SkolengoData]


async def async_setup_entry(hass: HomeAssistant, entry: SkolengoConfigEntry) -> bool:
    """Set up Skolengo from a config entry."""
    school = school_from_dict(entry.data[CONF_SCHOOL])

    @callback
    def _save_tokens(tokens: Tokens) -> None:
        # The refresh token rotates: the previous one is now dead. Persist the new set at once.
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKENS: tokens.as_dict()})

    client = SkolengoClient(
        async_get_clientsession(hass),
        Tokens.from_dict(entry.data[CONF_TOKENS]),
        school.ems_code,
        on_tokens_refreshed=_save_tokens,
    )
    try:
        account = await client.async_get_account()
    except SkolengoAuthError as err:
        raise ConfigEntryAuthFailed("the Skolengo session expired, sign in again") from err
    except SkolengoError as err:
        raise ConfigEntryNotReady(f"cannot reach Skolengo: {err}") from err

    entry.runtime_data = SkolengoData(client=client, account=account)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SkolengoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
