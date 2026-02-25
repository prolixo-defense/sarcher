"""
Tests for ExtractionEngine — page type detection and LLM extraction pipeline.

LLM calls are fully mocked via mock_llm_client.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.application.schemas.extraction_schemas import ExtractedPerson, PageExtractionResult
from src.infrastructure.llm.extraction_engine import ExtractionEngine


def _mock_preprocessor(markdown="## Our Team\n\nAlice Johnson — CEO\n"):
    prep = MagicMock()
    prep.preprocess.return_value = {
        "cleaned_markdown": markdown,
        "token_count": len(markdown) // 4,
        "extraction_method": "trafilatura",
    }
    return prep


def _make_result(
    people=None,
    page_type="team",
    confidence=0.9,
    company=None,
):
    return PageExtractionResult(
        people=people or [ExtractedPerson(full_name="Alice Johnson", job_title="CEO")],
        page_type=page_type,
        confidence=confidence,
        company=company,
    )


# ---------------------------------------------------------------------------
# Page type detection
# ---------------------------------------------------------------------------


def test_detect_team_url():
    engine = ExtractionEngine()
    assert engine._detect_page_type("https://example.com/team", "") == "team"


def test_detect_leadership_url():
    engine = ExtractionEngine()
    assert engine._detect_page_type("https://example.com/leadership", "") == "team"


def test_detect_about_url_with_team_content():
    engine = ExtractionEngine()
    pt = engine._detect_page_type(
        "https://example.com/about", "## Our Team\nMeet the team leaders here."
    )
    assert pt == "team"


def test_detect_linkedin_profile_url():
    engine = ExtractionEngine()
    assert engine._detect_page_type("https://www.linkedin.com/in/alice", "") == "profile"


def test_detect_directory_listing_from_content():
    engine = ExtractionEngine()
    content = "Company A, san francisco, ca\nCompany B, new york, ny\nCompany C, , tx"
    pt = engine._detect_page_type("https://directory.com/list", content)
    assert pt == "directory_listing"


def test_detect_default_about():
    engine = ExtractionEngine()
    pt = engine._detect_page_type("https://example.com/products", "We sell widgets globally.")
    assert pt == "about"


# ---------------------------------------------------------------------------
# Full extraction pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_calls_llm_and_returns_result():
    mock_llm = AsyncMock()
    mock_llm.extract_structured = AsyncMock(return_value=_make_result())

    engine = ExtractionEngine(llm_client=mock_llm, preprocessor=_mock_preprocessor())
    result = await engine.extract("https://example.com/team", "<html>Team</html>")

    assert isinstance(result, PageExtractionResult)
    mock_llm.extract_structured.assert_called_once()


@pytest.mark.asyncio
async def test_extract_returns_empty_on_llm_failure():
    mock_llm = AsyncMock()
    mock_llm.extract_structured = AsyncMock(side_effect=Exception("LLM unavailable"))

    engine = ExtractionEngine(llm_client=mock_llm, preprocessor=_mock_preprocessor())
    result = await engine.extract("https://example.com/team", "<html>Test</html>")

    assert isinstance(result, PageExtractionResult)
    assert result.confidence == 0.0
    assert result.people == []


@pytest.mark.asyncio
async def test_extract_uses_linkedin_prompt_for_linkedin_url():
    """ExtractionEngine should select the LinkedIn prompt for linkedin.com URLs."""
    mock_llm = AsyncMock()
    mock_llm.extract_structured = AsyncMock(
        return_value=PageExtractionResult(page_type="profile", confidence=0.9)
    )

    engine = ExtractionEngine(llm_client=mock_llm, preprocessor=_mock_preprocessor())
    await engine.extract("https://linkedin.com/in/alice", "<html>Profile</html>")

    call_kwargs = mock_llm.extract_structured.call_args
    system_prompt = call_kwargs.kwargs.get("system_prompt", "")
    assert "LinkedIn" in system_prompt or "profile" in system_prompt.lower()


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def test_post_process_splits_full_name_to_first_last():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Alice Johnson")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    assert processed.people[0].first_name == "Alice"
    assert processed.people[0].last_name == "Johnson"


def test_post_process_preserves_existing_first_last():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Alice J", first_name="Alice", last_name="Johnson")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    assert processed.people[0].last_name == "Johnson"


def test_post_process_removes_invalid_email():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Alice", email="not-valid-email")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    assert processed.people[0].email is None


def test_post_process_keeps_valid_email():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Alice", email="alice@example.com")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    assert processed.people[0].email == "alice@example.com"


def test_post_process_cleans_phone_noise():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Bob", phone="Call: (555) 123-4567 ext. 42")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    # Should keep digits and punctuation, strip "Call:" prefix
    phone = processed.people[0].phone
    assert phone is None or "Call:" not in phone


def test_post_process_drops_too_short_phone():
    engine = ExtractionEngine()
    person = ExtractedPerson(full_name="Carol", phone="123")
    result = PageExtractionResult(people=[person], page_type="team", confidence=0.8)
    processed = engine._post_process(result)
    assert processed.people[0].phone is None
