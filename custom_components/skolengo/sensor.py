"""Sensors of the Skolengo integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkolengoConfigEntry
from .api.const import SERVICE_HOMEWORK
from .entity import SkolengoStudentEntity
from .homework import homework_attributes

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: SkolengoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """One set of sensors per student, for the services their school grants."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = []
    for data in coordinator.data.students.values():
        if SERVICE_HOMEWORK in data.services:
            entities.append(SkolengoHomeworkSensor(coordinator, data.student))
    async_add_entities(entities)


class SkolengoHomeworkSensor(SkolengoStudentEntity, SensorEntity):
    """Number of homework items not done yet, with the items for the card."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, student) -> None:
        """Homework of one student."""
        super().__init__(coordinator, student, SERVICE_HOMEWORK, "homework")

    @property
    def native_value(self) -> int | None:
        """Homework items not done in the window."""
        data = self.student_data
        if data is None or data.homework is None:
            return None
        return sum(1 for hw in data.homework if not hw.done)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The items, sorted by due date, for the homework card."""
        data = self.student_data
        homework = data.homework if data and data.homework else []
        return {
            "student": data.student.full_name if data else None,
            "homework": [homework_attributes(hw) for hw in homework],
            "last_error": data.errors.get(SERVICE_HOMEWORK) if data else None,
        }
