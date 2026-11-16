"""Calendars of the Skolengo integration: the timetable of each student."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SkolengoConfigEntry
from .api import Lesson
from .api.const import SERVICE_LESSONS
from .entity import SkolengoTimedEntity
from .timetable import lesson_subject

PARALLEL_UPDATES = 0

CANCELED_LABEL = {"fr": "annulé"}


async def async_setup_entry(
    hass: HomeAssistant, entry: SkolengoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """One timetable calendar per student whose school grants the lessons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        SkolengoTimetableCalendar(coordinator, data.student)
        for data in coordinator.data.students.values()
        if SERVICE_LESSONS in data.services
    )


class SkolengoTimetableCalendar(SkolengoTimedEntity, CalendarEntity):
    """The lessons of the fetched window (see the "Timetable: days ahead" option)."""

    def __init__(self, coordinator, student) -> None:
        """Timetable of one student."""
        super().__init__(coordinator, student, SERVICE_LESSONS, "timetable")

    def _event(self, lesson: Lesson) -> CalendarEvent:
        summary = lesson_subject(lesson)
        if lesson.canceled:
            label = CANCELED_LABEL.get(self.hass.config.language.split("-")[0], "cancelled")
            summary = f"{summary} ({label})"
        return CalendarEvent(
            start=dt_util.as_local(lesson.start),
            end=dt_util.as_local(lesson.end),
            summary=summary,
            location=lesson.location,
            description=", ".join(lesson.teachers) or None,
            uid=lesson.id,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The current lesson, or the next one."""
        now = dt_util.utcnow()
        lesson = next((le for le in self.lessons or [] if le.end > now and not le.canceled), None)
        return self._event(lesson) if lesson else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Lessons overlapping the range (cancelled ones included, marked)."""
        return [self._event(le) for le in self.lessons or [] if le.end > start_date and le.start < end_date]
