"""
Tests for CorporateWebsiteAdapter — HTML parsing and email extraction.

All HTTP calls are mocked; no network access required.
"""
import pytest
from unittest.mock import AsyncMock, patch

from src.infrastructure.scrapers.base_scraper import ScrapedResponse
from src.infrastructure.scrapers.adapters.corporate_website import CorporateWebsiteAdapter

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

TEAM_PAGE_HTML = """
<html><body>
  <div class="team-member">
    <h3>Alice Johnson</h3>
    <p>Chief Executive Officer</p>
    <a href="mailto:alice@acme.com">alice@acme.com</a>
  </div>
  <div class="team-member">
    <h3>Bob Smith</h3>
    <p>Head of Engineering</p>
    <a href="https://linkedin.com/in/bobsmith">LinkedIn</a>
  </div>
  <div class="team-member">
    <h3>Carol Lee</h3>
    <p>VP Sales</p>
  </div>
</body></html>
"""

EMAIL_ONLY_PAGE_HTML = """
<html><body>
  <p>Contact us at sales@example.com or support@example.com</p>
  <p>Phone: (555) 867-5309</p>
</body></html>
"""

NO_CONTACTS_HTML = """
<html><body>
  <h1>About Us</h1>
  <p>We are a great company with a great team.</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scraper_returning(html: str, status: int = 200):
    """Return a mocked HttpScraper that always returns the given HTML."""
    mock_scraper = AsyncMock()
    mock_response = ScrapedResponse(
        url="http://example.com/team",
        status_code=status,
        html=html,
    )
    mock_scraper.fetch_with_retry = AsyncMock(return_value=mock_response)
    return mock_scraper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_team_page_extracts_names():
    adapter = CorporateWebsiteAdapter(scraper=_make_scraper_returning(TEAM_PAGE_HTML))
    results = await adapter.scrape("acme.com")
    names = [(r["first_name"], r["last_name"]) for r in results if r.get("first_name")]
    assert ("Alice", "Johnson") in names
    assert ("Bob", "Smith") in names


@pytest.mark.asyncio
async def test_parse_team_page_extracts_job_titles():
    adapter = CorporateWebsiteAdapter(scraper=_make_scraper_returning(TEAM_PAGE_HTML))
    results = await adapter.scrape("acme.com")
    titles = [r.get("job_title") for r in results if r.get("job_title")]
    assert any("CEO" in (t or "") or "Chief Executive" in (t or "") for t in titles)


@pytest.mark.asyncio
async def test_fallback_email_extraction():
    """When no team cards are found, emails are extracted from raw text."""
    adapter = CorporateWebsiteAdapter(scraper=_make_scraper_returning(EMAIL_ONLY_PAGE_HTML))
    results = await adapter.scrape("example.com")
    emails = [r.get("email") for r in results if r.get("email")]
    assert "sales@example.com" in emails or "support@example.com" in emails


@pytest.mark.asyncio
async def test_no_contacts_returns_empty_list():
    # Simulate 404 for every team page
    mock_scraper = AsyncMock()
    mock_scraper.fetch_with_retry = AsyncMock(
        return_value=ScrapedResponse(url="http://example.com/team", status_code=404, html="")
    )
    adapter = CorporateWebsiteAdapter(scraper=mock_scraper)
    results = await adapter.scrape("example.com")
    assert results == []


@pytest.mark.asyncio
async def test_results_include_company_domain():
    adapter = CorporateWebsiteAdapter(scraper=_make_scraper_returning(TEAM_PAGE_HTML))
    results = await adapter.scrape("acme.com")
    for r in results:
        assert r.get("company_domain") == "acme.com"


@pytest.mark.asyncio
async def test_results_include_source_field():
    adapter = CorporateWebsiteAdapter(scraper=_make_scraper_returning(EMAIL_ONLY_PAGE_HTML))
    results = await adapter.scrape("example.com")
    for r in results:
        assert r.get("source") == "website"


@pytest.mark.asyncio
async def test_https_added_to_domain():
    """Domains without a scheme should get https:// prepended."""
    adapter = CorporateWebsiteAdapter()
    result = adapter._add_scheme("example.com")
    assert result == "https://example.com"


def test_add_scheme_preserves_existing():
    adapter = CorporateWebsiteAdapter.__new__(CorporateWebsiteAdapter)
    assert adapter._add_scheme("https://example.com") == "https://example.com"
    assert adapter._add_scheme("http://example.com") == "http://example.com"


def test_extract_emails():
    adapter = CorporateWebsiteAdapter.__new__(CorporateWebsiteAdapter)
    html = "Contact: alice@test.com and bob@test.org"
    emails = adapter._extract_emails(html)
    assert "alice@test.com" in emails
    assert "bob@test.org" in emails


def test_extract_phones():
    adapter = CorporateWebsiteAdapter.__new__(CorporateWebsiteAdapter)
    html = "Call us at (555) 123-4567 or 800-555-0199"
    phones = adapter._extract_phones(html)
    assert len(phones) >= 1
