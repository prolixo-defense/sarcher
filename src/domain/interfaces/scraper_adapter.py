from abc import ABC, abstractmethod


class ScraperAdapter(ABC):
    """Placeholder interface for Phase 2 scraping implementations."""

    @abstractmethod
    def scrape(self, target_url: str, config: dict) -> dict:
        """Scrape the given URL and return raw extracted data."""
        ...
