"""Tests for the Skolengo config flow, reauth and options."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.skolengo.api import (
    Account,
    AuthorizationRequest,
    IdentityProvider,
    OidcConfig,
    SkolengoAuthError,
    SkolengoCaptchaRequiredError,
    SkolengoConnectionError,
    SkolengoInvalidCredentialsError,
    SkolengoLoginError,
    Student,
)
from custom_components.skolengo.config_flow import school_to_dict
from custom_components.skolengo.const import (
    CONF_CALLBACK_URL,
    CONF_HOMEWORK_DAYS,
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL,
    CONF_TIMETABLE_DAYS,
    CONF_TOKENS,
    DOMAIN,
)

from .helpers import AUTHORIZE, SCHOOL, TOKEN, make_tokens

FLOW = "custom_components.skolengo.config_flow"
OTHER_SCHOOL = SCHOOL.__class__(
    id="SKO-E-other", name="Lycée Exemple", city="AUTRE", ems_code="entexample", oidc_well_known_url="x"
)
PROVIDERS = [
    IdentityProvider("EAST-EDU_parent_eleve", "de l'académie de l'Est", "Élève ou parent"),
    IdentityProvider("WEST-EDU_parent_eleve", "de l'académie de l'Ouest", "Élève ou parent"),
]
ACCOUNT = Account(
    id="RSKO-P-parent-1",
    type="legalRepresentativeUserInfo",
    first_name="Alex",
    last_name="MARTIN",
    students=[Student("ESKO-P-child-1", "Lou", "MARTIN", "4A", None)],
    permissions=[],
)


@pytest.fixture
def api() -> Generator[MagicMock]:
    """Mock every API call made by the flow."""
    with (
        patch(f"{FLOW}.async_search_schools", AsyncMock(return_value=[SCHOOL, OTHER_SCHOOL])) as search,
        patch(f"{FLOW}.async_get_identity_providers", AsyncMock(return_value=PROVIDERS)) as providers,
        patch(f"{FLOW}.async_login", AsyncMock(return_value=make_tokens("access-1", "refresh-1"))) as login,
        patch(f"{FLOW}.async_discover", AsyncMock(return_value=OidcConfig(AUTHORIZE, TOKEN))) as discover,
        patch(
            f"{FLOW}.build_authorization_request",
            return_value=AuthorizationRequest(f"{AUTHORIZE}?client_id=x", "verifier", "st"),
        ),
        patch(
            f"{FLOW}.async_exchange_code", AsyncMock(return_value=make_tokens("access-2", "refresh-2"))
        ) as code,
        patch(f"{FLOW}.SkolengoClient") as client_cls,
        patch(f"{FLOW}._login_session", return_value=MagicMock()) as login_session,
        patch("custom_components.skolengo.async_setup_entry", AsyncMock(return_value=True)),
    ):
        client = client_cls.return_value
        client.async_get_account = AsyncMock(return_value=ACCOUNT)
        client.tokens = make_tokens("access-1", "refresh-1")
        yield MagicMock(
            search=search,
            providers=providers,
            login=login,
            discover=discover,
            exchange=code,
            client=client,
            login_session=login_session,
        )


async def _to_method_menu(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": " exemple "})
    assert result["step_id"] == "school"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SCHOOL: SCHOOL.id})
    assert result["step_id"] == "provider"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROVIDER: "WEST-EDU_parent_eleve"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["credentials", "browser"]
    return result


async def test_full_flow_with_credentials(hass: HomeAssistant, api: MagicMock) -> None:
    """School search → school → provider → login and password → entry, password not stored."""
    result = await _to_method_menu(hass)
    api.search.assert_awaited_once()
    assert api.search.await_args.args[1] == "exemple"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    assert result["step_id"] == "credentials"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: " a.martin12 ", CONF_PASSWORD: "s3cret"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Skolengo — Alex MARTIN"
    assert result["result"].unique_id == "RSKO-P-parent-1"
    data = result["data"]
    assert data[CONF_SCHOOL] == school_to_dict(SCHOOL)
    assert data[CONF_PROVIDER] == "WEST-EDU_parent_eleve"
    assert data[CONF_USERNAME] == "a.martin12"
    assert data[CONF_TOKENS]["refresh_token"] == "refresh-1"
    assert CONF_PASSWORD not in data
    assert "s3cret" not in repr(data)
    api.login.assert_awaited_once()
    assert api.login.await_args.args[1:] == (SCHOOL, "a.martin12", "s3cret", "WEST-EDU_parent_eleve")
    # every sign-in session is released
    assert api.login_session.return_value.detach.call_count == api.login_session.call_count


async def test_single_school_and_no_provider_page(hass: HomeAssistant, api: MagicMock) -> None:
    """One search result skips the school list; no choice page skips the provider step."""
    api.search.return_value = [SCHOOL]
    api.providers.return_value = []
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "exemple"})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a", CONF_PASSWORD: "b"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROVIDER] is None


async def test_search_errors(hass: HomeAssistant, api: MagicMock) -> None:
    """No result and network errors are shown on the search form."""
    api.search.return_value = []
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "nowhere"})
    assert result["errors"] == {"query": "no_school_found"}

    api.search.side_effect = SkolengoConnectionError("down")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "nowhere"})
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SkolengoInvalidCredentialsError("no"), "invalid_auth"),
        (SkolengoCaptchaRequiredError("captcha"), "captcha_required"),
        (SkolengoConnectionError("down"), "cannot_connect"),
        (SkolengoLoginError("Maintenance"), "login_failed"),
    ],
)
async def test_credentials_errors(hass: HomeAssistant, api: MagicMock, error: Exception, key: str) -> None:
    """Sign-in errors keep the form, with the login prefilled; a retry can succeed."""
    result = await _to_method_menu(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    api.login.side_effect = error
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a.martin12", CONF_PASSWORD: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    api.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a.martin12", CONF_PASSWORD: "good"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_browser_fallback(hass: HomeAssistant, api: MagicMock) -> None:
    """The pasted callback address is checked against the state, then exchanged."""
    result = await _to_method_menu(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "browser"})
    assert result["step_id"] == "browser"
    assert result["description_placeholders"]["auth_url"].startswith(AUTHORIZE)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CALLBACK_URL: "skoapp-prod://sign-in-callback?code=c&state=other"}
    )
    assert result["errors"] == {CONF_CALLBACK_URL: "invalid_callback"}

    api.exchange.side_effect = SkolengoAuthError("expired")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CALLBACK_URL: "skoapp-prod://sign-in-callback?code=c&state=st"}
    )
    assert result["errors"] == {"base": "code_expired"}

    api.exchange.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CALLBACK_URL: "skoapp-prod://sign-in-callback?code=c&state=st"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert api.exchange.await_args.args[2:] == ("c", "verifier")


async def test_already_configured(hass: HomeAssistant, api: MagicMock) -> None:
    """The same account (``sub``) cannot be added twice."""
    MockConfigEntry(domain=DOMAIN, unique_id="RSKO-P-parent-1", data={}).add_to_hass(hass)
    result = await _to_method_menu(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a", CONF_PASSWORD: "b"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="RSKO-P-parent-1",
        data={
            CONF_SCHOOL: school_to_dict(SCHOOL),
            CONF_PROVIDER: "WEST-EDU_parent_eleve",
            CONF_USERNAME: "a.martin12",
            CONF_TOKENS: make_tokens().as_dict(),
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_reauth(hass: HomeAssistant, api: MagicMock) -> None:
    """Reauth reuses school and provider, prefills the login and replaces the tokens."""
    entry = _entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    assert result["step_id"] == "credentials"
    schema_defaults = {str(k): k.description for k in result["data_schema"].schema}
    assert schema_defaults[CONF_USERNAME] == {"suggested_value": "a.martin12"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a.martin12", CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKENS]["refresh_token"] == "refresh-1"
    assert entry.data[CONF_PROVIDER] == "WEST-EDU_parent_eleve"


async def test_reauth_wrong_account(hass: HomeAssistant, api: MagicMock) -> None:
    """Signing in with another account does not overwrite the entry."""
    entry = _entry(hass)
    api.client.async_get_account.return_value = Account("RSKO-P-someone-else", "x", "B", "C", [], [])
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "other", CONF_PASSWORD: "x"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_TOKENS]["refresh_token"] == "refresh-0"


async def test_options(hass: HomeAssistant, api: MagicMock) -> None:
    """Options are stored as integers."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 45.0, CONF_HOMEWORK_DAYS: 10.0, CONF_TIMETABLE_DAYS: 5.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 45, CONF_HOMEWORK_DAYS: 10, CONF_TIMETABLE_DAYS: 5}
