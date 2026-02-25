"""
Tests for HtmlPreprocessor — HTML cleaning and Markdown conversion.
All external libraries (trafilatura, markdownify, tiktoken) may be real or mocked.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.infrastructure.llm.html_preprocessor import HtmlPreprocessor

SAMPLE_HTML = """
<html><head><title>Team</title></head>
<body>
  <nav>Nav links here — ignored</nav>
  <main>
    <h1>Our Team</h1>
    <div class="team-member">
      <h3>Alice Johnson</h3>
      <p>Chief Executive Officer</p>
    </div>
    <div class="team-member">
      <h3>Bob Smith</h3>
      <p>CTO</p>
    </div>
  </main>
  <footer>Footer — ignored</footer>
  <script>console.log("noise");</script>
</body></html>
"""


def test_preprocess_returns_expected_keys():
    prep = HtmlPreprocessor()
    result = prep.preprocess(SAMPLE_HTML)
    assert "cleaned_markdown" in result
    assert "token_count" in result
    assert "extraction_method" in result


def test_preprocess_cleaned_markdown_is_string():
    prep = HtmlPreprocessor()
    result = prep.preprocess(SAMPLE_HTML)
    assert isinstance(result["cleaned_markdown"], str)


def test_preprocess_non_empty_for_real_html():
    prep = HtmlPreprocessor()
    result = prep.preprocess(SAMPLE_HTML)
    assert result["cleaned_markdown"].strip() != ""


def test_token_count_positive():
    prep = HtmlPreprocessor()
    result = prep.preprocess(SAMPLE_HTML)
    assert result["token_count"] > 0


def test_extraction_method_is_trafilatura_or_beautifulsoup():
    prep = HtmlPreprocessor()
    result = prep.preprocess(SAMPLE_HTML)
    assert result["extraction_method"] in ("trafilatura", "beautifulsoup")


def test_trafilatura_fallback_to_bs4():
    """When trafilatura returns None, should fall back to BeautifulSoup."""
    prep = HtmlPreprocessor()
    with patch.object(HtmlPreprocessor, "_try_trafilatura", return_value=None):
        result = prep.preprocess(SAMPLE_HTML)
    assert result["extraction_method"] == "beautifulsoup"
    assert result["cleaned_markdown"].strip() != ""


def test_trafilatura_used_when_it_succeeds():
    """When trafilatura returns content, extraction_method should be 'trafilatura'."""
    prep = HtmlPreprocessor()
    with patch.object(HtmlPreprocessor, "_try_trafilatura", return_value="Extracted content"):
        result = prep.preprocess(SAMPLE_HTML)
    assert result["extraction_method"] == "trafilatura"


def test_truncate_to_max_tokens():
    """Output should be capped at max_tokens."""
    prep = HtmlPreprocessor()
    long_html = "<p>" + ("word " * 2000) + "</p>"
    result = prep.preprocess(long_html, max_tokens=10)
    assert result["token_count"] <= 10


def test_normalize_whitespace_collapses_blank_lines():
    prep = HtmlPreprocessor()
    messy = "line one\n\n\n\n\nline two"
    normalized = prep._normalize_whitespace(messy)
    assert "\n\n\n" not in normalized
    assert "line one" in normalized
    assert "line two" in normalized


def test_count_tokens_returns_positive_int():
    prep = HtmlPreprocessor()
    count = prep._count_tokens("Hello, world! This is a test sentence.")
    assert isinstance(count, int)
    assert count > 0


def test_truncate_result_shorter_than_original():
    prep = HtmlPreprocessor()
    long_text = "The quick brown fox jumps over the lazy dog. " * 200
    truncated = prep._truncate_to_tokens(long_text, max_tokens=20)
    assert len(truncated) < len(long_text)


def test_count_tokens_fallback_without_tiktoken():
    """Should return a length-based estimate if tiktoken is unavailable."""
    prep = HtmlPreprocessor()
    text = "a" * 400  # 400 chars → ~100 token estimate
    with patch("tiktoken.get_encoding", side_effect=ImportError("no tiktoken")):
        count = prep._count_tokens(text)
    assert count > 0
    assert isinstance(count, int)


def test_to_markdown_converts_html_tags():
    prep = HtmlPreprocessor()
    html = "<h1>Title</h1><p>Some text</p>"
    md = prep._to_markdown(html)
    # Should contain the text content
    assert "Title" in md
    assert "Some text" in md


def test_to_markdown_passthrough_for_plain_text():
    prep = HtmlPreprocessor()
    plain = "Just plain text without HTML tags"
    result = prep._to_markdown(plain)
    assert "plain text" in result
