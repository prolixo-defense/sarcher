"""
APScheduler-based workflow scheduler.

Scheduled jobs:
- process_campaigns: Every 30 min during business hours
- cleanup_expired: Daily at 3 AM
- credit_usage_report: Daily at 9 AM
"""
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class WorkflowScheduler:
    """
    Schedules and runs automated workflows via APScheduler.
    Uses a SQLite job store for persistence across restarts.
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        self._scheduler = None
        self._started = False

    def _get_scheduler(self):
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

                jobstores = {
                    "default": SQLAlchemyJobStore(
                        url="sqlite:///./data/scheduler.db"
                    )
                }
                self._scheduler = AsyncIOScheduler(
                    jobstores=jobstores,
                    timezone=getattr(self._settings, "timezone", "America/New_York"),
                )
            except Exception as exc:
                logger.warning("[Scheduler] SQLAlchemy job store unavailable (%s), using memory", exc)
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                self._scheduler = AsyncIOScheduler(
                    timezone=getattr(self._settings, "timezone", "America/New_York"),
                )
        return self._scheduler

    def start(self) -> None:
        """Start the scheduler."""
        scheduler = self._get_scheduler()
        if not self._started:
            scheduler.start()
            self._started = True
            logger.info("[Scheduler] Started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("[Scheduler] Stopped")

    def add_job(self, func: Callable, trigger: str, job_id: str | None = None, **kwargs) -> str:
        """
        Add a job to the scheduler.

        Args:
            func: The callable to run
            trigger: 'interval', 'cron', or 'date'
            job_id: Optional stable ID (prevents duplicate jobs)
            **kwargs: Trigger-specific arguments (e.g. minutes=30, hour=9)

        Returns job ID.
        """
        scheduler = self._get_scheduler()
        if job_id:
            # Replace existing job with same ID
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
        job = scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
        logger.info("[Scheduler] Added job '%s' (%s)", job.id, trigger)
        return job.id

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self._get_scheduler().remove_job(job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict]:
        """Return all scheduled jobs."""
        try:
            scheduler = self._get_scheduler()
            return [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "trigger": str(job.trigger),
                }
                for job in scheduler.get_jobs()
            ]
        except Exception as exc:
            logger.warning("[Scheduler] list_jobs failed: %s", exc)
            return []

    def register_default_jobs(self) -> None:
        """Register the standard workflow jobs."""
        from src.infrastructure.orchestration.workflows import (
            run_campaign_processing,
            run_cleanup_expired,
            run_credit_report,
        )

        bh_start = getattr(self._settings, "business_hours_start", 9)
        bh_end = getattr(self._settings, "business_hours_end", 18)
        tz = getattr(self._settings, "timezone", "America/New_York")

        # Process campaigns every 30 minutes during business hours (Mon-Fri)
        self.add_job(
            run_campaign_processing,
            "cron",
            job_id="process_campaigns",
            minute="*/30",
            hour=f"{bh_start}-{bh_end - 1}",
            day_of_week="mon-fri",
            timezone=tz,
        )

        # Cleanup expired leads daily at 3 AM
        self.add_job(
            run_cleanup_expired,
            "cron",
            job_id="cleanup_expired",
            hour=3,
            minute=0,
        )

        # Credit usage report daily at 9 AM
        self.add_job(
            run_credit_report,
            "cron",
            job_id="credit_usage_report",
            hour=bh_start,
            minute=0,
        )

        logger.info("[Scheduler] Default jobs registered")
