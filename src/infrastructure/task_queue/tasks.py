"""
Celery task definitions (with sync fallbacks when Redis is unavailable).

Phase 1 tasks: export_leads, cleanup_expired
Phase 2 tasks: scrape_corporate_website, scrape_linkedin_profile, scrape_directory
Phase 3 tasks: enrich_lead (real implementation using EnrichmentPipeline)
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

from src.infrastructure.task_queue.celery_app import celery_app, CELERY_AVAILABLE  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_scrape_and_ingest(raw_leads: list[dict], source_value: str) -> int:
    """
    Persist a list of raw lead dicts (from a scraper adapter) via IngestLead.
    Returns the count of leads successfully ingested.
    """
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
    from src.application.use_cases.ingest_lead import IngestLead
    from src.application.dtos.lead_dto import LeadCreateDTO
    from src.application.services.deduplication import DeduplicationService
    from src.domain.enums import DataSource

    # Map friendly source names to DataSource enum values
    _SOURCE_MAP = {
        "website": DataSource.CORPORATE_WEBSITE,
        "corporate_website": DataSource.CORPORATE_WEBSITE,
        "linkedin": DataSource.LINKEDIN,
        "directory": DataSource.BUSINESS_DIRECTORY,
        "business_directory": DataSource.BUSINESS_DIRECTORY,
    }
    source = _SOURCE_MAP.get(source_value, DataSource.MANUAL)

    session = SessionLocal()
    try:
        repo = SqlLeadRepository(session)
        dedup = DeduplicationService(repo)
        use_case = IngestLead(repo, dedup)
        count = 0
        for raw in raw_leads:
            try:
                dto = LeadCreateDTO(
                    first_name=raw.get("first_name", ""),
                    last_name=raw.get("last_name", ""),
                    email=raw.get("email"),
                    phone=raw.get("phone"),
                    job_title=raw.get("job_title"),
                    company_name=raw.get("company_name"),
                    company_domain=raw.get("company_domain"),
                    linkedin_url=raw.get("linkedin_url"),
                    location=raw.get("location"),
                    source=source,
                    confidence_score=float(raw.get("confidence_score", 0.7)),
                )
                use_case.execute(dto)
                session.commit()
                count += 1
            except Exception as exc:
                session.rollback()
                logger.warning("Skipping lead from scrape: %s", exc)
        return count
    finally:
        session.close()


def _build_enrichment_use_case(session):
    """Construct an EnrichLead use case with the real EnrichmentPipeline."""
    from src.infrastructure.config.settings import get_settings
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
    from src.infrastructure.enrichment.apollo_adapter import ApolloAdapter
    from src.infrastructure.enrichment.hunter_adapter import HunterAdapter
    from src.infrastructure.enrichment.credit_manager import CreditManager
    from src.infrastructure.enrichment.enrichment_pipeline import EnrichmentPipeline
    from src.application.use_cases.enrich_lead import EnrichLead

    settings = get_settings()
    repo = SqlLeadRepository(session)
    apollo = ApolloAdapter(settings=settings)
    hunter = HunterAdapter(settings=settings)
    credit_mgr = CreditManager(session, settings=settings)
    pipeline = EnrichmentPipeline(apollo, hunter, credit_mgr, settings=settings)
    return EnrichLead(repo, enrichment_pipeline=pipeline)


# ---------------------------------------------------------------------------
# Task definitions (Celery or plain-function fallbacks)
# ---------------------------------------------------------------------------

if CELERY_AVAILABLE and celery_app is not None:

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
    def scrape_target(self, target_url: str, config: dict):
        """Legacy generic scrape placeholder."""
        logger.info("scrape_target queued: %s", target_url)
        return {"status": "queued", "url": target_url}

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
    def enrich_lead(self, lead_id: str):
        """Enrich a lead using the Apollo → Hunter waterfall pipeline."""
        from src.infrastructure.database.connection import SessionLocal

        logger.info("[enrich_lead] %s", lead_id)
        session = SessionLocal()
        try:
            use_case = _build_enrichment_use_case(session)
            enriched = asyncio.run(use_case.execute_async(lead_id))
            session.commit()
            return {
                "lead_id": lead_id,
                "enrichment_status": enriched.enrichment_status.value,
            }
        except Exception as exc:
            session.rollback()
            logger.error("[enrich_lead] failed for %s: %s", lead_id, exc)
            raise self.retry(exc=exc)
        finally:
            session.close()

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
    def export_leads(self, export_config: dict):
        logger.info("export_leads queued: %s", export_config)
        return {"status": "queued", "config": export_config}

    @celery_app.task
    def cleanup_expired():
        """Delete expired leads (GDPR TTL cleanup). Schedule via Celery Beat."""
        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

        session = SessionLocal()
        try:
            repo = SqlLeadRepository(session)
            count = repo.delete_expired()
            session.commit()
            logger.info("Deleted %d expired leads", count)
            return {"deleted": count}
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Phase 2 scraping tasks
    # ------------------------------------------------------------------

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
    def scrape_corporate_website(self, domain: str):
        """Scrape a corporate website for team/contact info and ingest leads."""
        from src.infrastructure.scrapers.adapters.corporate_website import CorporateWebsiteAdapter

        logger.info("[scrape_corporate_website] %s", domain)
        adapter = CorporateWebsiteAdapter()
        raw_leads = asyncio.run(adapter.scrape(domain))
        count = _run_scrape_and_ingest(raw_leads, "corporate_website")
        logger.info("[scrape_corporate_website] ingested %d leads from %s", count, domain)
        return {"domain": domain, "leads_ingested": count}

    @celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
    def scrape_linkedin_profile(self, profile_url: str):
        """Scrape a single LinkedIn profile and ingest as a lead."""
        from src.infrastructure.scrapers.adapters.linkedin_adapter import LinkedInAdapter

        logger.info("[scrape_linkedin_profile] %s", profile_url)
        adapter = LinkedInAdapter()
        raw = asyncio.run(adapter.scrape(profile_url))
        count = _run_scrape_and_ingest([raw] if raw else [], "linkedin")
        return {"profile_url": profile_url, "leads_ingested": count}

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
    def scrape_directory(self, directory_url: str, config: dict):
        """Scrape a business directory page and ingest results."""
        from src.infrastructure.scrapers.adapters.directory_adapter import DirectoryAdapter

        logger.info("[scrape_directory] %s", directory_url)
        adapter = DirectoryAdapter()
        raw_leads = asyncio.run(adapter.scrape(directory_url, config))
        count = _run_scrape_and_ingest(raw_leads, "business_directory")
        return {"directory_url": directory_url, "leads_ingested": count}

else:
    # ------------------------------------------------------------------
    # Sync fallback implementations (no Redis / Celery)
    # ------------------------------------------------------------------

    def scrape_target(target_url: str, config: dict):  # type: ignore[misc]
        logger.info("[sync] scrape_target: %s", target_url)
        return {"status": "sync", "url": target_url}

    def enrich_lead(lead_id: str):  # type: ignore[misc]
        """Synchronous enrichment fallback."""
        from src.infrastructure.database.connection import SessionLocal

        logger.info("[sync] enrich_lead: %s", lead_id)
        session = SessionLocal()
        try:
            use_case = _build_enrichment_use_case(session)
            enriched = asyncio.run(use_case.execute_async(lead_id))
            session.commit()
            return {
                "lead_id": lead_id,
                "enrichment_status": enriched.enrichment_status.value,
            }
        except Exception as exc:
            session.rollback()
            logger.error("[sync] enrich_lead failed for %s: %s", lead_id, exc)
            raise
        finally:
            session.close()

    def export_leads(export_config: dict):  # type: ignore[misc]
        logger.info("[sync] export_leads: %s", export_config)
        return {"status": "sync", "config": export_config}

    def cleanup_expired():  # type: ignore[misc]
        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

        session = SessionLocal()
        try:
            repo = SqlLeadRepository(session)
            count = repo.delete_expired()
            session.commit()
            logger.info("[sync] Deleted %d expired leads", count)
            return {"deleted": count}
        finally:
            session.close()

    def scrape_corporate_website(domain: str):  # type: ignore[misc]
        from src.infrastructure.scrapers.adapters.corporate_website import CorporateWebsiteAdapter

        logger.info("[sync] scrape_corporate_website: %s", domain)
        adapter = CorporateWebsiteAdapter()
        raw_leads = asyncio.run(adapter.scrape(domain))
        count = _run_scrape_and_ingest(raw_leads, "corporate_website")
        return {"domain": domain, "leads_ingested": count}

    def scrape_linkedin_profile(profile_url: str):  # type: ignore[misc]
        from src.infrastructure.scrapers.adapters.linkedin_adapter import LinkedInAdapter

        logger.info("[sync] scrape_linkedin_profile: %s", profile_url)
        adapter = LinkedInAdapter()
        raw = asyncio.run(adapter.scrape(profile_url))
        count = _run_scrape_and_ingest([raw] if raw else [], "linkedin")
        return {"profile_url": profile_url, "leads_ingested": count}

    def scrape_directory(directory_url: str, config: dict):  # type: ignore[misc]
        from src.infrastructure.scrapers.adapters.directory_adapter import DirectoryAdapter

        logger.info("[sync] scrape_directory: %s", directory_url)
        adapter = DirectoryAdapter()
        raw_leads = asyncio.run(adapter.scrape(directory_url, config))
        count = _run_scrape_and_ingest(raw_leads, "business_directory")
        return {"directory_url": directory_url, "leads_ingested": count}
