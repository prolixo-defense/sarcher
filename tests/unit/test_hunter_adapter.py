"""
Tests for HunterAdapter — email discovery and verification.

All HTTP calls are mocked; no real network access required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.enrichment.hunter_adapter import HunterAdapter


def _settings(api_key="test_hunter_key"):
    s = MagicMock()
    s.hunter_api_key = api_key
    return s


def _mock_httpx_get(status_code: int, json_body: dict):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# find_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_email_returns_dict_on_success():
    adapter = HunterAdapter(settings=_settings())
    body = {
        "data": {
            "email": "alice@acme.com",
            "confidence": 92,
            "first_name": "Alice",
            "last_name": "Smith",
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.find_email("Alice", "Smith", "acme.com")

    assert result is not None
    assert result["email"] == "alice@acme.com"
    assert result["confidence"] == 92


@pytest.mark.asyncio
async def test_find_email_returns_none_without_api_key():
    adapter = HunterAdapter(settings=_settings(api_key=""))
    result = await adapter.find_email("Alice", "Smith", "acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_returns_none_when_email_is_null():
    adapter = HunterAdapter(settings=_settings())
    body = {"data": {"email": None}}
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.find_email("Alice", "Smith", "acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_returns_none_on_400():
    adapter = HunterAdapter(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(400, {})):
        result = await adapter.find_email("Alice", "Smith", "acme.com")
    assert result is None


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_email_returns_valid_status():
    adapter = HunterAdapter(settings=_settings())
    body = {"data": {"status": "valid", "score": 95}}
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.verify_email("alice@acme.com")

    assert result["status"] == "valid"
    assert result["score"] == 95
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_verify_email_returns_unknown_without_key():
    adapter = HunterAdapter(settings=_settings(api_key=""))
    result = await adapter.verify_email("alice@acme.com")
    assert result["status"] == "unknown"
    assert result["is_valid"] is False


@pytest.mark.asyncio
async def test_verify_email_accept_all_is_valid():
    adapter = HunterAdapter(settings=_settings())
    body = {"data": {"status": "accept_all", "score": 60}}
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.verify_email("bob@corp.com")
    assert result["is_valid"] is True


# ---------------------------------------------------------------------------
# domain_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_search_returns_list():
    adapter = HunterAdapter(settings=_settings())
    body = {
        "data": {
            "emails": [
                {"value": "alice@acme.com", "first_name": "Alice", "last_name": "Smith", "type": "personal"},
                {"value": "bob@acme.com", "first_name": "Bob", "last_name": "Jones", "type": "generic"},
            ]
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.domain_search("acme.com")

    assert len(result) == 2
    emails = [r["email"] for r in result]
    assert "alice@acme.com" in emails


@pytest.mark.asyncio
async def test_domain_search_returns_empty_without_key():
    adapter = HunterAdapter(settings=_settings(api_key=""))
    result = await adapter.domain_search("acme.com")
    assert result == []


@pytest.mark.asyncio
async def test_domain_search_filters_entries_without_email():
    adapter = HunterAdapter(settings=_settings())
    body = {
        "data": {
            "emails": [
                {"value": "alice@acme.com", "first_name": "Alice", "last_name": "Smith", "type": "personal"},
                {"value": None, "first_name": "Ghost", "last_name": "User", "type": "generic"},
            ]
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx_get(200, body)):
        result = await adapter.domain_search("acme.com")

    assert len(result) == 1  # ghost user filtered out
