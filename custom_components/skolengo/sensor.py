"""Sensors of the Skolengo integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SkolengoConfigEntry
from .api.const import SERVICE_HOMEWORK, SERVICE_LESSONS
from .entity import SkolengoStudentEntity, SkolengoTimedEntity
from .homework import homework_attributes
from .timetable import current_day, lesson_attributes, lesson_subject, next_lesson

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
        if SERVICE_LESSONS in data.services:
            entities.append(SkolengoTimetableSensor(coordinator, data.student))
            entities.append(SkolengoNextLessonSensor(coordinator, data.student))
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


class SkolengoTimetableSensor(SkolengoTimedEntity, SensorEntity):
    """Lessons of the current school day, with the whole window for the card."""

    def __init__(self, coordinator, student) -> None:
        """Timetable of one student."""
        super().__init__(coordinator, student, SERVICE_LESSONS, "timetable")

    @property
    def native_value(self) -> int | None:
        """Lessons (not cancelled) of today, or of the next day with lessons once today is over."""
        lessons = self.lessons
        if lessons is None:
            return None
        day = current_day(lessons, dt_util.now())
        return sum(1 for le in lessons if not le.canceled and dt_util.as_local(le.start).date() == day)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The lessons of the window, for the timetable card."""
        now = dt_util.now()
        lessons = self.lessons or []
        day = current_day(lessons, now)
        data = self.student_data
        return {
            "student": data.student.full_name if data else None,
            "day": day.isoformat() if day else None,
            "lessons": [lesson_attributes(le, now) for le in lessons],
            "last_error": data.errors.get(SERVICE_LESSONS) if data else None,
        }


class SkolengoNextLessonSensor(SkolengoTimedEntity, SensorEntity):
    """Start of the next lesson (not cancelled), for automations."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, student) -> None:
        """Next lesson of one student."""
        super().__init__(coordinator, student, SERVICE_LESSONS, "next_lesson")

    @property
    def native_value(self) -> datetime | None:
        """When the next lesson starts."""
        lesson = next_lesson(self.lessons or [], dt_util.utcnow())
        return lesson.start if lesson else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Subject, room, teacher and end of the next lesson."""
        lesson = next_lesson(self.lessons or [], dt_util.utcnow())
        if lesson is None:
            return {}
        return {
            "lesson": lesson_subject(lesson),
            "classroom": lesson.location,
            "teacher_name": ", ".join(lesson.teachers) or None,
            "end_at": dt_util.as_local(lesson.end).isoformat(),
        }
