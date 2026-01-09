"""Scheduler for periodic tasks like digest generation.

Uses APScheduler for cron-style scheduling of summaries and cleanup.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class DigestScheduler:
    """Manages scheduled tasks for the notification service.
    
    Handles:
    - Periodic digest generation (hourly, daily, custom times)
    - Cleanup of old notifications
    - Statistics collection
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._callbacks: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}
    
    def register_callback(
        self, 
        name: str, 
        callback: Callable[..., Coroutine[Any, Any, Any]]
    ) -> None:
        """Register a callback for scheduled tasks.
        
        Args:
            name: Callback identifier (e.g., "generate_digest", "cleanup")
            callback: Async function to call
        """
        self._callbacks[name] = callback
    
    def add_digest_job(
        self,
        job_id: str,
        hour: int,
        minute: int = 0,
        digest_type: str = "scheduled",
    ) -> None:
        """Add a scheduled digest at a specific time.
        
        Args:
            job_id: Unique identifier for this job
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            digest_type: Type label for the digest
        """
        trigger = CronTrigger(hour=hour, minute=minute)
        
        async def run_digest():
            callback = self._callbacks.get("generate_digest")
            if callback:
                logger.info(f"Running scheduled digest: {job_id} ({digest_type})")
                await callback(digest_type=digest_type, job_id=job_id)
        
        self.scheduler.add_job(
            run_digest,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
        )
        logger.info(f"Scheduled digest '{job_id}' at {hour:02d}:{minute:02d}")
    
    def add_hourly_digest(self) -> None:
        """Add hourly digest job (runs at the top of each hour)."""
        trigger = CronTrigger(minute=0)  # Every hour at :00
        
        async def run_hourly():
            callback = self._callbacks.get("generate_digest")
            if callback:
                hour = datetime.now().hour
                logger.info(f"Running hourly digest ({hour:02d}:00)")
                await callback(digest_type="hourly", job_id=f"hourly-{hour:02d}")
        
        self.scheduler.add_job(
            run_hourly,
            trigger=trigger,
            id="hourly-digest",
            replace_existing=True,
        )
        logger.info("Scheduled hourly digest")
    
    def add_cleanup_job(self, days_to_keep: int = 7) -> None:
        """Add daily cleanup job to remove old notifications.
        
        Args:
            days_to_keep: Number of days of history to retain
        """
        # Run cleanup at 3 AM
        trigger = CronTrigger(hour=3, minute=0)
        
        async def run_cleanup():
            callback = self._callbacks.get("cleanup")
            if callback:
                logger.info(f"Running cleanup (keeping {days_to_keep} days)")
                await callback(days_to_keep=days_to_keep)
        
        self.scheduler.add_job(
            run_cleanup,
            trigger=trigger,
            id="daily-cleanup",
            replace_existing=True,
        )
        logger.info(f"Scheduled daily cleanup at 03:00 (keeping {days_to_keep} days)")
    
    def setup_from_config(self, config: dict[str, Any]) -> None:
        """Configure scheduler from policy config.
        
        Expected config format:
        {
            "digest_schedule": [
                {"time": "09:00", "type": "morning"},
                {"time": "17:00", "type": "eod"},
            ],
            "hourly_digest": true,
            "cleanup_days": 7,
        }
        """
        # Add digest jobs from schedule
        digest_schedule = config.get("digest_schedule", [])
        for i, entry in enumerate(digest_schedule):
            time_str = entry.get("time", "")
            digest_type = entry.get("type", "scheduled")
            
            try:
                parts = time_str.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                
                self.add_digest_job(
                    job_id=f"digest-{i}-{time_str}",
                    hour=hour,
                    minute=minute,
                    digest_type=digest_type,
                )
            except (ValueError, IndexError) as e:
                logger.warning(f"Invalid digest time '{time_str}': {e}")
        
        # Add hourly digest if enabled
        if config.get("hourly_digest", False):
            self.add_hourly_digest()
        
        # Add cleanup job
        cleanup_days = config.get("cleanup_days", 7)
        self.add_cleanup_job(days_to_keep=cleanup_days)
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")
    
    def get_jobs(self) -> list[dict[str, Any]]:
        """Get list of scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "next_run": next_run.isoformat() if next_run else None,
            })
        return jobs
