"""
Web search adapter for discovering relevant pages during lead discovery.

Priority order (auto-detected from settings):
1. SerpAPI         — if SERP_API_KEY is set        (100 searches/month free)
2. Google CSE      — if GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID are set (100/day free)
3. DuckDuckGo HTML — free fallback, no API key required

Returns: list[{"url": str, "title": str, "snippet": str}]
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)


class GoogleSearchAdapter:
    """
    Multi-provider web search adapter.

    Selects the best available provider based on configured API keys.
    Falls back to DuckDuckGo HTML scraping when no API keys are present.
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()
        self._settings = settings

    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        """
        Search for pages matching *query* using the best available provider.

        Returns a list of {"url", "title", "snippet"} dicts.
        """
        serp_key: str = getattr(self._settings, "serp_api_key", "")
        cse_key: str = getattr(self._settings, "google_cse_api_key", "")
        cse_id: str = getattr(self._settings, "google_cse_id", "")

        if serp_key:
            logger.debug("Search via SerpAPI: %r", query)
            return await self._serpapi_search(query, num_results, serp_key)
        elif cse_key and cse_id:
            logger.debug("Search via Google CSE: %r", query)
            return await self._google_cse_search(query, num_results, cse_key, cse_id)
        else:
            logger.debug("Search via DuckDuckGo: %r", query)
            return await self._duckduckgo_search(query, num_results)

    # ------------------------------------------------------------------
    # Provider: SerpAPI
    # ------------------------------------------------------------------

    async def _serpapi_search(
        self, query: str, num_results: int, api_key: str
    ) -> list[dict]:
        """Search via SerpAPI (https://serpapi.com — 100 searches/month free)."""
        import httpx

        params = {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "num": num_results,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://serpapi.com/search.json", params=params)
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("organic_results", [])[:num_results]
        ]

    # ------------------------------------------------------------------
    # Provider: Google Custom Search API
    # ------------------------------------------------------------------

    async def _google_cse_search(
        self, query: str, num_results: int, api_key: str, cse_id: str
    ) -> list[dict]:
        """Search via Google Custom Search JSON API (100 queries/day free)."""
        import httpx

        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": min(num_results, 10),  # API cap is 10 per request
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("items", [])[:num_results]
        ]

    # ------------------------------------------------------------------
    # Provider: DuckDuckGo HTML scraping (free fallback)
    # ------------------------------------------------------------------

    async def _duckduckgo_search(self, query: str, num_results: int) -> list[dict]:
        """
        Search DuckDuckGo via their HTML endpoint — no API key required.

        Uses the lightweight HTML version (html.duckduckgo.com) which is
        more scraping-friendly than the main site.
        """
        import httpx
        from bs4 import BeautifulSoup

        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.warning("DuckDuckGo search request failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: list[dict] = []

        for a_tag in soup.select(".result__a")[:num_results]:
            href: str = a_tag.get("href", "")  # type: ignore[assignment]

            # DDG wraps real URLs in a redirect — extract the actual URL
            if href.startswith("//duckduckgo.com/l/"):
                try:
                    parsed = urllib.parse.urlparse("https:" + href)
                    qs = urllib.parse.parse_qs(parsed.query)
                    href = urllib.parse.unquote(qs.get("uddg", [href])[0])
                except Exception:
                    pass

            if not href.startswith("http"):
                continue

            title = a_tag.get_text(strip=True)

            snippet = ""
            parent = a_tag.find_parent("div", class_="result")
            if parent:
                snippet_el = parent.find(class_="result__snippet")
                if snippet_el:
                    snippet = snippet_el.get_text(strip=True)

            results.append({"url": href, "title": title, "snippet": snippet})

        logger.debug("DuckDuckGo returned %d results for %r", len(results), query)
        return results
