"""Tests for the unread messages sensor and the new message event."""

from __future__ import annotations

import copy

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skolengo.coordinator import EVENT_NEW_MESSAGE

from .common import make_entry, mock_api
from .helpers import API, fixture_json

SENSOR = "sensor.alex_martin_unread_messages"


async def test_unread_messages_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Unread count and the latest conversations, plain text."""
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == "1"
    assert state.attributes["total"] == 19
    first, second = state.attributes["messages"]
    assert first["subject"] == "Sortie scolaire"
    assert first["sender"] == "Mme ANNE DURAND"
    assert first["preview"] == "Bonjour,\ndépart à 8h"
    assert (first["read"], first["participations"]) == (False, 2)
    assert (second["read"], second["sender"], second["preview"]) == (True, None, None)


async def test_new_message_event(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An event per new unread message, none at the first update."""
    events = async_capture_events(hass, EVENT_NEW_MESSAGE)
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    assert events == []

    newer = copy.deepcopy(fixture_json("communications.json"))
    newer["included"][0]["attributes"]["dateTime"] = "2026-11-12T07:00:00Z"  # a reply in c-1
    newer["data"][1]["attributes"]["read"] = False  # c-2 marked unread, but no new message
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, skip=("communications",))
    aioclient_mock.get(f"{API}/communications", json=newer)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "config_entry_id": entry.entry_id,
        "id": "c-1",
        "subject": "Sortie scolaire",
        "sender": "Mme ANNE DURAND",
        "date": "2026-11-12T07:00:00+00:00",
        "preview": "Bonjour,\ndépart à 8h",
    }
    assert hass.states.get(SENSOR).state == "2"
