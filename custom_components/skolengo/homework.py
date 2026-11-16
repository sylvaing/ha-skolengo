"""Homework helpers shared by the sensor, the to-do list and the card attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .api import Homework


def homework_summary(hw: Homework) -> str:
    """``Subject: title`` (or just one of them)."""
    subject = hw.subject.label if hw.subject else ""
    title = hw.title or hw.text.split("\n", 1)[0]
    return f"{subject}: {title}" if subject and title else (subject or title or "?")


def homework_attributes(hw: Homework) -> dict[str, Any]:
    """What the homework card shows for one item (plain text, no HTML)."""
    due = dt_util.as_local(hw.due)
    return {
        "id": hw.id,
        "date": due.date().isoformat(),
        "due": due.isoformat(),
        "subject": hw.subject.label if hw.subject else None,
        "title": hw.title,
        "description": hw.text,
        "teacher": hw.teacher,
        "done": hw.done,
        "background_color": hw.subject.color if hw.subject else None,
    }
