"""
Phase 6 tests — Scaled discovery pipeline.

Tests cover:
1. SAM.gov adapter (mocked HTTP)
2. Market segments configuration
3. Size estimator
4. Deduplication logic
5. Segment query generation
6. Segment inference from query
7. State code parsing
8. Job posting company extraction
9. Discover endpoint with new fields
10. Pipeline stats per-source breakdown
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes.discover import (
    DiscoverRequest,
    DiscoverResult,
    QueryInterpretation,
    _deduplicate_results,
    _estimate_sizes,
    _extract_companies_from_job_listing,
    _extract_domain,
    _infer_segments_from_query,
    _merge_results,
    _parse_state_code,
)
from src.application.services.size_estimator import (
    classify_size_band,
    estimate_employee_count_from_text,
    estimate_size_band,
)
from src.infrastructure.scrapers.adapters.market_segments import (
    SEGMENTS,
    get_all_segment_keys,
    get_naics_codes_for_segments,
    get_search_queries_for_segments,
    get_segment_config,
    get_target_titles_for_segments,
)
from src.infrastructure.scrapers.adapters.sam_gov_adapter import SAMGovAdapter


# ---------------------------------------------------------------------------
# Market Segments
# ---------------------------------------------------------------------------


class TestMarketSegments:
    def test_all_9_segments_defined(self):
        assert len(SEGMENTS) == 9

    def test_get_all_segment_keys(self):
        keys = get_all_segment_keys()
        assert "dib" in keys
        assert "fedramp" in keys
        assert "ai_compliance" in keys
        assert "mssp" in keys
        assert "grc" in keys
        assert len(keys) == 9

    def test_get_segment_config_valid(self):
        dib = get_segment_config("dib")
        assert dib is not None
        assert dib["label"] == "Defense Industrial Base"
        assert len(dib["naics_codes"]) > 0
        assert len(dib["search_templates"]) == 10
        assert len(dib["target_titles"]) > 0
        assert len(dib["keywords"]) > 0

    def test_get_segment_config_invalid(self):
        assert get_segment_config("nonexistent") is None

    def test_naics_codes_deduplication(self):
        codes = get_naics_codes_for_segments(["dib", "fedramp"])
        # 541512 appears in both; should not be duplicated
        assert codes.count("541512") == 1

    def test_naics_codes_empty_segments(self):
        codes = get_naics_codes_for_segments([])
        assert codes == []

    def test_search_queries_geography(self):
        queries = get_search_queries_for_segments(["dib"], "VA", include_job_queries=False)
        assert len(queries) == 10
        # All queries should contain "VA"
        assert all("VA" in q for q in queries)

    def test_search_queries_no_geography(self):
        queries = get_search_queries_for_segments(["dib"], "", include_job_queries=False)
        assert len(queries) == 10
        # No "{geo}" placeholder should remain
        assert not any("{geo}" in q for q in queries)

    def test_search_queries_include_jobs(self):
        queries = get_search_queries_for_segments(["dib"], "", include_job_queries=True)
        assert len(queries) > 10  # 10 search + 5 job templates

    def test_target_titles_deduplication(self):
        titles = get_target_titles_for_segments(["dib", "fedramp"])
        # CEO appears in both segments; should not be duplicated (case-insensitive)
        ceo_count = sum(1 for t in titles if t.upper() == "CEO")
        assert ceo_count == 1

    def test_every_segment_has_required_keys(self):
        required = {"label", "naics_codes", "search_templates", "job_search_templates", "target_titles", "keywords"}
        for key, seg in SEGMENTS.items():
            for req in required:
                assert req in seg, f"Segment '{key}' missing '{req}'"

    def test_every_segment_has_10_search_templates(self):
        for key, seg in SEGMENTS.items():
            assert len(seg["search_templates"]) == 10, f"Segment '{key}' has {len(seg['search_templates'])} templates, expected 10"

    def test_search_templates_have_geo_placeholder(self):
        for key, seg in SEGMENTS.items():
            for template in seg["search_templates"]:
                assert "{geo}" in template, f"Segment '{key}' template missing {{geo}}: {template}"


# ---------------------------------------------------------------------------
# SAM.gov Adapter
# ---------------------------------------------------------------------------


class TestSAMGovAdapter:
    @pytest.fixture
    def mock_sam_response(self):
        return {
            "entityData": [
                {
                    "entityRegistration": {
                        "legalBusinessName": "Acme Defense LLC",
                        "dbaName": "Acme",
                        "cageCode": "1ABC2",
                        "ueiSAM": "ABCDEF123456",
                        "registrationStatus": "Active",
                    },
                    "coreData": {
                        "physicalAddress": {
                            "addressLine1": "123 Main St",
                            "addressLine2": "",
                            "city": "Arlington",
                            "stateOrProvinceCode": "VA",
                            "zipCode": "22201",
                        },
                        "generalInformation": {
                            "naicsCodeList": [
                                {"naicsCode": "541512"},
                                {"naicsCode": "541519"},
                            ],
                            "entityStructureDesc": "LLC",
                            "organizationStructureDesc": "Corporation",
                        },
                    },
                    "pointsOfContact": {
                        "governmentBusinessPOC": {
                            "firstName": "Jane",
                            "lastName": "Doe",
                            "email": "jane@acmedefense.com",
                            "usPhone": "703-555-1234",
                            "title": "CEO",
                        },
                    },
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_search_entities_parses_response(self, mock_sam_response):
        adapter = SAMGovAdapter(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_sam_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            results = await adapter.search_entities(naics_codes=["541512"], state="VA")

        assert len(results) == 1
        entity = results[0]
        assert entity["legal_name"] == "Acme Defense LLC"
        assert entity["cage_code"] == "1ABC2"
        assert entity["uei"] == "ABCDEF123456"
        assert entity["city"] == "Arlington"
        assert entity["state"] == "VA"
        assert entity["poc_first"] == "Jane"
        assert entity["poc_last"] == "Doe"
        assert entity["poc_email"] == "jane@acmedefense.com"
        assert entity["naics_codes"] == ["541512", "541519"]

    @pytest.mark.asyncio
    async def test_search_entities_no_api_key(self):
        adapter = SAMGovAdapter(api_key="")
        results = await adapter.search_entities(naics_codes=["541512"])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_entities_http_error(self):
        adapter = SAMGovAdapter(api_key="test-key")
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            results = await adapter.search_entities(naics_codes=["541512"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_all_pages_stops_on_short_page(self, mock_sam_response):
        """When a page returns fewer than PAGE_SIZE results, pagination stops."""
        adapter = SAMGovAdapter(api_key="test-key")
        call_count = 0

        async def mock_search_entities(naics_codes=None, state=None, page=0):
            nonlocal call_count
            call_count += 1
            if page == 0:
                return [{"legal_name": "Company A"}]  # 1 < PAGE_SIZE(10) -> last page
            return []

        adapter.search_entities = mock_search_entities
        results = await adapter.search_all_pages(naics_codes=["541512"], max_pages=5)
        assert len(results) == 1
        # Only 1 call because first page returned fewer than PAGE_SIZE items
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_search_all_pages_paginates_full_pages(self, mock_sam_response):
        """When a page returns exactly PAGE_SIZE results, fetch next page."""
        adapter = SAMGovAdapter(api_key="test-key")
        call_count = 0

        async def mock_search_entities(naics_codes=None, state=None, page=0):
            nonlocal call_count
            call_count += 1
            if page == 0:
                # Return exactly 10 items (PAGE_SIZE) to trigger next page fetch
                return [{"legal_name": f"Company {i}"} for i in range(10)]
            return []  # page 1 is empty

        adapter.search_entities = mock_search_entities
        results = await adapter.search_all_pages(naics_codes=["541512"], max_pages=5)
        assert len(results) == 10
        assert call_count == 2  # page 0 full -> fetch page 1 -> empty -> stop


# ---------------------------------------------------------------------------
# Size Estimator
# ---------------------------------------------------------------------------


class TestSizeEstimator:
    def test_classify_small(self):
        assert classify_size_band(10) == "small"
        assert classify_size_band(49) == "small"

    def test_classify_mid_market(self):
        assert classify_size_band(50) == "mid-market"
        assert classify_size_band(499) == "mid-market"

    def test_classify_enterprise(self):
        assert classify_size_band(500) == "enterprise"
        assert classify_size_band(10000) == "enterprise"

    def test_classify_unknown(self):
        assert classify_size_band(None) == "unknown"
        assert classify_size_band(0) == "unknown"
        assert classify_size_band(-1) == "unknown"

    def test_extract_from_text_employees(self):
        assert estimate_employee_count_from_text("We have 200 employees") == 200

    def test_extract_from_text_team_of(self):
        assert estimate_employee_count_from_text("a team of 50 people") == 50

    def test_extract_from_text_staff(self):
        assert estimate_employee_count_from_text("150 staff members work here") == 150

    def test_extract_from_text_employs(self):
        assert estimate_employee_count_from_text("The company employs 300 professionals") == 300

    def test_extract_from_text_range(self):
        count = estimate_employee_count_from_text("51-200 employees")
        assert count == 125  # midpoint

    def test_extract_from_text_with_comma(self):
        assert estimate_employee_count_from_text("over 1,500 employees") == 1500

    def test_extract_from_text_no_match(self):
        assert estimate_employee_count_from_text("great company culture") is None

    def test_extract_from_text_empty(self):
        assert estimate_employee_count_from_text("") is None
        assert estimate_employee_count_from_text(None) is None

    def test_estimate_size_band_explicit_count(self):
        band, count = estimate_size_band(employee_count=75)
        assert band == "mid-market"
        assert count == 75

    def test_estimate_size_band_apollo_data(self):
        band, count = estimate_size_band(apollo_data={"estimated_num_employees": 800})
        assert band == "enterprise"
        assert count == 800

    def test_estimate_size_band_snippet(self):
        band, count = estimate_size_band(snippet_text="team of 30 engineers")
        assert band == "small"
        assert count == 30

    def test_estimate_size_band_priority(self):
        # Explicit count beats Apollo and snippet
        band, count = estimate_size_band(
            employee_count=10,
            apollo_data={"estimated_num_employees": 500},
            snippet_text="5000 employees",
        )
        assert band == "small"
        assert count == 10

    def test_estimate_size_band_unknown(self):
        band, count = estimate_size_band()
        assert band == "unknown"
        assert count is None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_dedup_by_email(self):
        results = [
            DiscoverResult(name="John Doe", email="john@acme.com", company="Acme"),
            DiscoverResult(name="John Doe", email="john@acme.com", company="Acme Inc"),
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 1
        # Should keep richer data
        assert deduped[0].company in ("Acme", "Acme Inc")

    def test_dedup_keeps_different_emails(self):
        results = [
            DiscoverResult(name="John Doe", email="john@acme.com"),
            DiscoverResult(name="Jane Smith", email="jane@acme.com"),
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 2

    def test_dedup_no_email_no_crash(self):
        results = [
            DiscoverResult(name="John Doe", company="Acme"),
            DiscoverResult(name="Jane Smith", company="Beta"),
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 2

    def test_dedup_empty_list(self):
        assert _deduplicate_results([]) == []

    def test_merge_results_keeps_richer(self):
        a = DiscoverResult(name="John Doe", email="john@acme.com", confidence=0.8)
        b = DiscoverResult(name="John Doe", phone="555-1234", cage_code="1ABC2", confidence=0.9)
        merged = _merge_results(a, b)
        assert merged.email == "john@acme.com"
        assert merged.phone == "555-1234"
        assert merged.cage_code == "1ABC2"
        assert merged.confidence == 0.9


# ---------------------------------------------------------------------------
# Segment Inference
# ---------------------------------------------------------------------------


class TestSegmentInference:
    def test_infers_dib(self):
        segments = _infer_segments_from_query("CMMC defense contractors in Virginia")
        assert "dib" in segments

    def test_infers_fedramp(self):
        segments = _infer_segments_from_query("FedRAMP cloud providers")
        assert "fedramp" in segments

    def test_infers_mssp(self):
        segments = _infer_segments_from_query("managed security service providers")
        assert "mssp" in segments

    def test_infers_multiple(self):
        segments = _infer_segments_from_query("defense CMMC FedRAMP cloud")
        assert "dib" in segments
        assert "fedramp" in segments

    def test_no_segments_for_generic(self):
        segments = _infer_segments_from_query("marketing directors at SaaS companies")
        assert len(segments) == 0

    def test_case_insensitive(self):
        segments = _infer_segments_from_query("fedramp cloud security")
        assert "fedramp" in segments


# ---------------------------------------------------------------------------
# State Code Parsing
# ---------------------------------------------------------------------------


class TestStateCodeParsing:
    def test_two_letter_code(self):
        assert _parse_state_code("VA") == "VA"

    def test_full_name(self):
        assert _parse_state_code("Virginia") == "VA"

    def test_region_mapping(self):
        assert _parse_state_code("Northern Virginia") == "VA"

    def test_dmv(self):
        assert _parse_state_code("DMV") == "VA"

    def test_silicon_valley(self):
        assert _parse_state_code("Silicon Valley") == "CA"

    def test_dc(self):
        assert _parse_state_code("Washington DC") == "DC"

    def test_none(self):
        assert _parse_state_code(None) is None

    def test_empty(self):
        assert _parse_state_code("") is None

    def test_unknown_region(self):
        assert _parse_state_code("Mars") is None


# ---------------------------------------------------------------------------
# Job Posting Company Extraction
# ---------------------------------------------------------------------------


class TestJobPostingExtraction:
    def test_extracts_company_at_pattern(self):
        companies = _extract_companies_from_job_listing(
            "Security Engineer at Booz Allen Hamilton - Arlington, VA",
            "Top defense contractor Booz Allen is hiring..."
        )
        assert any("Booz Allen" in c for c in companies)

    def test_extracts_company_is_hiring(self):
        companies = _extract_companies_from_job_listing(
            "Raytheon Technologies is hiring a CMMC assessor",
            "Join our growing team of cybersecurity professionals"
        )
        assert any("Raytheon" in c for c in companies)

    def test_filters_noise(self):
        companies = _extract_companies_from_job_listing(
            "Full Time position in United States",
            "Apply Now for this great opportunity"
        )
        # "United States" and "Apply Now" should be filtered
        assert "United States" not in companies

    def test_empty_input(self):
        companies = _extract_companies_from_job_listing("", "")
        assert isinstance(companies, list)


# ---------------------------------------------------------------------------
# Domain Extraction
# ---------------------------------------------------------------------------


class TestDomainExtraction:
    def test_from_url(self):
        assert _extract_domain("https://www.example.com/page") == "example.com"

    def test_from_bare_domain(self):
        assert _extract_domain("example.com") == "example.com"

    def test_strips_www(self):
        assert _extract_domain("www.example.com") == "example.com"

    def test_empty(self):
        assert _extract_domain("") == ""

    def test_none_like(self):
        assert _extract_domain("") == ""


# ---------------------------------------------------------------------------
# DiscoverResult new fields
# ---------------------------------------------------------------------------


class TestDiscoverResultNewFields:
    def test_cage_code_field(self):
        r = DiscoverResult(name="Test", cage_code="1ABC2")
        assert r.cage_code == "1ABC2"

    def test_segment_field(self):
        r = DiscoverResult(name="Test", segment="dib")
        assert r.segment == "dib"

    def test_size_band_field(self):
        r = DiscoverResult(name="Test", size_band="mid-market")
        assert r.size_band == "mid-market"

    def test_company_domain_field(self):
        r = DiscoverResult(name="Test", company_domain="acme.com")
        assert r.company_domain == "acme.com"

    def test_defaults_to_none(self):
        r = DiscoverResult(name="Test")
        assert r.cage_code is None
        assert r.segment is None
        assert r.size_band is None
        assert r.company_domain is None


# ---------------------------------------------------------------------------
# DiscoverRequest new fields
# ---------------------------------------------------------------------------


class TestDiscoverRequestNewFields:
    def test_segments_field(self):
        req = DiscoverRequest(query="test", segments=["dib", "fedramp"])
        assert req.segments == ["dib", "fedramp"]

    def test_geography_field(self):
        req = DiscoverRequest(query="test", geography="VA")
        assert req.geography == "VA"

    def test_include_sam_gov_default(self):
        req = DiscoverRequest(query="test")
        assert req.include_sam_gov is True

    def test_include_job_postings_default(self):
        req = DiscoverRequest(query="test")
        assert req.include_job_postings is True

    def test_segments_default_none(self):
        req = DiscoverRequest(query="test")
        assert req.segments is None


# ---------------------------------------------------------------------------
# Size estimation in pipeline
# ---------------------------------------------------------------------------


class TestEstimateSizesInPipeline:
    def test_preserves_existing_size_band(self):
        results = [DiscoverResult(name="A", size_band="enterprise")]
        sized = _estimate_sizes(results)
        assert sized[0].size_band == "enterprise"

    def test_assigns_unknown_when_no_info(self):
        results = [DiscoverResult(name="A")]
        sized = _estimate_sizes(results)
        assert sized[0].size_band == "unknown"


# ---------------------------------------------------------------------------
# Organization entity new fields
# ---------------------------------------------------------------------------


class TestOrganizationEntityNewFields:
    def test_organization_has_new_fields(self):
        from src.domain.entities.organization import Organization
        from src.domain.enums import DataSource

        org = Organization(
            name="Acme Defense",
            source=DataSource.SAM_GOV,
            cage_code="1ABC2",
            uei="ABCDEF123456",
            naics_codes=["541512", "541519"],
            size_band="mid-market",
            segment="dib",
        )
        assert org.cage_code == "1ABC2"
        assert org.uei == "ABCDEF123456"
        assert org.naics_codes == ["541512", "541519"]
        assert org.size_band == "mid-market"
        assert org.segment == "dib"

    def test_organization_defaults(self):
        from src.domain.entities.organization import Organization
        from src.domain.enums import DataSource

        org = Organization(name="Test", source=DataSource.MANUAL)
        assert org.cage_code is None
        assert org.uei is None
        assert org.naics_codes == []
        assert org.size_band is None
        assert org.segment is None


# ---------------------------------------------------------------------------
# DataSource enum new values
# ---------------------------------------------------------------------------


class TestDataSourceEnumNewValues:
    def test_sam_gov_value(self):
        from src.domain.enums import DataSource
        assert DataSource.SAM_GOV.value == "sam_gov"

    def test_job_posting_value(self):
        from src.domain.enums import DataSource
        assert DataSource.JOB_POSTING.value == "job_posting"
