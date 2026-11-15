"""Errors raised by the Skolengo API client."""

from __future__ import annotations


class SkolengoError(Exception):
    """Base class of every Skolengo error."""


class SkolengoConnectionError(SkolengoError):
    """The server could not be reached, or did not answer in time."""


class SkolengoLoginError(SkolengoError):
    """The sign-in went through an unexpected page or answer."""


class SkolengoInvalidCredentialsError(SkolengoLoginError):
    """The identity provider rejected the login or the password."""


class SkolengoCaptchaRequiredError(SkolengoLoginError):
    """The identity provider asks for a captcha, which cannot be solved without a browser."""


class SkolengoUnknownProviderError(SkolengoLoginError):
    """The requested identity provider is not offered by the ENT."""


class SkolengoAuthError(SkolengoError):
    """The session is no longer valid: the user has to sign in again."""


class SkolengoApiError(SkolengoError):
    """The API answered with an error status."""

    def __init__(self, status: int, code: str | None = None, message: str | None = None) -> None:
        """Keep the HTTP status and the first JSON:API error code, when any."""
        self.status = status
        self.code = code
        super().__init__(
            f"HTTP {status}" + (f" {code}" if code else "") + (f": {message}" if message else "")
        )


class SkolengoForbiddenError(SkolengoApiError):
    """The account may not use this service (often: the school does not enable it)."""
