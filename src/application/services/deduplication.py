from dataclasses import dataclass

from thefuzz import fuzz

from src.domain.entities.lead import Lead
from src.domain.interfaces.lead_repository import LeadRepository


@dataclass
class DeduplicationResult:
    is_duplicate: bool
    matched_lead: Lead | None
    score: int
    match_reason: str


class DeduplicationService:
    """Detects duplicate leads using exact email match and fuzzy name+company matching."""

    FUZZY_THRESHOLD = 85

    def __init__(self, lead_repository: LeadRepository) -> None:
        self._repo = lead_repository

    def find_duplicate(self, candidate: Lead) -> DeduplicationResult:
        # 1. Exact email match
        if candidate.email:
            existing = self._repo.find_by_email(candidate.email.lower())
            if existing and existing.id != candidate.id:
                return DeduplicationResult(
                    is_duplicate=True,
                    matched_lead=existing,
                    score=100,
                    match_reason="exact_email",
                )

        # 2. Fuzzy name + company match
        if candidate.company_domain:
            same_domain_leads = self._repo.find_by_domain(candidate.company_domain)
            candidate_name = candidate.full_name().lower()
            for existing in same_domain_leads:
                if existing.id == candidate.id:
                    continue
                existing_name = existing.full_name().lower()
                name_score = fuzz.token_sort_ratio(candidate_name, existing_name)
                if name_score >= self.FUZZY_THRESHOLD:
                    return DeduplicationResult(
                        is_duplicate=True,
                        matched_lead=existing,
                        score=name_score,
                        match_reason="fuzzy_name_company",
                    )

        return DeduplicationResult(
            is_duplicate=False,
            matched_lead=None,
            score=0,
            match_reason="",
        )

    def merge(self, existing: Lead, incoming: Lead) -> Lead:
        """Merge incoming data into existing lead, keeping higher-confidence values."""
        if incoming.confidence_score >= existing.confidence_score:
            if incoming.email:
                existing.email = incoming.email
            if incoming.phone:
                existing.phone = incoming.phone
            if incoming.job_title:
                existing.job_title = incoming.job_title
            if incoming.linkedin_url:
                existing.linkedin_url = incoming.linkedin_url
            if incoming.location:
                existing.location = incoming.location
            existing.confidence_score = max(existing.confidence_score, incoming.confidence_score)
        # Always merge tags
        existing.tags = list(set(existing.tags + incoming.tags))
        # Always update raw_data
        if incoming.raw_data:
            existing.raw_data = {**(existing.raw_data or {}), **incoming.raw_data}
        from datetime import datetime, timezone
        existing.updated_at = datetime.now(timezone.utc)
        return existing
