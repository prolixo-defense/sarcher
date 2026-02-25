"""
Apollo.io API integration for lead enrichment.

Free tier: 10,000 credits/month (as of 2025).
Key endpoints:
  POST /api/v1/people/match        — match person by name + domain → email, title, phone
  POST /api/v1/organizations/enrich — company firmographic data

Requires APOLLO_API_KEY in .env (free account at apollo.io).
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.apollo.io/api/v1"


class ApolloAdapter:
    """
    Wraps Apollo.io people/match and organizations/enrich endpoints.

    Returns None silently when the API key is missing or the lookup fails
    (the enrichment pipeline falls through to the next provider).
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()
        self._api_key: str = settings.apollo_api_key
        self._timeout = httpx.Timeout(30.0)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self._api_key,
        }

    async def match_person(
        self, first_name: str, last_name: str, domain: str
    ) -> Optional[dict]:
        """
        Match a person by name + company domain.

        Returns a dict with: email, job_title, phone, linkedin_url — or None.
        """
        if not self._api_key:
            logger.debug("Apollo API key not configured; skipping person match.")
            return None

        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "organization_domains": [domain],
            "reveal_personal_emails": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{BASE_URL}/people/match",
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    person = data.get("person") or {}
                    if not person:
                        return None
                    phones = person.get("phone_numbers") or []
                    return {
                        "email": person.get("email"),
                        "job_title": person.get("title"),
                        "phone": phones[0].get("sanitized_number") if phones else None,
                        "linkedin_url": person.get("linkedin_url"),
                    }
                logger.debug("Apollo match_person: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("Apollo match_person error: %s", exc)
        return None

    async def enrich_organization(self, domain: str) -> Optional[dict]:
        """
        Enrich a company by domain.

        Returns a dict with: name, industry, employee_count, annual_revenue,
        technologies, location — or None.
        """
        if not self._api_key:
            logger.debug("Apollo API key not configured; skipping org enrich.")
            return None

        payload = {"domain": domain}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{BASE_URL}/organizations/enrich",
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    org = data.get("organization") or {}
                    if not org:
                        return None
                    techs = org.get("current_technologies") or []
                    return {
                        "name": org.get("name"),
                        "industry": org.get("industry"),
                        "employee_count": org.get("estimated_num_employees"),
                        "annual_revenue": org.get("annual_revenue_printed"),
                        "technologies": [t.get("name", "") for t in techs],
                        "location": org.get("city"),
                    }
                logger.debug("Apollo enrich_organization: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("Apollo enrich_organization error: %s", exc)
        return None
