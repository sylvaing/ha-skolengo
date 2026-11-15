"""Sign-in to Skolengo: school search, OIDC + PKCE, and the browser-less EduConnect login.

The official app signs in with OpenID Connect (authorization code + PKCE) and a redirect to the custom
scheme ``skoapp-prod://sign-in-callback``. A browser cannot follow that scheme, but an HTTP client does
not have to: the authorization code is read from the ``Location`` header of the last redirect.

``async_login`` walks the whole sign-in itself (ENT CAS page, identity provider such as EduConnect,
SAML auto-posted forms) with the user's login and password. It needs an ``aiohttp`` session with its
**own cookie jar**, used for this sign-in only and closed afterwards.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from yarl import URL

from .const import (
    API_BASE_URL,
    LOGIN_MAX_STEPS,
    LOGIN_USER_AGENT,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_REDIRECT_URI,
    OIDC_SCOPE,
    REQUEST_TIMEOUT,
)
from .exceptions import (
    SkolengoAuthError,
    SkolengoCaptchaRequiredError,
    SkolengoConnectionError,
    SkolengoError,
    SkolengoInvalidCredentialsError,
    SkolengoLoginError,
    SkolengoUnknownProviderError,
)
from .html import Form, parse_page
from .models import AuthorizationRequest, IdentityProvider, OidcConfig, School, Tokens

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
_LOGIN_HEADERS = {"User-Agent": LOGIN_USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_CALLBACK_SCHEME = urlparse(OIDC_REDIRECT_URI).scheme + "://"
# Field names used by the identity providers we know, tried before guessing from the input types.
_USERNAME_FIELDS = ("j_username", "username", "login", "email")
_BASIC_AUTH = "Basic " + base64.b64encode(f"{OIDC_CLIENT_ID}:{OIDC_CLIENT_SECRET}".encode()).decode()


async def async_search_schools(session: aiohttp.ClientSession, text: str, limit: int = 20) -> list[School]:
    """Search schools by name or town (public endpoint, no authentication)."""
    data = await _get_json(
        session, f"{API_BASE_URL}/schools", params={"filter[text]": text, "page[limit]": str(limit)}
    )
    schools = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        if not attrs.get("emsCode") or not attrs.get("emsOIDCWellKnownUrl"):
            continue
        schools.append(
            School(
                id=item["id"],
                name=attrs.get("name") or item["id"],
                city=attrs.get("city"),
                ems_code=attrs["emsCode"],
                oidc_well_known_url=attrs["emsOIDCWellKnownUrl"],
                address=attrs.get("addressLine1"),
            )
        )
    return schools


async def async_discover(session: aiohttp.ClientSession, well_known_url: str) -> OidcConfig:
    """Read the OpenID Connect discovery document of an ENT."""
    data = await _get_json(session, well_known_url)
    try:
        return OidcConfig(data["authorization_endpoint"], data["token_endpoint"])
    except KeyError as err:
        raise SkolengoLoginError(f"incomplete OIDC discovery document: missing {err}") from err


def build_authorization_request(oidc: OidcConfig) -> AuthorizationRequest:
    """Build an authorization URL with a fresh PKCE verifier and state."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    query = urlencode(
        {
            "client_id": OIDC_CLIENT_ID,
            "redirect_uri": OIDC_REDIRECT_URI,
            "response_type": "code",
            "scope": OIDC_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return AuthorizationRequest(
        url=f"{oidc.authorization_endpoint}?{query}", code_verifier=verifier, state=state
    )


def parse_callback_url(url: str, expected_state: str | None = None) -> str:
    """Return the authorization code of a ``skoapp-prod://sign-in-callback?code=…`` URL."""
    url = url.strip()
    if not url.startswith(_CALLBACK_SCHEME):
        raise SkolengoLoginError("not a Skolengo sign-in callback URL")
    query = parse_qs(urlparse(url).query)
    if "error" in query:
        raise SkolengoLoginError(f"sign-in refused: {query['error'][0]}")
    if expected_state is not None and query.get("state", [None])[0] != expected_state:
        raise SkolengoLoginError("sign-in state mismatch")
    try:
        return query["code"][0]
    except KeyError as err:
        raise SkolengoLoginError("no authorization code in the callback URL") from err


async def async_exchange_code(
    session: aiohttp.ClientSession, oidc: OidcConfig, code: str, code_verifier: str
) -> Tokens:
    """Exchange an authorization code for tokens (client_secret_basic)."""
    data = await _token_request(
        session,
        oidc.token_endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": OIDC_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
    )
    return Tokens.from_token_response(data, oidc.token_endpoint)


async def async_refresh_tokens(session: aiohttp.ClientSession, tokens: Tokens) -> Tokens:
    """Refresh the tokens. The refresh token rotates: persist the returned one."""
    data = await _token_request(
        session, tokens.token_endpoint, {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
    )
    return Tokens.from_token_response(data, tokens.token_endpoint, previous=tokens)


async def async_get_identity_providers(
    session: aiohttp.ClientSession, school: School
) -> list[IdentityProvider]:
    """List the sign-in choices the ENT offers for this school.

    Returns an empty list when the ENT goes straight to a login form without a choice page.
    """
    oidc = await async_discover(session, school.oidc_well_known_url)
    request = build_authorization_request(oidc)
    response, _ = await _follow(session, "GET", request.url)
    page = parse_page(response.text)
    return [
        IdentityProvider(id=r.value, label=r.label, category=r.category)
        for r in page.radios
        if r.name == "selection"
    ]


async def async_login(
    session: aiohttp.ClientSession,
    school: School,
    username: str,
    password: str,
    provider_id: str | None = None,
) -> Tokens:
    """Sign in with a login and password, without a browser, and return the tokens.

    ``provider_id`` is the identity provider to pick on the ENT's choice page (see
    ``async_get_identity_providers``); it may be ``None`` when the ENT has no choice page.
    """
    oidc = await async_discover(session, school.oidc_well_known_url)
    request = build_authorization_request(oidc)
    response, callback = await _follow(session, "GET", request.url)
    credentials_sent = False

    for _ in range(LOGIN_MAX_STEPS):
        if callback is not None:
            code = parse_callback_url(callback, request.state)
            return await async_exchange_code(session, oidc, code, request.code_verifier)

        if response.status >= 400:
            raise SkolengoLoginError(f"HTTP {response.status} on {_host(response.url)}")

        page = parse_page(response.text)
        if (inline := _find_callback_in_page(response.text)) is not None:
            callback = inline
            continue

        login_form = next((f for f in page.forms if f.has_type("password")), None)
        if login_form is not None:
            if credentials_sent:
                if page.has_captcha:
                    raise SkolengoCaptchaRequiredError("the identity provider now asks for a captcha")
                raise SkolengoInvalidCredentialsError("the identity provider rejected the login or password")
            if page.has_captcha:
                raise SkolengoCaptchaRequiredError("the identity provider asks for a captcha")
            _LOGGER.debug("Posting credentials to %s", _host(response.url))
            response, callback = await _submit(
                session, response.url, login_form, _credentials(login_form, username, password)
            )
            credentials_sent = True
            continue

        choice_form = next(
            (f for f in page.forms if any(i.type == "radio" and i.name == "selection" for i in f.inputs)),
            None,
        )
        if choice_form is not None:
            offered = [r.value for r in page.radios if r.name == "selection"]
            if provider_id is None or provider_id not in offered:
                raise SkolengoUnknownProviderError(
                    f"identity provider {provider_id!r} not offered: {offered}"
                )
            data = choice_form.values()
            data["selection"] = provider_id
            response, callback = await _submit(session, response.url, choice_form, data)
            continue

        auto_form = next((f for f in page.forms if f.is_auto_submit), None)
        if auto_form is not None:
            response, callback = await _submit(session, response.url, auto_form, _auto_values(auto_form))
            continue

        raise SkolengoLoginError(
            f"unexpected sign-in page on {_host(response.url)}: {page.title or 'untitled'}"
        )

    raise SkolengoLoginError("too many sign-in steps")


# --- internals -------------------------------------------------------------------------------------


class _Response:
    """The parts of an HTTP response the sign-in needs, read before the connection is released."""

    __slots__ = ("headers", "status", "text", "url")

    def __init__(self, status: int, url: URL, headers: dict[str, str], text: str) -> None:
        self.status = status
        self.url = url
        self.headers = headers
        self.text = text


def _host(url: URL | str) -> str:
    return URL(str(url)).host or "?"


def _find_callback_in_page(text: str) -> str | None:
    """Some providers render the final redirect in the page (form action, link, script)."""
    idx = text.find(OIDC_REDIRECT_URI + "?")
    if idx < 0:
        return None
    end = idx
    while end < len(text) and text[end] not in "\"'<> \n\r\t":
        end += 1
    return unescape(text[idx:end])


def _credentials(form: Form, username: str, password: str) -> dict[str, str]:
    data = form.values()
    password_field = next(i.name for i in form.inputs if i.type == "password")
    names = {i.name for i in form.inputs}
    user_field = next((n for n in _USERNAME_FIELDS if n in names), None)
    if user_field is None:
        user_field = next(
            (i.name for i in form.inputs if i.type in ("text", "email") and i.name != password_field), None
        )
    if user_field is None:
        raise SkolengoLoginError("login form without a username field")
    data[user_field] = username
    data[password_field] = password
    if form.buttons:
        name, value = form.buttons[0]
        data.setdefault(name, value)
    return data


def _auto_values(form: Form) -> dict[str, str]:
    """Values of a hidden-only form, as its JavaScript would post them."""
    data = form.values()
    if "shib_idp_ls_supported" in data:
        # Shibboleth's local-storage probe: report it as supported and successfully read (empty).
        data["shib_idp_ls_supported"] = "true"
        for key in data:
            if key.startswith("shib_idp_ls_success."):
                data[key] = "true"
    for name, value in form.buttons:
        data.setdefault(name, value)
    return data


async def _submit(
    session: aiohttp.ClientSession, base: URL, form: Form, data: dict[str, str]
) -> tuple[_Response, str | None]:
    target = base.join(URL(form.action)) if form.action else base
    if form.method == "post":
        return await _follow(session, "POST", str(target), data=data)
    return await _follow(session, "GET", str(target.with_query(None)), params=data)


async def _follow(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[_Response, str | None]:
    """Request a URL and follow redirects by hand; stop at the app callback and return it."""
    for _ in range(LOGIN_MAX_STEPS):
        try:
            async with session.request(
                method,
                url,
                data=data,
                params=params,
                headers=_LOGIN_HEADERS,
                allow_redirects=False,
                timeout=_TIMEOUT,
            ) as resp:
                text = await resp.text(errors="replace")
                response = _Response(resp.status, resp.url, dict(resp.headers), text)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SkolengoConnectionError(f"cannot reach {_host(url)}: {err}") from err

        if response.status not in _REDIRECT_STATUSES:
            return response, None
        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            raise SkolengoLoginError(f"redirect without location on {_host(response.url)}")
        if location.startswith(_CALLBACK_SCHEME):
            return response, location
        url = str(response.url.join(URL(location)))
        # A redirect turns the request into a plain GET (303, and 301/302 in practice).
        method, data, params = "GET", None, None
    raise SkolengoLoginError("too many redirects")


async def _get_json(
    session: aiohttp.ClientSession, url: str, params: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        async with session.get(
            url, params=params, headers={"Accept": "application/json"}, timeout=_TIMEOUT
        ) as resp:
            if resp.status >= 400:
                raise SkolengoError(f"HTTP {resp.status} on {_host(url)}")
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SkolengoConnectionError(f"cannot reach {_host(url)}: {err}") from err


async def _token_request(session: aiohttp.ClientSession, token_endpoint: str, form: dict[str, str]) -> dict:
    try:
        async with session.post(
            token_endpoint,
            data=form,
            # client_secret_basic is required: the secret in the body is refused with a 401.
            headers={"Accept": "application/json", "Authorization": _BASIC_AUTH},
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status in (400, 401):
                # invalid_grant: expired, revoked or already used (rotated) refresh token / code.
                raise SkolengoAuthError(f"token endpoint refused the grant (HTTP {resp.status})")
            if resp.status >= 400:
                raise SkolengoConnectionError(f"token endpoint error (HTTP {resp.status})")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SkolengoConnectionError(f"cannot reach the token endpoint: {err}") from err
    if "access_token" not in data:
        raise SkolengoAuthError("token endpoint answer without access_token")
    return data
