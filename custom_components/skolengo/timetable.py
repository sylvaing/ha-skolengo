"""Timetable helpers shared by the sensors, the calendar and the card attributes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .api import Lesson

# Lessons starting before this local hour are "morning" (card: lunch break, half days).
AFTERNOON_HOUR = 12


def lesson_subject(lesson: Lesson) -> str:
    """The subject label, or the lesson title."""
    return (lesson.subject.label if lesson.subject and lesson.subject.label else lesson.title) or "?"


def lesson_attributes(lesson: Lesson, now: datetime) -> dict[str, Any]:
    """What the timetable card shows for one lesson (local times)."""
    start, end = dt_util.as_local(lesson.start), dt_util.as_local(lesson.end)
    if lesson.canceled:
        status = "canceled"
    elif end <= now:
        status = "ended"
    elif start <= now:
        status = "ongoing"
    else:
        status = "upcoming"
    return {
        "id": lesson.id,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "lesson": lesson_subject(lesson),
        "classroom": lesson.location,
        "teacher_name": ", ".join(lesson.teachers) or None,
        "canceled": lesson.canceled,
        "status": status,
        "homework_due": lesson.homework_due,
        "background_color": lesson.subject.color if lesson.subject else None,
        "is_morning": start.hour < AFTERNOON_HOUR,
        "is_afternoon": start.hour >= AFTERNOON_HOUR,
    }


def current_day(lessons: list[Lesson], now: datetime) -> date | None:
    """Today while a lesson of today is not over, else the next day with lessons."""
    for lesson in lessons:
        if dt_util.as_local(lesson.end) > now and not lesson.canceled:
            return dt_util.as_local(lesson.start).date()
    return None


def next_lesson(lessons: list[Lesson], now: datetime) -> Lesson | None:
    """The next lesson (not cancelled) that has not started yet."""
    return next((le for le in lessons if le.start > now and not le.canceled), None)


def next_change(lessons: list[Lesson], now: datetime) -> datetime | None:
    """The next lesson start or end: when the time-based states change."""
    times = [t for le in lessons for t in (le.start, le.end) if t > now]
    return min(times, default=None)
