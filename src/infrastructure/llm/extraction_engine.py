"""
Orchestrates LLM-based data extraction from web pages.

Flow:
1. Detect page type (team / profile / directory / about) from URL + content
2. Preprocess HTML → clean Markdown (HtmlPreprocessor)
3. Select appropriate prompt template
4. Call LLM with prompt + content (via LLMClient + instructor)
5. Post-process: normalise names, validate emails, clean phones
6. Return PageExtractionResult
"""
import logging
import re
from typing import Optional

from src.application.schemas.extraction_schemas import PageExtractionResult
from src.infrastructure.llm.html_preprocessor import HtmlPreprocessor
from src.infrastructure.llm.llm_client import LLMClient
from src.infrastructure.llm.prompt_templates import (
    DIRECTORY_LISTING_EXTRACTION,
    LINKEDIN_PROFILE_EXTRACTION,
    TEAM_PAGE_EXTRACTION,
)

logger = logging.getLogger(__name__)

_TEAM_URL_RE = re.compile(
    r"/(team|our-team|leadership|management|people|staff|about|who-we-are|bios?)",
    re.IGNORECASE,
)
_LINKEDIN_RE = re.compile(r"linkedin\.com", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_TEAM_CONTENT_KEYWORDS = [
    "our team",
    "meet the team",
    "leadership team",
    "management team",
    "our people",
    "meet our",
    "our leadership",
    "team members",
]


class ExtractionEngine:
    """
    Orchestrates LLM-based extraction from web pages.

    Combine with HtmlPreprocessor (cleans HTML) and LLMClient (calls LLM)
    to transform raw scraped HTML into validated PageExtractionResult objects.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        preprocessor: Optional[HtmlPreprocessor] = None,
    ):
        self._llm = llm_client or LLMClient()
        self._prep = preprocessor or HtmlPreprocessor()

    async def extract(self, url: str, raw_html: str) -> PageExtractionResult:
        """Full extraction pipeline for a single page."""
        preprocessed = self._prep.preprocess(raw_html)
        markdown = preprocessed["cleaned_markdown"]

        page_type = self._detect_page_type(url, markdown)
        prompt = self._select_prompt(page_type)

        try:
            result = await self._llm.extract_structured(
                content=markdown,
                response_model=PageExtractionResult,
                system_prompt=prompt,
            )
        except Exception as exc:
            logger.error("LLM extraction failed for %s: %s", url, exc)
            result = PageExtractionResult(
                page_type=page_type,
                confidence=0.0,
                extraction_notes=f"LLM extraction failed: {exc}",
            )

        return self._post_process(result)

    def _detect_page_type(self, url: str, markdown: str) -> str:
        """Heuristic page-type classification using URL and content signals."""
        if _LINKEDIN_RE.search(url):
            return "profile"
        if _TEAM_URL_RE.search(url):
            return "team"

        # Content-based signals
        lower = markdown.lower()
        if any(kw in lower for kw in _TEAM_CONTENT_KEYWORDS):
            return "team"

        # Multiple geo-markers suggest a directory listing
        location_hits = sum(
            lower.count(loc)
            for loc in (", ca", ", ny", ", tx", ", fl", "san francisco", "new york")
        )
        if location_hits >= 3:
            return "directory_listing"

        return "about"

    @staticmethod
    def _select_prompt(page_type: str) -> str:
        if page_type == "profile":
            return LINKEDIN_PROFILE_EXTRACTION
        if page_type == "directory_listing":
            return DIRECTORY_LISTING_EXTRACTION
        return TEAM_PAGE_EXTRACTION  # covers team, about, contact

    def _post_process(self, result: PageExtractionResult) -> PageExtractionResult:
        """Clean LLM output: split names, validate emails, normalise phones."""
        cleaned_people = []
        for person in result.people:
            # Split full_name → first/last when not already done
            first = person.first_name or ""
            last = person.last_name or ""
            if not first and person.full_name:
                parts = person.full_name.strip().split(None, 1)
                first = parts[0]
                last = parts[1] if len(parts) > 1 else ""
                person = person.model_copy(
                    update={"first_name": first, "last_name": last}
                )

            # Validate email format — drop obviously bad values
            if person.email and not _EMAIL_RE.match(person.email.strip()):
                person = person.model_copy(update={"email": None})

            # Normalise phone: keep only digits, +, -, parens, spaces
            if person.phone:
                cleaned_phone = re.sub(r"[^\d\s\+\-\(\)]", "", person.phone).strip()
                if len(cleaned_phone) < 7:
                    cleaned_phone = None  # type: ignore[assignment]
                person = person.model_copy(update={"phone": cleaned_phone})

            cleaned_people.append(person)

        return result.model_copy(update={"people": cleaned_people})
