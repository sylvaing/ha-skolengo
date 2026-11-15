"""Data models returned by the Skolengo API client."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class School:
    """A school, as returned by the school search."""

    id: str
    name: str
    city: str | None
    ems_code: str
    oidc_well_known_url: str
    address: str | None = None


@dataclass(frozen=True, slots=True)
class OidcConfig:
    """The endpoints of an ENT's OpenID Connect provider."""

    authorization_endpoint: str
    token_endpoint: str


@dataclass(frozen=True, slots=True)
class IdentityProvider:
    """One sign-in choice offered by the ENT (e.g. EduConnect of an académie)."""

    id: str
    label: str
    category: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """An OIDC authorization request, with the PKCE verifier and state to check the answer."""

    url: str
    code_verifier: str
    state: str


@dataclass(slots=True)
class Tokens:
    """An OIDC token set. The refresh token rotates: always keep the latest one."""

    access_token: str
    refresh_token: str
    id_token: str
    expires_at: float
    token_endpoint: str

    @classmethod
    def from_token_response(
        cls, data: dict[str, Any], token_endpoint: str, previous: Tokens | None = None
    ) -> Tokens:
        """Build from a token endpoint answer (a refresh answer may omit the id_token)."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or (previous.refresh_token if previous else ""),
            id_token=data.get("id_token") or (previous.id_token if previous else ""),
            expires_at=time.time() + float(data.get("expires_in", 3600)),
            token_endpoint=token_endpoint,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        """Restore from storage."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            id_token=data.get("id_token", ""),
            expires_at=float(data.get("expires_at", 0)),
            token_endpoint=data["token_endpoint"],
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "expires_at": self.expires_at,
            "token_endpoint": self.token_endpoint,
        }

    @property
    def subject(self) -> str | None:
        """The user id (`sub` claim of the id_token)."""
        try:
            payload = self.id_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))["sub"]
        except IndexError, KeyError, ValueError:
            return None

    def expires_within(self, seconds: float) -> bool:
        """Whether the access token expires in less than `seconds`."""
        return self.expires_at - time.time() < seconds


@dataclass(frozen=True, slots=True)
class SchoolRef:
    """A school as referenced from the user info."""

    id: str
    name: str | None
    city: str | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class Student:
    """A student visible from the account (a child of a parent account, or the student themself)."""

    id: str
    first_name: str
    last_name: str
    class_name: str | None
    school: SchoolRef | None

    @property
    def full_name(self) -> str:
        """First and last name."""
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True, slots=True)
class Permission:
    """A service granted to the account in one school, with its allowed operations."""

    school_id: str
    service: str
    operations: frozenset[str]


@dataclass(frozen=True, slots=True)
class Account:
    """The signed-in account."""

    id: str
    type: str
    first_name: str
    last_name: str
    students: list[Student]
    permissions: list[Permission]

    @property
    def is_parent(self) -> bool:
        """Whether this is a legal representative (parent) account."""
        return self.type == "legalRepresentativeUserInfo"

    def has_service(self, school_id: str, service: str) -> bool:
        """Whether the account may use `service` in the given school."""
        return any(p.school_id == school_id and p.service == service for p in self.permissions)

    def schools_with_service(self, service: str) -> list[str]:
        """Ids of the schools that grant `service`."""
        return [p.school_id for p in self.permissions if p.service == service]


@dataclass(frozen=True, slots=True)
class Subject:
    """A school subject."""

    id: str
    label: str
    color: str | None


@dataclass(frozen=True, slots=True)
class Homework:
    """A homework assignment."""

    id: str
    title: str
    text: str
    due: datetime
    done: bool
    subject: Subject | None
    teacher: str | None


@dataclass(frozen=True, slots=True)
class Lesson:
    """A lesson of the timetable."""

    id: str
    start: datetime
    end: datetime
    title: str
    location: str | None
    canceled: bool
    subject: Subject | None
    teachers: list[str] = field(default_factory=list)
    homework_due: bool = False


@dataclass(frozen=True, slots=True)
class MailFolder:
    """A folder of the classic messaging."""

    id: str
    name: str
    type: str
    position: int


@dataclass(frozen=True, slots=True)
class Communication:
    """A conversation (thread) of the classic messaging."""

    id: str
    subject: str
    read: bool
    participations: int
    last_date: datetime | None
    sender: str | None
    preview: str | None


@dataclass(frozen=True, slots=True)
class CommunicationPage:
    """A page of conversations and the folder size."""

    communications: list[Communication]
    total: int | None
