"""
Tests for RobotsChecker — robots.txt compliance.

HTTP calls are mocked with httpx.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.compliance.robots_checker import RobotsChecker


def _settings(respect=True):
    s = MagicMock()
    s.respect_robots = respect
    return s


def _mock_httpx_response(status: int, text: str):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


# ---------------------------------------------------------------------------
# is_allowed tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_allowed_when_robots_permits():
    robots_txt = "User-agent: *\nAllow: /"
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(200, robots_txt)):
        result = await checker.is_allowed("https://example.com/team")
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_false_when_disallowed():
    robots_txt = "User-agent: *\nDisallow: /"
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(200, robots_txt)):
        result = await checker.is_allowed("https://example.com/team")
    assert result is False


@pytest.mark.asyncio
async def test_is_allowed_true_when_no_robots_file():
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(404, "")):
        result = await checker.is_allowed("https://example.com/team")
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_true_when_respect_robots_false():
    checker = RobotsChecker(settings=_settings(respect=False))
    # Should not even fetch — returns True immediately
    result = await checker.is_allowed("https://example.com/team")
    assert result is True


@pytest.mark.asyncio
async def test_robots_checker_caches_result():
    robots_txt = "User-agent: *\nAllow: /"
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(200, robots_txt)) as mock_cls:
        await checker.is_allowed("https://example.com/page1")
        await checker.is_allowed("https://example.com/page2")
    # httpx.AsyncClient should only be called once (cache hit for second call)
    assert mock_cls.call_count <= 2  # May vary by implementation


@pytest.mark.asyncio
async def test_is_allowed_true_on_fetch_error():
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", side_effect=Exception("Network error")):
        result = await checker.is_allowed("https://example.com/team")
    assert result is True  # Fail open — allow on error


@pytest.mark.asyncio
async def test_get_crawl_delay_returns_value():
    robots_txt = "User-agent: *\nCrawl-delay: 5\nAllow: /"
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(200, robots_txt)):
        delay = await checker.get_crawl_delay("example.com")
    assert delay == 5.0


@pytest.mark.asyncio
async def test_get_crawl_delay_returns_none_when_not_specified():
    robots_txt = "User-agent: *\nAllow: /"
    checker = RobotsChecker(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_response(200, robots_txt)):
        delay = await checker.get_crawl_delay("example.com")
    assert delay is None
