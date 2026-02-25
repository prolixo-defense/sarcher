"""
Tests for LLMClient — token counting and structured extraction.

LLM calls are fully mocked; no Ollama or cloud API required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from src.infrastructure.llm.llm_client import LLMClient


class _SimpleModel(BaseModel):
    name: str
    value: int = 0


def _mock_settings(
    model="ollama/llama3.1:8b",
    base_url="http://localhost:11434",
    temperature=0.1,
    max_tokens=4000,
):
    s = MagicMock()
    s.llm_model = model
    s.llm_base_url = base_url
    s.llm_temperature = temperature
    s.llm_max_tokens = max_tokens
    return s


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def test_count_tokens_returns_positive_int():
    client = LLMClient(settings=_mock_settings())
    count = client.count_tokens("Hello, world! This is a test.")
    assert isinstance(count, int)
    assert count > 0


def test_count_tokens_increases_with_text_length():
    client = LLMClient(settings=_mock_settings())
    short = client.count_tokens("Hi")
    long = client.count_tokens("Hi " * 200)
    assert long > short


def test_count_tokens_fallback_on_tiktoken_error():
    """Should return a character-based estimate when tiktoken fails."""
    client = LLMClient(settings=_mock_settings())
    with patch("tiktoken.get_encoding", side_effect=Exception("unavailable")):
        count = client.count_tokens("Hello world, this is a test string of decent length.")
    assert isinstance(count, int)
    assert count > 0


# ---------------------------------------------------------------------------
# extract_structured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_structured_returns_pydantic_model():
    client = LLMClient(settings=_mock_settings())
    expected = _SimpleModel(name="Alice", value=42)

    mock_instructor_client = MagicMock()
    mock_instructor_client.chat.completions.create = AsyncMock(return_value=expected)

    with patch.object(client, "_get_client", return_value=mock_instructor_client):
        result = await client.extract_structured(
            content="Alice is 42 years old",
            response_model=_SimpleModel,
        )

    assert result.name == "Alice"
    assert result.value == 42


@pytest.mark.asyncio
async def test_extract_structured_passes_system_prompt():
    """System prompt should appear as the first message with role='system'."""
    client = LLMClient(settings=_mock_settings())

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return _SimpleModel(name="Bob")

    mock_inst = MagicMock()
    mock_inst.chat.completions.create = _capture

    with patch.object(client, "_get_client", return_value=mock_inst):
        await client.extract_structured(
            content="Extract Bob",
            response_model=_SimpleModel,
            system_prompt="You are a precise extractor.",
        )

    messages = captured.get("messages", [])
    system_msgs = [m for m in messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert "extractor" in system_msgs[0]["content"]


@pytest.mark.asyncio
async def test_extract_structured_passes_api_base_when_configured():
    """api_base should be set in the kwargs when llm_base_url is not empty."""
    client = LLMClient(settings=_mock_settings(base_url="http://localhost:11434"))

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return _SimpleModel(name="x")

    mock_inst = MagicMock()
    mock_inst.chat.completions.create = _capture

    with patch.object(client, "_get_client", return_value=mock_inst):
        await client.extract_structured(content="test", response_model=_SimpleModel)

    assert captured.get("api_base") == "http://localhost:11434"


@pytest.mark.asyncio
async def test_extract_structured_no_api_base_when_url_empty():
    """api_base should NOT be set when llm_base_url is empty."""
    client = LLMClient(settings=_mock_settings(base_url=""))

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return _SimpleModel(name="y")

    mock_inst = MagicMock()
    mock_inst.chat.completions.create = _capture

    with patch.object(client, "_get_client", return_value=mock_inst):
        await client.extract_structured(content="test", response_model=_SimpleModel)

    assert "api_base" not in captured


@pytest.mark.asyncio
async def test_extract_structured_uses_custom_temperature():
    client = LLMClient(settings=_mock_settings(temperature=0.5))

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return _SimpleModel(name="z")

    mock_inst = MagicMock()
    mock_inst.chat.completions.create = _capture

    with patch.object(client, "_get_client", return_value=mock_inst):
        await client.extract_structured(
            content="test",
            response_model=_SimpleModel,
            temperature=0.9,
        )

    # Explicit temperature override should win
    assert captured.get("temperature") == 0.9
