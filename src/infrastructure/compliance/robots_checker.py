"""
robots.txt compliance checker.

Fetches and caches robots.txt per domain for 24 hours.
Respects Crawl-delay directives.
"""
import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class RobotsChecker:
    """Checks robots.txt before scraping any URL."""

    CACHE_TTL_SECONDS = 86400  # 24 hours

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        # Cache: domain -> (RobotFileParser, fetched_at)
        self._cache: dict[str, tuple[RobotFileParser, float]] = {}

    async def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Returns True if the URL is allowed to be crawled."""
        if not getattr(self._settings, "respect_robots", True):
            return True

        try:
            parser = await self._get_parser(url)
            allowed = parser.can_fetch(user_agent, url)
            if not allowed:
                logger.info("[RobotsChecker] Blocked by robots.txt: %s", url)
            return allowed
        except Exception as exc:
            logger.warning("[RobotsChecker] Error checking robots.txt for %s: %s", url, exc)
            return True  # Allow on error (conservative for scraping, but avoids blocking)

    async def get_crawl_delay(self, domain: str) -> float | None:
        """Return the Crawl-delay for a domain, or None if not specified."""
        try:
            robots_url = f"https://{domain}/robots.txt"
            parser = await self._get_parser(robots_url)
            delay = parser.crawl_delay("*")
            return float(delay) if delay is not None else None
        except Exception:
            return None

    async def _get_parser(self, url: str) -> RobotFileParser:
        """Fetch and cache robots.txt for the domain of the given URL."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{domain}/robots.txt"

        now = time.time()
        cached = self._cache.get(domain)
        if cached is not None:
            parser, fetched_at = cached
            if now - fetched_at < self.CACHE_TTL_SECONDS:
                return parser

        # Fetch robots.txt
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # No robots.txt = allow all
                    parser.allow_all = True
        except Exception as exc:
            logger.debug("[RobotsChecker] Could not fetch %s: %s", robots_url, exc)
            parser.allow_all = True

        self._cache[domain] = (parser, now)
        return parser
