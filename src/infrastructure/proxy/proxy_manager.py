import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 300  # 5-minute cooldown for failed proxies


class ProxyManager:
    """
    Manages proxy rotation for scraping.

    MVP / zero-cost mode:
    - Loads proxies from a local text file (one per line: protocol://ip:port)
    - Works with NO proxies (direct connection) as a graceful fallback
    - Round-robin rotation with optional sticky sessions per domain
    - Ban detection: 403/429 causes a cooldown period before reuse
    - Health check: tests all proxies and removes dead ones
    """

    def __init__(self, proxy_file: str = "./data/proxies.txt"):
        self._proxy_file = proxy_file
        self._proxies: list[str] = []
        self._index: int = 0
        self._failures: dict[str, float] = {}   # proxy -> timestamp of last failure
        self._domain_sticky: dict[str, str] = {}  # domain -> assigned proxy
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self._proxy_file):
            logger.info("No proxy file at %s; using direct connections", self._proxy_file)
            return
        with open(self._proxy_file) as f:
            proxies = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        self._proxies = proxies
        logger.info("Loaded %d proxies from %s", len(self._proxies), self._proxy_file)

    def _is_cooling(self, proxy: str) -> bool:
        ts = self._failures.get(proxy)
        if ts is None:
            return False
        return (time.time() - ts) < COOLDOWN_SECONDS

    def _available(self) -> list[str]:
        return [p for p in self._proxies if not self._is_cooling(p)]

    async def get_proxy(self, domain: Optional[str] = None) -> Optional[str]:
        """
        Return the next available proxy.
        Returns None if no proxies are configured or all are cooling down.
        """
        self._load()
        if not self._proxies:
            return None

        # Sticky session: return the same proxy for this domain if still healthy
        if domain and domain in self._domain_sticky:
            sticky = self._domain_sticky[domain]
            if not self._is_cooling(sticky):
                return sticky
            del self._domain_sticky[domain]

        available = self._available()
        if not available:
            logger.warning("All proxies are cooling down; falling back to direct connection")
            return None

        proxy = available[self._index % len(available)]
        self._index += 1
        if domain:
            self._domain_sticky[domain] = proxy
        return proxy

    async def report_failure(self, proxy: str, reason: str = "unknown"):
        """Mark a proxy as temporarily unavailable (triggers cooldown)."""
        logger.warning(
            "Proxy %s failed (%s); cooling down for %ds", proxy, reason, COOLDOWN_SECONDS
        )
        self._failures[proxy] = time.time()
        # Remove from all sticky sessions
        self._domain_sticky = {d: p for d, p in self._domain_sticky.items() if p != proxy}

    async def health_check(self):
        """
        Test all loaded proxies with a lightweight HTTP request.
        Removes proxies that fail or respond incorrectly.
        """
        self._load()
        if not self._proxies:
            return

        import httpx

        original_count = len(self._proxies)
        healthy: list[str] = []

        for proxy in self._proxies:
            try:
                proxies_map = {"https://": proxy, "http://": proxy}
                async with httpx.AsyncClient(proxies=proxies_map, timeout=10) as client:
                    r = await client.get("http://httpbin.org/ip")
                    if r.status_code == 200:
                        healthy.append(proxy)
                    else:
                        logger.info("Proxy %s unhealthy (status=%d)", proxy, r.status_code)
            except Exception as e:
                logger.info("Proxy %s failed health check: %s", proxy, e)

        self._proxies = healthy
        logger.info(
            "Health check done: %d/%d proxies healthy", len(healthy), original_count
        )
