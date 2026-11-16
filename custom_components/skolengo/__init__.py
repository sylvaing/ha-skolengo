"""The Skolengo integration.

Unofficial integration for the Skolengo school ENT (Kosmos), used by many French regional ENTs.
Entities and cards are tracked in the GitHub issues.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AppConfig, SkolengoClient, SkolengoError, Tokens, async_get_app_config
from .cards import async_register_cards
from .config_flow import school_from_dict
from .const import CONF_SCHOOL, CONF_TOKENS, DOMAIN
from .coordinator import SkolengoCoordinator
from .entity import account_device_info, student_device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Ship the Lovelace cards once, whatever the number of entries."""
    await async_register_cards(hass)
    return True


@dataclass(slots=True)
class SkolengoData:
    """Runtime data of a config entry."""

    client: SkolengoClient
    coordinator: SkolengoCoordinator


type SkolengoConfigEntry = ConfigEntry[SkolengoData]


async def async_setup_entry(hass: HomeAssistant, entry: SkolengoConfigEntry) -> bool:
    """Set up Skolengo from a config entry."""
    school = school_from_dict(entry.data[CONF_SCHOOL])
    session = async_get_clientsession(hass)

    @callback
    def _save_tokens(tokens: Tokens) -> None:
        # The refresh token rotates: the previous one is now dead. Persist the new set at once.
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKENS: tokens.as_dict()})

    client = SkolengoClient(
        session,
        Tokens.from_dict(entry.data[CONF_TOKENS]),
        school.ems_code,
        on_tokens_refreshed=_save_tokens,
    )
    try:
        app_config = await async_get_app_config(session)
    except SkolengoError as err:
        _LOGGER.debug("Skolengo app config unavailable, using default retry hints: %s", err)
        app_config = AppConfig()

    coordinator = SkolengoCoordinator(hass, entry, client, app_config)
    # Raises ConfigEntryAuthFailed (reauth) or ConfigEntryNotReady (retry later).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SkolengoData(client=client, coordinator=coordinator)

    _async_register_devices(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SkolengoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SkolengoConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device that no longer matches a student (or the account) of the entry."""
    snapshot = entry.runtime_data.coordinator.data
    current = {(DOMAIN, s.id) for s in snapshot.account.students} | {(DOMAIN, snapshot.account.id)}
    return not device.identifiers & current


@callback
def _async_register_devices(
    hass: HomeAssistant, entry: SkolengoConfigEntry, coordinator: SkolengoCoordinator
) -> None:
    """One device per student with at least one granted service, plus the account if it has messaging."""
    registry = dr.async_get(hass)
    snapshot = coordinator.data
    for data in snapshot.students.values():
        if data.services:
            registry.async_get_or_create(config_entry_id=entry.entry_id, **student_device_info(data.student))
    if snapshot.has_messages:
        registry.async_get_or_create(config_entry_id=entry.entry_id, **account_device_info(snapshot.account))
