"""Tests for the config entry setup: token persistence and reauth trigger."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.skolengo.config_flow import school_to_dict
from custom_components.skolengo.const import CONF_PROVIDER, CONF_SCHOOL, CONF_TOKENS, DOMAIN

from .helpers import API, SCHOOL, TOKEN, fixture_json, make_tokens, token_response


def _entry(hass: HomeAssistant, expires_in: float = 3600) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="RSKO-P-parent-1",
        data={
            CONF_SCHOOL: school_to_dict(SCHOOL),
            CONF_PROVIDER: "WEST-EDU_parent_eleve",
            CONF_USERNAME: "a.martin12",
            CONF_TOKENS: make_tokens(expires_in=expires_in).as_dict(),
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The account is read at setup and kept in runtime data."""
    aioclient_mock.get(f"{API}/users-info/RSKO-P-parent-1", json=fixture_json("users_info_parent.json"))
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert [s.first_name for s in entry.runtime_data.account.students] == ["Lou", "Sam"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_rotated_tokens_are_persisted(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An expired access token is refreshed at setup and the new refresh token saved in the entry."""
    aioclient_mock.post(TOKEN, json=token_response("access-2", "refresh-2"))
    aioclient_mock.get(f"{API}/users-info/RSKO-P-parent-1", json=fixture_json("users_info_parent.json"))
    entry = _entry(hass, expires_in=-10)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.data[CONF_TOKENS]["refresh_token"] == "refresh-2"
    assert entry.data[CONF_TOKENS]["access_token"] == "access-2"


async def test_dead_session_starts_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A refused refresh puts the entry in error and starts the reauth flow."""
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    entry = _entry(hass, expires_in=-10)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_network_error_retries(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A server error at setup means retry later, not reauth."""

    async def down(method, url, data):
        return AiohttpClientMockResponse(method, url, status=503)

    aioclient_mock.get(f"{API}/users-info/RSKO-P-parent-1", side_effect=down)
    entry = _entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
