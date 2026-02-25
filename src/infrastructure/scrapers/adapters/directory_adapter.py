"""
Business directory scraping adapter.

Configurable via CSS selectors so it can handle any directory-like site
(Crunchbase, Yellow Pages, industry-specific databases, etc.).
Uses the fast HttpScraper path since most directories are server-rendered.
Supports automatic pagination.
"""
import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Sensible defaults for generic directory pages
DEFAULT_CONFIG: dict = {
    "item_selector": "div.company, li.listing, div.result, article, li.item",
    "name_selector": "h2, h3, .company-name, .name, .title",
    "location_selector": ".location, .address, [class*='location']",
    "description_selector": "p.description, .excerpt, p.summary, p",
    "next_page_selector": "a.next, a[rel='next'], .pagination a:last-child, a.pagination-next",
    "max_pages": 5,
}


class DirectoryAdapter:
    """
    Scrape business directory listing pages and extract company/contact data.

    The adapter is configurable with CSS selectors so it can be targeted at
    any directory-like page structure without code changes.

    Usage::

        adapter = DirectoryAdapter()
        results = await adapter.scrape(
            "https://example-directory.com/companies",
            config={"item_selector": "div.company-card"},
        )
    """

    def __init__(self, scraper=None, extraction_engine=None):
        self._scraper = scraper
        self._extraction_engine = extraction_engine

    def _get_scraper(self):
        if self._scraper is None:
            from src.infrastructure.scrapers.http_scraper import HttpScraper

            self._scraper = HttpScraper()
        return self._scraper

    def _parse_page(self, html: str, config: dict, base_url: str) -> list[dict]:
        """Parse one directory listing page for company / contact entries."""
        results: list[dict] = []
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            items = soup.select(config["item_selector"])
            for item in items[:50]:
                entry: dict = {}

                name_tag = item.select_one(config["name_selector"])
                if name_tag:
                    entry["company_name"] = name_tag.get_text(strip=True)

                loc_tag = item.select_one(config["location_selector"])
                if loc_tag:
                    entry["location"] = loc_tag.get_text(strip=True)

                desc_tag = item.select_one(config["description_selector"])
                if desc_tag:
                    entry["description"] = desc_tag.get_text(strip=True)[:500]

                # Attempt to extract a company domain from hyperlinks
                link_tag = item.select_one("a[href]")
                if link_tag:
                    href = link_tag.get("href", "")
                    if href.startswith("http"):
                        entry["company_domain"] = urlparse(href).netloc
                    elif href:
                        full = urljoin(base_url, href)
                        entry["company_domain"] = urlparse(full).netloc

                if entry.get("company_name") or entry.get("company_domain"):
                    entry.setdefault("first_name", "")
                    entry.setdefault("last_name", "")
                    entry.setdefault("source", "directory")
                    entry.setdefault("confidence_score", 0.5)
                    results.append(entry)

        except Exception as exc:
            logger.error("Directory page parse error: %s", exc)

        return results

    def _find_next_page(self, html: str, config: dict, base_url: str) -> Optional[str]:
        """Return the URL of the next listing page, or None if not found."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            link = soup.select_one(config["next_page_selector"])
            if link and link.get("href"):
                return urljoin(base_url, link["href"])
        except Exception:
            pass
        return None

    async def scrape(
        self, directory_url: str, config: Optional[dict] = None
    ) -> list[dict]:
        """
        Scrape a directory starting at *directory_url*.

        Parameters
        ----------
        directory_url: Starting URL of the directory listing.
        config:        Optional dict of CSS selectors that override DEFAULT_CONFIG.
                       Useful for targeting specific directory sites.

        Returns
        -------
        List of raw lead / company dicts compatible with LeadCreateDTO.
        """
        merged = {**DEFAULT_CONFIG, **(config or {})}
        max_pages: int = merged.get("max_pages", 5)
        scraper = self._get_scraper()

        all_results: list[dict] = []
        current_url = directory_url

        for page_num in range(max_pages):
            logger.info("Scraping directory page %d: %s", page_num + 1, current_url)
            response = await scraper.fetch_with_retry(current_url)

            if not response.is_success():
                logger.warning(
                    "Failed to fetch directory page %s (status=%d)",
                    current_url, response.status_code,
                )
                break

            # Phase 3: use LLM extraction when engine is injected
            if self._extraction_engine is not None:
                try:
                    extracted = await self._extraction_engine.extract(current_url, response.html)
                    page_results = []
                    for person in extracted.people:
                        entry: dict = {
                            "first_name": person.first_name or "",
                            "last_name": person.last_name or "",
                            "email": person.email,
                            "phone": person.phone,
                            "job_title": person.job_title,
                            "source": "directory",
                            "confidence_score": extracted.confidence,
                        }
                        if extracted.company:
                            entry["company_name"] = extracted.company.name
                            entry["company_domain"] = extracted.company.domain
                        page_results.append(entry)
                    if not page_results:
                        page_results = self._parse_page(response.html, merged, directory_url)
                except Exception as exc:
                    logger.error("LLM extraction failed, using BS4 fallback: %s", exc)
                    page_results = self._parse_page(response.html, merged, directory_url)
            else:
                page_results = self._parse_page(response.html, merged, directory_url)
            all_results.extend(page_results)
            logger.info(
                "Page %d: %d entries found (total so far: %d)",
                page_num + 1, len(page_results), len(all_results),
            )

            if not page_results:
                break

            next_url = self._find_next_page(response.html, merged, directory_url)
            if not next_url or next_url == current_url:
                break
            current_url = next_url

        logger.info(
            "Directory scrape complete: %d entries from %s", len(all_results), directory_url
        )
        return all_results
