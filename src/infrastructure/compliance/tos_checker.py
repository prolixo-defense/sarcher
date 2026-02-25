"""
Basic Terms of Service awareness checker.

This is a lightweight, awareness-only tool — not legal advice.
Checks for common ToS language that may restrict automated access.
"""
import logging

logger = logging.getLogger(__name__)


class ToSChecker:
    """Basic ToS awareness checker (educational — not legal advice)."""

    # Keywords that suggest ToS restrictions on automated access
    RESTRICTIVE_PATTERNS = [
        "no scraping",
        "no crawling",
        "no automated",
        "no robots",
        "prohibit automated",
        "automated access is prohibited",
        "scraping is prohibited",
        "no spider",
    ]

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings

    async def check(self, url: str) -> dict:
        """
        Fetch the ToS/legal page for a domain and check for restrictive language.

        Returns {allowed: bool, notes: list[str], url_checked: str}.
        NOTE: Returns allowed=True by default — this is advisory only.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        tos_candidates = [
            f"{domain}/terms",
            f"{domain}/terms-of-service",
            f"{domain}/legal",
            f"{domain}/tos",
        ]

        notes = []
        checked_url = None

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                for tos_url in tos_candidates:
                    try:
                        resp = await client.get(tos_url)
                        if resp.status_code == 200:
                            checked_url = tos_url
                            text_lower = resp.text.lower()
                            for pattern in self.RESTRICTIVE_PATTERNS:
                                if pattern in text_lower:
                                    notes.append(f"ToS may restrict automated access: '{pattern}'")
                            break
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("[ToSChecker] Could not check ToS for %s: %s", url, exc)

        return {
            "allowed": True,  # Advisory only — caller makes the final decision
            "notes": notes,
            "url_checked": checked_url,
            "has_restrictions": len(notes) > 0,
        }
