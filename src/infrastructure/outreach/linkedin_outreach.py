"""
LinkedIn outreach via Playwright browser automation.
Reuses BrowserScraper from Phase 2 with full humanization.

CRITICAL SAFETY:
- Requires a warmed LinkedIn account (manual usage for 2+ weeks)
- Max 25 connection requests/day, 50 messages/day
- Random 45-180 second delays between actions
- Never run outside business hours
- All actions logged for audit trail
"""
import asyncio
import logging
import random
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LinkedInOutreach:
    """LinkedIn actions via Playwright browser automation."""

    DAILY_CONNECTION_LIMIT = 25
    DAILY_MESSAGE_LIMIT = 50
    MIN_DELAY = 45
    MAX_DELAY = 180

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        self._connection_count_today: int = 0
        self._message_count_today: int = 0
        self._action_log: list[dict] = []

    async def view_profile(self, profile_url: str) -> bool:
        """Visit a LinkedIn profile (generates notification to prospect)."""
        logger.info("[LinkedIn] Viewing profile: %s", profile_url)
        try:
            from src.infrastructure.scrapers.browser_scraper import BrowserScraper

            scraper = BrowserScraper(settings=self._settings)
            await scraper.fetch(profile_url)
            self._log_action("view_profile", profile_url)
            await self._human_delay()
            return True
        except Exception as exc:
            logger.error("[LinkedIn] view_profile failed for %s: %s", profile_url, exc)
            return False

    async def send_connection(self, profile_url: str, note: str) -> bool:
        """Send a connection request with a personalized note (max 300 chars)."""
        if self._connection_count_today >= self.DAILY_CONNECTION_LIMIT:
            logger.warning("[LinkedIn] Daily connection limit reached (%d)", self.DAILY_CONNECTION_LIMIT)
            return False
        if len(note) > 300:
            note = note[:297] + "..."
        logger.info("[LinkedIn] Sending connection to %s", profile_url)
        try:
            from src.infrastructure.scrapers.browser_scraper import BrowserScraper

            scraper = BrowserScraper(settings=self._settings)
            page = await scraper._get_page()
            await page.goto(profile_url, timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))

            # Click Connect button
            connect_btn = page.locator("button:has-text('Connect')").first
            if await connect_btn.count() > 0:
                await connect_btn.click()
                await page.wait_for_timeout(random.randint(1000, 2000))

                # Add a note
                add_note_btn = page.locator("button:has-text('Add a note')")
                if await add_note_btn.count() > 0:
                    await add_note_btn.click()
                    await page.wait_for_timeout(500)
                    note_input = page.locator("textarea[name='message']")
                    await note_input.fill(note)
                    await page.wait_for_timeout(500)

                send_btn = page.locator("button:has-text('Send')").last
                await send_btn.click()

                self._connection_count_today += 1
                self._log_action("send_connection", profile_url, note[:50])
                await self._human_delay()
                return True

            logger.warning("[LinkedIn] No Connect button found for %s", profile_url)
            return False
        except Exception as exc:
            logger.error("[LinkedIn] send_connection failed for %s: %s", profile_url, exc)
            return False

    async def send_message(self, profile_url: str, message: str) -> bool:
        """Send a message to an existing connection."""
        if self._message_count_today >= self.DAILY_MESSAGE_LIMIT:
            logger.warning("[LinkedIn] Daily message limit reached (%d)", self.DAILY_MESSAGE_LIMIT)
            return False
        logger.info("[LinkedIn] Sending message to %s", profile_url)
        try:
            from src.infrastructure.scrapers.browser_scraper import BrowserScraper

            scraper = BrowserScraper(settings=self._settings)
            page = await scraper._get_page()
            await page.goto(profile_url, timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))

            msg_btn = page.locator("button:has-text('Message')").first
            if await msg_btn.count() > 0:
                await msg_btn.click()
                await page.wait_for_timeout(1000)
                msg_input = page.locator("div.msg-form__contenteditable")
                await msg_input.fill(message)
                await page.wait_for_timeout(500)
                send_btn = page.locator("button.msg-form__send-button")
                await send_btn.click()

                self._message_count_today += 1
                self._log_action("send_message", profile_url, message[:50])
                await self._human_delay()
                return True

            logger.warning("[LinkedIn] No Message button found for %s", profile_url)
            return False
        except Exception as exc:
            logger.error("[LinkedIn] send_message failed for %s: %s", profile_url, exc)
            return False

    async def like_post(self, post_url: str) -> bool:
        """Like a recent post to warm up the relationship."""
        logger.info("[LinkedIn] Liking post: %s", post_url)
        try:
            from src.infrastructure.scrapers.browser_scraper import BrowserScraper

            scraper = BrowserScraper(settings=self._settings)
            page = await scraper._get_page()
            await page.goto(post_url, timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))

            like_btn = page.locator("button[aria-label*='Like']").first
            if await like_btn.count() > 0:
                await like_btn.click()
                self._log_action("like_post", post_url)
                await self._human_delay()
                return True
            return False
        except Exception as exc:
            logger.error("[LinkedIn] like_post failed for %s: %s", post_url, exc)
            return False

    async def _human_delay(self) -> None:
        """Random sleep to simulate human behaviour."""
        delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
        logger.debug("[LinkedIn] Waiting %.1fs", delay)
        await asyncio.sleep(delay)

    def _log_action(self, action: str, url: str, detail: str = "") -> None:
        self._action_log.append({
            "action": action,
            "url": url,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_action_log(self) -> list[dict]:
        return list(self._action_log)
