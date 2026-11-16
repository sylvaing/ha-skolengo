"""Tests for the Lovelace cards shipped with the integration."""

from __future__ import annotations

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.skolengo.cards import CARDS_URL
from custom_components.skolengo.const import DOMAIN


class _Urls(set):
    """Stand-in for the frontend's URL manager (the frontend itself is not installed in tests)."""


async def test_cards_served_and_registered(hass: HomeAssistant, hass_client) -> None:
    """The module is served by HA and added to the frontend, versioned."""
    hass.data[DATA_EXTRA_MODULE_URL] = _Urls()
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    (url,) = hass.data[DATA_EXTRA_MODULE_URL]
    assert url.startswith(f"{CARDS_URL}?v=")

    client = await hass_client()
    resp = await client.get(CARDS_URL)
    assert resp.status == 200
    body = await resp.text()
    assert "customElements.define" in body
    assert "skolengo-homework-card" in body
