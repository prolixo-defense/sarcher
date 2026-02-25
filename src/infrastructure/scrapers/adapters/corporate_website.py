"""
Corporate website scraping adapter.

Discovers and scrapes team/leadership/contact pages on company websites
to extract names, titles, emails, phone numbers, and LinkedIn URLs.
Uses the fast HttpScraper path since most corporate sites are server-rendered.
"""
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from src.infrastructure.fingerprint.tls_manager import TLSManager
from src.infrastructure.proxy.proxy_manager import ProxyManager
from src.infrastructure.scrapers.http_scraper import HttpScraper

logger = logging.getLogger(__name__)

# URL path suffixes to probe for team/contact information
TEAM_PAGE_PATTERNS = [
    "/team", "/our-team", "/leadership", "/management",
    "/people", "/staff", "/about", "/about-us",
    "/who-we-are", "/company", "/contact", "/contact-us",
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"
)
_LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+"
)


class CorporateWebsiteAdapter:
    """
    Scrapes corporate websites for team and contact information.

    Strategy:
    1. Probe common team/contact page paths under the company domain.
    2. Parse each found page with BeautifulSoup.
    3. Extract person cards (name + title), email addresses (mailto: / text
       regex), phone numbers, and LinkedIn profile links.
    4. Return a list of raw lead dicts ready for LeadCreateDTO.
    """

    def __init__(
        self,
        tls_manager: Optional[TLSManager] = None,
        proxy_manager: Optional[ProxyManager] = None,
        scraper: Optional[HttpScraper] = None,
        extraction_engine=None,  # Optional[ExtractionEngine] for Phase 3 LLM extraction
    ):
        self._scraper = scraper or HttpScraper(
            tls_manager=tls_manager or TLSManager(),
            proxy_manager=proxy_manager,
        )
        self._extraction_engine = extraction_engine

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_scheme(domain: str) -> str:
        if not domain.startswith(("http://", "https://")):
            return f"https://{domain}"
        return domain

    @staticmethod
    def _extract_emails(html: str) -> list[str]:
        return list(dict.fromkeys(_EMAIL_RE.findall(html)))

    @staticmethod
    def _extract_phones(html: str) -> list[str]:
        return list(dict.fromkeys(_PHONE_RE.findall(html)))

    @staticmethod
    def _extract_linkedin_urls(html: str) -> list[str]:
        return list(dict.fromkeys(_LINKEDIN_RE.findall(html)))

    @staticmethod
    def _parse_team_members(html: str) -> list[dict]:
        """
        Extract name/title pairs from a team page.

        Tries two strategies:
        1. Find common CSS-class-named team-card containers and look for a
           heading (name) followed by a paragraph/span (title).
        2. Fall through to raw email extraction when no cards are found.
        """
        results: list[dict] = []
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # Strategy 1: look for card-like containers with team-related classes.
            # Use substring matching so "team-member", "team_person", etc. are caught.
            CARD_KEYWORDS = ("team", "person", "member", "staff", "leadership", "card", "bio")
            containers = soup.find_all(
                lambda tag: tag.name in ("article", "div", "li", "section")
                and any(
                    kw in " ".join(tag.get("class", [])).lower()
                    for kw in CARD_KEYWORDS
                ),
                limit=100,
            )

            for container in containers:
                name: Optional[str] = None
                title: Optional[str] = None
                email: Optional[str] = None
                linkedin: Optional[str] = None

                # Name: first short heading that looks like a person name
                for h_tag in container.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
                    text = h_tag.get_text(strip=True)
                    words = text.split()
                    if 2 <= len(words) <= 5 and all(
                        c.isalpha() or c in " '-." for c in text
                    ):
                        name = text
                        break

                # Title: first short paragraph or span after the name heading
                if name:
                    for p_tag in container.find_all(["p", "span", "small", "em", "div"]):
                        text = p_tag.get_text(strip=True)
                        if text and 1 <= len(text.split()) <= 10 and len(text) < 80:
                            title = text
                            break

                # Email: mailto link inside the card
                mail_link = container.find("a", href=_EMAIL_RE)
                if mail_link:
                    match = _EMAIL_RE.search(mail_link["href"])
                    if match:
                        email = match.group()

                # LinkedIn: anchor link
                li_link = container.find(
                    "a", href=lambda h: h and "linkedin.com/in/" in h
                )
                if li_link:
                    linkedin = li_link["href"]

                if name:
                    parts = name.split(None, 1)
                    results.append({
                        "first_name": parts[0],
                        "last_name": parts[1] if len(parts) > 1 else "",
                        "job_title": title,
                        "email": email,
                        "linkedin_url": linkedin,
                    })

        except Exception as exc:
            logger.error("BeautifulSoup parse error: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def scrape(self, domain: str) -> list[dict]:
        """
        Scrape *domain* for team/contact information.

        Returns a list of raw lead dicts with keys compatible with LeadCreateDTO.
        """
        base_url = self._add_scheme(domain)
        domain_host = urlparse(base_url).netloc
        all_results: list[dict] = []
        visited: set[str] = set()

        for path in TEAM_PAGE_PATTERNS:
            url = urljoin(base_url, path)
            if url in visited:
                continue
            visited.add(url)

            logger.info("Probing team page: %s", url)
            response = await self._scraper.fetch_with_retry(url)
            if not response.is_success():
                logger.debug("No useful response from %s (status=%d)", url, response.status_code)
                continue

            # Phase 3: use LLM extraction when engine is injected
            if self._extraction_engine is not None:
                try:
                    extracted = await self._extraction_engine.extract(url, response.html)
                    members = []
                    for person in extracted.people:
                        first = person.first_name or ""
                        last = person.last_name or ""
                        if not first and person.full_name:
                            parts = person.full_name.strip().split(None, 1)
                            first = parts[0]
                            last = parts[1] if len(parts) > 1 else ""
                        if first or last or person.email:
                            members.append({
                                "first_name": first,
                                "last_name": last,
                                "job_title": person.job_title,
                                "email": person.email,
                                "linkedin_url": person.linkedin_url,
                            })
                except Exception as exc:
                    logger.error("LLM extraction failed, using BS4 fallback: %s", exc)
                    members = self._parse_team_members(response.html)
            else:
                members = self._parse_team_members(response.html)

            # If no structured cards found, fall back to raw email/phone extraction
            if not members:
                emails = self._extract_emails(response.html)
                phones = self._extract_phones(response.html)
                for i, email in enumerate(emails[:20]):
                    members.append({
                        "first_name": "",
                        "last_name": "",
                        "email": email,
                        "phone": phones[i] if i < len(phones) else None,
                    })

            if members:
                logger.info("Found %d contacts at %s", len(members), url)
                # Enrich each result with shared metadata
                phones_page = self._extract_phones(response.html)
                linkedin_urls = self._extract_linkedin_urls(response.html)

                for idx, m in enumerate(members):
                    m.setdefault("company_domain", domain_host)
                    m.setdefault("source", "website")
                    m.setdefault("confidence_score", 0.7)
                    if not m.get("phone") and idx == 0 and phones_page:
                        m["phone"] = phones_page[0]
                    if not m.get("linkedin_url") and idx < len(linkedin_urls):
                        m["linkedin_url"] = linkedin_urls[idx]

                all_results.extend(members)

            # Stop early once we have enough contacts
            if len(all_results) >= 30:
                break

        logger.info("Total contacts for %s: %d", domain, len(all_results))
        return all_results
