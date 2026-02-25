"""
Natural language lead discovery endpoint with SSE streaming progress.

Pipeline:
1. POST /api/discover  → creates a job, starts background task, returns {job_id}
2. GET  /api/discover/{job_id}/stream → SSE stream of progress events
3. Final SSE event "complete" includes results + stats

Pipeline stages:
  INTERPRET → SEARCH → SCRAPE → EXTRACT → MATCH → [ENRICH] → [SAVE] → COMPLETE
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

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
    max_results: int = 25
    enrich: bool = False
    save: bool = True


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


class DiscoverJobResponse(BaseModel):
    job_id: str
    stream_url: str


# ---------------------------------------------------------------------------
# LLM prompt for query interpretation
# ---------------------------------------------------------------------------

_DISCOVER_PROMPT = """\
You are a B2B lead research assistant. Parse the user's description and return \
structured search parameters as valid JSON.

Generate 3-5 effective web search queries to find company team pages, \
LinkedIn profiles, or directory listings matching these people.

Focus search queries on pages that list employees, e.g.:
- "SaaS startup New York team page"
- "fintech VP Engineering linkedin.com"
- "marketing director B2B software company about us"

User description: {query}
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
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
# Pipeline
# ---------------------------------------------------------------------------


async def _run_discovery_pipeline(job_id: str, request: DiscoverRequest) -> None:
    """Background task: orchestrate the full discovery pipeline."""
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
        # Stage 1: Interpret the natural language query
        # ------------------------------------------------------------------
        await emit("interpreting", "Understanding your search...", 5)
        interpretation = await _interpret_query(request.query)
        await emit(
            "searching",
            f"Generated {len(interpretation.search_queries)} search queries.",
            15,
            queries=interpretation.search_queries,
            interpretation=interpretation.model_dump(),
        )

        # ------------------------------------------------------------------
        # Stage 2: Search for relevant URLs
        # ------------------------------------------------------------------
        urls = await _search_for_urls(interpretation.search_queries)
        logger.info("Discovery job %s: found %d URLs", job_id, len(urls))

        # ------------------------------------------------------------------
        # Stage 3: Scrape + Extract
        # ------------------------------------------------------------------
        all_people: list[DiscoverResult] = []
        scrape_targets = urls[:10]  # cap at 10 pages for speed

        for i, url_info in enumerate(scrape_targets):
            url = url_info.get("url", "")
            if not url:
                continue

            progress = 20 + int(50 * (i / max(len(scrape_targets), 1)))
            await emit(
                "scraping",
                f"Scraping page {i + 1} of {len(scrape_targets)}: {_truncate(url, 60)}",
                progress,
            )

            try:
                people = await _scrape_and_extract(
                    url,
                    url_info.get("title", ""),
                    interpretation,
                )
                all_people.extend(people)
                pages_scraped += 1
                people_found = len(all_people)
                await emit(
                    "extracting",
                    f"Found {people_found} people so far...",
                    progress + 3,
                    count=people_found,
                )
            except Exception as exc:
                logger.warning("Scrape/extract failed for %s: %s", url, exc)

        # ------------------------------------------------------------------
        # Stage 4: Match & Rank
        # ------------------------------------------------------------------
        await emit("matching", "Filtering to relevant matches...", 75)
        matched = _match_and_rank(all_people, interpretation, request.max_results)
        await emit(
            "matching",
            f"Matched {len(matched)} relevant leads",
            80,
            matched=len(matched),
        )

        # ------------------------------------------------------------------
        # Stage 5: Enrich (optional — full pipeline or explicit enrich=True)
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
        # Stage 6: Save to database
        # ------------------------------------------------------------------
        if request.save and matched:
            await emit("saving", f"Saving {len(matched)} leads to database...", 97)
            _save_results_to_db(matched, interpretation)

        # ------------------------------------------------------------------
        # Complete
        # ------------------------------------------------------------------
        elapsed = round(time.monotonic() - start_time, 1)
        await emit(
            "complete",
            f"Done! Found {len(matched)} matching leads.",
            100,
            results=[r.model_dump() for r in matched],
            stats={
                "pages_scraped": pages_scraped,
                "people_found": people_found,
                "people_matched": len(matched),
                "people_enriched": sum(
                    1 for r in matched if r.enrichment_status == "completed"
                ),
                "time_elapsed_seconds": elapsed,
            },
            query_interpretation=interpretation.model_dump(),
        )

    except Exception as exc:
        logger.exception("Discovery pipeline failed for job %s", job_id)
        await emit("error", f"Pipeline failed: {exc}", 0)


# ---------------------------------------------------------------------------
# Helper: interpret query via LLM (with heuristic fallback)
# ---------------------------------------------------------------------------


async def _interpret_query(query: str) -> QueryInterpretation:
    """Use LLM to extract structured search parameters from natural language."""
    try:
        from src.infrastructure.llm.llm_client import LLMClient

        client = LLMClient()
        prompt = _DISCOVER_PROMPT.format(query=query)
        result: QueryInterpretation = await client.extract_structured(
            content=prompt,
            response_model=QueryInterpretation,
            temperature=0.2,
            max_retries=2,
        )
        # Ensure we always have at least some search queries
        if not result.search_queries:
            result = result.model_copy(
                update={"search_queries": _fallback_queries(query, result)}
            )
        return result
    except Exception as exc:
        logger.warning("LLM interpretation failed, using heuristics: %s", exc)
        return _heuristic_interpret(query)


def _heuristic_interpret(query: str) -> QueryInterpretation:
    """Simple keyword-based interpretation when LLM is unavailable."""
    words = query.lower().split()

    title_keywords = {
        "cto", "ceo", "coo", "cpo", "vp", "director", "manager", "head",
        "president", "founder", "engineer", "developer", "designer",
        "analyst", "sales", "marketing", "product", "finance", "recruiter",
    }
    industry_keywords = {
        "saas", "fintech", "healthcare", "edtech", "ecommerce", "b2b",
        "b2c", "startup", "software", "tech", "ai", "ml", "data",
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
    base = query[:80]
    queries = [
        f"{base} team page",
        f"{base} about us employees",
    ]
    if interp.target_titles:
        title = interp.target_titles[0]
        industry = interp.target_industries[0] if interp.target_industries else ""
        queries.append(f"{title} {industry} company team".strip())
    queries.append(f"{base} linkedin.com/in")
    queries.append(f"{base} company directory")
    return queries[:5]


# ---------------------------------------------------------------------------
# Helper: search for URLs
# ---------------------------------------------------------------------------


async def _search_for_urls(queries: list[str]) -> list[dict]:
    """Run each search query and collect unique, useful URLs."""
    from src.infrastructure.scrapers.adapters.google_search import GoogleSearchAdapter

    adapter = GoogleSearchAdapter()
    seen_urls: set[str] = set()
    results: list[dict] = []

    for query in queries[:5]:
        try:
            hits = await adapter.search(query, num_results=5)
            for hit in hits:
                url = hit.get("url", "")
                if url and url not in seen_urls and _is_useful_url(url):
                    seen_urls.add(url)
                    results.append(hit)
        except Exception as exc:
            logger.warning("Search failed for query %r: %s", query, exc)

    return results


def _is_useful_url(url: str) -> bool:
    """Filter out URLs unlikely to contain people data."""
    skip = {
        "google.com", "bing.com", "yahoo.com", "youtube.com",
        "twitter.com", "x.com", "facebook.com", "wikipedia.org",
        "reddit.com", "amazon.com", "glassdoor.com", "indeed.com",
        "yelp.com", "crunchbase.com", "duckduckgo.com",
    }
    url_lower = url.lower()
    return not any(s in url_lower for s in skip)


# ---------------------------------------------------------------------------
# Helper: scrape + extract people from a URL
# ---------------------------------------------------------------------------


async def _scrape_and_extract(
    url: str,
    page_title: str,
    interpretation: QueryInterpretation,
) -> list[DiscoverResult]:
    """Fetch a URL and extract structured people data."""
    from src.infrastructure.scrapers.http_scraper import HttpScraper
    from src.infrastructure.llm.extraction_engine import ExtractionEngine

    scraper = HttpScraper()
    response = await scraper.fetch(url)

    if not response.html or response.was_blocked or response.status_code >= 400:
        return []

    engine = ExtractionEngine()
    extraction = await engine.extract(url, response.html)

    company_name: str | None = None
    if extraction.company:
        company_name = extraction.company.name
    else:
        company_name = _guess_company_from_url(url, page_title)

    location: str | None = extraction.company.location if extraction.company else None
    source = _classify_source(url)
    confidence = float(extraction.confidence)

    results: list[DiscoverResult] = []
    for person in extraction.people:
        full_name = (
            person.full_name
            or f"{person.first_name or ''} {person.last_name or ''}".strip()
        )
        if not full_name:
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
            )
        )

    return results


def _guess_company_from_url(url: str, title: str) -> str | None:
    import re
    from urllib.parse import urlparse

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

        # --- Title match (0–40 pts) ---
        if person.title and interpretation.target_titles:
            best = max(
                fuzz.partial_ratio(person.title.lower(), t.lower())
                for t in interpretation.target_titles
            )
            score += int(best * 0.4)
        elif not interpretation.target_titles:
            score += 20  # no constraint → neutral

        # --- Company match (0–20 pts) ---
        if person.company and interpretation.target_companies:
            best = max(
                fuzz.partial_ratio(person.company.lower(), c.lower())
                for c in interpretation.target_companies
            )
            score += int(best * 0.2)
        elif not interpretation.target_companies:
            score += 10  # no constraint → neutral

        # --- Industry / keyword match (0–20 pts) ---
        all_kw = interpretation.target_industries + interpretation.keywords
        if all_kw and person.title:
            combined = " ".join(all_kw).lower()
            score += int(fuzz.partial_ratio(person.title.lower(), combined) * 0.2)
        elif not all_kw:
            score += 10

        # --- Location match (0–20 pts) ---
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
    """Persist discovered leads to the database using IngestLead."""
    try:
        from src.application.dtos.lead_dto import LeadCreateDTO
        from src.application.services.deduplication import DeduplicationService
        from src.application.use_cases.ingest_lead import IngestLead
        from src.domain.enums import DataSource
        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.database.repositories.sql_lead_repository import (
            SqlLeadRepository,
        )

        session = SessionLocal()
        try:
            repo = SqlLeadRepository(session)
            dedup = DeduplicationService(repo)
            ingest = IngestLead(repo, dedup)

            _source_map = {
                "linkedin": DataSource.LINKEDIN,
                "directory": DataSource.BUSINESS_DIRECTORY,
                "website": DataSource.CORPORATE_WEBSITE,
            }

            saved = 0
            for result in results:
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
                    dto = LeadCreateDTO(
                        first_name=first,
                        last_name=last,
                        email=result.email,
                        phone=result.phone,
                        job_title=result.title,
                        company_name=result.company,
                        linkedin_url=result.linkedin,
                        location=result.location,
                        source=source,
                        confidence_score=min(1.0, max(0.0, result.confidence)),
                    )
                    ingest.execute(dto)
                    saved += 1
                except Exception as exc:
                    logger.warning("Failed to save lead %s: %s", result.name, exc)

            logger.info("Saved %d/%d discovered leads to DB", saved, len(results))
        finally:
            session.close()

    except Exception as exc:
        logger.error("Failed to save results to DB: %s", exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
