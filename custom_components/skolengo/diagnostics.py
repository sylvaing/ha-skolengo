"""Diagnostics of the Skolengo integration: structure and counts, never personal data."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import SkolengoConfigEntry
from .const import CONF_TOKENS, DOMAIN
from .coordinator import SkolengoSnapshot, StudentData

# Personal or secret values of the entry data.
TO_REDACT = {CONF_TOKENS, CONF_USERNAME, "access_token", "refresh_token", "id_token", "unique_id"}


def _student(index: int, data: StudentData) -> dict[str, Any]:
    """A student as counts and states, without names, ids, texts or dates of birth."""
    return {
        "student": f"student_{index}",
        "school": data.student.school.name if data.student.school else None,
        "class": data.student.class_name,
        "services": sorted(data.services),
        "homework": None
        if data.homework is None
        else {"count": len(data.homework), "done": sum(1 for h in data.homework if h.done)},
        "lessons": None
        if data.lessons is None
        else {"count": len(data.lessons), "canceled": sum(1 for le in data.lessons if le.canceled)},
        "errors": dict(data.errors),
    }


def _snapshot(snapshot: SkolengoSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    account = snapshot.account
    mailbox = snapshot.mailbox
    return {
        "account": {
            "type": account.type,
            "permissions": sorted(
                {(p.school_id[-6:], p.service, ",".join(sorted(p.operations))) for p in account.permissions}
            ),
        },
        "students": [_student(i, d) for i, d in enumerate(snapshot.students.values(), 1)],
        "mailbox": None
        if mailbox is None
        else {
            "folders": [f.type for f in mailbox.folders],
            "latest": len(mailbox.inbox.communications),
            "unread": mailbox.unread,
            "total": mailbox.inbox.total,
        },
        "mailbox_error": snapshot.mailbox_error,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SkolengoConfigEntry
) -> dict[str, Any]:
    """Entry settings (secrets removed) and what the last update returned."""
    coordinator = entry.runtime_data.coordinator
    tokens = entry.data.get(CONF_TOKENS) or {}
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "token_expires_at": tokens.get("expires_at"),
            "token_endpoint": tokens.get("token_endpoint"),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "data": _snapshot(coordinator.data),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: SkolengoConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """What is known about the student (or the account) of the device."""
    snapshot = entry.runtime_data.coordinator.data
    ids = {i for d, i in device.identifiers if d == DOMAIN}
    for index, data in enumerate(snapshot.students.values(), 1):
        if data.student.id in ids:
            return {"student": _student(index, data)}
    return {"account": (_snapshot(snapshot) or {}).get("mailbox")}
