"""Authenticated client of the Skolengo mobile API (the app's "BFF")."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import aiohttp

from .auth import async_refresh_tokens
from .const import API_BASE_URL, REQUEST_TIMEOUT, TOKEN_REFRESH_MARGIN
from .exceptions import (
    SkolengoApiError,
    SkolengoAuthError,
    SkolengoConnectionError,
    SkolengoForbiddenError,
)
from .html import html_to_text
from .jsonapi import Document, attrs
from .models import (
    Account,
    Communication,
    CommunicationPage,
    Homework,
    Lesson,
    MailFolder,
    Permission,
    SchoolRef,
    Student,
    Subject,
    Tokens,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

TokensCallback = Callable[[Tokens], Awaitable[None] | None]


class SkolengoClient:
    """Reads (and, for homework, updates) the data of a signed-in account.

    ``on_tokens_refreshed`` is called after every refresh with the new tokens. The refresh token
    rotates: the caller **must** persist them, or the session is lost at the next restart.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens,
        ems_code: str,
        on_tokens_refreshed: TokensCallback | None = None,
    ) -> None:
        """Keep the session, the tokens and the ENT code (``X-Skolengo-Ems-Code``)."""
        self._session = session
        self._tokens = tokens
        self._ems_code = ems_code
        self._on_tokens_refreshed = on_tokens_refreshed
        self._refresh_lock = asyncio.Lock()

    @property
    def tokens(self) -> Tokens:
        """The current tokens."""
        return self._tokens

    @property
    def user_id(self) -> str | None:
        """The signed-in user id (``sub``)."""
        return self._tokens.subject

    # --- account -----------------------------------------------------------------------------------

    async def async_get_account(self) -> Account:
        """The account, its students (children of a parent account) and permissions per school."""
        user_id = self.user_id
        if not user_id:
            raise SkolengoAuthError("the id_token has no subject")
        doc = await self._get(
            f"/users-info/{user_id}",
            {"include": "students,students.school,school,schools,prioritySchool"},
        )
        user = doc.data[0]
        a = attrs(user)
        students = [self._student(doc, s) for s in doc.related(user, "students")]
        if not students and user.get("type") != "legalRepresentativeUserInfo":
            # A student account: the user is the student.
            students = [self._student(doc, user)]
        permissions = [
            Permission(
                school_id=p.get("schoolId", ""),
                service=p.get("service", ""),
                operations=frozenset(p.get("permittedOperations") or []),
            )
            for p in a.get("permissions") or []
        ]
        return Account(
            id=user["id"],
            type=user.get("type", ""),
            first_name=a.get("firstName", ""),
            last_name=a.get("lastName", ""),
            students=students,
            permissions=permissions,
        )

    @staticmethod
    def _student(doc: Document, res: dict[str, Any]) -> Student:
        a = attrs(res)
        school = doc.related_one(res, "school")
        return Student(
            id=res["id"],
            first_name=a.get("firstName", ""),
            last_name=a.get("lastName", ""),
            class_name=a.get("className"),
            school=SchoolRef(
                id=school["id"],
                name=attrs(school).get("name"),
                city=attrs(school).get("city"),
                timezone=attrs(school).get("timeZone"),
            )
            if school
            else None,
        )

    # --- homework ----------------------------------------------------------------------------------

    async def async_get_homework(
        self, student_id: str, school_id: str, start: date, end: date
    ) -> list[Homework]:
        """Homework due between ``start`` and ``end`` (inclusive), sorted by due date."""
        doc = await self._get(
            "/homework-assignments",
            {
                "filter[student.id]": student_id,
                "filter[dueDate][GE]": start.isoformat(),
                "filter[dueDate][LE]": end.isoformat(),
                "include": "subject,teacher,teacher.person",
                # The sparse fieldsets are required: without them the API answers 500.
                "fields[homework]": "title,done,dueDateTime,html",
                "fields[subject]": "label,color",
                "page[limit]": "100",
            },
            school_id=school_id,
        )
        items = []
        for res in doc.data:
            a = attrs(res)
            due = _parse_dt(a.get("dueDateTime"))
            if due is None:
                continue
            title = (a.get("title") or "").strip()
            body = html_to_text(a.get("html"))
            items.append(
                Homework(
                    id=res["id"],
                    title=title,
                    text=title if not body or body == title else (f"{title}\n{body}" if title else body),
                    due=due,
                    done=bool(a.get("done")),
                    subject=_subject(doc.related_one(res, "subject")),
                    teacher=_person_name(doc, doc.related_one(res, "teacher")),
                )
            )
        return sorted(items, key=lambda h: h.due)

    async def async_set_homework_done(
        self, student_id: str, school_id: str, homework_id: str, done: bool
    ) -> None:
        """Mark a homework as done or not done."""
        await self._request(
            "PATCH",
            f"/homework-assignments/{homework_id}",
            params={"filter[student.id]": student_id},
            json={"data": {"type": "homework", "id": homework_id, "attributes": {"done": done}}},
            school_id=school_id,
        )

    # --- timetable ---------------------------------------------------------------------------------

    async def async_get_lessons(
        self, student_id: str, school_id: str, start: date, end: date
    ) -> list[Lesson]:
        """Lessons between ``start`` and ``end`` (inclusive), sorted by start time."""
        doc = await self._get(
            "/agendas",
            {
                "filter[student.id]": student_id,
                "filter[date][GE]": start.isoformat(),
                "filter[date][LE]": end.isoformat(),
                "include": "lessons,lessons.subject,lessons.teachers,lessons.teachers.person",
            },
            school_id=school_id,
        )
        lessons = []
        seen: set[str] = set()
        for day in doc.data:
            for res in doc.related(day, "lessons"):
                a = attrs(res)
                lesson_start, lesson_end = _parse_dt(a.get("startDateTime")), _parse_dt(a.get("endDateTime"))
                if lesson_start is None or lesson_end is None or res["id"] in seen:
                    continue
                seen.add(res["id"])
                subject = _subject(doc.related_one(res, "subject"))
                lessons.append(
                    Lesson(
                        id=res["id"],
                        start=lesson_start,
                        end=lesson_end,
                        title=a.get("title") or (subject.label if subject else ""),
                        location=a.get("location"),
                        canceled=bool(a.get("canceled")),
                        subject=subject,
                        teachers=[
                            n for n in (_person_name(doc, t) for t in doc.related(res, "teachers")) if n
                        ],
                        homework_due=bool(a.get("anyHomeworkToDoForTheLesson")),
                    )
                )
        return sorted(lessons, key=lambda le: le.start)

    # --- messaging ---------------------------------------------------------------------------------

    async def async_get_mail_folders(self, school_id: str) -> list[MailFolder]:
        """Folders of the classic messaging (inbox, sent, trash, personal…)."""
        user_id = self.user_id
        doc = await self._get(
            f"/users-mail-settings/{user_id}", {"include": "folders,folders.parent"}, school_id=school_id
        )
        folders = [
            MailFolder(
                id=f["id"],
                name=attrs(f).get("name", ""),
                type=attrs(f).get("type", ""),
                position=int(attrs(f).get("position") or 0),
            )
            for f in doc.included
            if f.get("type") == "folder"
        ]
        return sorted(folders, key=lambda f: f.position)

    async def async_get_communications(
        self, school_id: str, folder_id: str, limit: int = 20
    ) -> CommunicationPage:
        """Latest conversations of a folder, most recent first, with the folder size."""
        doc = await self._get(
            "/communications",
            {
                "filter[folders.id]": folder_id,
                "include": "lastParticipation,lastParticipation.sender,lastParticipation.sender.person",
                "page[limit]": str(limit),
            },
            school_id=school_id,
        )
        items = []
        for res in doc.data:
            a = attrs(res)
            last = doc.related_one(res, "lastParticipation")
            la = attrs(last)
            # contentWithoutHtml is often null: fall back to the HTML content.
            preview = (la.get("contentWithoutHtml") or html_to_text(la.get("content"))).strip() or None
            items.append(
                Communication(
                    id=res["id"],
                    subject=(a.get("subject") or "").strip(),
                    read=bool(a.get("read")),
                    participations=int(a.get("participationsNumber") or 0),
                    last_date=_parse_dt(la.get("dateTime")),
                    sender=_person_name(doc, doc.related_one(last, "sender")) if last else None,
                    preview=preview[:300] if preview else None,
                )
            )
        total = doc.meta.get("totalResourceCount")
        return CommunicationPage(communications=items, total=int(total) if total is not None else None)

    # --- transport ---------------------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str], school_id: str | None = None) -> Document:
        return Document(await self._request("GET", path, params=params, school_id=school_id) or {})

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        school_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self._tokens.expires_within(TOKEN_REFRESH_MARGIN):
            await self._async_refresh(self._tokens)
        for attempt in (1, 2):
            used = self._tokens
            headers = {
                "Authorization": f"Bearer {used.access_token}",
                "Accept": "application/json",
                "X-Skolengo-Date-Format": "utc",
                # Required by every authenticated call (users-info answers 500 without it).
                "X-Skolengo-Ems-Code": self._ems_code,
            }
            if school_id:
                headers["X-Skolengo-School-Id"] = school_id
            try:
                async with self._session.request(
                    method,
                    f"{API_BASE_URL}{path}",
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        await self._async_refresh(used)
                        continue
                    if resp.status == 401:
                        raise SkolengoAuthError("the API refused the refreshed access token")
                    if resp.status >= 400:
                        raise _api_error(resp.status, await _safe_json(resp))
                    if resp.status == 204:
                        return None
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SkolengoConnectionError(f"cannot reach the Skolengo API: {err}") from err
        raise SkolengoAuthError("unreachable")  # pragma: no cover

    async def _async_refresh(self, used: Tokens) -> None:
        """Refresh once even when several requests notice the expiry at the same time."""
        async with self._refresh_lock:
            if self._tokens is not used:
                return  # another request already refreshed
            _LOGGER.debug("Refreshing the Skolengo access token")
            self._tokens = await async_refresh_tokens(self._session, used)
            if self._on_tokens_refreshed is not None:
                result = self._on_tokens_refreshed(self._tokens)
                if result is not None:
                    await result


def _api_error(status: int, body: dict[str, Any] | None) -> SkolengoApiError:
    code = message = None
    errors = (body or {}).get("errors") or []
    if errors:
        first = errors[0]
        code = first.get("code") or first.get("title")
        message = first.get("detail")
        if message and len(message) > 200:
            message = message[:200] + "…"
    if status == 403:
        return SkolengoForbiddenError(status, code, message)
    return SkolengoApiError(status, code, message)


async def _safe_json(resp: aiohttp.ClientResponse) -> dict[str, Any] | None:
    try:
        data = await resp.json(content_type=None)
    except ValueError, aiohttp.ClientError:
        return None
    return data if isinstance(data, dict) else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _subject(res: dict[str, Any] | None) -> Subject | None:
    if not res:
        return None
    a = attrs(res)
    return Subject(id=res["id"], label=(a.get("label") or "").strip(), color=a.get("color"))


def _person_name(doc: Document, res: dict[str, Any] | None) -> str | None:
    """``Mme Claire DUPONT``-like name of a teacher, person or sender (following ``person`` if needed)."""
    if not res:
        return None
    a = attrs(res)
    if not a.get("lastName") and not a.get("firstName"):
        person = doc.related_one(res, "person")
        if person is not None and person is not res and attrs(person):
            return _person_name(doc, person)
        return a.get("label") or a.get("name") or None
    parts = [a.get("title"), a.get("firstName"), a.get("lastName")]
    return " ".join(p.strip() for p in parts if p and p.strip()) or None
