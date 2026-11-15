"""Config flow for the Skolengo integration.

Sign-in without a browser: the user picks the school, then the identity provider offered by the ENT
(e.g. EduConnect of an académie), then types the login and password. The integration walks the
sign-in itself and keeps only the tokens; the password is never stored.

A fallback, for FranceConnect accounts or when a captcha is required, lets the user sign in in a
browser and paste the ``skoapp-prod://sign-in-callback?code=…`` address the browser could not open.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AuthorizationRequest,
    IdentityProvider,
    OidcConfig,
    School,
    SkolengoAuthError,
    SkolengoCaptchaRequiredError,
    SkolengoClient,
    SkolengoConnectionError,
    SkolengoError,
    SkolengoInvalidCredentialsError,
    SkolengoLoginError,
    SkolengoUnknownProviderError,
    Tokens,
    async_discover,
    async_exchange_code,
    async_get_identity_providers,
    async_login,
    async_search_schools,
    build_authorization_request,
    parse_callback_url,
)
from .const import (
    CONF_CALLBACK_URL,
    CONF_HOMEWORK_DAYS,
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL,
    CONF_TIMETABLE_DAYS,
    CONF_TOKENS,
    DEFAULT_HOMEWORK_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMETABLE_DAYS,
    DOMAIN,
    MAX_DAYS,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONF_QUERY = "query"


def school_to_dict(school: School) -> dict[str, Any]:
    """Serialise a school for the config entry."""
    return {
        "id": school.id,
        "name": school.name,
        "city": school.city,
        "ems_code": school.ems_code,
        "oidc_well_known_url": school.oidc_well_known_url,
    }


def school_from_dict(data: Mapping[str, Any]) -> School:
    """Restore a school from the config entry."""
    return School(
        id=data["id"],
        name=data["name"],
        city=data.get("city"),
        ems_code=data["ems_code"],
        oidc_well_known_url=data["oidc_well_known_url"],
    )


def _provider_label(provider: IdentityProvider) -> str:
    return f"{provider.category} — {provider.label}" if provider.category else provider.label


class SkolengoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Skolengo."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow state."""
        self._schools: list[School] = []
        self._school: School | None = None
        self._providers: list[IdentityProvider] = []
        self._provider_id: str | None = None
        self._username: str | None = None
        self._auth_request: AuthorizationRequest | None = None
        self._oidc: OidcConfig | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SkolengoOptionsFlow:
        """Options: polling interval and how many days to fetch."""
        return SkolengoOptionsFlow()

    # --- school ------------------------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Search the school by name or town."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._schools = await async_search_schools(
                    async_get_clientsession(self.hass), user_input[CONF_QUERY].strip()
                )
            except SkolengoError as err:
                _LOGGER.debug("School search failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not self._schools:
                    errors[CONF_QUERY] = "no_school_found"
                elif len(self._schools) == 1:
                    return await self._async_school_chosen(self._schools[0])
                else:
                    return await self.async_step_school()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_QUERY): str}), user_input
            ),
            errors=errors,
        )

    async def async_step_school(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the school among the search results."""
        if user_input is not None:
            school = next(s for s in self._schools if s.id == user_input[CONF_SCHOOL])
            return await self._async_school_chosen(school)

        options = [
            SelectOptionDict(value=s.id, label=f"{s.name} — {s.city}" if s.city else s.name)
            for s in self._schools
        ]
        return self.async_show_form(
            step_id="school",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHOOL): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def _async_school_chosen(self, school: School) -> ConfigFlowResult:
        self._school = school
        session = _login_session(self.hass)
        try:
            self._providers = await async_get_identity_providers(session, school)
        except SkolengoError as err:
            _LOGGER.debug("Cannot read the identity providers: %s", err)
            return self.async_abort(reason="cannot_connect")
        finally:
            await session.close()
        if not self._providers:
            self._provider_id = None
            return await self.async_step_method()
        return await self.async_step_provider()

    async def async_step_provider(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the identity provider (e.g. "Élève ou parent — de l'académie de …")."""
        if user_input is not None:
            self._provider_id = user_input[CONF_PROVIDER]
            return await self.async_step_method()

        options = [SelectOptionDict(value=p.id, label=_provider_label(p)) for p in self._providers]
        return self.async_show_form(
            step_id="provider",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"school": self._school.name if self._school else ""},
        )

    # --- sign-in -----------------------------------------------------------------------------------

    async def async_step_method(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sign in with login and password (recommended), or in a browser."""
        return self.async_show_menu(step_id="method", menu_options=["credentials", "browser"])

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Login and password, used once to sign in and never stored."""
        assert self._school is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            session = _login_session(self.hass)
            try:
                tokens = await async_login(
                    session, self._school, self._username, user_input[CONF_PASSWORD], self._provider_id
                )
            except SkolengoInvalidCredentialsError:
                errors["base"] = "invalid_auth"
            except SkolengoCaptchaRequiredError:
                errors["base"] = "captcha_required"
            except SkolengoUnknownProviderError:
                errors["base"] = "unknown_provider"
            except SkolengoConnectionError:
                errors["base"] = "cannot_connect"
            except (SkolengoLoginError, SkolengoAuthError) as err:
                _LOGGER.warning("Skolengo sign-in failed: %s", err)
                errors["base"] = "login_failed"
            else:
                return await self._async_signed_in(tokens)
            finally:
                await session.close()

        return self.async_show_form(
            step_id="credentials",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_USERNAME): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
                        ),
                        vol.Required(CONF_PASSWORD): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.PASSWORD, autocomplete="current-password"
                            )
                        ),
                    }
                ),
                {CONF_USERNAME: self._username} if self._username else None,
            ),
            errors=errors,
            description_placeholders={"school": self._school.name},
        )

    async def async_step_browser(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Fallback: sign in in a browser, then paste the address it could not open."""
        assert self._school is not None
        session = async_get_clientsession(self.hass)
        errors: dict[str, str] = {}

        if user_input is not None and self._oidc is not None and self._auth_request is not None:
            try:
                code = parse_callback_url(user_input[CONF_CALLBACK_URL], self._auth_request.state)
                tokens = await async_exchange_code(
                    session, self._oidc, code, self._auth_request.code_verifier
                )
            except SkolengoConnectionError:
                errors["base"] = "cannot_connect"
            except SkolengoAuthError:
                # The code is single-use and short-lived: start again with a fresh request.
                self._auth_request = None
                errors["base"] = "code_expired"
            except SkolengoError:
                errors[CONF_CALLBACK_URL] = "invalid_callback"
            else:
                return await self._async_signed_in(tokens)

        if self._oidc is None or self._auth_request is None:
            try:
                self._oidc = await async_discover(session, self._school.oidc_well_known_url)
            except SkolengoError:
                return self.async_abort(reason="cannot_connect")
            self._auth_request = build_authorization_request(self._oidc)

        return self.async_show_form(
            step_id="browser",
            data_schema=vol.Schema({vol.Required(CONF_CALLBACK_URL): str}),
            errors=errors,
            description_placeholders={"auth_url": self._auth_request.url, "school": self._school.name},
        )

    async def _async_signed_in(self, tokens: Tokens) -> ConfigFlowResult:
        """Check the account, then create (or, on reauth, update) the entry."""
        assert self._school is not None
        client = SkolengoClient(async_get_clientsession(self.hass), tokens, self._school.ems_code)
        try:
            account = await client.async_get_account()
        except SkolengoError as err:
            _LOGGER.warning("Signed in, but the account cannot be read: %s", err)
            return self.async_abort(reason="cannot_connect")
        tokens = client.tokens  # in case they were refreshed meanwhile

        await self.async_set_unique_id(account.id)
        data = {
            CONF_SCHOOL: school_to_dict(self._school),
            CONF_PROVIDER: self._provider_id,
            CONF_USERNAME: self._username,
            CONF_TOKENS: tokens.as_dict(),
        }
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)

        self._abort_if_unique_id_configured()
        title = f"{account.first_name} {account.last_name}".strip() or self._school.name
        return self.async_create_entry(title=f"Skolengo — {title}", data=data)

    # --- reauth ------------------------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The session can no longer be refreshed: sign in again (same school and provider)."""
        self._school = school_from_dict(entry_data[CONF_SCHOOL])
        self._provider_id = entry_data.get(CONF_PROVIDER)
        self._username = entry_data.get(CONF_USERNAME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Explain why, then offer the same sign-in methods."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"school": self._school.name if self._school else ""},
            )
        return await self.async_step_method()


class SkolengoOptionsFlow(OptionsFlowWithReload):
    """Polling interval and fetch windows."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})

        def number(minimum: int, maximum: int) -> NumberSelector:
            return NumberSelector(
                NumberSelectorConfig(min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX)
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): number(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
                vol.Required(
                    CONF_HOMEWORK_DAYS, default=options.get(CONF_HOMEWORK_DAYS, DEFAULT_HOMEWORK_DAYS)
                ): number(1, MAX_DAYS),
                vol.Required(
                    CONF_TIMETABLE_DAYS, default=options.get(CONF_TIMETABLE_DAYS, DEFAULT_TIMETABLE_DAYS)
                ): number(1, MAX_DAYS),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _login_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """A session with its own cookie jar for one sign-in (closed by the caller)."""
    return async_create_clientsession(hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar())
