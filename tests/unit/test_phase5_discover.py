"""
Phase 5 tests — Natural language discovery endpoint and Google search adapter.

Tests cover:
1. Query interpretation (LLM + heuristic fallback)
2. Discover endpoint (POST /api/discover)
3. SSE stream endpoint (GET /api/discover/{job_id}/stream)
4. Google search adapter (all providers)
5. Match & rank scoring
6. URL filtering
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.routes.discover import (
    QueryInterpretation,
    DiscoverResult,
    _heuristic_interpret,
    _fallback_queries,
    _is_useful_url,
    _match_and_rank,
    _classify_source,
    _truncate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """FastAPI test client with discover routes."""
    from src.api.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Heuristic interpretation
# ---------------------------------------------------------------------------


class TestHeuristicInterpret:
    def test_extracts_titles(self):
        result = _heuristic_interpret("marketing director at a SaaS company")
        assert "marketing" in result.target_titles or "director" in result.target_titles

    def test_extracts_industries(self):
        result = _heuristic_interpret("fintech startup founders")
        assert "fintech" in result.target_industries or "startup" in result.target_industries

    def test_produces_search_queries(self):
        result = _heuristic_interpret("VP Engineering at AI companies")
        assert len(result.search_queries) >= 1

    def test_keywords_populated(self):
        result = _heuristic_interpret("cto founder ai startup")
        assert len(result.keywords) >= 1

    def test_empty_query_does_not_raise(self):
        result = _heuristic_interpret("")
        assert isinstance(result, QueryInterpretation)


# ---------------------------------------------------------------------------
# Fallback query generation
# ---------------------------------------------------------------------------


class TestFallbackQueries:
    def test_returns_list(self):
        stub = QueryInterpretation(target_titles=["CEO"], target_industries=["SaaS"])
        queries = _fallback_queries("CEO SaaS companies", stub)
        assert isinstance(queries, list)
        assert len(queries) >= 1

    def test_caps_at_eight(self):
        stub = QueryInterpretation(target_titles=["CTO"])
        queries = _fallback_queries("CTO", stub)
        assert len(queries) <= 9  # 8 base + 1 optional title query

    def test_includes_base_query(self):
        stub = QueryInterpretation()
        queries = _fallback_queries("marketing director NYC", stub)
        combined = " ".join(queries)
        assert "marketing" in combined.lower()


# ---------------------------------------------------------------------------
# URL filtering
# ---------------------------------------------------------------------------


class TestIsUsefulUrl:
    def test_allows_company_page(self):
        assert _is_useful_url("https://acme.com/team") is True

    def test_blocks_google(self):
        assert _is_useful_url("https://www.google.com/search?q=test") is False

    def test_blocks_youtube(self):
        assert _is_useful_url("https://youtube.com/watch?v=abc") is False

    def test_blocks_wikipedia(self):
        assert _is_useful_url("https://en.wikipedia.org/wiki/Marketing") is False

    def test_allows_linkedin(self):
        # LinkedIn is useful even though it may be blocked; filtering is about domain relevance
        assert _is_useful_url("https://linkedin.com/in/janesmith") is True


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------


class TestClassifySource:
    def test_linkedin(self):
        assert _classify_source("https://linkedin.com/in/foo") == "linkedin"

    def test_directory(self):
        assert _classify_source("https://example.com/directory/members") == "directory"

    def test_website_default(self):
        assert _classify_source("https://acme.com/team") == "website"


# ---------------------------------------------------------------------------
# Match & rank
# ---------------------------------------------------------------------------


class TestMatchAndRank:
    def _make_result(self, name, title=None, company=None, location=None, email=None) -> DiscoverResult:
        return DiscoverResult(
            name=name,
            title=title,
            company=company,
            location=location,
            email=email,
            source="website",
            confidence=0.8,
        )

    def test_returns_at_most_max_results(self):
        people = [self._make_result(f"Person {i}", title="Engineer") for i in range(20)]
        interp = QueryInterpretation(target_titles=["Engineer"])
        result = _match_and_rank(people, interp, max_results=5)
        assert len(result) <= 5

    def test_title_match_scores_higher(self):
        matched = self._make_result("Alice", title="Marketing Director")
        unmatched = self._make_result("Bob", title="Junior Developer")
        interp = QueryInterpretation(target_titles=["Marketing Director"])
        ranked = _match_and_rank([unmatched, matched], interp, max_results=10)
        assert ranked[0].name == "Alice"

    def test_email_bonus_applied(self):
        with_email = self._make_result("Alice", title="Director", email="alice@co.com")
        without_email = self._make_result("Bob", title="Director")
        interp = QueryInterpretation(target_titles=["Director"])
        ranked = _match_and_rank([without_email, with_email], interp, max_results=10)
        alice = next(r for r in ranked if r.name == "Alice")
        bob = next(r for r in ranked if r.name == "Bob")
        assert alice.relevance_score >= bob.relevance_score

    def test_scores_attached_to_results(self):
        people = [self._make_result("Alice", title="CTO")]
        interp = QueryInterpretation(target_titles=["CTO"])
        result = _match_and_rank(people, interp, max_results=10)
        assert result[0].relevance_score >= 0

    def test_empty_input_returns_empty(self):
        result = _match_and_rank([], QueryInterpretation(), max_results=10)
        assert result == []

    def test_no_constraints_gives_neutral_score(self):
        people = [self._make_result("Alice", title="Director")]
        interp = QueryInterpretation()  # no constraints
        result = _match_and_rank(people, interp, max_results=10)
        assert result[0].relevance_score > 0


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_string_truncated(self):
        s = _truncate("a" * 20, 10)
        assert len(s) <= 10
        assert s.endswith("...")


# ---------------------------------------------------------------------------
# Discover endpoint
# ---------------------------------------------------------------------------


class TestDiscoverEndpoint:
    """
    NOTE: We mock _run_discovery_pipeline in all POST tests because the
    background task makes real network calls (LLM + DuckDuckGo) which would
    cause the test to hang.  The background task's internal logic is tested
    separately via the integration tests below.
    """

    def test_post_returns_job_id(self, client):
        with patch(
            "src.api.routes.discover._run_discovery_pipeline",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                "/api/discover",
                json={"query": "marketing directors at SaaS companies", "save": False},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "stream_url" in data

    def test_stream_url_format(self, client):
        with patch(
            "src.api.routes.discover._run_discovery_pipeline",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                "/api/discover",
                json={"query": "CTO at fintech startups", "save": False},
            )
        data = resp.json()
        job_id = data["job_id"]
        assert data["stream_url"] == f"/api/discover/{job_id}/stream"

    def test_missing_query_returns_422(self, client):
        resp = client.post("/api/discover", json={})
        assert resp.status_code == 422

    def test_stream_endpoint_exists(self, client):
        """SSE endpoint returns 200 and emits events (queue pre-populated)."""
        import time
        import uuid

        import src.api.routes.discover as discover_mod

        # Pre-populate the job queue with a "complete" event so the SSE generator
        # exits immediately without waiting for the pipeline.
        job_id = str(uuid.uuid4())
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait({
            "stage": "complete",
            "message": "Done! Found 0 matching leads.",
            "progress": 100,
            "results": [],
            "stats": {
                "pages_scraped": 0, "people_found": 0, "people_matched": 0,
                "people_enriched": 0, "time_elapsed_seconds": 0.1,
            },
            "query_interpretation": {},
        })
        discover_mod._job_queues[job_id] = q
        discover_mod._job_created[job_id] = time.monotonic()

        stream_resp = client.get(
            f"/api/discover/{job_id}/stream",
            headers={"Accept": "text/event-stream"},
        )
        assert stream_resp.status_code == 200
        assert b"complete" in stream_resp.content

    def test_stream_unknown_job_returns_error_event(self, client):
        resp = client.get(
            "/api/discover/nonexistent-job-id/stream",
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert b"error" in resp.content


# ---------------------------------------------------------------------------
# Google search adapter
# ---------------------------------------------------------------------------


class TestGoogleSearchAdapter:
    @pytest.mark.asyncio
    async def test_duckduckgo_returns_list(self):
        """DuckDuckGo fallback returns a list (may be empty if network unavailable)."""
        from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

        adapter = GoogleSearchAdapter.__new__(GoogleSearchAdapter)
        adapter._settings = MagicMock(
            serp_api_key="",
            google_cse_api_key="",
            google_cse_id="",
        )

        # Mock httpx to avoid real network calls
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = """
        <html><body>
          <div class="result">
            <a class="result__a" href="https://acme.com/team">Acme Team</a>
            <div class="result__snippet">Great SaaS company team page</div>
          </div>
          <div class="result">
            <a class="result__a" href="https://beta.com/about">Beta About</a>
            <div class="result__snippet">Another company</div>
          </div>
        </body></html>
        """

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await adapter._duckduckgo_search("SaaS company team page", 5)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_auto_selects_serpapi_when_key_set(self):
        from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

        adapter = GoogleSearchAdapter.__new__(GoogleSearchAdapter)
        adapter._settings = MagicMock(
            serp_api_key="test-key",
            google_cse_api_key="",
            google_cse_id="",
        )

        with patch.object(adapter, "_serpapi_search", new_callable=AsyncMock) as mock_serp:
            mock_serp.return_value = [{"url": "https://example.com", "title": "Ex", "snippet": ""}]
            results = await adapter.search("test query", 5)

        mock_serp.assert_called_once()
        assert results == [{"url": "https://example.com", "title": "Ex", "snippet": ""}]

    @pytest.mark.asyncio
    async def test_search_auto_selects_cse_when_keys_set(self):
        from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

        adapter = GoogleSearchAdapter.__new__(GoogleSearchAdapter)
        adapter._settings = MagicMock(
            serp_api_key="",
            google_cse_api_key="cse-key",
            google_cse_id="cx-id",
        )

        with patch.object(adapter, "_google_cse_search", new_callable=AsyncMock) as mock_cse:
            mock_cse.return_value = [{"url": "https://example.com", "title": "Ex", "snippet": ""}]
            results = await adapter.search("test query", 5)

        mock_cse.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_falls_back_to_duckduckgo(self):
        from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

        adapter = GoogleSearchAdapter.__new__(GoogleSearchAdapter)
        adapter._settings = MagicMock(
            serp_api_key="",
            google_cse_api_key="",
            google_cse_id="",
        )

        with patch.object(adapter, "_duckduckgo_search", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []
            await adapter.search("test query", 5)

        mock_ddg.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: discover pipeline with mocked scraping
# ---------------------------------------------------------------------------


class TestDiscoverPipelineIntegration:
    @pytest.mark.asyncio
    async def test_interpret_query_falls_back_on_llm_failure(self):
        """When LLM fails, heuristic interpretation is used."""
        from src.api.routes.discover import _interpret_query

        with patch("src.infrastructure.llm.llm_client.LLMClient") as MockLLM:
            MockLLM.return_value.extract_structured = AsyncMock(
                side_effect=Exception("LLM unavailable")
            )
            result = await _interpret_query("marketing directors at SaaS startups")

        assert isinstance(result, QueryInterpretation)
        assert len(result.search_queries) >= 1

    @pytest.mark.asyncio
    async def test_search_for_urls_handles_search_failure(self):
        """When search fails, returns empty list without raising."""
        from src.api.routes.discover import _search_for_urls

        with patch(
            "src.infrastructure.scrapers.adapters.google_search.GoogleSearchAdapter.search",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            result = await _search_for_urls(["test query"])

        assert result == []
