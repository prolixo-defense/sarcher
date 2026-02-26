"""
Natural language lead discovery endpoint with SSE streaming progress.

Pipeline:
1. POST /api/discover  → creates a job, starts background task, returns {job_id}
2. GET  /api/discover/{job_id}/stream → SSE stream of progress events
3. Final SSE event "complete" includes results + stats

Pipeline stages (scaled):
  INTERPRET → [SAM.gov | WEB SEARCH | JOB MINING] → DEDUP → SIZE → MATCH → [ENRICH] → [SAVE] → COMPLETE
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["discover"])

# ---------------------------------------------------------------------------
# In-memory job state  (single-process — not for multi-worker deployments)
# ---------------------------------------------------------------------------
_job_queues: dict[str, asyncio.Queue] = {}
_job_created: dict[str, float] = {}
_JOB_TTL_SECONDS = 600  # clean up jobs older than 10 minutes


def _cleanup_old_jobs() -> None:
    now = time.monotonic()
    stale = [jid for jid, ts in list(_job_created.items()) if now - ts > _JOB_TTL_SECONDS]
    for jid in stale:
        _job_queues.pop(jid, None)
        _job_created.pop(jid, None)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DiscoverRequest(BaseModel):
    query: str
    mode: str = "quick"      # "quick" or "full"
    max_results: int = 200
    enrich: bool = False
    save: bool = True
    # Phase 6: scaled discovery fields
    segments: list[str] | None = None
    include_sam_gov: bool = True
    include_job_postings: bool = True
    geography: str | None = None


class QueryInterpretation(BaseModel):
    target_titles: list[str] = []
    target_companies: list[str] = []
    target_industries: list[str] = []
    target_locations: list[str] = []
    company_size: str | None = None
    keywords: list[str] = []
    search_queries: list[str] = []


class DiscoverResult(BaseModel):
    name: str
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    location: str | None = None
    source: str | None = None
    relevance_score: int = 0
    confidence: float = 0.0
    enrichment_status: str = "pending"
    # Phase 6 fields
    cage_code: str | None = None
    segment: str | None = None
    size_band: str | None = None
    company_domain: str | None = None


class DiscoverJobResponse(BaseModel):
    job_id: str
    stream_url: str


# ---------------------------------------------------------------------------
# LLM prompt for query interpretation
# ---------------------------------------------------------------------------

_DISCOVER_PROMPT = """\
You are a B2B lead research assistant. A user has described the type of people \
they want to find. Extract structured search parameters from their description \
and generate effective web search queries.

Rules for search_queries:
1. Every query MUST include at least one keyword from the user's description.
2. Target company websites, "about us" pages, "team" pages, or association \
member directories — NOT job boards like LinkedIn, Indeed, or Glassdoor.
3. Do NOT use site: operators. Use natural language queries.
4. Use the user's exact terminology (acronyms, industry terms, certifications).
5. Aim for queries like: "<keyword> company team page", \
"<keyword> consultants staff", "<keyword> association member directory".
6. If an acronym (e.g. CMMC, ITAR, FedRAMP) could match unrelated industries, \
add a disambiguating term like "cybersecurity" or "DoD" to EVERY query.

User description: {query}
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    urls: list[str]
    query: str = "replay"
    max_results: int = 200
    save: bool = True


@router.post("/api/discover/replay", response_model=DiscoverJobResponse)
async def replay_urls(
    request: ReplayRequest,
    background_tasks: BackgroundTasks,
) -> DiscoverJobResponse:
    """Re-run extraction on a fixed list of URLs, skipping the search step."""
    _cleanup_old_jobs()
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _job_queues[job_id] = queue
    _job_created[job_id] = time.monotonic()
    background_tasks.add_task(_run_replay_pipeline, job_id, request)
    return DiscoverJobResponse(job_id=job_id, stream_url=f"/api/discover/{job_id}/stream")


@router.post("/api/discover", response_model=DiscoverJobResponse)
async def discover_leads(
    request: DiscoverRequest,
    background_tasks: BackgroundTasks,
) -> DiscoverJobResponse:
    """
    Start a natural language lead discovery job.

    Returns a job_id immediately; the pipeline runs in the background.
    Subscribe to /api/discover/{job_id}/stream for real-time progress.
    """
    _cleanup_old_jobs()

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _job_queues[job_id] = queue
    _job_created[job_id] = time.monotonic()

    background_tasks.add_task(_run_discovery_pipeline, job_id, request)

    return DiscoverJobResponse(
        job_id=job_id,
        stream_url=f"/api/discover/{job_id}/stream",
    )


@router.get("/api/discover/{job_id}/stream")
async def discover_stream(job_id: str, request: Request) -> EventSourceResponse:
    """
    SSE stream of progress events for a discovery job.

    Events emitted by stage:
      interpreting → searching → scraping → extracting → matching
      → enriching → saving → complete | error
    """

    async def event_generator():
        queue = _job_queues.get(job_id)
        if queue is None:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"stage": "error", "message": "Job not found or expired", "progress": 0}
                ),
            }
            return

        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected for job %s", job_id)
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keepalive ping so the connection doesn't time out
                yield {"event": "ping", "data": "{}"}
                continue

            stage = event.get("stage", "update")
            yield {"event": stage, "data": json.dumps(event)}

            if stage in ("complete", "error"):
                # Allow the client a moment to receive the final event
                await asyncio.sleep(1)
                _job_queues.pop(job_id, None)
                _job_created.pop(job_id, None)
                break

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Pipeline: replay (unchanged)
# ---------------------------------------------------------------------------


async def _run_replay_pipeline(job_id: str, request: ReplayRequest) -> None:
    """Re-run extraction on a fixed URL list — skips interpret + search stages."""
    queue = _job_queues.get(job_id)
    if queue is None:
        return

    start_time = time.monotonic()
    pages_scraped = 0
    people_found = 0

    async def emit(stage: str, message: str, progress: int, **extra: Any) -> None:
        event: dict[str, Any] = {"stage": stage, "message": message, "progress": progress, **extra}
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    try:
        url_infos = [{"url": u, "title": ""} for u in request.urls]
        await emit("scraping", f"Replaying {len(url_infos)} URLs with current model...", 5)

        all_people: list[DiscoverResult] = []
        for i, url_info in enumerate(url_infos):
            url = url_info["url"]
            progress = 5 + int(85 * (i / max(len(url_infos), 1)))
            await emit("scraping", f"Page {i+1}/{len(url_infos)}: {_truncate(url, 60)}", progress)
            try:
                people = await _scrape_and_extract(url, "", QueryInterpretation())
                all_people.extend(people)
                pages_scraped += 1
                people_found = len(all_people)
                await emit("extracting", f"Found {people_found} people so far...", progress + 2, count=people_found)
            except Exception as exc:
                logger.warning("Replay scrape failed for %s: %s", url, exc)

        await emit("matching", "Filtering to relevant matches...", 92)
        matched = _match_and_rank(all_people, QueryInterpretation(), request.max_results)

        if request.save and matched:
            await emit("saving", f"Saving {len(matched)} leads...", 97)
            _save_results_to_db(matched, QueryInterpretation())

        elapsed = round(time.monotonic() - start_time, 1)
        await emit(
            "complete",
            f"Done! Found {len(matched)} leads (hallucination-filtered).",
            100,
            results=[r.model_dump() for r in matched],
            stats={
                "pages_scraped": pages_scraped,
                "people_found": people_found,
                "people_matched": len(matched),
                "people_enriched": 0,
                "time_elapsed_seconds": elapsed,
            },
        )
    except Exception as exc:
        logger.exception("Replay pipeline failed for job %s", job_id)
        await emit("error", f"Replay failed: {exc}", 0)


# ---------------------------------------------------------------------------
# Pipeline: scaled discovery (Phase 6)
# ---------------------------------------------------------------------------


async def _run_discovery_pipeline(job_id: str, request: DiscoverRequest) -> None:
    """Background task: orchestrate the full scaled discovery pipeline."""
    queue = _job_queues.get(job_id)
    if queue is None:
        return

    start_time = time.monotonic()
    pages_scraped = 0
    people_found = 0

    async def emit(stage: str, message: str, progress: int, **extra: Any) -> None:
        event: dict[str, Any] = {
            "stage": stage,
            "message": message,
            "progress": progress,
            **extra,
        }
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Job %s queue full — dropping event", job_id)

    try:
        # ------------------------------------------------------------------
        # Stage 1: Interpret the natural language query + determine segments
        # ------------------------------------------------------------------
        await emit("interpreting", "Understanding your search...", 5)
        interpretation = await _interpret_query(request.query)

        # Determine active segments
        segments = request.segments or _infer_segments_from_query(request.query)

        # If segments are active, augment search queries with segment templates
        if segments:
            from src.infrastructure.scrapers.adapters.market_segments import (
                get_search_queries_for_segments,
                get_target_titles_for_segments,
            )
            segment_queries = get_search_queries_for_segments(
                segments, request.geography or "", include_job_queries=False,
            )
            # Merge segment queries with LLM-generated queries
            all_queries = list(interpretation.search_queries)
            for q in segment_queries:
                if q not in all_queries:
                    all_queries.append(q)
            interpretation = interpretation.model_copy(
                update={"search_queries": all_queries}
            )
            # Augment target titles from segments
            seg_titles = get_target_titles_for_segments(segments)
            merged_titles = list(interpretation.target_titles)
            for t in seg_titles:
                if t.lower() not in {x.lower() for x in merged_titles}:
                    merged_titles.append(t)
            interpretation = interpretation.model_copy(
                update={"target_titles": merged_titles}
            )

        await emit(
            "searching",
            f"Generated {len(interpretation.search_queries)} search queries"
            + (f" for {len(segments)} segment(s)." if segments else "."),
            15,
            queries=interpretation.search_queries[:20],  # cap for SSE payload
            interpretation=interpretation.model_dump(),
            segments=segments,
        )

        # ------------------------------------------------------------------
        # Stage 2: Run data sources in parallel
        # ------------------------------------------------------------------
        sam_results: list[DiscoverResult] = []
        web_results: list[DiscoverResult] = []
        job_results: list[DiscoverResult] = []

        async def run_sam_gov():
            nonlocal sam_results
            if not request.include_sam_gov or not segments:
                return
            try:
                sam_results = await _run_sam_gov_search(segments, request.geography, emit)
            except Exception as exc:
                logger.warning("SAM.gov search failed: %s", exc)

        async def run_web_search():
            nonlocal web_results, pages_scraped, people_found
            try:
                urls = await _search_for_urls(interpretation.search_queries)
                logger.info("Discovery job %s: found %d URLs", job_id, len(urls))

                scrape_targets = urls[:30]
                for i, url_info in enumerate(scrape_targets):
                    url = url_info.get("url", "")
                    if not url:
                        continue
                    progress = 20 + int(40 * (i / max(len(scrape_targets), 1)))
                    await emit(
                        "scraping",
                        f"Scraping page {i + 1} of {len(scrape_targets)}: {_truncate(url, 60)}",
                        progress,
                    )
                    try:
                        people = await _scrape_and_extract(url, url_info.get("title", ""), interpretation)
                        web_results.extend(people)
                        pages_scraped += 1
                        people_found = len(web_results)
                        await emit("extracting", f"Found {people_found} people so far...", progress + 2, count=people_found)
                    except Exception as exc:
                        logger.warning("Scrape/extract failed for %s: %s", url, exc)
            except Exception as exc:
                logger.warning("Web search failed: %s", exc)

        async def run_job_mining():
            nonlocal job_results
            if not request.include_job_postings or not segments:
                return
            try:
                job_results = await _run_job_posting_search(segments, request.geography, emit)
            except Exception as exc:
                logger.warning("Job posting search failed: %s", exc)

        # Run all 3 data sources concurrently
        await emit("searching", "Querying SAM.gov, web search, and job postings in parallel...", 18)
        await asyncio.gather(run_sam_gov(), run_web_search(), run_job_mining())

        # ------------------------------------------------------------------
        # Stage 3: Merge + Deduplicate
        # ------------------------------------------------------------------
        all_results = [*sam_results, *web_results, *job_results]
        await emit("matching", f"Collected {len(all_results)} raw results. Deduplicating...", 65)
        deduped = _deduplicate_results(all_results)
        await emit("matching", f"Deduplicated to {len(deduped)} unique results.", 68)

        # ------------------------------------------------------------------
        # Stage 4: Estimate size bands
        # ------------------------------------------------------------------
        sized = _estimate_sizes(deduped)
        await emit("matching", f"Size estimation complete for {len(sized)} results.", 70)

        # ------------------------------------------------------------------
        # Stage 5: Determine segments for results
        # ------------------------------------------------------------------
        if segments:
            sized = _assign_segments(sized, segments)

        # ------------------------------------------------------------------
        # Stage 6: Match & Rank
        # ------------------------------------------------------------------
        await emit("matching", "Ranking results...", 75)
        matched = _match_and_rank(sized, interpretation, request.max_results)
        await emit(
            "matching",
            f"Matched {len(matched)} relevant leads",
            80,
            matched=len(matched),
        )

        # ------------------------------------------------------------------
        # Stage 7: Enrich (optional — full pipeline or explicit enrich=True)
        # ------------------------------------------------------------------
        if request.enrich or request.mode == "full":
            for i, lead in enumerate(matched):
                progress = 80 + int(15 * (i / max(len(matched), 1)))
                await emit(
                    "enriching",
                    f"Getting contact info for {lead.name}...",
                    progress,
                    current=lead.name,
                )
                matched[i] = await _enrich_lead_result(lead)

        # ------------------------------------------------------------------
        # Stage 8: Save to database
        # ------------------------------------------------------------------
        if request.save and matched:
            await emit("saving", f"Saving {len(matched)} leads to database...", 97)
            _save_results_to_db(matched, interpretation)

        # ------------------------------------------------------------------
        # Complete — with per-source breakdown
        # ------------------------------------------------------------------
        elapsed = round(time.monotonic() - start_time, 1)
        await emit(
            "complete",
            f"Done! Found {len(matched)} matching leads.",
            100,
            results=[r.model_dump() for r in matched],
            stats={
                "pages_scraped": pages_scraped,
                "people_found": len(all_results),
                "people_matched": len(matched),
                "people_enriched": sum(
                    1 for r in matched if r.enrichment_status == "completed"
                ),
                "time_elapsed_seconds": elapsed,
                "sam_gov_companies": len(sam_results),
                "web_search_people": len(web_results),
                "job_mining_companies": len(job_results),
                "total_deduped": len(deduped),
            },
            query_interpretation=interpretation.model_dump(),
            segments=segments,
        )

    except Exception as exc:
        logger.exception("Discovery pipeline failed for job %s", job_id)
        await emit("error", f"Pipeline failed: {exc}", 0)


# ---------------------------------------------------------------------------
# Data source: SAM.gov
# ---------------------------------------------------------------------------


async def _run_sam_gov_search(
    segments: list[str],
    geography: str | None,
    emit,
) -> list[DiscoverResult]:
    """Query SAM.gov for active entity registrations matching segment NAICS codes."""
    from src.infrastructure.config.settings import get_settings
    from src.infrastructure.scrapers.adapters.market_segments import get_naics_codes_for_segments
    from src.infrastructure.scrapers.adapters.sam_gov_adapter import SAMGovAdapter

    settings = get_settings()
    if not settings.sam_gov_api_key:
        logger.info("SAM.gov API key not configured — skipping SAM.gov source")
        return []

    naics_codes = get_naics_codes_for_segments(segments)
    if not naics_codes:
        return []

    # Parse state from geography (e.g. "VA", "Virginia", "Northern Virginia")
    state = _parse_state_code(geography) if geography else None

    adapter = SAMGovAdapter(api_key=settings.sam_gov_api_key)
    await emit("searching", f"Querying SAM.gov ({len(naics_codes)} NAICS codes)...", 16)

    entities = await adapter.search_all_pages(naics_codes=naics_codes, state=state, max_pages=10)

    results: list[DiscoverResult] = []
    for entity in entities:
        legal_name = entity.get("legal_name", "")
        if not legal_name:
            continue

        # Build a result for the POC if available
        poc_name = f"{entity.get('poc_first', '')} {entity.get('poc_last', '')}".strip()
        if poc_name:
            location = ", ".join(
                p for p in [entity.get("city", ""), entity.get("state", "")] if p
            )
            results.append(DiscoverResult(
                name=poc_name,
                first_name=entity.get("poc_first"),
                last_name=entity.get("poc_last"),
                title=entity.get("poc_title") or "Government Business POC",
                company=legal_name,
                email=entity.get("poc_email"),
                phone=entity.get("poc_phone"),
                location=location,
                source="sam_gov",
                cage_code=entity.get("cage_code"),
                confidence=0.9,
            ))
        else:
            # Company-only result (no POC name)
            location = ", ".join(
                p for p in [entity.get("city", ""), entity.get("state", "")] if p
            )
            results.append(DiscoverResult(
                name=legal_name,
                company=legal_name,
                location=location,
                source="sam_gov",
                cage_code=entity.get("cage_code"),
                confidence=0.8,
            ))

    logger.info("SAM.gov: %d results from %d entities", len(results), len(entities))
    return results


# ---------------------------------------------------------------------------
# Data source: Job posting mining (no LLM)
# ---------------------------------------------------------------------------


async def _run_job_posting_search(
    segments: list[str],
    geography: str | None,
    emit,
) -> list[DiscoverResult]:
    """
    Search for job postings to harvest company names.

    No LLM needed — just extract company names from search result titles/snippets.
    """
    from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter
    from src.infrastructure.scrapers.adapters.market_segments import SEGMENTS

    adapter = GoogleSearchAdapter()
    geo = geography.strip() if geography else ""

    # Collect job search queries from active segments
    job_queries: list[str] = []
    for seg_key in segments:
        seg = SEGMENTS.get(seg_key)
        if not seg:
            continue
        for template in seg.get("job_search_templates", []):
            q = template.replace("{geo}", geo).strip()
            if q not in job_queries:
                job_queries.append(q)

    if not job_queries:
        return []

    await emit("searching", f"Mining {len(job_queries)} job posting queries...", 17)

    seen_companies: set[str] = set()
    results: list[DiscoverResult] = []

    for query in job_queries[:10]:  # cap at 10 queries
        try:
            hits = await adapter.search(query, num_results=10)
            for hit in hits:
                companies = _extract_companies_from_job_listing(
                    hit.get("title", ""), hit.get("snippet", "")
                )
                for company_name in companies:
                    normalized = company_name.lower().strip()
                    if normalized in seen_companies or len(normalized) < 3:
                        continue
                    seen_companies.add(normalized)
                    results.append(DiscoverResult(
                        name=company_name,
                        company=company_name,
                        source="job_posting",
                        confidence=0.6,
                    ))
        except Exception as exc:
            logger.warning("Job posting search failed for %r: %s", query, exc)

    logger.info("Job posting mining: %d unique companies from %d queries", len(results), len(job_queries))
    return results


def _extract_companies_from_job_listing(title: str, snippet: str) -> list[str]:
    """Extract company names from job listing search result via regex patterns."""
    companies: list[str] = []
    text = f"{title} {snippet}"

    # Pattern: "at <Company>" or "@ <Company>"
    for m in re.finditer(r'(?:at|@)\s+([A-Z][A-Za-z\s&,.\'-]{2,40}?)(?:\s*[-–—|,]|\s+is\s|\s+in\s|\.$)', text):
        name = m.group(1).strip().rstrip(",.-")
        if name and len(name) > 2:
            companies.append(name)

    # Pattern: "<Company> is hiring" / "is looking for"
    for m in re.finditer(r'([A-Z][A-Za-z\s&,.\'-]{2,40}?)\s+(?:is\s+(?:hiring|looking|seeking|recruiting))', text):
        name = m.group(1).strip().rstrip(",.-")
        if name and len(name) > 2:
            companies.append(name)

    # Pattern: title-cased multi-word names that look like companies
    for m in re.finditer(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\b', text):
        name = m.group(1)
        # Filter out common noise
        noise = {
            "United States", "New York", "San Francisco", "Los Angeles",
            "Top Secret", "Job Description", "Apply Now", "Full Time",
            "Part Time", "Equal Opportunity", "Department Defense",
        }
        if name not in noise and name not in companies:
            companies.append(name)

    return companies[:5]  # cap per listing


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_results(results: list[DiscoverResult]) -> list[DiscoverResult]:
    """Deduplicate results by domain or fuzzy company name match."""
    if not results:
        return results

    try:
        from thefuzz import fuzz
    except ImportError:
        # Without thefuzz, just deduplicate on exact company name
        seen: set[str] = set()
        deduped: list[DiscoverResult] = []
        for r in results:
            key = (r.email or r.name or "").lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)
            elif not key:
                deduped.append(r)
        return deduped

    deduped: list[DiscoverResult] = []
    seen_emails: set[str] = set()
    seen_domains: set[str] = set()

    for r in results:
        # Dedup by email (exact)
        if r.email:
            email_lower = r.email.lower()
            if email_lower in seen_emails:
                # Merge: find existing and keep richer data
                for i, existing in enumerate(deduped):
                    if existing.email and existing.email.lower() == email_lower:
                        deduped[i] = _merge_results(existing, r)
                        break
                continue
            seen_emails.add(email_lower)

        # Dedup by company domain (if extractable)
        domain = _extract_domain(r.company_domain or "")
        if not domain and r.email:
            domain = r.email.split("@")[-1].lower() if "@" in r.email else ""

        if domain and domain in seen_domains:
            # Check if same person by name
            is_dup = False
            for i, existing in enumerate(deduped):
                existing_domain = _extract_domain(existing.company_domain or "")
                if not existing_domain and existing.email and "@" in existing.email:
                    existing_domain = existing.email.split("@")[-1].lower()
                if existing_domain == domain:
                    # Same domain — check if same person by name fuzzy match
                    if r.name and existing.name:
                        if fuzz.ratio(r.name.lower(), existing.name.lower()) >= 85:
                            deduped[i] = _merge_results(existing, r)
                            is_dup = True
                            break
            if is_dup:
                continue
        if domain:
            seen_domains.add(domain)

        # Dedup by fuzzy company name (for results without domain)
        if not domain and r.company:
            is_dup = False
            for i, existing in enumerate(deduped):
                if existing.company and not r.name:
                    if fuzz.ratio(r.company.lower(), existing.company.lower()) >= 85:
                        # Same company, no name — likely same entity
                        if not r.name or (existing.name and fuzz.ratio(r.name.lower(), existing.name.lower()) >= 85):
                            deduped[i] = _merge_results(existing, r)
                            is_dup = True
                            break
            if is_dup:
                continue

        deduped.append(r)

    return deduped


def _merge_results(existing: DiscoverResult, new: DiscoverResult) -> DiscoverResult:
    """Merge two DiscoverResult records, keeping the richer data."""
    return existing.model_copy(update={
        "email": existing.email or new.email,
        "phone": existing.phone or new.phone,
        "linkedin": existing.linkedin or new.linkedin,
        "title": existing.title or new.title,
        "location": existing.location or new.location,
        "cage_code": existing.cage_code or new.cage_code,
        "segment": existing.segment or new.segment,
        "size_band": existing.size_band or new.size_band,
        "company_domain": existing.company_domain or new.company_domain,
        "confidence": max(existing.confidence, new.confidence),
        "first_name": existing.first_name or new.first_name,
        "last_name": existing.last_name or new.last_name,
    })


def _extract_domain(url_or_domain: str) -> str:
    """Extract bare domain from a URL or domain string."""
    if not url_or_domain:
        return ""
    if "://" in url_or_domain:
        try:
            domain = urlparse(url_or_domain).netloc
        except Exception:
            return ""
    else:
        domain = url_or_domain
    domain = re.sub(r"^www\.", "", domain.lower())
    return domain


# ---------------------------------------------------------------------------
# Size estimation
# ---------------------------------------------------------------------------


def _estimate_sizes(results: list[DiscoverResult]) -> list[DiscoverResult]:
    """Apply size band estimation to all results."""
    from src.application.services.size_estimator import estimate_size_band

    sized: list[DiscoverResult] = []
    for r in results:
        if r.size_band:
            sized.append(r)
            continue
        band, _ = estimate_size_band(snippet_text=r.location or "")
        sized.append(r.model_copy(update={"size_band": band}))
    return sized


# ---------------------------------------------------------------------------
# Segment assignment
# ---------------------------------------------------------------------------


def _assign_segments(results: list[DiscoverResult], active_segments: list[str]) -> list[DiscoverResult]:
    """Assign segment labels to results based on source or active segments."""
    if len(active_segments) == 1:
        # Single segment — assign to all
        seg = active_segments[0]
        return [
            r.model_copy(update={"segment": r.segment or seg})
            for r in results
        ]

    # Multiple segments — use source hints
    return [
        r.model_copy(update={"segment": r.segment or (active_segments[0] if active_segments else None)})
        for r in results
    ]


# ---------------------------------------------------------------------------
# Segment inference from query
# ---------------------------------------------------------------------------


_SEGMENT_KEYWORDS: dict[str, list[str]] = {
    "dib": ["defense", "dod", "cmmc", "itar", "dfars", "cage", "cleared", "military", "aerospace"],
    "fedramp": ["fedramp", "stateramp", "ato", "government cloud", "il4", "il5", "3pao"],
    "ai_compliance": ["ai governance", "responsible ai", "ai ethics", "ai audit", "eu ai act"],
    "mssp": ["mssp", "managed security", "mdr", "soc", "managed detection"],
    "grc": ["grc", "governance risk", "soc 2", "iso 27001", "compliance audit"],
    "cleared_it": ["cleared it", "ts/sci", "security clearance", "cleared developer"],
    "supply_chain": ["supply chain", "sbom", "scrm", "vendor risk", "software composition"],
    "zero_trust": ["zero trust", "ztna", "sase", "microsegmentation", "privileged access"],
    "cyber_training": ["cyber training", "security awareness", "cyber range", "phishing simulation"],
}


def _infer_segments_from_query(query: str) -> list[str]:
    """Infer market segments from the user's natural language query."""
    query_lower = query.lower()
    matched: list[str] = []
    for seg_key, keywords in _SEGMENT_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                if seg_key not in matched:
                    matched.append(seg_key)
                break
    return matched


# ---------------------------------------------------------------------------
# State code parsing
# ---------------------------------------------------------------------------

_STATE_NAMES_TO_CODES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}

_REGION_TO_STATE: dict[str, str] = {
    "northern virginia": "VA", "nova": "VA", "dmv": "VA",
    "silicon valley": "CA", "bay area": "CA",
    "dc metro": "DC", "d.c.": "DC", "washington dc": "DC",
}


def _parse_state_code(geography: str) -> str | None:
    """Parse a US state code from a geography string."""
    if not geography:
        return None
    geo_lower = geography.lower().strip()

    # Check region mappings first
    for region, code in _REGION_TO_STATE.items():
        if region in geo_lower:
            return code

    # Check if it's already a 2-letter code
    if len(geo_lower) == 2 and geo_lower.upper() in {v for v in _STATE_NAMES_TO_CODES.values()}:
        return geo_lower.upper()

    # Check full state names
    for name, code in _STATE_NAMES_TO_CODES.items():
        if name in geo_lower:
            return code

    return None


# ---------------------------------------------------------------------------
# Helper: interpret query via LLM (with heuristic fallback)
# ---------------------------------------------------------------------------


async def _interpret_query(query: str) -> QueryInterpretation:
    """Use LLM to extract structured search parameters from natural language."""
    try:
        from src.infrastructure.llm.llm_client import LLMClient

        client = LLMClient()
        prompt = _DISCOVER_PROMPT.format(query=query)
        result: QueryInterpretation = await asyncio.wait_for(
            client.extract_structured(
                content=prompt,
                response_model=QueryInterpretation,
                temperature=0.2,
                max_retries=1,
            ),
            timeout=45.0,
        )
        # Ensure we always have at least some search queries
        if not result.search_queries:
            result = result.model_copy(
                update={"search_queries": _fallback_queries(query, result)}
            )
        # Guard: if the LLM output doesn't reference any user keyword, it hallucinated.
        # Fall back to heuristics so we at least search with the correct terms.
        if not _queries_reference_input(query, result.search_queries):
            logger.warning(
                "LLM search queries don't reference user keywords — falling back to heuristics"
            )
            return _heuristic_interpret(query)
        return result
    except Exception as exc:
        logger.warning("LLM interpretation failed, using heuristics: %s", exc)
        return _heuristic_interpret(query)


def _queries_reference_input(query: str, search_queries: list[str]) -> bool:
    """Return True if at least one search query shares a meaningful word with the input."""
    user_words = {w.lower().strip(".,;:") for w in query.split() if len(w) > 3}
    if not user_words:
        return True  # short query — can't validate, trust LLM
    for sq in search_queries:
        sq_lower = sq.lower()
        if any(word in sq_lower for word in user_words):
            return True
    return False


def _heuristic_interpret(query: str) -> QueryInterpretation:
    """Simple keyword-based interpretation when LLM is unavailable."""
    words = [w.lower().strip(".,;:") for w in query.split()]

    title_keywords = {
        "cto", "ceo", "coo", "cpo", "vp", "director", "manager", "head",
        "president", "founder", "engineer", "developer", "designer",
        "analyst", "sales", "marketing", "product", "finance", "recruiter",
        "consultant", "auditor", "assessor", "officer", "specialist",
        "advisor", "partner", "principal", "associate",
    }
    industry_keywords = {
        "saas", "fintech", "healthcare", "edtech", "ecommerce", "b2b",
        "b2c", "startup", "software", "tech", "ai", "ml", "data",
        # government / defense
        "cmmc", "c3pao", "defense", "contractor", "dod", "federal",
        "government", "nist", "cybersecurity", "compliance", "grc",
        "aerospace", "military", "nato", "itar", "fedramp", "fisma",
    }

    titles = [w for w in words if w in title_keywords]
    industries = [w for w in words if w in industry_keywords]
    stub = QueryInterpretation(target_titles=titles, target_industries=industries)

    return QueryInterpretation(
        target_titles=titles,
        target_industries=industries,
        keywords=words[:10],
        search_queries=_fallback_queries(query, stub),
    )


def _fallback_queries(query: str, interp: QueryInterpretation) -> list[str]:
    """Generate web search queries from query + interpretation."""
    base = query[:80].strip()
    kw = " ".join(interp.keywords[:4]) if interp.keywords else base

    # Disambiguate acronyms that collide with other industries
    _DISAMBIG = {"cmmc": "cybersecurity", "itar": "defense", "fedramp": "cloud security"}
    disambig = ""
    for acronym, context in _DISAMBIG.items():
        if acronym in base.lower():
            disambig = f" {context}"
            break

    queries = [
        f"{base}{disambig} team page",
        f"{base}{disambig} staff directory",
        f"{base}{disambig} about us people",
        f"{kw}{disambig} company employees",
        f"{base}{disambig} member directory",
        f"{base}{disambig} association members list",
        f"{base}{disambig} consultants partners team",
        f"{base}{disambig} certified professionals directory",
    ]
    if interp.target_titles:
        title = interp.target_titles[0]
        queries.append(f"{title} {base} linkedin profile")
    return queries[:8]


# ---------------------------------------------------------------------------
# Helper: search for URLs
# ---------------------------------------------------------------------------


async def _search_for_urls(queries: list[str]) -> list[dict]:
    """
    Two-pass search to maximise people-bearing pages.

    Pass 1: Run the caller's queries to discover company names and direct
            team/about pages.
    Pass 2: For each company name found in pass-1 snippets that doesn't
            already have a team-page URL, search for "<company> team" to find
            their staff page directly.
    """
    from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

    adapter = GoogleSearchAdapter()
    seen_urls: set[str] = set()
    results: list[dict] = []
    company_names_found: list[str] = []

    # --- Pass 1 ---
    for query in queries[:12]:  # increased from 8 to 12 for segment queries
        try:
            hits = await adapter.search(query, num_results=10)
            for hit in hits:
                url = hit.get("url", "")
                if url and url not in seen_urls and _is_useful_url(url):
                    seen_urls.add(url)
                    results.append(hit)
                # Harvest company names from snippets for pass-2
                snippet = hit.get("snippet", "") + " " + hit.get("title", "")
                _extract_company_names_from_text(snippet, company_names_found)
        except Exception as exc:
            logger.warning("Search failed for query %r: %s", query, exc)

    # --- Pass 2: search for each company's team/about page ---
    unique_companies = list(dict.fromkeys(company_names_found))[:15]
    for company in unique_companies:
        for suffix in ("team page", "about us staff", "our people"):
            q = f'"{company}" {suffix}'
            try:
                hits = await adapter.search(q, num_results=3)
                for hit in hits:
                    url = hit.get("url", "")
                    if url and url not in seen_urls and _is_useful_url(url):
                        seen_urls.add(url)
                        results.append(hit)
            except Exception as exc:
                logger.warning("Pass-2 search failed for %r: %s", q, exc)

    logger.info("_search_for_urls: %d unique URLs (companies harvested: %d)",
                len(results), len(unique_companies))
    return results


def _extract_company_names_from_text(text: str, out: list[str]) -> None:
    """
    Heuristically pull company-like proper nouns from a search snippet.
    Looks for capitalised 2-4 word phrases that look like org names.
    """
    # Match sequences of title-cased words (2-4), e.g. "Redspin Inc", "Kratos Defense"
    for m in re.finditer(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\b', text):
        name = m.group(1)
        # skip generic noise
        if name.lower() in {
            "defense contractor", "cmmc compliance", "cyber security",
            "united states", "department defense", "third party",
        }:
            continue
        if name not in out:
            out.append(name)


def _is_useful_url(url: str) -> bool:
    """Filter out URLs unlikely to contain people/team data."""
    skip = {
        # general noise
        "google.com", "bing.com", "yahoo.com", "youtube.com",
        "twitter.com", "x.com", "facebook.com", "wikipedia.org",
        "reddit.com", "amazon.com", "glassdoor.com", "indeed.com",
        "yelp.com", "crunchbase.com", "duckduckgo.com",
        # government policy/doc pages — no staff listings
        "dodcio.defense.gov", "dcma.mil", "business.defense.gov",
        "acquisition.gov", "sam.gov", "regulations.gov",
        # medical/hospital — "CMMC" also means Children's / Central Maine
        # Medical Center; these never list defense contractor staff
        "cmmc.health", "cmhc.org", "themha.org", "ahd.com",
        "providence.org", "mspcollective.org", "nidiaonline.org",
    }
    url_lower = url.lower()
    if any(s in url_lower for s in skip):
        return False
    # Skip PDF/doc links — no extractable people
    if url_lower.endswith((".pdf", ".docx", ".xlsx", ".pptx")):
        return False
    # Skip hospital / medical directory pages by path keywords
    if any(seg in url_lower for seg in (
        "/hospital", "/medical-center", "/health-plan",
        "/member-hospital", "/phone-directory",
    )):
        return False
    return True


# ---------------------------------------------------------------------------
# Helper: scrape + extract people from a URL
# ---------------------------------------------------------------------------


async def _scrape_and_extract(
    url: str,
    page_title: str,
    interpretation: QueryInterpretation,
) -> list[DiscoverResult]:
    """Fetch a URL and extract structured people data.

    Strategy:
    1. Try HttpScraper (fast, lightweight).
    2. If blocked or the extracted markdown is near-empty (JS-rendered SPA),
       fall back to BrowserScraper (Playwright + stealth).
    """
    from src.infrastructure.scrapers.http_scraper import HttpScraper
    from src.infrastructure.scrapers.browser_scraper import BrowserScraper
    from src.infrastructure.llm.extraction_engine import ExtractionEngine
    from src.infrastructure.llm.html_preprocessor import HtmlPreprocessor

    prep = HtmlPreprocessor()

    http_resp = await HttpScraper().fetch(url)
    http_md = prep.preprocess(http_resp.html or "", max_tokens=200)["cleaned_markdown"].strip()

    # Try browser when HTTP is hard-blocked, returns an error status, or yields
    # near-empty markdown (JS-rendered SPA).  Block-detection false-positives
    # (Cloudflare CDN sites with real content) are handled below by preferring
    # whichever scraper produced the richer markdown.
    use_browser = http_resp.status_code >= 400 or len(http_md) < 200

    browser_html: str | None = None
    if use_browser:
        logger.info(
            "HTTP result thin/error for %s (status=%d, md_len=%d) — trying browser",
            url, http_resp.status_code, len(http_md),
        )
        browser = BrowserScraper()
        try:
            br_resp = await browser.fetch(url)
            if br_resp.html:
                br_md = prep.preprocess(br_resp.html, max_tokens=200)[
                    "cleaned_markdown"
                ].strip()
                if len(br_md) >= 200:
                    browser_html = br_resp.html
                    logger.info("Browser got %d chars of markdown for %s", len(br_md), url)
        except Exception as exc:
            logger.warning("Browser fallback failed for %s: %s", url, exc)
        finally:
            await browser.close()

    # Choose best HTML by markdown quality, not was_blocked flag
    # (block-detection has false positives on CF-hosted sites with real content)
    if browser_html:
        final_html = browser_html
    elif len(http_md) >= 200:
        # HTTP has substantial content even if block-detection fired
        final_html = http_resp.html
    else:
        logger.debug("No usable content from %s (http_md=%d chars)", url, len(http_md))
        return []

    engine = ExtractionEngine()
    extraction = await engine.extract(url, final_html)

    company_name: str | None = None
    if extraction.company:
        company_name = extraction.company.name
    else:
        company_name = _guess_company_from_url(url, page_title)

    location: str | None = extraction.company.location if extraction.company else None
    source = _classify_source(url)
    confidence = float(extraction.confidence)

    # Extract domain from URL for company_domain field
    company_domain = _extract_domain(url)

    results: list[DiscoverResult] = []
    for person in extraction.people:
        full_name = (
            person.full_name
            or f"{person.first_name or ''} {person.last_name or ''}".strip()
        )
        if not full_name:
            continue
        if _is_placeholder_name(full_name):
            logger.debug("Skipping hallucinated placeholder name: %r", full_name)
            continue

        results.append(
            DiscoverResult(
                name=full_name,
                first_name=person.first_name,
                last_name=person.last_name,
                title=person.job_title,
                company=company_name,
                email=person.email,
                phone=person.phone,
                linkedin=person.linkedin_url,
                location=location,
                source=source,
                confidence=confidence,
                enrichment_status="pending",
                company_domain=company_domain,
            )
        )

    return results


_PLACEHOLDER_NAMES = {
    "jane smith", "john doe", "john smith", "jane doe", "first last",
    "firstname lastname", "name surname", "full name", "person name",
    "example person", "sample user", "test user", "your name",
}


def _is_placeholder_name(name: str) -> bool:
    """Detect LLM-hallucinated placeholder names."""
    return name.lower().strip() in _PLACEHOLDER_NAMES


def _guess_company_from_url(url: str, title: str) -> str | None:
    domain = urlparse(url).netloc
    domain = re.sub(r"^www\.", "", domain)
    parts = domain.split(".")
    if parts:
        return parts[0].replace("-", " ").title()
    return None


def _classify_source(url: str) -> str:
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    if any(k in url_lower for k in ("directory", "members", "listing", ".org")):
        return "directory"
    return "website"


# ---------------------------------------------------------------------------
# Helper: match & rank people against search criteria
# ---------------------------------------------------------------------------


def _match_and_rank(
    people: list[DiscoverResult],
    interpretation: QueryInterpretation,
    max_results: int,
) -> list[DiscoverResult]:
    """Score each person against the search criteria and return top results."""
    try:
        from thefuzz import fuzz
    except ImportError:
        # If thefuzz unavailable, return people as-is with neutral scores
        return [p.model_copy(update={"relevance_score": 50}) for p in people[:max_results]]

    scored: list[tuple[int, DiscoverResult]] = []

    for person in people:
        score = 0

        # --- Title match (0-40 pts) ---
        if person.title and interpretation.target_titles:
            best = max(
                fuzz.partial_ratio(person.title.lower(), t.lower())
                for t in interpretation.target_titles
            )
            score += int(best * 0.4)
        elif not interpretation.target_titles:
            score += 20  # no constraint -> neutral

        # --- Company match (0-20 pts) ---
        if person.company and interpretation.target_companies:
            best = max(
                fuzz.partial_ratio(person.company.lower(), c.lower())
                for c in interpretation.target_companies
            )
            score += int(best * 0.2)
        elif not interpretation.target_companies:
            score += 10  # no constraint -> neutral

        # --- Industry / keyword match (0-20 pts) ---
        all_kw = interpretation.target_industries + interpretation.keywords
        if all_kw and person.title:
            combined = " ".join(all_kw).lower()
            score += int(fuzz.partial_ratio(person.title.lower(), combined) * 0.2)
        elif not all_kw:
            score += 10

        # --- Location match (0-20 pts) ---
        if person.location and interpretation.target_locations:
            best = max(
                fuzz.partial_ratio(person.location.lower(), loc.lower())
                for loc in interpretation.target_locations
            )
            score += int(best * 0.2)
        elif not interpretation.target_locations:
            score += 10

        # Bonus for having contact info
        if person.email:
            score = min(100, score + 5)
        if person.linkedin:
            score = min(100, score + 3)

        scored.append((min(100, score), person))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        person.model_copy(update={"relevance_score": s})
        for s, person in scored[:max_results]
    ]


# ---------------------------------------------------------------------------
# Helper: enrich a DiscoverResult
# ---------------------------------------------------------------------------


async def _enrich_lead_result(lead: DiscoverResult) -> DiscoverResult:
    """Attempt to enrich a result with email via Apollo / Hunter waterfall."""
    try:
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        if not settings.apollo_api_key and not settings.hunter_api_key:
            return lead  # no keys configured — skip silently

        from src.domain.entities.lead import Lead
        from src.domain.enums import DataSource
        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.enrichment.apollo_adapter import ApolloAdapter
        from src.infrastructure.enrichment.credit_manager import CreditManager
        from src.infrastructure.enrichment.enrichment_pipeline import EnrichmentPipeline
        from src.infrastructure.enrichment.hunter_adapter import HunterAdapter

        session = SessionLocal()
        try:
            credit_mgr = CreditManager(session)
            apollo = ApolloAdapter(settings=settings)
            hunter = HunterAdapter(settings=settings)
            pipeline = EnrichmentPipeline(apollo, hunter, credit_mgr, settings=settings)

            first = lead.first_name or (lead.name.split()[0] if lead.name else "")
            last = lead.last_name or (
                " ".join(lead.name.split()[1:]) if lead.name and len(lead.name.split()) > 1 else ""
            )

            temp = Lead(
                first_name=first,
                last_name=last,
                email=lead.email,
                job_title=lead.title,
                company_name=lead.company,
                source=DataSource.CORPORATE_WEBSITE,
            )

            enriched = await pipeline.enrich(temp)

            return lead.model_copy(
                update={
                    "email": enriched.email or lead.email,
                    "phone": enriched.phone or lead.phone,
                    "linkedin": enriched.linkedin_url or lead.linkedin,
                    "enrichment_status": "completed",
                }
            )
        finally:
            session.close()

    except Exception as exc:
        logger.warning("Enrichment failed for %s: %s", lead.name, exc)
        return lead.model_copy(update={"enrichment_status": "failed"})


# ---------------------------------------------------------------------------
# Helper: save results to the lead database
# ---------------------------------------------------------------------------


def _save_results_to_db(
    results: list[DiscoverResult],
    interpretation: QueryInterpretation,
) -> None:
    """Persist discovered leads and organizations to the database."""
    try:
        from src.application.dtos.lead_dto import LeadCreateDTO
        from src.application.services.deduplication import DeduplicationService
        from src.application.use_cases.ingest_lead import IngestLead
        from src.domain.entities.organization import Organization
        from src.domain.enums import DataSource
        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.database.repositories.sql_lead_repository import (
            SqlLeadRepository,
        )
        from src.infrastructure.database.repositories.sql_organization_repository import (
            SqlOrganizationRepository,
        )

        session = SessionLocal()
        try:
            repo = SqlLeadRepository(session)
            dedup = DeduplicationService(repo)
            ingest = IngestLead(repo, dedup)
            org_repo = SqlOrganizationRepository(session)

            _source_map = {
                "linkedin": DataSource.LINKEDIN,
                "directory": DataSource.BUSINESS_DIRECTORY,
                "website": DataSource.CORPORATE_WEBSITE,
                "sam_gov": DataSource.SAM_GOV,
                "job_posting": DataSource.JOB_POSTING,
            }

            saved_leads = 0
            saved_orgs = 0
            seen_companies: set[str] = set()

            for result in results:
                # --- Save organization if new ---
                if result.company and result.company.lower() not in seen_companies:
                    seen_companies.add(result.company.lower())
                    try:
                        source = _source_map.get(
                            result.source or "website", DataSource.CORPORATE_WEBSITE
                        )
                        org = Organization(
                            name=result.company,
                            source=source,
                            domain=result.company_domain,
                            location=result.location,
                            cage_code=result.cage_code,
                            size_band=result.size_band,
                            segment=result.segment,
                        )
                        org_repo.upsert(org)
                        saved_orgs += 1
                    except Exception as exc:
                        logger.warning("Failed to save org %s: %s", result.company, exc)

                # --- Save lead ---
                try:
                    first = result.first_name or ""
                    last = result.last_name or ""
                    if not first and result.name:
                        parts = result.name.strip().split(None, 1)
                        first = parts[0]
                        last = parts[1] if len(parts) > 1 else ""

                    source = _source_map.get(
                        result.source or "website", DataSource.CORPORATE_WEBSITE
                    )
                    tags = []
                    if result.segment:
                        tags.append(f"segment:{result.segment}")
                    if result.size_band:
                        tags.append(f"size:{result.size_band}")
                    if result.cage_code:
                        tags.append(f"cage:{result.cage_code}")

                    dto = LeadCreateDTO(
                        first_name=first,
                        last_name=last,
                        email=result.email,
                        phone=result.phone,
                        job_title=result.title,
                        company_name=result.company,
                        company_domain=result.company_domain,
                        linkedin_url=result.linkedin,
                        location=result.location,
                        source=source,
                        confidence_score=min(1.0, max(0.0, result.confidence)),
                        tags=tags,
                    )
                    ingest.execute(dto)
                    saved_leads += 1
                except Exception as exc:
                    logger.warning("Failed to save lead %s: %s", result.name, exc)

            logger.info(
                "Saved %d/%d leads and %d orgs to DB",
                saved_leads, len(results), saved_orgs,
            )
        finally:
            session.close()

    except Exception as exc:
        logger.error("Failed to save results to DB: %s", exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
