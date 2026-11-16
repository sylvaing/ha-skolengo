"""Base entities and devices of the Skolengo integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Account, Student
from .api.const import SERVICE_HOMEWORK
from .const import DOMAIN
from .coordinator import SkolengoCoordinator, StudentData

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
