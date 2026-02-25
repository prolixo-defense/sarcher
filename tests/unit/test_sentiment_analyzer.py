"""
Tests for SentimentAnalyzer — LLM-powered reply classification.

LLM client is mocked; keyword matching tests run without mocking.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.ai_agents.sentiment_analyzer import SentimentAnalyzer


def _settings():
    s = MagicMock()
    s.llm_model = "ollama/llama3.1:8b"
    s.llm_base_url = "http://localhost:11434"
    s.llm_temperature = 0.1
    s.llm_max_tokens = 1000
    return s


# ---------------------------------------------------------------------------
# Keyword-based opt-out tests (no LLM needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_detects_opt_out_keyword_unsubscribe():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = await analyzer.analyze("Please unsubscribe me from your list.")
    assert result["sentiment"] == "OPT_OUT"
    assert result["suggested_action"] == "opt_out"
    assert result["urgency"] == "immediate"


@pytest.mark.asyncio
async def test_analyze_detects_opt_out_keyword_remove_me():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = await analyzer.analyze("Please remove me from your emails.")
    assert result["sentiment"] == "OPT_OUT"


@pytest.mark.asyncio
async def test_analyze_detects_opt_out_case_insensitive():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = await analyzer.analyze("PLEASE STOP EMAILING ME")
    assert result["sentiment"] == "OPT_OUT"


@pytest.mark.asyncio
async def test_analyze_detects_bounce():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = await analyzer.analyze("Delivery Status Notification: undeliverable to user@example.com")
    assert result["sentiment"] == "BOUNCE"
    assert result["suggested_action"] == "stop"


# ---------------------------------------------------------------------------
# LLM-based tests (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_calls_llm_for_normal_reply():
    analyzer = SentimentAnalyzer(settings=_settings())

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        "sentiment": "POSITIVE_INTERESTED",
        "confidence": 0.9,
        "summary": "Prospect wants to chat.",
        "suggested_action": "reply",
        "urgency": "normal",
    }

    with patch("src.infrastructure.llm.llm_client.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        instance.extract_structured = AsyncMock(return_value=mock_result)
        result = await analyzer.analyze("This sounds interesting, let's chat!")

    assert result["sentiment"] in ("POSITIVE_INTERESTED", "NEUTRAL_QUESTION")


@pytest.mark.asyncio
async def test_analyze_falls_back_to_heuristic_on_llm_failure():
    analyzer = SentimentAnalyzer(settings=_settings())
    with patch("src.infrastructure.llm.llm_client.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        instance.extract_structured = AsyncMock(side_effect=Exception("LLM unavailable"))
        result = await analyzer.analyze("Yes, I'm interested in learning more!")
    # Should return a heuristic result, not raise
    assert "sentiment" in result
    assert "suggested_action" in result


@pytest.mark.asyncio
async def test_analyze_heuristic_auto_reply():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = analyzer._heuristic_classify("I'm out of the office until January 5th. Auto-reply.")
    assert result["sentiment"] == "AUTO_REPLY"


@pytest.mark.asyncio
async def test_analyze_heuristic_positive():
    analyzer = SentimentAnalyzer(settings=_settings())
    result = analyzer._heuristic_classify("Sounds good, tell me more about this!")
    assert result["sentiment"] == "POSITIVE_INTERESTED"
