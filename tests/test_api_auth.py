"""Tests for the browser-less sign-in (CAS choice page, Shibboleth/EduConnect, OIDC code exchange)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skolengo.api import (
    SkolengoAuthError,
    SkolengoCaptchaRequiredError,
    SkolengoInvalidCredentialsError,
    SkolengoLoginError,
    SkolengoUnknownProviderError,
    async_get_identity_providers,
    async_login,
    async_refresh_tokens,
    async_search_schools,
    build_authorization_request,
    parse_callback_url,
)
from custom_components.skolengo.api.models import OidcConfig

from .helpers import API, AUTHORIZE, SCHOOL, TOKEN, WELL_KNOWN, fixture_text, make_tokens, token_response

CAS = "https://cas.example.test"
IDP = "https://idp.example.test/idp/profile/SAML2/POST/SSO"
STATE = "fixed-random"


@pytest.fixture
def fixed_random():
    """Make the PKCE verifier and the OIDC state predictable."""
    with patch("custom_components.skolengo.api.auth.secrets.token_urlsafe", return_value=STATE):
        yield


def mock_sign_in(aioclient_mock: AiohttpClientMocker, login_page: str = "educonnect_login.html") -> None:
    """Register the whole sign-in path. More specific URLs first: the mocker matches query subsets."""
    aioclient_mock.get(WELL_KNOWN, json={"authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN})
    aioclient_mock.get(AUTHORIZE, status=302, headers={"Location": f"{CAS}/login?service=svc"})
    aioclient_mock.get(
        f"{CAS}/login?selection=WEST-EDU_parent_eleve", status=302, headers={"Location": "/delegate/EDU"}
    )
    aioclient_mock.get(f"{CAS}/login", text=fixture_text("cas_wayf.html"))
    aioclient_mock.get(f"{CAS}/delegate/EDU", text=fixture_text("saml_request.html"))
    aioclient_mock.post(f"{IDP}?execution=e1s2", text=fixture_text("saml_response.html"))
    aioclient_mock.post(f"{IDP}?execution=e1s1", status=302, headers={"Location": f"{IDP}?execution=e1s2"})
    aioclient_mock.post(IDP, status=302, headers={"Location": "?execution=e1s1"})
    aioclient_mock.get(f"{IDP}?execution=e1s2", text=fixture_text(login_page))
    aioclient_mock.get(f"{IDP}?execution=e1s1", text=fixture_text("shib_local_storage.html"))
    aioclient_mock.post(
        f"{CAS}/login/EDU",
        status=302,
        headers={"Location": f"skoapp-prod://sign-in-callback?code=the-code&state={STATE}"},
    )
    aioclient_mock.post(TOKEN, json=token_response())


def posted(aioclient_mock: AiohttpClientMocker, url: str) -> dict:
    """Form data of the POST sent to ``url``."""
    for method, called, data, _ in aioclient_mock.mock_calls:
        if method.upper() == "POST" and str(called) == url:
            return dict(data)
    raise AssertionError(f"no POST to {url}")


async def test_login_success(aioclient_mock: AiohttpClientMocker, fixed_random) -> None:
    """The whole path is walked without a browser and the code is read from the redirect."""
    mock_sign_in(aioclient_mock)
    session = aioclient_mock.create_session(None)

    tokens = await async_login(session, SCHOOL, "a.martin12", "s3cret", provider_id="WEST-EDU_parent_eleve")

    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"
    assert tokens.subject == "RSKO-P-parent-1"
    assert tokens.token_endpoint == TOKEN

    shib = posted(aioclient_mock, f"{IDP}?execution=e1s1")
    assert shib["shib_idp_ls_supported"] == "true"
    assert shib["shib_idp_ls_success.shib_idp_session_ss"] == "true"
    assert shib["csrf_token"] == "csrf-ls"

    creds = posted(aioclient_mock, f"{IDP}?execution=e1s2")
    assert creds == {
        "csrf_token": "csrf-login",
        "j_username": "a.martin12",
        "j_password": "s3cret",
        "_eventId_proceed": "",
    }
    assert posted(aioclient_mock, f"{CAS}/login/EDU")["SAMLResponse"]

    exchange = posted(aioclient_mock, TOKEN)
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code"] == "the-code"
    assert exchange["code_verifier"] == STATE
    assert exchange["redirect_uri"] == "skoapp-prod://sign-in-callback"
    await session.close()


async def test_login_invalid_credentials(aioclient_mock: AiohttpClientMocker, fixed_random) -> None:
    """The login form shown again after posting means the credentials were refused."""
    mock_sign_in(aioclient_mock)
    aioclient_mock._mocks = [
        m for m in aioclient_mock._mocks if not (m.method == "post" and str(m.url) == f"{IDP}?execution=e1s2")
    ]
    aioclient_mock.post(f"{IDP}?execution=e1s2", text=fixture_text("educonnect_login.html"))
    # The more specific mock must come before the generic POST on the bare IDP URL.
    aioclient_mock._mocks.insert(0, aioclient_mock._mocks.pop())
    session = aioclient_mock.create_session(None)

    with pytest.raises(SkolengoInvalidCredentialsError):
        await async_login(session, SCHOOL, "a.martin12", "wrong", provider_id="WEST-EDU_parent_eleve")
    await session.close()


async def test_login_captcha(aioclient_mock: AiohttpClientMocker, fixed_random) -> None:
    """A captcha on the login form stops the sign-in before posting the password."""
    mock_sign_in(aioclient_mock, login_page="educonnect_login_captcha.html")
    session = aioclient_mock.create_session(None)

    with pytest.raises(SkolengoCaptchaRequiredError):
        await async_login(session, SCHOOL, "a.martin12", "s3cret", provider_id="WEST-EDU_parent_eleve")
    assert not any(
        str(url) == f"{IDP}?execution=e1s2" and m == "POST" for m, url, _, _ in aioclient_mock.mock_calls
    )
    await session.close()


async def test_login_unknown_provider(aioclient_mock: AiohttpClientMocker, fixed_random) -> None:
    """A provider that the choice page does not offer is reported."""
    mock_sign_in(aioclient_mock)
    session = aioclient_mock.create_session(None)

    with pytest.raises(SkolengoUnknownProviderError):
        await async_login(session, SCHOOL, "a.martin12", "s3cret", provider_id="NOPE")
    await session.close()


async def test_login_unexpected_page(aioclient_mock: AiohttpClientMocker, fixed_random) -> None:
    """A page with nothing to do (e.g. maintenance) ends the sign-in with its title."""
    aioclient_mock.get(WELL_KNOWN, json={"authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN})
    aioclient_mock.get(
        AUTHORIZE, text="<html><head><title>Maintenance</title></head><body>Bientôt</body></html>"
    )
    session = aioclient_mock.create_session(None)

    with pytest.raises(SkolengoLoginError, match="Maintenance"):
        await async_login(session, SCHOOL, "a.martin12", "s3cret", provider_id="WEST-EDU_parent_eleve")
    await session.close()


async def test_identity_providers(aioclient_mock: AiohttpClientMocker) -> None:
    """The choice page radios come back with their fieldset category and label."""
    mock_sign_in(aioclient_mock)
    session = aioclient_mock.create_session(None)

    providers = await async_get_identity_providers(session, SCHOOL)

    assert [(p.id, p.category, p.label) for p in providers] == [
        ("EAST-EDU_parent_eleve", "Élève ou parent", "de l’académie de l'Est"),
        ("WEST-EDU_parent_eleve", "Élève ou parent", "de l’académie de l'Ouest"),
        ("WEST-AAA_enseignant", "Enseignant", "de l’académie de l'Ouest"),
        ("ENT", None, "Autres comptes et invités"),
    ]
    await session.close()


async def test_search_schools(aioclient_mock: AiohttpClientMocker) -> None:
    """Schools without an ENT code or OIDC URL are skipped."""
    aioclient_mock.get(
        f"{API}/schools",
        json={
            "data": [
                {
                    "id": "SKO-E-1",
                    "type": "school",
                    "attributes": {
                        "name": "Collège Exemple",
                        "city": "VILLE",
                        "emsCode": "entexample",
                        "emsOIDCWellKnownUrl": WELL_KNOWN,
                    },
                },
                {"id": "SKO-E-2", "type": "school", "attributes": {"name": "Sans ENT"}},
            ]
        },
    )
    session = aioclient_mock.create_session(None)

    schools = await async_search_schools(session, "exemple")

    assert [(s.id, s.ems_code) for s in schools] == [("SKO-E-1", "entexample")]
    assert aioclient_mock.mock_calls[0][1].query["filter[text]"] == "exemple"
    await session.close()


async def test_refresh_rotates(aioclient_mock: AiohttpClientMocker) -> None:
    """A refresh answer without id_token keeps the previous one; the refresh token is replaced."""
    aioclient_mock.post(TOKEN, json=token_response("access-2", "refresh-2", with_id_token=False))
    session = aioclient_mock.create_session(None)
    old = make_tokens()

    new = await async_refresh_tokens(session, old)

    assert (new.access_token, new.refresh_token) == ("access-2", "refresh-2")
    assert new.id_token == old.id_token
    assert posted(aioclient_mock, TOKEN) == {"grant_type": "refresh_token", "refresh_token": "refresh-0"}
    await session.close()


async def test_refresh_refused(aioclient_mock: AiohttpClientMocker) -> None:
    """An expired or already used refresh token means the user must sign in again."""
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    session = aioclient_mock.create_session(None)

    with pytest.raises(SkolengoAuthError):
        await async_refresh_tokens(session, make_tokens())
    await session.close()


def test_authorization_request_and_callback() -> None:
    """PKCE S256 URL, and the code of a pasted callback URL with its state checked."""
    request = build_authorization_request(OidcConfig(AUTHORIZE, TOKEN))
    assert request.url.startswith(AUTHORIZE + "?")
    assert "code_challenge_method=S256" in request.url
    assert f"state={request.state}" in request.url

    url = f"skoapp-prod://sign-in-callback?code=abc&state={request.state}"
    assert parse_callback_url(f"  {url} ", request.state) == "abc"
    with pytest.raises(SkolengoLoginError):
        parse_callback_url(url, "other-state")
    with pytest.raises(SkolengoLoginError):
        parse_callback_url("https://example.test/?code=abc")
    with pytest.raises(SkolengoLoginError):
        parse_callback_url("skoapp-prod://sign-in-callback?error=access_denied")
