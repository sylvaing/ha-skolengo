"""Config entry and API mocks shared by the entity tests."""

from __future__ import annotations

from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.skolengo.config_flow import school_to_dict
from custom_components.skolengo.const import CONF_PROVIDER, CONF_SCHOOL, CONF_TOKENS, DOMAIN

from .helpers import API, SCHOOL, fixture_json, make_tokens

USERS_INFO = f"{API}/users-info/RSKO-P-parent-1"


def make_entry(hass: HomeAssistant, expires_in: float = 3600, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="RSKO-P-parent-1",
        data={
            CONF_SCHOOL: school_to_dict(SCHOOL),
            CONF_PROVIDER: "WEST-EDU_parent_eleve",
            CONF_USERNAME: "a.martin12",
            CONF_TOKENS: make_tokens(expires_in=expires_in).as_dict(),
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def mock_api(aioclient_mock: AiohttpClientMocker, skip: tuple[str, ...] = ()) -> None:
    """Register every endpoint the coordinator reads (except those in ``skip``)."""
    aioclient_mock.get(
        f"{API}/sko-app-configs/current",
        json={"data": {"attributes": {"apiCallRetryDelay": 500, "apiCallMaxRetries": 5}}},
    )
    endpoints = {
        "users-info": (USERS_INFO, "users_info_parent.json"),
        "homework": (f"{API}/homework-assignments", "homework.json"),
        "agendas": (f"{API}/agendas", "agendas.json"),
        "mail": (f"{API}/users-mail-settings/RSKO-P-parent-1", "mail_settings.json"),
        "communications": (f"{API}/communications", "communications.json"),
    }
    for name, (url, fixture) in endpoints.items():
        if name not in skip:
            aioclient_mock.get(url, json=fixture_json(fixture))


def calls(aioclient_mock: AiohttpClientMocker, path: str) -> list:
    """Recorded calls whose path contains ``path``."""
    return [c for c in aioclient_mock.mock_calls if path in str(c[1])]


def status(code: int):
    """Side effect answering an HTTP error."""

    async def answer(method, url, data):
        return AiohttpClientMockResponse(method, url, status=code, json={"errors": [{"title": str(code)}]})

    return answer
