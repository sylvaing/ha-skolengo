"""Tests for the authenticated Skolengo API client (anonymised fixtures)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.skolengo.api import (
    SkolengoApiError,
    SkolengoAuthError,
    SkolengoClient,
    SkolengoConnectionError,
    SkolengoForbiddenError,
    Tokens,
)
from custom_components.skolengo.api.html import html_to_text

from .helpers import API, TOKEN, fixture_json, make_tokens, token_response

START, END = date(2026, 11, 15), date(2026, 11, 30)


def make_client(aioclient_mock: AiohttpClientMocker, tokens: Tokens | None = None, saved: list | None = None):
    """A client on the mocked session; refreshed tokens are appended to ``saved``."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    return session, SkolengoClient(
        session, tokens or make_tokens(), "entexample", (saved.append if saved is not None else None)
    )


def api_headers(aioclient_mock: AiohttpClientMocker, index: int = -1) -> dict:
    """Headers of a recorded API call."""
    return aioclient_mock.mock_calls[index][3]


async def test_account_parent(aioclient_mock: AiohttpClientMocker) -> None:
    """Children, their schools and the per-school services of a parent account."""
    aioclient_mock.get(f"{API}/users-info/RSKO-P-parent-1", json=fixture_json("users_info_parent.json"))
    session, client = make_client(aioclient_mock)

    account = await client.async_get_account()

    assert account.is_parent
    assert [(s.first_name, s.class_name, s.school.id, s.school.name) for s in account.students] == [
        ("Lou", "4A", "SKO-E-college", "Collège Exemple"),
        ("Sam", "2B", "SKO-E-lycee", "Lycée Exemple"),
    ]
    assert account.has_service("SKO-E-college", "TAF")
    assert not account.has_service("SKO-E-lycee", "TAF")
    assert account.schools_with_service("MSG") == ["SKO-E-college"]
    headers = api_headers(aioclient_mock)
    assert headers["Authorization"] == "Bearer access-0"
    assert headers["X-Skolengo-Ems-Code"] == "entexample"
    assert "X-Skolengo-School-Id" not in headers
    await session.close()


async def test_account_student(aioclient_mock: AiohttpClientMocker) -> None:
    """A student account is its own (only) student."""
    aioclient_mock.get(
        f"{API}/users-info/RSKO-P-parent-1",
        json={
            "data": {
                "id": "RSKO-P-parent-1",
                "type": "studentUserInfo",
                "attributes": {
                    "firstName": "Lou",
                    "lastName": "MARTIN",
                    "className": "4A",
                    "permissions": [],
                },
                "relationships": {"school": {"data": {"id": "SKO-E-college", "type": "school"}}},
            },
            "included": [
                {"id": "SKO-E-college", "type": "school", "attributes": {"name": "Collège Exemple"}}
            ],
        },
    )
    session, client = make_client(aioclient_mock)

    account = await client.async_get_account()

    assert not account.is_parent
    assert [(s.id, s.full_name, s.school.id) for s in account.students] == [
        ("RSKO-P-parent-1", "Lou MARTIN", "SKO-E-college")
    ]
    await session.close()


async def test_homework(aioclient_mock: AiohttpClientMocker) -> None:
    """Sorted by due date, text built from title + HTML, the sparse fieldsets are sent."""
    aioclient_mock.get(f"{API}/homework-assignments", json=fixture_json("homework.json"))
    session, client = make_client(aioclient_mock)

    items = await client.async_get_homework("ESKO-P-child-1", "SKO-E-college", START, END)

    assert [h.id for h in items] == ["hw-1", "hw-2"]
    first, second = items
    assert first.text == "p 41 n°5"  # empty HTML document ignored
    assert first.done and first.subject.label == "MATHEMATIQUES" and first.subject.color == "#185abc"
    assert first.teacher == "Mme ANNE DURAND"
    assert first.due == datetime(2026, 11, 16, 8, 5, tzinfo=UTC)
    assert second.text == "Exercices\nFinir l'exercice 3\n• page 12"
    assert not second.done

    _, url, _, headers = aioclient_mock.mock_calls[-1]
    assert url.query["fields[homework]"] == "title,done,dueDateTime,html"
    assert url.query["filter[dueDate][GE]"] == "2026-11-15"
    assert url.query["filter[student.id]"] == "ESKO-P-child-1"
    assert headers["X-Skolengo-School-Id"] == "SKO-E-college"
    await session.close()


async def test_set_homework_done(aioclient_mock: AiohttpClientMocker) -> None:
    """PATCH with the JSON:API body."""
    aioclient_mock.patch(
        f"{API}/homework-assignments/hw-2", json={"data": {"id": "hw-2", "type": "homework"}}
    )
    session, client = make_client(aioclient_mock)

    await client.async_set_homework_done("ESKO-P-child-1", "SKO-E-college", "hw-2", True)

    method, url, body, _ = aioclient_mock.mock_calls[-1]
    assert method.upper() == "PATCH"
    assert url.query["filter[student.id]"] == "ESKO-P-child-1"
    assert body == {"data": {"type": "homework", "id": "hw-2", "attributes": {"done": True}}}
    await session.close()


async def test_lessons(aioclient_mock: AiohttpClientMocker) -> None:
    """Lessons of every day, resolved and sorted."""
    aioclient_mock.get(f"{API}/agendas", json=fixture_json("agendas.json"))
    session, client = make_client(aioclient_mock)

    lessons = await client.async_get_lessons("ESKO-P-child-1", "SKO-E-college", START, END)

    assert [(le.id, le.title, le.location, le.canceled, le.teachers, le.homework_due) for le in lessons] == [
        ("l-1", "HISTOIRE-GEOGRAPHIE", "B21", False, ["M. PAUL ROUX"], False),
        ("l-2", "MATHEMATIQUES", "B34", True, ["Mme ANNE DURAND"], True),
    ]
    assert lessons[1].subject.color == "#185abc"
    await session.close()


async def test_messaging(aioclient_mock: AiohttpClientMocker) -> None:
    """Folders sorted by position; conversations with sender (through ``person``) and preview."""
    aioclient_mock.get(f"{API}/users-mail-settings/RSKO-P-parent-1", json=fixture_json("mail_settings.json"))
    aioclient_mock.get(f"{API}/communications", json=fixture_json("communications.json"))
    session, client = make_client(aioclient_mock)

    folders = await client.async_get_mail_folders("SKO-E-college")
    page = await client.async_get_communications("SKO-E-college", "f-inbox", 10)

    assert [(f.id, f.type) for f in folders] == [("f-inbox", "INBOX"), ("f-sent", "SENT")]
    assert page.total == 19
    first, second = page.communications
    assert (first.subject, first.read, first.participations, first.sender) == (
        "Sortie scolaire",
        False,
        2,
        "Mme ANNE DURAND",
    )
    assert first.preview == "Bonjour,\ndépart à 8h"
    assert first.last_date == datetime(2026, 11, 11, 20, 11, 51, tzinfo=UTC)
    assert second.sender is None and second.preview is None
    await session.close()


async def test_refresh_on_401_persists_rotated_tokens(aioclient_mock: AiohttpClientMocker) -> None:
    """A 401 triggers one refresh, the call is retried, the new tokens are handed back."""
    calls = 0

    async def users_info(method, url, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse("get", url, status=401)
        return AiohttpClientMockResponse("get", url, json=fixture_json("users_info_parent.json"))

    aioclient_mock.get(f"{API}/users-info/RSKO-P-parent-1", side_effect=users_info)
    aioclient_mock.post(TOKEN, json=token_response("access-2", "refresh-2"))
    saved: list[Tokens] = []
    session, client = make_client(aioclient_mock, saved=saved)

    await client.async_get_account()

    assert calls == 2
    assert [t.refresh_token for t in saved] == ["refresh-2"]
    assert client.tokens.access_token == "access-2"
    assert api_headers(aioclient_mock)["Authorization"] == "Bearer access-2"
    await session.close()


async def test_proactive_refresh_once_for_concurrent_calls(aioclient_mock: AiohttpClientMocker) -> None:
    """Expired tokens are refreshed before calling, once even for parallel requests."""
    aioclient_mock.get(f"{API}/agendas", json=fixture_json("agendas.json"))
    aioclient_mock.get(f"{API}/homework-assignments", json=fixture_json("homework.json"))
    aioclient_mock.post(TOKEN, json=token_response("access-2", "refresh-2"))
    saved: list[Tokens] = []
    session, client = make_client(aioclient_mock, make_tokens(expires_in=-10), saved)

    await asyncio.gather(
        client.async_get_lessons("s", "SKO-E-college", START, END),
        client.async_get_homework("s", "SKO-E-college", START, END),
    )

    assert len(saved) == 1
    assert sum(1 for m, url, _, _ in aioclient_mock.mock_calls if str(url) == TOKEN) == 1
    await session.close()


async def test_refresh_refused_raises_auth_error(aioclient_mock: AiohttpClientMocker) -> None:
    """A dead refresh token surfaces as SkolengoAuthError (the integration starts a reauth)."""
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    session, client = make_client(aioclient_mock, make_tokens(expires_in=-10))

    with pytest.raises(SkolengoAuthError):
        await client.async_get_account()
    await session.close()


async def test_error_mapping(aioclient_mock: AiohttpClientMocker) -> None:
    """403 is a forbidden service; other errors keep their status and JSON:API code."""
    aioclient_mock.get(
        f"{API}/homework-assignments",
        status=403,
        json={"errors": [{"status": "403", "title": "FORBIDDEN", "detail": "Access is forbidden"}]},
    )
    aioclient_mock.get(
        f"{API}/agendas",
        status=500,
        json={"errors": [{"code": "PRONOTE_RESOURCES_NOT_READY", "detail": "x"}]},
    )
    session, client = make_client(aioclient_mock)

    with pytest.raises(SkolengoForbiddenError):
        await client.async_get_homework("s", "SKO-E-lycee", START, END)
    with pytest.raises(SkolengoApiError) as err:
        await client.async_get_lessons("s", "SKO-E-lycee", START, END)
    assert (err.value.status, err.value.code) == (500, "PRONOTE_RESOURCES_NOT_READY")
    await session.close()


def test_html_to_text() -> None:
    """Paragraphs, line breaks, lists and entities; scripts dropped."""
    assert html_to_text(None) == ""
    assert html_to_text("<p>Un&nbsp;<b>deux</b></p><p></p><p>trois<br/>quatre</p><script>x()</script>") == (
        "Un deux\n\ntrois\nquatre"
    )


async def test_connection_error_and_non_json_error(aioclient_mock: AiohttpClientMocker) -> None:
    """Network failures and error pages without JSON are mapped to the client's exceptions."""
    aioclient_mock.get(f"{API}/homework-assignments", exc=aiohttp.ClientConnectionError("boom"))
    aioclient_mock.get(f"{API}/agendas", status=502, text="<html>Bad gateway</html>")
    session, client = make_client(aioclient_mock)

    with pytest.raises(SkolengoConnectionError):
        await client.async_get_homework("s", "SKO-E-lycee", START, END)
    with pytest.raises(SkolengoApiError) as err:
        await client.async_get_lessons("s", "SKO-E-lycee", START, END)
    assert (err.value.status, err.value.code) == (502, None)
    await session.close()
