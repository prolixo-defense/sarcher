"""
Predefined workflow definitions and callable workflow functions.

These are used by the WorkflowScheduler and DAGRunner.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow callable functions (for APScheduler)
# ---------------------------------------------------------------------------


def run_campaign_processing(**kwargs) -> None:
    """Process all active campaigns. Called by scheduler."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_campaign_repository import SqlCampaignRepository
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
    from src.infrastructure.outreach.email_sender import EmailSender
    from src.infrastructure.outreach.sequence_manager import SequenceManager

    session = SessionLocal()
    try:
        campaign_repo = SqlCampaignRepository(session)
        message_repo = SqlMessageRepository(session)
        email_sender = EmailSender()
        manager = SequenceManager(campaign_repo, message_repo, email_sender)

        campaigns = campaign_repo.find_all({"status": "active"})
        for campaign in campaigns:
            try:
                result = asyncio.run(manager.process_campaign(campaign.id))
                logger.info("[Workflow] Campaign %s: %s", campaign.id, result)
            except Exception as exc:
                logger.error("[Workflow] Campaign %s processing failed: %s", campaign.id, exc)
        session.commit()
    except Exception as exc:
        logger.error("[Workflow] run_campaign_processing failed: %s", exc)
        session.rollback()
    finally:
        session.close()


def run_cleanup_expired(**kwargs) -> None:
    """Clean up expired leads (GDPR TTL). Called by scheduler."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.compliance.gdpr_manager import GDPRManager

    session = SessionLocal()
    try:
        gdpr = GDPRManager(session)
        count = asyncio.run(gdpr.cleanup_expired())
        session.commit()
        logger.info("[Workflow] Cleaned up %d expired leads", count)
    except Exception as exc:
        logger.error("[Workflow] run_cleanup_expired failed: %s", exc)
        session.rollback()
    finally:
        session.close()


def run_credit_report(**kwargs) -> None:
    """Log daily credit usage summary. Called by scheduler."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.enrichment.credit_manager import CreditManager

    session = SessionLocal()
    try:
        mgr = CreditManager(session)
        summary = asyncio.run(mgr.get_usage_summary())
        for provider, data in summary.items():
            logger.info(
                "[Credits] %s: %d/%d used (%d remaining) — month %s",
                provider,
                data["used"],
                data["budget"],
                data["remaining"],
                data["month"],
            )
    except Exception as exc:
        logger.error("[Workflow] run_credit_report failed: %s", exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Full pipeline DAG definition
# ---------------------------------------------------------------------------


FULL_PIPELINE_WORKFLOW = {
    "discover": {
        "description": "Scrape target websites for leads",
        "func": "scrape_targets",  # Resolved at runtime
        "depends_on": [],
        "retry": 2,
    },
    "extract": {
        "description": "LLM extraction from scraped pages",
        "func": "extract_leads",
        "depends_on": ["discover"],
        "retry": 2,
    },
    "deduplicate": {
        "description": "Remove duplicate leads",
        "func": "deduplicate_leads",
        "depends_on": ["extract"],
        "retry": 1,
    },
    "enrich": {
        "description": "Enrich leads via Apollo/Hunter waterfall",
        "func": "enrich_leads",
        "depends_on": ["deduplicate"],
        "retry": 3,
    },
    "qualify": {
        "description": "Score and qualify leads",
        "func": "qualify_leads",
        "depends_on": ["enrich"],
        "retry": 1,
    },
    "outreach": {
        "description": "Queue outreach for qualified leads",
        "func": "queue_outreach",
        "depends_on": ["qualify"],
        "retry": 1,
    },
}


async def build_pipeline_dag(targets: list[str], campaign_id: str | None = None) -> dict:
    """
    Build a runnable pipeline DAG from target URLs.
    Substitutes string function names with actual callables.
    """
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

    async def scrape_targets(context: dict, results: dict) -> dict:
        from src.infrastructure.scrapers.adapters.corporate_website import CorporateWebsiteAdapter
        all_leads = []
        for target in context.get("targets", []):
            adapter = CorporateWebsiteAdapter()
            leads = await adapter.scrape(target)
            all_leads.extend(leads)
        return {"raw_leads": all_leads, "count": len(all_leads)}

    async def extract_leads(context: dict, results: dict) -> dict:
        raw_leads = results.get("discover", {}).get("result", {}).get("raw_leads", [])
        return {"leads": raw_leads, "count": len(raw_leads)}

    async def deduplicate_leads(context: dict, results: dict) -> dict:
        leads = results.get("extract", {}).get("result", {}).get("leads", [])
        # Simple dedup by email
        seen_emails = set()
        unique = []
        for lead in leads:
            key = lead.get("email") or f"{lead.get('first_name')}_{lead.get('last_name')}_{lead.get('company_domain')}"
            if key not in seen_emails:
                seen_emails.add(key)
                unique.append(lead)
        return {"leads": unique, "count": len(unique)}

    async def enrich_leads(context: dict, results: dict) -> dict:
        from src.infrastructure.task_queue.tasks import _build_enrichment_use_case
        leads_data = results.get("deduplicate", {}).get("result", {}).get("leads", [])
        session = SessionLocal()
        enriched_count = 0
        try:
            repo = SqlLeadRepository(session)
            for lead_data in leads_data[:10]:  # Limit to 10 for safety
                lead = repo.find_by_id(lead_data.get("id", ""))
                if lead:
                    use_case = _build_enrichment_use_case(session)
                    await use_case.execute_async(lead.id)
                    enriched_count += 1
            session.commit()
        finally:
            session.close()
        return {"enriched": enriched_count}

    async def qualify_leads(context: dict, results: dict) -> dict:
        # Simple qualification: leads with email AND job_title are qualified
        session = SessionLocal()
        try:
            repo = SqlLeadRepository(session)
            all_leads, _ = repo.search({}, limit=100, offset=0)
            qualified = [l for l in all_leads if l.email and l.job_title]
            return {"qualified_count": len(qualified)}
        finally:
            session.close()

    async def queue_outreach(context: dict, results: dict) -> dict:
        cid = context.get("campaign_id")
        if not cid:
            return {"queued": 0, "note": "No campaign_id in context"}
        return {"queued": 0, "campaign_id": cid}

    return {
        "discover": {"func": scrape_targets, "depends_on": [], "retry": 2},
        "extract": {"func": extract_leads, "depends_on": ["discover"], "retry": 1},
        "deduplicate": {"func": deduplicate_leads, "depends_on": ["extract"], "retry": 1},
        "enrich": {"func": enrich_leads, "depends_on": ["deduplicate"], "retry": 2},
        "qualify": {"func": qualify_leads, "depends_on": ["enrich"], "retry": 1},
        "outreach": {"func": queue_outreach, "depends_on": ["qualify"], "retry": 1},
    }
