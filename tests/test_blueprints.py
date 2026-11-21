"""Run the notification blueprints in a real automation engine."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.device_automation import action as device_action
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import template
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "skolengo"
HOMEWORK = "sensor.lou_martin_homework"


@pytest.fixture(autouse=True)
async def stop_automations(hass: HomeAssistant):
    """Turn the automations off at the end, so their time triggers do not outlive the test."""
    yield
    if hass.services.has_service("automation", "turn_off"):
        await hass.services.async_call("automation", "turn_off", {"entity_id": "all"}, blocking=True)


@pytest.fixture
def phone(hass: HomeAssistant) -> str:
    """A phone of the mobile app, as the notification target."""
    entry = MockConfigEntry(domain="mobile_app")
    entry.add_to_hass(hass)
    return (
        dr.async_get(hass)
        .async_get_or_create(config_entry_id=entry.entry_id, identifiers={("mobile_app", "p")})
        .id
    )


@pytest.fixture
def notifications():
    """Notifications sent through the mobile app device action, rendered.

    The mobile app itself is not set up: its device action is replaced, the rest of the automation
    engine (triggers, variables, conditions, templates) runs for real.
    """
    sent: list[dict] = []

    async def validate(hass, config):
        assert config["domain"] == "mobile_app" and config["type"] == "notify"
        return config

    async def call(hass, config, variables, context):
        sent.append(
            {
                key: template.Template(str(config[key]), hass).async_render(variables)
                for key in ("title", "message")
            }
        )

    with (
        patch.object(device_action, "async_validate_action_config", validate),
        patch.object(device_action, "async_call_action_from_config", call),
    ):
        yield sent


async def _automation(hass: HomeAssistant, blueprint: str, inputs: dict) -> None:
    target = Path(hass.config.path("blueprints/automation/skolengo"))

    def copy() -> None:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(BLUEPRINTS / blueprint, target / blueprint)

    await hass.async_add_executor_job(copy)
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": [{"use_blueprint": {"path": f"skolengo/{blueprint}", "input": inputs}}]},
    )
    await hass.async_block_till_done()
    assert hass.states.get("automation.skolengo_notify_new_messages") or hass.states.async_entity_ids(
        "automation"
    )


async def test_new_message(hass: HomeAssistant, phone: str, notifications: list) -> None:
    """A notification per new message, with the preview cut; other entries filtered out."""
    extra = async_capture_events(hass, "extra_ran")
    await _automation(
        hass,
        "new_message.yaml",
        {
            "notify_device": phone,
            "config_entry": "entry-1",
            "preview_length": 10,
            "extra_actions": [{"event": "extra_ran", "event_data": {"s": "{{ subject }}"}}],
        },
    )
    data = {
        "config_entry_id": "entry-1",
        "id": "c-1",
        "subject": "Sortie",
        "sender": "Mme DURAND",
        "date": "2026-11-12T07:00:00+00:00",
        "preview": "Bonjour, départ à 8h devant le collège",
    }
    hass.bus.async_fire("skolengo_new_message", data)
    hass.bus.async_fire("skolengo_new_message", {**data, "config_entry_id": "other"})
    await hass.async_block_till_done()

    assert notifications == [{"title": "✉️ Sortie", "message": "Mme DURAND — Bonjour, d…"}]
    assert [e.data for e in extra] == [{"s": "Sortie"}]


def _homework(date: str, subject: str, done: bool) -> dict:
    return {
        "id": subject,
        "date": date,
        "subject": subject,
        "title": f"{subject} ex",
        "description": "",
        "done": done,
    }


@pytest.mark.parametrize(
    ("now", "language", "expected"),
    [
        # Thursday evening → Friday
        (
            "2026-11-19T18:59:30+01:00",
            "fr",
            ("📚 Lou MARTIN : 2 devoirs pour demain", "• MATHS : MATHS ex\n• SVT : SVT ex"),
        ),
        # Friday evening → Monday
        (
            "2026-11-20T18:59:30+01:00",
            "en",
            ("📚 Lou MARTIN: 1 homework for Monday", "• ANGLAIS : ANGLAIS ex"),
        ),
    ],
)
async def test_homework_reminder(
    hass: HomeAssistant,
    phone: str,
    notifications: list,
    freezer: FrozenDateTimeFactory,
    now,
    language,
    expected,
) -> None:
    """At the chosen time, the homework of the next school day not done yet."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime.fromisoformat(now))
    hass.states.async_set(
        HOMEWORK,
        "3",
        {
            "student": "Lou MARTIN",
            "homework": [
                _homework("2026-11-20", "MATHS", False),
                _homework("2026-11-20", "SVT", False),
                _homework("2026-11-20", "FRANCAIS", True),
                _homework("2026-11-23", "ANGLAIS", False),
            ],
        },
    )
    await _automation(
        hass,
        "homework_reminder.yaml",
        {
            "homework_entity": HOMEWORK,
            "notify_device": phone,
            "reminder_time": "19:00:00",
            "language": language,
        },
    )
    freezer.tick(60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert [(n["title"], n["message"]) for n in notifications] == [expected]


async def test_no_reminder_without_homework(
    hass: HomeAssistant, phone: str, notifications: list, freezer: FrozenDateTimeFactory
) -> None:
    """Nothing due (or everything done): no notification."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime.fromisoformat("2026-11-19T18:59:30+01:00"))
    hass.states.async_set(
        HOMEWORK, "0", {"student": "Lou", "homework": [_homework("2026-11-20", "MATHS", True)]}
    )
    await _automation(hass, "homework_reminder.yaml", {"homework_entity": HOMEWORK, "notify_device": phone})
    freezer.tick(60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert notifications == []
