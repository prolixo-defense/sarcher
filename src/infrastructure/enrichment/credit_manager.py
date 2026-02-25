"""
API credit budget tracker.

Persists credit usage in the credit_usage DB table and enforces
per-provider monthly budgets so we never exceed free-tier limits.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Map provider names to their budget setting field
_BUDGET_FIELDS: dict[str, str] = {
    "apollo": "apollo_monthly_budget",
    "hunter": "hunter_monthly_budget",
}


class CreditManager:
    """
    Tracks API credit usage per provider per month.

    Budget limits are read from settings and compared against the
    DB-persisted spend records (credit_usage table).

    All public methods are declared async for interface consistency with
    the async enrichment pipeline, but internally execute synchronous
    SQLAlchemy queries (fast for SQLite and lightweight RDBs).
    """

    def __init__(self, db_session, settings=None):
        self._session = db_session
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()
        self._settings = settings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_month(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def _get_budget(self, provider: str) -> int:
        field = _BUDGET_FIELDS.get(provider)
        if field:
            return int(getattr(self._settings, field, 0))
        return 0

    def _get_used(self, provider: str, month: str) -> int:
        from sqlalchemy import func
        from src.infrastructure.database.models import CreditUsageModel

        total = (
            self._session.query(func.sum(CreditUsageModel.credits_used))
            .filter(
                CreditUsageModel.provider == provider,
                CreditUsageModel.month == month,
            )
            .scalar()
        )
        return total or 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def can_spend(self, provider: str, credits: int = 1) -> bool:
        """Return True if the monthly budget has room for *credits* more."""
        budget = self._get_budget(provider)
        if budget <= 0:
            return False
        month = self._current_month()
        used = self._get_used(provider, month)
        return (used + credits) <= budget

    async def record_spend(
        self,
        provider: str,
        credits: int,
        lead_id: str,
        endpoint: str = "",
    ) -> None:
        """Persist a credit spend record (caller must commit the session)."""
        from src.infrastructure.database.models import CreditUsageModel

        record = CreditUsageModel(
            id=str(uuid.uuid4()),
            provider=provider,
            credits_used=credits,
            lead_id=lead_id,
            endpoint=endpoint,
            month=self._current_month(),
        )
        self._session.add(record)
        self._session.flush()
        logger.debug(
            "Credit recorded: provider=%s credits=%d lead=%s",
            provider,
            credits,
            lead_id,
        )

    async def get_usage_summary(self) -> dict:
        """Return usage stats per provider for the current month."""
        month = self._current_month()
        summary: dict = {}
        for provider in ["apollo", "hunter"]:
            used = self._get_used(provider, month)
            budget = self._get_budget(provider)
            summary[provider] = {
                "used": used,
                "budget": budget,
                "remaining": max(0, budget - used),
                "month": month,
            }
        return summary
