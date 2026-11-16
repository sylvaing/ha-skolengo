"""Tests for the homework sensor and to-do list."""

from __future__ import annotations

import json

import pytest
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skolengo.const import DOMAIN

from .common import calls, make_entry, mock_api
from .helpers import API, TOKEN

SENSOR = "sensor.lou_martin_homework"
TODO = "todo.lou_martin_homework"
PATCH_URL = f"{API}/homework-assignments/hw-2"


async def _setup(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    mock_api(aioclient_mock)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_homework_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Count of homework not done, with plain-text items for the card."""
    await _setup(hass, aioclient_mock)
    state = hass.states.get(SENSOR)
    assert state.state == "1"
    items = state.attributes["homework"]
    assert [i["id"] for i in items] == ["hw-1", "hw-2"]
    assert items[1]["subject"] == "ESPAGNOL LV2"
    assert items[1]["background_color"] == "#d4534c"
    assert items[1]["description"] == "Exercices\nFinir l'exercice 3\n• page 12"
    assert items[1]["teacher"] == "M. LUC PETIT"
    assert items[0]["done"] is True
    assert "<" not in json.dumps(items)


async def test_entities_only_for_granted_services(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sam's school does not grant homework: no homework entity for Sam."""
    entry = await _setup(hass, aioclient_mock)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    homework = sorted(e.entity_id for e in entities if e.unique_id.endswith("_homework"))
    assert homework == [SENSOR, TODO]
    assert all(e.platform == DOMAIN for e in entities)


async def test_todo_items(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """One item per homework, ticked when done."""
    await _setup(hass, aioclient_mock)
    result = await hass.services.async_call(
        TODO_DOMAIN,
        "get_items",
        {"entity_id": TODO, "status": ["needs_action", "completed"]},
        blocking=True,
        return_response=True,
    )
    items = result[TODO]["items"]
    assert [(i["uid"], i["status"]) for i in items] == [("hw-1", "completed"), ("hw-2", "needs_action")]
    assert items[0]["summary"] == "MATHEMATIQUES: p 41 n°5"
    assert hass.states.get(TODO).state == "1"


async def test_mark_done_sends_patch(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Ticking an item PATCHes the ENT and updates the entities at once."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.patch(PATCH_URL, status=204)
    before = len(calls(aioclient_mock, "homework-assignments"))

    await hass.services.async_call(
        TODO_DOMAIN, "update_item", {"entity_id": TODO, "item": "hw-2", "status": "completed"}, blocking=True
    )

    patch = [c for c in aioclient_mock.mock_calls if c[0] == "PATCH"]
    assert len(patch) == 1
    assert patch[0][1].query["filter[student.id]"] == "ESKO-P-child-1"
    assert patch[0][2] == {"data": {"type": "homework", "id": "hw-2", "attributes": {"done": True}}}
    assert patch[0][3]["X-Skolengo-School-Id"] == "SKO-E-college"
    # no full refresh: the local copy is updated
    assert len(calls(aioclient_mock, "homework-assignments")) == before + 1
    assert hass.states.get(SENSOR).state == "0"
    assert hass.states.get(TODO).state == "0"


async def test_unchanged_status_sends_nothing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Re-ticking a done item does not call the ENT."""
    await _setup(hass, aioclient_mock)
    await hass.services.async_call(
        TODO_DOMAIN, "update_item", {"entity_id": TODO, "item": "hw-1", "status": "completed"}, blocking=True
    )
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "PATCH"]


@pytest.mark.parametrize(("code", "key"), [(403, "homework_forbidden"), (500, "homework_update_failed")])
async def test_mark_done_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, code: int, key: str
) -> None:
    """A refusal of the ENT is reported and nothing changes."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.patch(PATCH_URL, status=code, json={"errors": [{"title": "NOPE"}]})
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"entity_id": TODO, "item": "hw-2", "status": "completed"},
            blocking=True,
        )
    assert err.value.translation_key == key
    assert hass.states.get(SENSOR).state == "1"


async def test_unknown_item(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An item that is not in the list is a validation error."""
    await _setup(hass, aioclient_mock)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"entity_id": TODO, "item": "nope", "status": "completed"},
            blocking=True,
        )


async def test_mark_done_with_dead_session_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A session refused while ticking starts the reauth flow."""
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.patch(PATCH_URL, status=401)
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"entity_id": TODO, "item": "hw-2", "status": "completed"},
            blocking=True,
        )
    assert err.value.translation_key == "auth_expired"
    await hass.async_block_till_done()
    assert any(
        flow["context"]["source"] == "reauth" for flow in entry.async_get_active_flows(hass, {"reauth"})
    )
