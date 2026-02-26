"""
SAM.gov Entity Information API adapter.

Queries the free SAM.gov Entity Management API v3 to discover registered
government contractors by NAICS code and geography.

API docs: https://open.gsa.gov/api/entity-api/
Requires a free API key from https://sam.gov/data-services/
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.sam.gov/entity-information/v3/entities"
_PAGE_SIZE = 10
_MAX_PAGES = 20  # 200 entities max


class SAMGovAdapter:
    """Adapter for the SAM.gov Entity Information API."""

    def __init__(self, api_key: str = "", timeout: float = 20.0):
        self._api_key = api_key
        self._timeout = timeout

    async def search_entities(
        self,
        naics_codes: list[str] | None = None,
        state: str | None = None,
        page: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Search SAM.gov for active entity registrations.

        Args:
            naics_codes: NAICS codes to filter by (OR logic).
            state: Two-letter US state code (e.g. "VA").
            page: Zero-based page number.

        Returns:
            List of parsed entity dicts.
        """
        if not self._api_key:
            logger.debug("SAM.gov API key not configured — skipping")
            return []

        params: dict[str, str] = {
            "api_key": self._api_key,
            "registrationStatus": "A",
            "includeSections": "entityRegistration,coreData,pointsOfContact",
            "page": str(page),
            "size": str(_PAGE_SIZE),
        }

        if naics_codes:
            params["naicsCode"] = ",".join(naics_codes)
        if state:
            params["physicalAddressStateCode"] = state.upper()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("SAM.gov API error (HTTP %d): %s", exc.response.status_code, exc)
            return []
        except Exception as exc:
            logger.warning("SAM.gov API request failed: %s", exc)
            return []

        entities_raw = data.get("entityData", [])
        return [self._parse_entity(e) for e in entities_raw]

    async def search_all_pages(
        self,
        naics_codes: list[str] | None = None,
        state: str | None = None,
        max_pages: int = _MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """
        Paginate through SAM.gov results up to max_pages.

        Returns all parsed entities across pages (up to max_pages * PAGE_SIZE).
        """
        all_entities: list[dict[str, Any]] = []
        for page in range(max_pages):
            batch = await self.search_entities(naics_codes=naics_codes, state=state, page=page)
            if not batch:
                break
            all_entities.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break  # last page
        logger.info("SAM.gov: fetched %d entities across %d+ page(s)", len(all_entities), page + 1)
        return all_entities

    def _parse_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Parse a SAM.gov entity response into a flat dict."""
        reg = entity.get("entityRegistration", {})
        core = entity.get("coreData", {})
        pocs = entity.get("pointsOfContact", {})

        # Physical address
        phys = core.get("physicalAddress", {})
        address_parts = [
            phys.get("addressLine1", ""),
            phys.get("addressLine2", ""),
        ]
        address = ", ".join(p for p in address_parts if p).strip(", ")
        city = phys.get("city", "")
        state_code = phys.get("stateOrProvinceCode", "")
        zip_code = phys.get("zipCode", "")

        # Government business POC
        gov_poc = pocs.get("governmentBusinessPOC", {})
        poc_first = gov_poc.get("firstName", "")
        poc_last = gov_poc.get("lastName", "")
        poc_email = gov_poc.get("email", "")
        poc_phone = gov_poc.get("usPhone", "")
        poc_title = gov_poc.get("title", "")

        # NAICS codes from the entity
        general_info = core.get("generalInformation", {})
        naics_list = general_info.get("naicsCodeList", [])
        naics_codes = []
        for entry in naics_list:
            if isinstance(entry, dict):
                code = entry.get("naicsCode", "")
                if code:
                    naics_codes.append(str(code))
            elif isinstance(entry, str):
                naics_codes.append(entry)

        return {
            "legal_name": reg.get("legalBusinessName", ""),
            "dba_name": reg.get("dbaName", ""),
            "cage_code": reg.get("cageCode", ""),
            "uei": reg.get("ueiSAM", ""),
            "sam_status": reg.get("registrationStatus", ""),
            "address": address,
            "city": city,
            "state": state_code,
            "zip_code": zip_code,
            "poc_first": poc_first,
            "poc_last": poc_last,
            "poc_email": poc_email,
            "poc_phone": poc_phone,
            "poc_title": poc_title,
            "naics_codes": naics_codes,
            "entity_type": general_info.get("entityStructureDesc", ""),
            "organization_type": general_info.get("organizationStructureDesc", ""),
        }
