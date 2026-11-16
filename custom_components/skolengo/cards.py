"""Serve and register the Lovelace cards shipped with the integration (no manual resource)."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARDS_URL = f"/{DOMAIN}/skolengo-cards.js"
CARDS_PATH = Path(__file__).parent / "frontend" / "skolengo-cards.js"


async def async_register_cards(hass: HomeAssistant) -> None:
    """Serve the cards module and load it in every frontend, versioned against stale caches."""
    if hass.http is None:  # no web server (e.g. some tests)
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(CARDS_PATH), cache_headers=False)]
    )
    if DATA_EXTRA_MODULE_URL not in hass.data:
        _LOGGER.debug("The frontend is not loaded: the Skolengo cards are served but not registered")
        return
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARDS_URL}?v={integration.version}")
