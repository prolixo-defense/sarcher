"""
Waterfall enrichment pipeline.

Tries Apollo.io first (best coverage), falls back to Hunter.io for email,
and tracks all credit usage through CreditManager.
"""
import asyncio
import logging

from src.domain.entities.lead import Lead

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    """
    Waterfall enrichment: Apollo first, Hunter as email fallback.

    Flow per lead:
    1. Apollo person match  → email, title, phone (if enrich_phone=True)
    2. Apollo org enrich    → company name / location if missing
    3. Hunter email finder  → email fallback when Apollo found nothing
    All credit usage is tracked via CreditManager.
    """

    def __init__(self, apollo, hunter, credit_mgr, settings=None):
        self._apollo = apollo
        self._hunter = hunter
        self._credit_mgr = credit_mgr
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()
        self._enrich_phone: bool = settings.enrich_phone

    async def enrich(self, lead: Lead) -> Lead:
        """Run the full waterfall enrichment for a single lead."""
        domain = lead.company_domain

        # --- Step 1: Apollo person match ---
        if lead.first_name and lead.last_name and domain:
            if await self._credit_mgr.can_spend("apollo"):
                try:
                    apollo_person = await self._apollo.match_person(
                        lead.first_name, lead.last_name, domain
                    )
                    if apollo_person:
                        await self._credit_mgr.record_spend(
                            "apollo", 1, lead.id, "people/match"
                        )
                        if apollo_person.get("email") and not lead.email:
                            lead.email = apollo_person["email"]
                        if apollo_person.get("job_title") and not lead.job_title:
                            lead.job_title = apollo_person["job_title"]
                        if (
                            self._enrich_phone
                            and apollo_person.get("phone")
                            and not lead.phone
                        ):
                            lead.phone = apollo_person["phone"]
                        if apollo_person.get("linkedin_url") and not lead.linkedin_url:
                            lead.linkedin_url = apollo_person["linkedin_url"]
                except Exception as exc:
                    logger.warning("Apollo person match failed for %s: %s", lead.id, exc)

        # --- Step 2: Apollo org enrich ---
        if domain:
            if await self._credit_mgr.can_spend("apollo"):
                try:
                    apollo_org = await self._apollo.enrich_organization(domain)
                    if apollo_org:
                        await self._credit_mgr.record_spend(
                            "apollo", 1, lead.id, "organizations/enrich"
                        )
                        if apollo_org.get("name") and not lead.company_name:
                            lead.company_name = apollo_org["name"]
                        if apollo_org.get("location") and not lead.location:
                            lead.location = apollo_org["location"]
                except Exception as exc:
                    logger.warning("Apollo org enrich failed for %s: %s", lead.id, exc)

        # --- Step 3: Hunter email fallback ---
        if not lead.email and lead.first_name and lead.last_name and domain:
            if await self._credit_mgr.can_spend("hunter"):
                try:
                    hunter_result = await self._hunter.find_email(
                        lead.first_name, lead.last_name, domain
                    )
                    if hunter_result and hunter_result.get("email"):
                        await self._credit_mgr.record_spend(
                            "hunter", 1, lead.id, "email-finder"
                        )
                        lead.email = hunter_result["email"]
                except Exception as exc:
                    logger.warning("Hunter email find failed for %s: %s", lead.id, exc)

        return lead

    async def enrich_batch(
        self, leads: list[Lead], concurrency: int = 5
    ) -> list[Lead]:
        """Enrich multiple leads with controlled concurrency."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _enrich_one(lead: Lead) -> Lead:
            async with semaphore:
                try:
                    return await self.enrich(lead)
                except Exception as exc:
                    logger.error("Enrich failed for lead %s: %s", lead.id, exc)
                    return lead

        return list(await asyncio.gather(*(_enrich_one(lead) for lead in leads)))
