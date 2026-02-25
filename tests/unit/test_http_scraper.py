"""
Tests for HttpScraper — block detection, ScrapedResponse helpers, retry logic.

Network calls are mocked so these tests run without internet or curl_cffi.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.scrapers.base_scraper import BaseScraper, ScrapedResponse, BLOCK_KEYWORDS


# ---------------------------------------------------------------------------
# ScrapedResponse helpers
# ---------------------------------------------------------------------------


def test_scraped_response_is_success_200():
    r = ScrapedResponse(url="http://example.com", status_code=200, html="<html>ok</html>")
    assert r.is_success() is True


def test_scraped_response_is_success_blocked():
    r = ScrapedResponse(
        url="http://example.com", status_code=200, html="<html>captcha</html>", was_blocked=True
    )
    assert r.is_success() is False


def test_scraped_response_is_success_error():
    r = ScrapedResponse(
        url="http://example.com", status_code=200, html="ok", error="timeout"
    )
    assert r.is_success() is False


def test_scraped_response_is_success_4xx():
    for code in (400, 403, 404, 429, 500, 503):
        r = ScrapedResponse(url="http://example.com", status_code=code, html="")
        assert r.is_success() is False, f"Expected failure for status {code}"


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("keyword", [
    "captcha", "recaptcha", "cloudflare", "access denied",
    "too many requests", "unusual traffic", "are you a robot",
])
def test_detect_block_keywords(keyword):
    html = f"<html><body>Sorry, {keyword} page</body></html>"
    assert BaseScraper.detect_block(200, html, {}) is True


def test_detect_block_403():
    assert BaseScraper.detect_block(403, "<html>Forbidden</html>", {}) is True


def test_detect_block_429():
    assert BaseScraper.detect_block(429, "<html>Rate limited</html>", {}) is True


def test_detect_block_503():
    assert BaseScraper.detect_block(503, "<html>Service unavailable</html>", {}) is True


def test_detect_block_clean_200():
    html = "<html><body><h1>Welcome to Acme Corp</h1></body></html>"
    assert BaseScraper.detect_block(200, html, {}) is False


# ---------------------------------------------------------------------------
# HttpScraper — httpx fallback path (no curl_cffi required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_scraper_httpx_fallback_success():
    """When curl_cffi is unavailable the scraper falls back to httpx."""
    from src.infrastructure.scrapers.http_scraper import HttpScraper

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>Hello</body></html>"
    mock_response.headers = {}

    with (
        patch("src.infrastructure.scrapers.http_scraper.CURL_CFFI_AVAILABLE", False),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = HttpScraper(delay_min=0, delay_max=0)
        response = await scraper.fetch("http://example.com")

    assert response.status_code == 200
    assert response.is_success()
    assert "Hello" in response.html


@pytest.mark.asyncio
async def test_http_scraper_fetch_with_retry_succeeds_on_second_attempt():
    """fetch_with_retry should retry and return the first successful response."""
    from src.infrastructure.scrapers.http_scraper import HttpScraper

    call_count = 0

    async def fake_fetch(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ScrapedResponse(url=url, status_code=429, html="rate limited", was_blocked=True)
        return ScrapedResponse(url=url, status_code=200, html="<html>ok</html>")

    scraper = HttpScraper(delay_min=0, delay_max=0)
    scraper.fetch = fake_fetch

    response = await scraper.fetch_with_retry("http://example.com", max_retries=3)
    assert response.is_success()
    assert call_count == 2


@pytest.mark.asyncio
async def test_http_scraper_fetch_with_retry_exhausted():
    """fetch_with_retry returns the last bad response after all retries fail."""
    from src.infrastructure.scrapers.http_scraper import HttpScraper

    async def always_blocked(url, **kwargs):
        return ScrapedResponse(url=url, status_code=429, html="blocked", was_blocked=True)

    scraper = HttpScraper(delay_min=0, delay_max=0)
    scraper.fetch = always_blocked

    response = await scraper.fetch_with_retry("http://example.com", max_retries=2)
    assert not response.is_success()
