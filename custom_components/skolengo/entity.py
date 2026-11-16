"""Base entities and devices of the Skolengo integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import Account, Lesson, Student
from .api.const import SERVICE_HOMEWORK
from .const import DOMAIN
from .coordinator import SkolengoCoordinator, StudentData
from .timetable import next_change

MANUFACTURER = "Kosmos (Skolengo)"


def student_device_info(student: Student) -> DeviceInfo:
    """One device per student."""
    return DeviceInfo(
        identifiers={(DOMAIN, student.id)},
        name=student.full_name,
        manufacturer=MANUFACTURER,
        model=student.school.name if student.school and student.school.name else "Skolengo",
        model_id=student.class_name,
        entry_type=DeviceEntryType.SERVICE,
    )


def account_device_info(account: Account) -> DeviceInfo:
    """The account's own device (messaging)."""
    return DeviceInfo(
        identifiers={(DOMAIN, account.id)},
        name=f"{account.first_name} {account.last_name}".strip() or "Skolengo",
        manufacturer=MANUFACTURER,
        model="Skolengo account",
        entry_type=DeviceEntryType.SERVICE,
    )


class SkolengoStudentEntity(CoordinatorEntity[SkolengoCoordinator]):
    """An entity about one student and one service.

    Available as soon as the service has been fetched once; it then keeps the last known data while
    the service (or the whole update) fails, so one failing service never hides the others.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SkolengoCoordinator, student: Student, service: str, key: str) -> None:
        """Bind to the student's device."""
        super().__init__(coordinator)
        self._student_id = student.id
        self._service = service
        self._attr_unique_id = f"{student.id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = student_device_info(student)

    @property
    def student_data(self) -> StudentData | None:
        """Current data of the student."""
        return self.coordinator.data.students.get(self._student_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Available once the service has data, even if its last update failed."""
        data = self.student_data
        if data is None or self._service not in data.services:
            return False
        value = data.homework if self._service == SERVICE_HOMEWORK else data.lessons
        return value is not None


class SkolengoTimedEntity(SkolengoStudentEntity):
    """A timetable entity whose state also changes when a lesson starts or ends."""

    _unsub_timer: CALLBACK_TYPE | None = None

    @property
    def lessons(self) -> list[Lesson] | None:
        """The lessons of the window."""
        data = self.student_data
        return data.lessons if data else None

    async def async_added_to_hass(self) -> None:
        """Also plan the next time-based change."""
        await super().async_added_to_hass()
        self._schedule()
        self.async_on_remove(self._cancel_timer)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule()
        super()._handle_coordinator_update()

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _schedule(self) -> None:
        self._cancel_timer()
        when = next_change(self.lessons or [], dt_util.utcnow())
        if when is not None:
            self._unsub_timer = async_track_point_in_utc_time(self.hass, self._time_changed, when)

    @callback
    def _time_changed(self, _now: datetime) -> None:
        self._unsub_timer = None
        self._schedule()
        self.async_write_ha_state()


class SkolengoAccountEntity(CoordinatorEntity[SkolengoCoordinator]):
    """An entity about the account itself (messaging)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SkolengoCoordinator, key: str) -> None:
        """Bind to the account's device."""
        super().__init__(coordinator)
        account = coordinator.data.account
        self._attr_unique_id = f"{account.id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = account_device_info(account)

    @property
    def available(self) -> bool:
        """Available once the inbox has been read, even if its last update failed."""
        return self.coordinator.data is not None and self.coordinator.data.mailbox is not None
