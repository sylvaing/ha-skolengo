"""Tests for the diagnostics: useful structure, no personal data."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skolengo.const import DOMAIN
from custom_components.skolengo.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .common import make_entry, mock_api

PERSONAL = (
    "MARTIN",
    "Lou",
    "Alex",
    "a.martin12",
    "access-0",
    "refresh-0",
    "RSKO-P-parent-1",
    "ESKO-P-child",
    "DURAND",
    "Sortie",
    "exercice",
    "eyJ",
)


async def test_entry_diagnostics(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Counts, services and errors; no tokens, names, ids or texts."""
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    dump = json.dumps(diag, default=str)
    for value in PERSONAL:
        assert value not in dump, value
    assert diag["entry"]["data"]["tokens"] == "**REDACTED**"
    first = diag["data"]["students"][0]
    assert first["services"] == ["CDT", "TAF"]
    assert first["homework"] == {"count": 2, "done": 1}
    assert first["lessons"] == {"count": 2, "canceled": 1}
    assert diag["data"]["mailbox"]["unread"] == 1


async def test_device_diagnostics(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A student's device shows that student only."""
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ESKO-P-child-1"), entry.entry_id)

    diag = await async_get_device_diagnostics(hass, entry, device)
    assert diag["student"]["class"] == "4A"
    assert "Lou" not in json.dumps(diag)
