"""
LinkedIn profile scraping adapter.

LinkedIn is the most heavily protected scraping target. This adapter:
- Requires a valid li_at session cookie (the user provides their own)
- Uses BrowserScraper with playwright-stealth
- Enforces a strict daily rate limit (≤ 80 profiles / day)
- Waits 30–120 seconds between profile requests
- Stops immediately if a security-check page is detected
"""
import asyncio
import logging
import random
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


class LinkedInAdapter:
    """
    Scrape a single LinkedIn profile URL and return a raw lead dict.

    Configuration (via settings or constructor):
        li_at_cookie      — LinkedIn session cookie (required)
        DAILY_LIMIT       — Maximum profiles per calendar day
        MIN/MAX_DELAY_SECONDS — Pause between consecutive requests
    """

    DAILY_LIMIT = 80
    MIN_DELAY_SECONDS = 30
    MAX_DELAY_SECONDS = 120

    _SECURITY_MARKERS = [
        "security check",
        "verify your identity",
        "unusual activity",
        "checkpoint",
        "authwall",
        "join linkedin",
        "sign in to linkedin",
        "we need to verify",
    ]

    def __init__(self, li_at_cookie: Optional[str] = None):
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        self._li_at_cookie = li_at_cookie or settings.linkedin_li_at_cookie
        self._scraper = None          # lazy-initialised BrowserScraper
        self._daily_count = 0
        self._last_reset = date.today()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._last_reset:
            self._daily_count = 0
            self._last_reset = today

    def _check_limit(self):
        self._reset_if_new_day()
        if self._daily_count >= self.DAILY_LIMIT:
            raise RuntimeError(
                f"LinkedIn daily limit reached ({self.DAILY_LIMIT} profiles). "
                "Retry tomorrow."
            )

    def _get_scraper(self):
        if self._scraper is None:
            from src.infrastructure.scrapers.browser_scraper import BrowserScraper

            self._scraper = BrowserScraper()
        return self._scraper

    def _is_security_check(self, html: str) -> bool:
        lower = html.lower()
        return any(marker in lower for marker in self._SECURITY_MARKERS)

    def _parse_profile(self, html: str, profile_url: str) -> dict:
        """Extract structured data from a LinkedIn profile page."""
        result: dict = {"linkedin_url": profile_url, "source": "linkedin"}
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # --- Name (h1) ---
            h1 = soup.find("h1")
            if h1:
                name = h1.get_text(strip=True)
                parts = name.split(None, 1)
                result["first_name"] = parts[0] if parts else ""
                result["last_name"] = parts[1] if len(parts) > 1 else ""

            # --- Headline / title ---
            for cls_hint in ("headline", "title", "subtitle", "text-body-medium"):
                tag = soup.find(
                    lambda t: t.name in ("div", "span", "h2")
                    and cls_hint in " ".join(t.get("class", [])),
                )
                if tag:
                    text = tag.get_text(strip=True)
                    if text and 1 < len(text.split()) <= 15:
                        result["job_title"] = text
                        break

            # --- Current company (first entry in experience section) ---
            exp = soup.find(id="experience") or soup.find(
                attrs={"data-section": "experience"}
            )
            if exp:
                for span in exp.find_all("span", limit=30):
                    text = span.get_text(strip=True)
                    if text and 1 <= len(text.split()) <= 6:
                        result.setdefault("company_name", text)
                        break

            # --- Location ---
            loc = soup.find(
                lambda t: t.name in ("span", "div")
                and "location" in " ".join(t.get("class", [])).lower()
            )
            if loc:
                result["location"] = loc.get_text(strip=True)

        except Exception as exc:
            logger.error("LinkedIn profile parse error: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def scrape(self, profile_url: str) -> dict:
        """
        Scrape a single LinkedIn profile.

        Returns a raw lead dict, or an empty dict if blocked / not configured.
        """
        self._check_limit()

        if not self._li_at_cookie:
            logger.error(
                "LinkedIn li_at cookie not configured. "
                "Set LINKEDIN_LI_AT_COOKIE in your .env file."
            )
            return {}

        scraper = self._get_scraper()
        await scraper.launch_browser()

        # Inject the li_at session cookie before navigating
        page = await scraper._new_page()
        await page.context.add_cookies([
            {
                "name": "li_at",
                "value": self._li_at_cookie,
                "domain": ".linkedin.com",
                "path": "/",
            }
        ])
        await page.close()

        # Fetch profile
        response = await scraper.fetch(
            profile_url,
            wait_for=".profile-photo-edit, h1, .pv-top-card",
        )

        if self._is_security_check(response.html):
            logger.error(
                "LinkedIn security check triggered at %s — stopping immediately. "
                "Wait several hours before retrying to protect the account.",
                profile_url,
            )
            await scraper.close()
            return {}

        self._daily_count += 1
        result = self._parse_profile(response.html, profile_url)

        # Respectful delay before next call
        delay = random.uniform(self.MIN_DELAY_SECONDS, self.MAX_DELAY_SECONDS)
        logger.info(
            "LinkedIn profile scraped (%d/%d today). Waiting %.0fs.",
            self._daily_count, self.DAILY_LIMIT, delay,
        )
        await asyncio.sleep(delay)

        return result
