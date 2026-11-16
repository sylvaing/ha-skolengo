"""Tests for the timetable sensors and calendar."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import make_entry, mock_api

TIMETABLE = "sensor.lou_martin_timetable"
NEXT = "sensor.lou_martin_next_lesson"
CALENDAR = "calendar.lou_martin_timetable"
# l-1: 08:05-09:05 Paris; l-2 (cancelled): 09:05-10:00 Paris, on 2026-11-16
MORNING = datetime.fromisoformat("2026-11-16T06:00:00+00:00")


@pytest.fixture
async def setup(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory):
    """The entry set up at 07:00 Paris time."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(MORNING)
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _move(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str) -> None:
    freezer.move_to(datetime.fromisoformat(when))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("setup")
async def test_timetable_sensor(hass: HomeAssistant) -> None:
    """Lessons of the day (cancelled ones not counted), in local time, for the card."""
    state = hass.states.get(TIMETABLE)
    assert state.state == "1"
    assert state.attributes["day"] == "2026-11-16"
    first, second = state.attributes["lessons"]
    assert first == {
        "id": "l-1",
        "start_at": "2026-11-16T08:05:00+01:00",
        "end_at": "2026-11-16T09:05:00+01:00",
        "start_time": "08:05",
        "end_time": "09:05",
        "lesson": "HISTOIRE-GEOGRAPHIE",
        "classroom": "B21",
        "teacher_name": "M. PAUL ROUX",
        "canceled": False,
        "status": "upcoming",
        "homework_due": False,
        "background_color": "#ffed00",
        "is_morning": True,
        "is_afternoon": False,
    }
    assert (second["status"], second["homework_due"]) == ("canceled", True)


@pytest.mark.usefixtures("setup")
async def test_states_follow_the_clock(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Without any API update, states change when a lesson starts and ends."""
    state = hass.states.get(NEXT)
    assert state.state == "2026-11-16T07:05:00+00:00"
    assert state.attributes["lesson"] == "HISTOIRE-GEOGRAPHIE"
    assert state.attributes["classroom"] == "B21"

    await _move(hass, freezer, "2026-11-16T07:06:00+00:00")
    assert hass.states.get(NEXT).state == "unknown"  # the only later lesson is cancelled
    assert hass.states.get(TIMETABLE).attributes["lessons"][0]["status"] == "ongoing"
    assert hass.states.get(CALENDAR).state == "on"

    await _move(hass, freezer, "2026-11-16T08:06:00+00:00")
    assert hass.states.get(TIMETABLE).attributes["lessons"][0]["status"] == "ended"
    assert hass.states.get(TIMETABLE).state == "0"
    assert hass.states.get(CALENDAR).state == "off"


@pytest.mark.usefixtures("setup")
async def test_calendar(hass: HomeAssistant) -> None:
    """Every lesson is an event; cancelled ones are marked."""
    state = hass.states.get(CALENDAR)
    assert state.state == "off"
    assert state.attributes["message"] == "HISTOIRE-GEOGRAPHIE"
    assert state.attributes["location"] == "B21"

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR, "start_date_time": MORNING, "duration": timedelta(days=1)},
        blocking=True,
        return_response=True,
    )
    events = result[CALENDAR]["events"]
    assert [e["summary"] for e in events] == ["HISTOIRE-GEOGRAPHIE", "MATHEMATIQUES (cancelled)"]
    assert events[0]["start"] == "2026-11-16T08:05:00+01:00"
    assert events[0]["description"] == "M. PAUL ROUX"
