from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScrapeRequest(BaseModel):
    target_url: str
    config: dict = {}


class WebsiteScrapeRequest(BaseModel):
    domain: str


class LinkedInScrapeRequest(BaseModel):
    profile_url: str


class DirectoryScrapeRequest(BaseModel):
    directory_url: str
    selectors: Optional[dict] = None


class BatchScrapeTarget(BaseModel):
    target: str
    source_type: str = "website"   # website | linkedin | directory
    config: Optional[dict] = None


class BatchScrapeRequest(BaseModel):
    targets: list[BatchScrapeTarget]


class EnrichRequest(BaseModel):
    lead_id: str


class TaskResponse(BaseModel):
    task_id: str | None
    status: str
    message: str


# ---------------------------------------------------------------------------
# Phase 1 endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------


@router.post("/scrape", response_model=TaskResponse)
def queue_scrape(req: ScrapeRequest):
    from src.infrastructure.task_queue.tasks import scrape_target, CELERY_AVAILABLE
    if CELERY_AVAILABLE:
        task = scrape_target.delay(req.target_url, req.config)
        return TaskResponse(task_id=task.id, status="queued", message="Scrape job queued.")
    scrape_target(req.target_url, req.config)
    return TaskResponse(task_id=None, status="sync", message="Scrape ran synchronously (no Redis).")


@router.post("/cleanup", response_model=TaskResponse)
def run_cleanup():
    from src.infrastructure.task_queue.tasks import cleanup_expired, CELERY_AVAILABLE
    if CELERY_AVAILABLE:
        task = cleanup_expired.delay()
        return TaskResponse(task_id=task.id, status="queued", message="Cleanup job queued.")
    result = cleanup_expired()
    return TaskResponse(
        task_id=None,
        status="done",
        message=f"Cleanup complete. Deleted: {result.get('deleted', 0)} expired leads.",
    )


@router.get("/{task_id}", response_model=dict)
def get_task_status(task_id: str):
    from src.infrastructure.task_queue.celery_app import CELERY_AVAILABLE, celery_app
    if not CELERY_AVAILABLE or celery_app is None:
        raise HTTPException(status_code=503, detail="Celery is not available.")
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


# ---------------------------------------------------------------------------
# Phase 2 scraping endpoints
# ---------------------------------------------------------------------------


@router.post("/scrape/website", response_model=TaskResponse)
def scrape_website(req: WebsiteScrapeRequest):
    """Queue (or run) a corporate website scrape job."""
    from src.infrastructure.task_queue.tasks import scrape_corporate_website, CELERY_AVAILABLE

    if CELERY_AVAILABLE:
        task = scrape_corporate_website.delay(req.domain)
        return TaskResponse(
            task_id=task.id,
            status="queued",
            message=f"Website scrape queued for {req.domain}.",
        )
    result = scrape_corporate_website(req.domain)
    return TaskResponse(
        task_id=None,
        status="done",
        message=f"Scraped {req.domain}: {result.get('leads_ingested', 0)} leads ingested.",
    )


@router.post("/scrape/linkedin", response_model=TaskResponse)
def scrape_linkedin(req: LinkedInScrapeRequest):
    """Queue (or run) a LinkedIn profile scrape job."""
    from src.infrastructure.task_queue.tasks import scrape_linkedin_profile, CELERY_AVAILABLE

    if CELERY_AVAILABLE:
        task = scrape_linkedin_profile.delay(req.profile_url)
        return TaskResponse(
            task_id=task.id,
            status="queued",
            message=f"LinkedIn scrape queued for {req.profile_url}.",
        )
    result = scrape_linkedin_profile(req.profile_url)
    return TaskResponse(
        task_id=None,
        status="done",
        message=f"Scraped LinkedIn profile: {result.get('leads_ingested', 0)} leads ingested.",
    )


@router.post("/scrape/directory", response_model=TaskResponse)
def scrape_directory_endpoint(req: DirectoryScrapeRequest):
    """Queue (or run) a business directory scrape job."""
    from src.infrastructure.task_queue.tasks import scrape_directory, CELERY_AVAILABLE

    config = req.selectors or {}
    if CELERY_AVAILABLE:
        task = scrape_directory.delay(req.directory_url, config)
        return TaskResponse(
            task_id=task.id,
            status="queued",
            message=f"Directory scrape queued for {req.directory_url}.",
        )
    result = scrape_directory(req.directory_url, config)
    return TaskResponse(
        task_id=None,
        status="done",
        message=f"Scraped directory: {result.get('leads_ingested', 0)} leads ingested.",
    )


@router.post("/scrape/batch", response_model=list[TaskResponse])
def scrape_batch(req: BatchScrapeRequest):
    """Queue multiple scrape jobs at once."""
    from src.infrastructure.task_queue.tasks import (
        scrape_corporate_website,
        scrape_linkedin_profile,
        scrape_directory,
        CELERY_AVAILABLE,
    )

    responses: list[TaskResponse] = []
    for item in req.targets:
        try:
            cfg = item.config or {}
            if item.source_type == "linkedin":
                if CELERY_AVAILABLE:
                    task = scrape_linkedin_profile.delay(item.target)
                    responses.append(TaskResponse(task_id=task.id, status="queued", message=item.target))
                else:
                    result = scrape_linkedin_profile(item.target)
                    responses.append(TaskResponse(task_id=None, status="done",
                                                   message=f"{item.target}: {result.get('leads_ingested', 0)} leads"))
            elif item.source_type == "directory":
                if CELERY_AVAILABLE:
                    task = scrape_directory.delay(item.target, cfg)
                    responses.append(TaskResponse(task_id=task.id, status="queued", message=item.target))
                else:
                    result = scrape_directory(item.target, cfg)
                    responses.append(TaskResponse(task_id=None, status="done",
                                                   message=f"{item.target}: {result.get('leads_ingested', 0)} leads"))
            else:  # website (default)
                if CELERY_AVAILABLE:
                    task = scrape_corporate_website.delay(item.target)
                    responses.append(TaskResponse(task_id=task.id, status="queued", message=item.target))
                else:
                    result = scrape_corporate_website(item.target)
                    responses.append(TaskResponse(task_id=None, status="done",
                                                   message=f"{item.target}: {result.get('leads_ingested', 0)} leads"))
        except Exception as exc:
            responses.append(TaskResponse(task_id=None, status="error", message=f"{item.target}: {exc}"))

    return responses


# ---------------------------------------------------------------------------
# Phase 3 enrichment endpoints
# ---------------------------------------------------------------------------


@router.post("/enrich/{lead_id}", response_model=TaskResponse)
def enrich_lead_endpoint(lead_id: str):
    """Queue (or run) enrichment for a single lead."""
    from src.infrastructure.task_queue.tasks import enrich_lead, CELERY_AVAILABLE

    if CELERY_AVAILABLE:
        task = enrich_lead.delay(lead_id)
        return TaskResponse(
            task_id=task.id,
            status="queued",
            message=f"Enrichment queued for lead {lead_id}.",
        )
    result = enrich_lead(lead_id)
    return TaskResponse(
        task_id=None,
        status="done",
        message=f"Lead {lead_id} enriched: {result.get('enrichment_status', 'unknown')}.",
    )


@router.get("/credits/summary", response_model=dict)
def get_credit_summary():
    """Return current month API credit usage per provider."""
    import asyncio
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.enrichment.credit_manager import CreditManager

    session = SessionLocal()
    try:
        mgr = CreditManager(session)
        summary = asyncio.run(mgr.get_usage_summary())
        return {"credits": summary}
    finally:
        session.close()
