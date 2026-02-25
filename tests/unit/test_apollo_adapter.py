"""
Tests for ApolloAdapter — person match and organisation enrich.

All HTTP calls are mocked with httpx; no real network access required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.enrichment.apollo_adapter import ApolloAdapter


def _settings(api_key="test_apollo_key"):
    s = MagicMock()
    s.apollo_api_key = api_key
    return s


def _mock_httpx(status_code: int, json_body: dict):
    """Return a context-manager mock for httpx.AsyncClient that yields a mock response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# match_person
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_person_returns_dict_on_success():
    adapter = ApolloAdapter(settings=_settings())
    body = {
        "person": {
            "email": "alice@acme.com",
            "title": "CEO",
            "linkedin_url": "https://linkedin.com/in/alice",
            "phone_numbers": [{"sanitized_number": "+15551234567"}],
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body)):
        result = await adapter.match_person("Alice", "Smith", "acme.com")

    assert result is not None
    assert result["email"] == "alice@acme.com"
    assert result["job_title"] == "CEO"
    assert result["linkedin_url"] == "https://linkedin.com/in/alice"


@pytest.mark.asyncio
async def test_match_person_returns_none_without_api_key():
    adapter = ApolloAdapter(settings=_settings(api_key=""))
    result = await adapter.match_person("Alice", "Smith", "acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_match_person_returns_none_on_404():
    adapter = ApolloAdapter(settings=_settings())
    with patch("httpx.AsyncClient", return_value=_mock_httpx(404, {})):
        result = await adapter.match_person("Alice", "Smith", "acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_match_person_returns_none_when_person_empty():
    adapter = ApolloAdapter(settings=_settings())
    body = {"person": None}
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body)):
        result = await adapter.match_person("Alice", "Smith", "acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_match_person_handles_no_phone_numbers():
    adapter = ApolloAdapter(settings=_settings())
    body = {
        "person": {
            "email": "alice@acme.com",
            "title": "VP",
            "linkedin_url": None,
            "phone_numbers": [],
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body)):
        result = await adapter.match_person("Alice", "Smith", "acme.com")

    assert result is not None
    assert result["phone"] is None


# ---------------------------------------------------------------------------
# enrich_organization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_organization_returns_dict_on_success():
    adapter = ApolloAdapter(settings=_settings())
    body = {
        "organization": {
            "name": "Acme Corp",
            "industry": "Technology",
            "estimated_num_employees": 500,
            "annual_revenue_printed": "$10M",
            "current_technologies": [{"name": "Python"}, {"name": "React"}],
            "city": "San Francisco",
        }
    }
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body)):
        result = await adapter.enrich_organization("acme.com")

    assert result is not None
    assert result["name"] == "Acme Corp"
    assert result["industry"] == "Technology"
    assert "Python" in result["technologies"]
    assert result["location"] == "San Francisco"


@pytest.mark.asyncio
async def test_enrich_organization_returns_none_without_key():
    adapter = ApolloAdapter(settings=_settings(api_key=""))
    result = await adapter.enrich_organization("acme.com")
    assert result is None


@pytest.mark.asyncio
async def test_enrich_organization_returns_none_on_empty_org():
    adapter = ApolloAdapter(settings=_settings())
    body = {"organization": {}}
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body)):
        result = await adapter.enrich_organization("acme.com")
    assert result is None
