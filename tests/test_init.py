"""Tests for the config entry setup, the coordinator and the devices."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.skolengo.const import (
    CONF_HOMEWORK_DAYS,
    CONF_TOKENS,
    DOMAIN,
)
from custom_components.skolengo.coordinator import NIGHT_INTERVAL

from .common import USERS_INFO, calls, mock_api, status
from .common import make_entry as _entry
from .helpers import API, TOKEN, fixture_json, token_response


@pytest.fixture(autouse=True)
def no_retry_sleep():
    """Do not really wait between retries."""
    with patch("custom_components.skolengo.coordinator.asyncio.sleep"):
        yield


async def test_setup_fetches_granted_services(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only the services granted by each student's school are read; devices follow."""
    mock_api(aioclient_mock)
    entry = _entry(hass, options={CONF_HOMEWORK_DAYS: 10})

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    snapshot = entry.runtime_data.coordinator.data

    lou, sam = snapshot.students["ESKO-P-child-1"], snapshot.students["ESKO-P-child-2"]
    assert lou.services == {"TAF", "CDT"}
    assert [h.id for h in lou.homework] == ["hw-1", "hw-2"]
    assert [le.id for le in lou.lessons] == ["l-1", "l-2"]
    assert sam.services == frozenset() and sam.homework is None and sam.lessons is None
    assert snapshot.mailbox.unread == 1
    assert snapshot.mailbox.inbox.total == 19

    # Sam's school grants neither homework nor lessons: no call is made for Sam.
    assert all("ESKO-P-child-1" in str(c[1]) for c in calls(aioclient_mock, "homework-assignments"))
    hw_query = calls(aioclient_mock, "homework-assignments")[0][1].query
    today = dt_util.now().date()
    assert hw_query["filter[dueDate][GE]"] == today.isoformat()
    assert hw_query["filter[dueDate][LE]"] == (today + timedelta(days=10)).isoformat()

    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    assert sorted(d.name for d in devices) == ["Alex MARTIN", "Lou MARTIN"]
    lou_device = registry.async_get_device_by_identifier((DOMAIN, "ESKO-P-child-1"), entry.entry_id)
    assert (lou_device.model, lou_device.model_id) == ("Collège Exemple", "4A")

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_one_failing_service_keeps_the_others(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A service in error is recorded; the other services are still updated."""
    mock_api(aioclient_mock, skip=("agendas",))
    aioclient_mock.get(f"{API}/agendas", side_effect=status(500))
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    lou = entry.runtime_data.coordinator.data.students["ESKO-P-child-1"]
    assert lou.homework is not None
    assert lou.lessons is None
    assert "500" in lou.errors["CDT"]
    # a plain 500 is not retried
    assert len(calls(aioclient_mock, "/agendas")) == 1


async def test_failed_service_keeps_previous_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When a service fails after a success, its last data is kept."""
    mock_api(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, skip=("homework",))
    aioclient_mock.get(f"{API}/homework-assignments", side_effect=status(403))
    await coordinator.async_refresh()

    lou = coordinator.data.students["ESKO-P-child-1"]
    assert [h.id for h in lou.homework] == ["hw-1", "hw-2"]
    assert "403" in lou.errors["TAF"]
    assert coordinator.last_update_success


async def test_transient_errors_are_retried(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """503 answers are retried (bounded by the app config hints, at most 3 retries)."""
    mock_api(aioclient_mock, skip=("agendas",))
    answers = iter([503, 503, 200])

    async def flaky(method, url, data):
        code = next(answers)
        if code != 200:
            return AiohttpClientMockResponse(method, url, status=code)
        return AiohttpClientMockResponse(method, url, json=fixture_json("agendas.json"))

    aioclient_mock.get(f"{API}/agendas", side_effect=flaky)
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.coordinator.data.students["ESKO-P-child-1"].lessons is not None
    assert len(calls(aioclient_mock, "/agendas")) == 3


async def test_every_service_failing_is_not_ready(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """If nothing at all can be read at setup, the entry retries later."""
    mock_api(aioclient_mock, skip=("homework", "agendas", "mail"))
    for url in (
        f"{API}/homework-assignments",
        f"{API}/agendas",
        f"{API}/users-mail-settings/RSKO-P-parent-1",
    ):
        aioclient_mock.get(url, side_effect=status(500))
    entry = _entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rotated_tokens_are_persisted(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An expired access token is refreshed and the new refresh token saved in the entry."""
    aioclient_mock.post(TOKEN, json=token_response("access-2", "refresh-2"))
    mock_api(aioclient_mock)
    entry = _entry(hass, expires_in=-10)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.data[CONF_TOKENS]["refresh_token"] == "refresh-2"
    assert entry.data[CONF_TOKENS]["access_token"] == "access-2"
    assert len(calls(aioclient_mock, TOKEN)) == 1


async def test_dead_session_starts_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A refused refresh puts the entry in error and starts the reauth flow."""
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    mock_api(aioclient_mock)
    entry = _entry(hass, expires_in=-10)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert [f["context"]["source"] for f in hass.config_entries.flow.async_progress()] == ["reauth"]


async def test_session_dying_later_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A session that dies after setup also leads to reauth."""
    mock_api(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, skip=("users-info",))
    aioclient_mock.get(USERS_INFO, side_effect=status(401))
    aioclient_mock.post(TOKEN, status=400, json={"error": "invalid_grant"})
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [f["context"]["source"] for f in hass.config_entries.flow.async_progress()] == ["reauth"]


async def test_app_config_unavailable_uses_defaults(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The retry hints are optional."""
    mock_api(aioclient_mock)
    aioclient_mock._mocks = [m for m in aioclient_mock._mocks if "sko-app-configs" not in str(m.url)]
    aioclient_mock.get(f"{API}/sko-app-configs/current", status=503)
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)


@pytest.mark.parametrize(("hour", "night"), [(23, True), (3, True), (6, False), (14, False)])
async def test_night_interval(hass: HomeAssistant, hour: int, night: bool) -> None:
    """At night the coordinator polls at most every NIGHT_INTERVAL."""
    from custom_components.skolengo.coordinator import SkolengoCoordinator

    entry = _entry(hass)
    coordinator = SkolengoCoordinator(hass, entry, client=None)  # type: ignore[arg-type]
    now = datetime(2026, 11, 16, hour, 0, tzinfo=dt_util.get_default_time_zone())
    expected = NIGHT_INTERVAL if night else timedelta(minutes=30)
    assert coordinator._next_interval(now) == expected


async def test_remove_stale_device(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A device of a student no longer on the account can be removed, a current one cannot."""
    from custom_components.skolengo import async_remove_config_entry_device

    mock_api(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    registry = dr.async_get(hass)
    stale = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "ESKO-P-gone")}
    )
    current = registry.async_get_device_by_identifier((DOMAIN, "ESKO-P-child-1"), entry.entry_id)

    assert await async_remove_config_entry_device(hass, entry, stale)
    assert not await async_remove_config_entry_device(hass, entry, current)


async def test_scheduled_refresh(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The coordinator refreshes on its own after the interval, while something listens."""
    mock_api(aioclient_mock)
    entry = _entry(hass)
    with patch(
        "custom_components.skolengo.coordinator.dt_util.now", return_value=datetime(2026, 11, 16, 10, 0)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
    before = len(calls(aioclient_mock, "users-info"))
    # The coordinator only polls while entities listen to it.
    entry.runtime_data.coordinator.async_add_listener(lambda: None)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=4))
    await hass.async_block_till_done()

    assert len(calls(aioclient_mock, "users-info")) == before + 1


async def test_account_failure_keeps_previous_account(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Once loaded, an account read failure keeps the previous account and still updates services."""
    mock_api(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, skip=("users-info",))
    aioclient_mock.get(USERS_INFO, side_effect=status(503))
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data.account.id == "RSKO-P-parent-1"
    assert calls(aioclient_mock, "homework-assignments")
