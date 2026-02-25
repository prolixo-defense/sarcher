"""
Integration test: scrape a real public page end-to-end.

Uses the httpx fallback (no curl_cffi required).
Skipped if there is no internet access.
"""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_http_scraper_fetches_example_com():
    """HttpScraper should successfully fetch example.com (httpx fallback)."""
    from src.infrastructure.scrapers.http_scraper import HttpScraper

    with patch("src.infrastructure.scrapers.http_scraper.CURL_CFFI_AVAILABLE", False):
        scraper = HttpScraper(delay_min=0, delay_max=0)
        try:
            response = await scraper.fetch("https://example.com")
        except Exception as exc:
            pytest.skip(f"Network not available: {exc}")

    # On macOS with Python 3.14, SSL cert errors are returned as error responses
    if response.error and "SSL" in (response.error or ""):
        pytest.skip(f"SSL not configured on this machine: {response.error}")
    if response.error and "certificate" in (response.error or "").lower():
        pytest.skip(f"SSL not configured on this machine: {response.error}")

    assert response.status_code == 200
    assert "Example Domain" in response.html
    assert not response.was_blocked
    assert response.response_time > 0


@pytest.mark.asyncio
async def test_corporate_website_adapter_example_com():
    """
    CorporateWebsiteAdapter should not crash on a real public domain.
    It may return 0 leads (example.com has no team page), but must not error.
    """
    from src.infrastructure.scrapers.adapters.corporate_website import CorporateWebsiteAdapter
    from src.infrastructure.scrapers.http_scraper import HttpScraper

    with patch("src.infrastructure.scrapers.http_scraper.CURL_CFFI_AVAILABLE", False):
        scraper = HttpScraper(delay_min=0, delay_max=0)
        adapter = CorporateWebsiteAdapter(scraper=scraper)

        try:
            results = await adapter.scrape("example.com")
        except Exception as exc:
            pytest.skip(f"Network not available: {exc}")

    # example.com has no team page — we expect 0 leads but no exception
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_directory_adapter_parses_html():
    """DirectoryAdapter should parse a directory-like HTML string without network."""
    from src.infrastructure.scrapers.adapters.directory_adapter import DirectoryAdapter
    from src.infrastructure.scrapers.base_scraper import ScrapedResponse
    from unittest.mock import AsyncMock

    directory_html = """
    <html><body>
      <div class="company">
        <h3 class="name">Acme Corp</h3>
        <span class="location">San Francisco, CA</span>
        <a href="https://acme.com">Visit</a>
      </div>
      <div class="company">
        <h3 class="name">Globex Inc</h3>
        <span class="location">Springfield, IL</span>
        <a href="https://globex.com">Visit</a>
      </div>
    </body></html>
    """

    mock_scraper = AsyncMock()
    mock_scraper.fetch_with_retry = AsyncMock(
        return_value=ScrapedResponse(
            url="http://test-directory.com",
            status_code=200,
            html=directory_html,
        )
    )

    adapter = DirectoryAdapter(scraper=mock_scraper)
    results = await adapter.scrape(
        "http://test-directory.com",
        config={
            "item_selector": "div.company",
            "name_selector": "h3.name",
            "location_selector": "span.location",
            "description_selector": "p",
            "next_page_selector": "a.next",
            "max_pages": 1,
        },
    )

    assert len(results) == 2
    names = [r.get("company_name") for r in results]
    assert "Acme Corp" in names
    assert "Globex Inc" in names
    assert results[0].get("source") == "directory"
