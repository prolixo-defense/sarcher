"""
Fast HTTP scraper using curl_cffi for TLS fingerprint impersonation.

Primary scraper for static / server-rendered pages. Falls back to httpx
if curl_cffi is not installed (useful in test environments).
"""
import asyncio
import logging
import random
import time
from typing import Optional
from urllib.parse import urlparse

from src.infrastructure.fingerprint.tls_manager import (
    CURL_CFFI_AVAILABLE,
    IMPERSONATION_PROFILES,
    TLSManager,
)
from src.infrastructure.proxy.proxy_manager import ProxyManager
from src.infrastructure.scrapers.base_scraper import BaseScraper, ScrapedResponse

logger = logging.getLogger(__name__)

# Realistic browser request headers (Chrome-flavoured)
_REALISTIC_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class HttpScraper(BaseScraper):
    """
    curl_cffi-backed HTTP scraper with:
    - TLS fingerprint impersonation (impersonates Chrome/Firefox/Safari)
    - Matching User-Agent rotation (UA is always consistent with TLS profile)
    - Optional proxy support via ProxyManager
    - Randomised jitter delays between requests
    - Block detection and automatic retry with profile switching
    """

    def __init__(
        self,
        tls_manager: Optional[TLSManager] = None,
        proxy_manager: Optional[ProxyManager] = None,
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
    ):
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        self._tls = tls_manager or TLSManager()
        self._proxy_manager = proxy_manager
        self._delay_min = delay_min if delay_min is not None else settings.scrape_delay_min
        self._delay_max = delay_max if delay_max is not None else settings.scrape_delay_max

    async def _jitter(self):
        await asyncio.sleep(random.uniform(self._delay_min, self._delay_max))

    async def fetch(self, url: str, **kwargs) -> ScrapedResponse:
        """
        Fetch *url* with TLS impersonation, realistic headers, optional proxy,
        and a randomised jitter delay before the request.
        """
        if not CURL_CFFI_AVAILABLE:
            logger.warning("curl_cffi not available — using httpx fallback for %s", url)
            return await self._httpx_fallback(url)

        from curl_cffi.requests import AsyncSession

        profile, ua = self._tls.get_profile_and_ua()
        headers = {**_REALISTIC_HEADERS, "User-Agent": ua}

        proxy: Optional[str] = None
        if self._proxy_manager:
            domain = urlparse(url).netloc
            proxy = await self._proxy_manager.get_proxy(domain)

        await self._jitter()

        start = time.monotonic()
        try:
            proxies = {"https": proxy, "http": proxy} if proxy else None
            async with AsyncSession(impersonate=profile) as session:
                response = await session.get(
                    url,
                    headers=headers,
                    proxies=proxies,
                    timeout=30,
                    allow_redirects=True,
                    **{k: v for k, v in kwargs.items() if k not in ("impersonate",)},
                )
            elapsed = time.monotonic() - start
            html = response.text
            resp_headers = dict(response.headers)
            was_blocked = self.detect_block(response.status_code, html, resp_headers)

            if was_blocked:
                logger.warning(
                    "Block detected at %s (status=%d, profile=%s)", url, response.status_code, profile
                )
                if proxy and self._proxy_manager:
                    await self._proxy_manager.report_failure(proxy, f"status={response.status_code}")

            return ScrapedResponse(
                url=url,
                status_code=response.status_code,
                html=html,
                headers=resp_headers,
                response_time=elapsed,
                was_blocked=was_blocked,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error("Fetch error for %s: %s", url, exc)
            return ScrapedResponse(
                url=url,
                status_code=0,
                html="",
                response_time=elapsed,
                was_blocked=False,
                error=str(exc),
            )

    async def _httpx_fallback(self, url: str) -> ScrapedResponse:
        """Fallback to httpx when curl_cffi is unavailable."""
        import httpx

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url, headers=_REALISTIC_HEADERS)
            elapsed = time.monotonic() - start
            html = response.text
            was_blocked = self.detect_block(response.status_code, html, dict(response.headers))
            return ScrapedResponse(
                url=url,
                status_code=response.status_code,
                html=html,
                headers=dict(response.headers),
                response_time=elapsed,
                was_blocked=was_blocked,
            )
        except Exception as exc:
            return ScrapedResponse(
                url=url,
                status_code=0,
                html="",
                response_time=time.monotonic() - start,
                was_blocked=False,
                error=str(exc),
            )

    async def fetch_with_retry(self, url: str, max_retries: int = 3) -> ScrapedResponse:
        """
        Fetch with exponential backoff.
        On block detection, rotate to a fresh TLS profile before each retry.
        """
        last: Optional[ScrapedResponse] = None
        for attempt in range(max_retries + 1):
            response = await self.fetch(url)
            if response.is_success():
                return response
            last = response
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0.5, 2.0)
                logger.info(
                    "Retry %d/%d for %s in %.1fs (was_blocked=%s, status=%d)",
                    attempt + 1, max_retries, url, wait,
                    response.was_blocked, response.status_code,
                )
                await asyncio.sleep(wait)
                # Advance TLS profile so next attempt has a different fingerprint
                self._tls.get_profile()

        return last or ScrapedResponse(url=url, status_code=0, html="", was_blocked=True)
