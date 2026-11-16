"""Data update coordinator: one per config entry, fetching each student's granted services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Account,
    AppConfig,
    CommunicationPage,
    Homework,
    Lesson,
    MailFolder,
    SkolengoApiError,
    SkolengoAuthError,
    SkolengoClient,
    SkolengoConnectionError,
    SkolengoError,
    Student,
)
from .api.const import SERVICE_HOMEWORK, SERVICE_LESSONS, SERVICE_MESSAGES
from .const import (
    CONF_HOMEWORK_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_TIMETABLE_DAYS,
    DEFAULT_HOMEWORK_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMETABLE_DAYS,
    DOMAIN,
)

if TYPE_CHECKING:
    from . import SkolengoConfigEntry

_LOGGER = logging.getLogger(__name__)

# Services this integration reads, per student.
STUDENT_SERVICES = (SERVICE_HOMEWORK, SERVICE_LESSONS)

# At night nothing changes in the ENT: poll at most every NIGHT_INTERVAL.
NIGHT_START, NIGHT_END = 22, 6
NIGHT_INTERVAL = timedelta(hours=3)

# Retry hints of the app config are honoured, within these bounds.
MAX_RETRIES = 3
MAX_RETRY_DELAY = 5.0
# Server errors worth retrying. A plain 500 is often permanent (e.g. Pronote-proxied services).
TRANSIENT_STATUSES = {502, 503, 504}
TRANSIENT_CODES = {"PRONOTE_RESOURCES_NOT_READY"}

INBOX_PAGE_SIZE = 20


@dataclass(slots=True)
class StudentData:
    """What is known about one student. ``None`` = never fetched successfully."""

    student: Student
    services: frozenset[str]
    homework: list[Homework] | None = None
    lessons: list[Lesson] | None = None
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MailboxData:
    """Inbox of the account's classic messaging."""

    school_id: str
    folders: list[MailFolder]
    inbox: CommunicationPage

    @property
    def unread(self) -> int:
        """Unread conversations among the latest ones."""
        return sum(1 for c in self.inbox.communications if not c.read)


@dataclass(slots=True)
class SkolengoSnapshot:
    """Everything the entities read."""

    account: Account
    students: dict[str, StudentData]
    mailbox: MailboxData | None = None
    mailbox_error: str | None = None

    @property
    def has_messages(self) -> bool:
        """Whether the account may use the classic messaging."""
        return bool(self.account.schools_with_service(SERVICE_MESSAGES))


class SkolengoCoordinator(DataUpdateCoordinator[SkolengoSnapshot]):
    """Fetch the account, then each granted service, tolerating partial failures."""

    config_entry: SkolengoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SkolengoConfigEntry,
        client: SkolengoClient,
        app_config: AppConfig | None = None,
    ) -> None:
        """Read the options (interval, fetch windows) of the entry."""
        self._interval = timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._interval,
        )
        self.client = client
        self._homework_days = int(entry.options.get(CONF_HOMEWORK_DAYS, DEFAULT_HOMEWORK_DAYS))
        self._timetable_days = int(entry.options.get(CONF_TIMETABLE_DAYS, DEFAULT_TIMETABLE_DAYS))
        app_config = app_config or AppConfig()
        self._retries = min(app_config.max_retries, MAX_RETRIES)
        self._retry_delay = min(app_config.retry_delay, MAX_RETRY_DELAY)
        self._failing: set[str] = set()

    # --- update ------------------------------------------------------------------------------------

    async def _async_update_data(self) -> SkolengoSnapshot:
        previous = self.data
        try:
            account = await self._call(self.client.async_get_account)
        except SkolengoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SkolengoError as err:
            if previous is None:
                raise UpdateFailed(f"cannot read the Skolengo account: {err}") from err
            _LOGGER.debug("Account not refreshed, keeping the previous one: %s", err)
            account = previous.account

        today = dt_util.now().date()
        snapshot = SkolengoSnapshot(account=account, students={})
        attempted = succeeded = 0
        try:
            for student in account.students:
                school_id = student.school.id if student.school else None
                services = frozenset(
                    s for s in STUDENT_SERVICES if school_id and account.has_service(school_id, s)
                )
                old = previous.students.get(student.id) if previous else None
                data = StudentData(student=student, services=services)
                if old is not None:
                    data.homework, data.lessons = old.homework, old.lessons
                snapshot.students[student.id] = data
                if not school_id:
                    continue

                if SERVICE_HOMEWORK in services:
                    attempted += 1
                    result = await self._service(
                        f"{student.id}/homework",
                        data,
                        SERVICE_HOMEWORK,
                        lambda s=student, sid=school_id: self.client.async_get_homework(
                            s.id, sid, today, today + timedelta(days=self._homework_days)
                        ),
                    )
                    if result is not None:
                        data.homework, succeeded = result, succeeded + 1

                if SERVICE_LESSONS in services:
                    attempted += 1
                    result = await self._service(
                        f"{student.id}/lessons",
                        data,
                        SERVICE_LESSONS,
                        lambda s=student, sid=school_id: self.client.async_get_lessons(
                            s.id, sid, today, today + timedelta(days=self._timetable_days)
                        ),
                    )
                    if result is not None:
                        data.lessons, succeeded = result, succeeded + 1

            if snapshot.has_messages:
                attempted += 1
                snapshot.mailbox = previous.mailbox if previous else None
                mailbox = await self._mailbox(account, snapshot)
                if mailbox is not None:
                    snapshot.mailbox, succeeded = mailbox, succeeded + 1
        except SkolengoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        if attempted and not succeeded:
            errors = [e for d in snapshot.students.values() for e in d.errors.values()]
            if snapshot.mailbox_error:
                errors.append(snapshot.mailbox_error)
            raise UpdateFailed(f"every Skolengo service failed: {'; '.join(errors)}")

        self.update_interval = self._next_interval(dt_util.now())
        return snapshot

    async def _service[T](
        self,
        key: str,
        data: StudentData,
        service: str,
        fetch: Callable[[], Awaitable[T]],
    ) -> T | None:
        """Fetch one service; on failure record the error and keep the previous value."""
        try:
            result = await self._call(fetch)
        except SkolengoAuthError:
            raise
        except SkolengoError as err:
            data.errors[service] = str(err)
            self._log_failure(key, err)
            return None
        self._log_recovery(key)
        return result

    async def _mailbox(self, account: Account, snapshot: SkolengoSnapshot) -> MailboxData | None:
        school_id = account.schools_with_service(SERVICE_MESSAGES)[0]
        try:
            folders = await self._call(lambda: self.client.async_get_mail_folders(school_id))
            inbox = next((f for f in folders if f.type == "INBOX"), None)
            if inbox is None:
                raise SkolengoApiError(404, "NO_INBOX", "no inbox folder")
            page = await self._call(
                lambda: self.client.async_get_communications(school_id, inbox.id, INBOX_PAGE_SIZE)
            )
        except SkolengoAuthError:
            raise
        except SkolengoError as err:
            snapshot.mailbox_error = str(err)
            self._log_failure("mailbox", err)
            return None
        self._log_recovery("mailbox")
        return MailboxData(school_id=school_id, folders=folders, inbox=page)

    async def _call[T](self, fetch: Callable[[], Awaitable[T]]) -> T:
        """Call the API, retrying transient errors as the app config recommends."""
        for attempt in range(self._retries + 1):
            try:
                return await fetch()
            except (SkolengoConnectionError, SkolengoApiError) as err:
                if attempt >= self._retries or not _is_transient(err):
                    raise
                await asyncio.sleep(self._retry_delay * (attempt + 1))
        raise AssertionError("unreachable")  # pragma: no cover

    def _next_interval(self, now: datetime) -> timedelta:
        if now.hour >= NIGHT_START or now.hour < NIGHT_END:
            return max(self._interval, NIGHT_INTERVAL)
        return self._interval

    def _log_failure(self, key: str, err: SkolengoError) -> None:
        if key in self._failing:
            _LOGGER.debug("Skolengo %s still failing: %s", key, err)
        else:
            self._failing.add(key)
            _LOGGER.warning("Skolengo %s could not be updated, keeping the previous data: %s", key, err)

    def _log_recovery(self, key: str) -> None:
        if key in self._failing:
            self._failing.discard(key)
            _LOGGER.info("Skolengo %s is updating again", key)


def _is_transient(err: SkolengoError) -> bool:
    if isinstance(err, SkolengoConnectionError):
        return True
    return isinstance(err, SkolengoApiError) and (
        err.status in TRANSIENT_STATUSES or err.code in TRANSIENT_CODES
    )
