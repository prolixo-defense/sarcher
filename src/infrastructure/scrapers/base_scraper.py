from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# Keywords that indicate a soft-block or CAPTCHA page
BLOCK_KEYWORDS = [
    "captcha",
    "recaptcha",
    "verify you are human",
    "access denied",
    "cloudflare",
    "please enable javascript",
    "bot detection",
    "rate limit exceeded",
    "too many requests",
    "temporarily blocked",
    "unusual traffic",
    "automated queries",
    "are you a robot",
    "ddos-guard",
]


@dataclass
class ScrapedResponse:
    """Result of a single scrape attempt."""

    url: str
    status_code: int
    html: str
    headers: dict = field(default_factory=dict)
    response_time: float = 0.0
    was_blocked: bool = False
    error: Optional[str] = None

    def is_success(self) -> bool:
        """True if the request succeeded without a block."""
        return self.status_code in (200, 201, 202, 203) and not self.was_blocked and not self.error


class BaseScraper(ABC):
    """Abstract base for all scrapers. Provides shared block-detection logic."""

    @staticmethod
    def detect_block(status_code: int, html: str, headers: dict) -> bool:
        """
        Detect soft-blocks: CAPTCHA pages, rate-limit messages, Cloudflare challenges.
        Also catches hard 403/429/503 responses.
        """
        if status_code in (403, 429, 503):
            return True
        html_lower = html.lower()
        return any(kw in html_lower for kw in BLOCK_KEYWORDS)

    @abstractmethod
    async def fetch(self, url: str, **kwargs) -> ScrapedResponse:
        """Fetch a URL and return a ScrapedResponse."""
        ...

    @abstractmethod
    async def fetch_with_retry(self, url: str, max_retries: int = 3) -> ScrapedResponse:
        """Fetch with retry logic — implementations switch profiles on block."""
        ...
