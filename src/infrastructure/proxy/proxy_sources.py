"""
Free proxy list fetchers.

WARNING: Free proxies are slow, unreliable, and short-lived.
This module is a starting point for MVP use — for production,
use a commercial proxy provider.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def fetch_free_proxies() -> list[str]:
    """
    Fetch HTTP proxies from public free-proxy APIs.
    Returns a list of proxy strings in the format: http://ip:port
    """
    proxies: list[str] = []

    # Source: proxyscrape.com public API
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.proxyscrape.com/v2/"
                "?request=displayproxies&protocol=http"
                "&timeout=10000&country=all&ssl=all&anonymity=all"
            )
            if r.status_code == 200:
                for line in r.text.strip().splitlines():
                    line = line.strip()
                    if line and ":" in line:
                        proxies.append(f"http://{line}")
    except Exception as e:
        logger.warning("Failed to fetch from proxyscrape: %s", e)

    logger.info("Fetched %d free proxies", len(proxies))
    return proxies


def save_proxies_to_file(proxies: list[str], filepath: str = "./data/proxies.txt"):
    """Persist a proxy list to a text file (one per line)."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w") as f:
        for proxy in proxies:
            f.write(proxy + "\n")
    logger.info("Saved %d proxies to %s", len(proxies), filepath)
