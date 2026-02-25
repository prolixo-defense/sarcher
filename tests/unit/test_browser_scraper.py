"""
Tests for BrowserScraper — initialisation, settings, and non-network behaviour.

get_settings() is called inside __init__() so we patch it at its source:
  src.infrastructure.config.settings.get_settings
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.infrastructure.scrapers.browser_scraper import BrowserScraper, VIEWPORT_SIZES

_MOCK_SETTINGS = MagicMock(headless=True, screenshot_dir="./data/screenshots")
_SETTINGS_PATH = "src.infrastructure.config.settings.get_settings"


def test_browser_scraper_defaults_to_settings_headless():
    """headless should come from settings if not passed explicitly."""
    with patch(_SETTINGS_PATH, return_value=_MOCK_SETTINGS):
        scraper = BrowserScraper()
    assert scraper._headless is True


def test_browser_scraper_explicit_headless_overrides_settings():
    with patch(_SETTINGS_PATH, return_value=_MOCK_SETTINGS):
        scraper = BrowserScraper(headless=False)
    assert scraper._headless is False


def test_default_viewport_is_one_of_known_sizes():
    with patch(_SETTINGS_PATH, return_value=_MOCK_SETTINGS):
        scraper = BrowserScraper()
    assert scraper._default_viewport in VIEWPORT_SIZES


def test_browser_scraper_initially_has_no_browser():
    with patch(_SETTINGS_PATH, return_value=_MOCK_SETTINGS):
        scraper = BrowserScraper()
    assert scraper._browser is None
    assert scraper._playwright is None


@pytest.mark.asyncio
async def test_close_does_nothing_when_not_launched():
    """close() should be a no-op when the browser was never started."""
    with patch(_SETTINGS_PATH, return_value=_MOCK_SETTINGS):
        scraper = BrowserScraper()
    # Should not raise
    await scraper.close()
