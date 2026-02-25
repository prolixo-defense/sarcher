"""
ExtractLeadsFromPage use case.

Receives raw HTML from a scraper, runs it through the ExtractionEngine
(LLM-based), and converts the results to LeadCreateDTOs ready for ingestion.
"""
import logging

from src.application.dtos.lead_dto import LeadCreateDTO
from src.domain.enums import DataSource

logger = logging.getLogger(__name__)


class ExtractLeadsFromPage:
    """
    Use case: extract structured leads from raw page HTML using LLM.

    1. Call ExtractionEngine.extract(url, html)
    2. Convert each ExtractedPerson to a LeadCreateDTO
    3. Skip people with neither name nor email
    4. Return the list of DTOs (caller handles ingestion)
    """

    def __init__(self, extraction_engine):
        self._engine = extraction_engine

    async def execute(self, url: str, html: str) -> list[LeadCreateDTO]:
        """Extract leads from *html* fetched from *url*."""
        result = await self._engine.extract(url, html)

        leads: list[LeadCreateDTO] = []
        for person in result.people:
            try:
                first = person.first_name or ""
                last = person.last_name or ""
                if not first and person.full_name:
                    parts = person.full_name.strip().split(None, 1)
                    first = parts[0]
                    last = parts[1] if len(parts) > 1 else ""

                company_name = result.company.name if result.company else None
                company_domain = result.company.domain if result.company else None

                dto = LeadCreateDTO(
                    first_name=first,
                    last_name=last,
                    email=person.email,
                    phone=person.phone,
                    job_title=person.job_title,
                    company_name=company_name,
                    company_domain=company_domain,
                    linkedin_url=person.linkedin_url,
                    source=DataSource.CORPORATE_WEBSITE,
                    confidence_score=min(1.0, max(0.0, result.confidence)),
                )
                leads.append(dto)
            except (ValueError, Exception) as exc:
                logger.warning("Skipping invalid person from extraction: %s", exc)

        logger.info("Extracted %d leads from %s", len(leads), url)
        return leads
