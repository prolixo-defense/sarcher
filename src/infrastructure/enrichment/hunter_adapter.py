"""
Hunter.io API integration for email discovery and verification.

Free tier: 25 searches/month + 50 verifications/month.
Key endpoints:
  GET /v2/email-finder    — find email by name + domain
  GET /v2/email-verifier  — verify deliverability
  GET /v2/domain-search   — find all emails at a domain

Requires HUNTER_API_KEY in .env (free account at hunter.io).
Used as fallback when Apollo finds no email.
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hunter.io/v2"


class HunterAdapter:
    """
    Wraps Hunter.io email-finder, email-verifier, and domain-search endpoints.

    Returns None / empty list silently when the key is missing or lookup fails.
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()
        self._api_key: str = settings.hunter_api_key
        self._timeout = httpx.Timeout(30.0)

    def _params(self, extra: Optional[dict] = None) -> dict:
        return {"api_key": self._api_key, **(extra or {})}

    async def find_email(
        self, first_name: str, last_name: str, domain: str
    ) -> Optional[dict]:
        """
        Find a person's professional email.

        Returns a dict with: email, confidence — or None if not found.
        """
        if not self._api_key:
            logger.debug("Hunter API key not configured; skipping email find.")
            return None

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{BASE_URL}/email-finder",
                    params=self._params(
                        {
                            "domain": domain,
                            "first_name": first_name,
                            "last_name": last_name,
                        }
                    ),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    email = data.get("email")
                    if email:
                        return {
                            "email": email,
                            "confidence": data.get("confidence", 0),
                            "first_name": data.get("first_name"),
                            "last_name": data.get("last_name"),
                        }
                logger.debug("Hunter find_email: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("Hunter find_email error: %s", exc)
        return None

    async def verify_email(self, email: str) -> dict:
        """
        Verify email deliverability.

        Returns a dict with: status, score, is_valid.
        """
        if not self._api_key:
            return {"status": "unknown", "score": 0, "is_valid": False}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{BASE_URL}/email-verifier",
                    params=self._params({"email": email}),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    status = data.get("status", "unknown")
                    score = data.get("score", 0)
                    return {
                        "status": status,
                        "score": score,
                        "is_valid": status in ("valid", "accept_all"),
                    }
        except Exception as exc:
            logger.warning("Hunter verify_email error: %s", exc)
        return {"status": "unknown", "score": 0, "is_valid": False}

    async def domain_search(self, domain: str) -> list[dict]:
        """
        Find all known emails at a domain (up to 10).

        Returns a list of dicts with: email, first_name, last_name, type.
        """
        if not self._api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{BASE_URL}/domain-search",
                    params=self._params({"domain": domain, "limit": 10}),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    emails = data.get("emails", [])
                    return [
                        {
                            "email": e.get("value"),
                            "first_name": e.get("first_name"),
                            "last_name": e.get("last_name"),
                            "type": e.get("type", "generic"),
                        }
                        for e in emails
                        if e.get("value")
                    ]
        except Exception as exc:
            logger.warning("Hunter domain_search error: %s", exc)
        return []
