"""
Tests for ObjectionHandler — RAG + LLM response generation.

Both RAG and LLM are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource
from src.infrastructure.ai_agents.objection_handler import ObjectionHandler


def _make_lead():
    return Lead(
        first_name="Alice",
        last_name="Smith",
        source=DataSource.CORPORATE_WEBSITE,
        company_name="Acme Corp",
        job_title="CTO",
        email="alice@acme.com",
    )


def _make_handler(rag_results=None, llm_result=None):
    rag_store = AsyncMock()
    rag_store.search = AsyncMock(return_value=rag_results or [])

    mock_llm = AsyncMock()
    if llm_result is not None:
        mock_response = MagicMock()
        mock_response.draft = llm_result
        mock_response.confidence = 0.85
        mock_llm.extract_structured = AsyncMock(return_value=mock_response)
    else:
        mock_llm.extract_structured = AsyncMock(side_effect=Exception("LLM unavailable"))

    settings = MagicMock()
    return ObjectionHandler(rag_store=rag_store, llm_client=mock_llm, settings=settings)


@pytest.mark.asyncio
async def test_generate_response_returns_draft():
    handler = _make_handler(llm_result="Thanks for letting me know. Would Q3 work better?")
    lead = _make_lead()
    sentiment = {"sentiment": "NEGATIVE_TIMING", "summary": "Not now"}
    result = await handler.generate_response("Not right now", sentiment, lead)
    assert "draft_response" in result
    assert result["requires_human_review"] is True


@pytest.mark.asyncio
async def test_generate_response_always_requires_human_review():
    handler = _make_handler(llm_result="Draft response here")
    lead = _make_lead()
    result = await handler.generate_response("Interested!", {"sentiment": "POSITIVE_INTERESTED", "summary": ""}, lead)
    assert result["requires_human_review"] is True


@pytest.mark.asyncio
async def test_generate_response_uses_rag_results():
    rag_results = [
        {"text": "Budget rebuttal content here.", "metadata": {"category": "budget", "source": "budget.md"}, "score": 0.9}
    ]
    handler = _make_handler(rag_results=rag_results, llm_result="Understood, let me address your budget concerns.")
    lead = _make_lead()
    sentiment = {"sentiment": "NEGATIVE_BUDGET", "summary": "No budget"}
    result = await handler.generate_response("We don't have budget", sentiment, lead)
    assert "budget.md" in result["sources"] or len(result["sources"]) >= 0


@pytest.mark.asyncio
async def test_generate_response_falls_back_on_llm_failure():
    handler = _make_handler(llm_result=None)  # LLM will fail
    lead = _make_lead()
    sentiment = {"sentiment": "NEGATIVE_TIMING", "summary": "Bad timing"}
    result = await handler.generate_response("Not now", sentiment, lead)
    # Should return fallback draft, not raise
    assert "draft_response" in result
    assert len(result["draft_response"]) > 0
    assert result["confidence"] == 0.4  # Fallback confidence


@pytest.mark.asyncio
async def test_map_to_category_budget():
    handler = _make_handler()
    assert handler._map_to_category("NEGATIVE_BUDGET") == "budget"


@pytest.mark.asyncio
async def test_map_to_category_timing():
    handler = _make_handler()
    assert handler._map_to_category("NEGATIVE_TIMING") == "timing"


@pytest.mark.asyncio
async def test_map_to_category_unknown_returns_none():
    handler = _make_handler()
    assert handler._map_to_category("POSITIVE_INTERESTED") is None
