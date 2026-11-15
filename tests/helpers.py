"""Shared helpers for the Skolengo tests (anonymised fixtures, fake tokens)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from custom_components.skolengo.api import School, Tokens

FIXTURES = Path(__file__).parent / "fixtures"

WELL_KNOWN = "https://sso.example.test/oidc/.well-known"
AUTHORIZE = "https://sso.example.test/oidc/authorize"
TOKEN = "https://sso.example.test/oidc/token"
API = "https://api.skolengo.com/api/v1/bff-sko-app"

SCHOOL = School(
    id="SKO-E-college",
    name="Collège Exemple",
    city="VILLE",
    ems_code="entexample",
    oidc_well_known_url=WELL_KNOWN,
)


def fixture_text(name: str) -> str:
    """Content of a fixture file."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> Any:
    """Parsed JSON fixture."""
    return json.loads(fixture_text(name))


def id_token(sub: str = "RSKO-P-parent-1") -> str:
    """An unsigned JWT carrying only the ``sub`` claim (the client never checks signatures)."""

    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part({'sub': sub})}.sig"


def token_response(access: str = "access-1", refresh: str = "refresh-1", with_id_token: bool = True) -> dict:
    """A token endpoint answer."""
    data = {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": 86400}
    if with_id_token:
        data["id_token"] = id_token()
    return data


def make_tokens(access: str = "access-0", refresh: str = "refresh-0", expires_in: float = 3600) -> Tokens:
    """Tokens as stored in a config entry."""
    return Tokens(
        access_token=access,
        refresh_token=refresh,
        id_token=id_token(),
        expires_at=time.time() + expires_in,
        token_endpoint=TOKEN,
    )
