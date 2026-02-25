"""
Playwright-based browser scraper with stealth patches and humanization.

Used for JavaScript-heavy sites (LinkedIn, SPAs) that don't render meaningful
HTML without executing client-side code.
"""
import asyncio
import logging
import os
import random
import time
from typing import Optional

from src.infrastructure.scrapers.base_scraper import BaseScraper, ScrapedResponse

logger = logging.getLogger(__name__)

# Realistic viewport sizes (width × height)
VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
]


class BrowserScraper(BaseScraper):
    """
    Playwright Chromium scraper with:
    - playwright-stealth patches (hides webdriver, fixes navigator properties)
    - Randomised viewport from common real-world resolutions
    - Human-like scroll before HTML extraction
    - Debug screenshots saved to SCREENSHOT_DIR
    - Automatic resource cleanup via close()
    """

    def __init__(self, headless: Optional[bool] = None):
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        self._headless = headless if headless is not None else settings.headless
        self._screenshot_dir = settings.screenshot_dir
        self._browser = None
        self._playwright = None
        self._stealth_fn = None
        self._default_viewport: dict = random.choice(VIEWPORT_SIZES)

    async def launch_browser(self):
        """Launch Playwright Chromium. Applies stealth patches if available."""
        from playwright.async_api import async_playwright

        try:
            from playwright_stealth import Stealth

            _stealth = Stealth()
            self._stealth_fn = _stealth.apply_stealth_async
        except ImportError:
            logger.warning("playwright-stealth not installed; stealth mode disabled")
            self._stealth_fn = None

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        return self._browser

    async def _new_page(self):
        """Create a new browser page in a fresh context, applying stealth if available."""
        if self._browser is None:
            await self.launch_browser()

        context = await self._browser.new_context(
            viewport=self._default_viewport,
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = await context.new_page()
        if self._stealth_fn:
            await self._stealth_fn(page)
        return page

    async def fetch(self, url: str, wait_for: Optional[str] = None, **kwargs) -> ScrapedResponse:
        """
        Navigate to *url*, wait for content, scroll naturally, extract HTML.

        Parameters
        ----------
        url:      Target URL.
        wait_for: Optional CSS selector to wait for after load (e.g. 'h1').
                  Falls back to networkidle if not provided.
        """
        page = await self._new_page()
        start = time.monotonic()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10_000)
                except Exception:
                    pass  # Best-effort — continue even if selector not found
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass

            # Human-like scroll to trigger lazy-loaded content
            from src.infrastructure.scrapers.humanization.scroll_behavior import human_scroll

            await human_scroll(page)

            html = await page.content()
            elapsed = time.monotonic() - start
            was_blocked = self.detect_block(200, html, {})

            # Save debug screenshot
            try:
                os.makedirs(self._screenshot_dir, exist_ok=True)
                slug = url.replace("://", "_").replace("/", "_")[:60]
                await page.screenshot(
                    path=os.path.join(self._screenshot_dir, f"{slug}.png"),
                    full_page=False,
                )
            except Exception:
                pass

            return ScrapedResponse(
                url=url,
                status_code=200,
                html=html,
                response_time=elapsed,
                was_blocked=was_blocked,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error("Browser fetch error for %s: %s", url, exc)
            return ScrapedResponse(
                url=url,
                status_code=0,
                html="",
                response_time=elapsed,
                was_blocked=False,
                error=str(exc),
            )
        finally:
            try:
                await page.context.close()
            except Exception:
                pass

    async def fetch_with_retry(self, url: str, max_retries: int = 3) -> ScrapedResponse:
        """Browser fetch with exponential backoff."""
        last: Optional[ScrapedResponse] = None
        for attempt in range(max_retries + 1):
            response = await self.fetch(url)
            if response.is_success():
                return response
            last = response
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(1.0, 3.0)
                logger.info(
                    "Browser retry %d/%d for %s in %.1fs",
                    attempt + 1, max_retries, url, wait,
                )
                await asyncio.sleep(wait)
        return last or ScrapedResponse(url=url, status_code=0, html="", was_blocked=True)

    async def fetch_with_interaction(
        self, url: str, actions: list[dict]
    ) -> ScrapedResponse:
        """
        Navigate to *url* then execute a sequence of human-like actions.

        Each action dict may have:
            {"type": "click",  "selector": "..."}
            {"type": "type",   "selector": "...", "text": "..."}
            {"type": "scroll", "direction": "down"}
            {"type": "wait",   "seconds": 1.5}
        """
        from src.infrastructure.scrapers.humanization.mouse_movements import human_click
        from src.infrastructure.scrapers.humanization.typing_simulator import human_type
        from src.infrastructure.scrapers.humanization.scroll_behavior import human_scroll

        page = await self._new_page()
        start = time.monotonic()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            for action in actions:
                atype = action.get("type", "")
                selector = action.get("selector", "")
                if atype == "click" and selector:
                    await human_click(page, selector)
                elif atype == "type" and selector:
                    await human_type(page, selector, action.get("text", ""))
                elif atype == "scroll":
                    await human_scroll(page, direction=action.get("direction", "down"))
                elif atype == "wait":
                    await asyncio.sleep(float(action.get("seconds", 1.0)))

            html = await page.content()
            elapsed = time.monotonic() - start
            was_blocked = self.detect_block(200, html, {})
            return ScrapedResponse(
                url=url,
                status_code=200,
                html=html,
                response_time=elapsed,
                was_blocked=was_blocked,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return ScrapedResponse(
                url=url,
                status_code=0,
                html="",
                response_time=elapsed,
                was_blocked=False,
                error=str(exc),
            )
        finally:
            try:
                await page.context.close()
            except Exception:
                pass

    async def close(self):
        """Shut down the browser and Playwright cleanly."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
