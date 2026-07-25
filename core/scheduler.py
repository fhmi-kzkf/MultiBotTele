"""
Scheduler — APScheduler integration for organic conversation bursts.

Manages:
  - Periodic burst triggers with configurable intervals
  - Active hours enforcement
  - Hot-reload of scheduling parameters
  - Clean start/stop lifecycle
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config_manager import AppConfig, get_config
from core.jitter import calculate_burst_delay, is_within_active_hours

logger = logging.getLogger(__name__)

BURST_JOB_ID = "conversation_burst"


class BurstScheduler:
    """
    Manages periodic conversation bursts using APScheduler.

    The scheduler triggers at regular intervals (configurable via config.json)
    and calls the orchestrator's burst method. Each trigger checks:
      1. Kill switch status
      2. Active hours
      3. Burst delay range
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._burst_callback: Optional[Callable[[], Awaitable[None]]] = None
        self._is_running = False

    def set_burst_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        """
        Set the callback that fires on each burst trigger.
        Typically: orchestrator.run_scheduled_burst
        """
        self._burst_callback = callback

    async def start(self, config: Optional[AppConfig] = None) -> None:
        """Start the scheduler with burst jobs based on config."""
        if config is None:
            config = get_config()

        if not self._burst_callback:
            logger.error("No burst callback set — cannot start scheduler")
            return

        # Calculate initial interval from config
        burst_range = config.global_settings.burst_delay_minutes
        interval_minutes = (burst_range.min + burst_range.max) / 2.0

        # Add the burst job
        self._scheduler.add_job(
            self._execute_burst,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=BURST_JOB_ID,
            replace_existing=True,
            max_instances=1,
            name="Conversation Burst Trigger",
        )

        self._scheduler.start()
        self._is_running = True
        logger.info(
            f"Scheduler started — bursts every ~{interval_minutes:.0f} min "
            f"(range: {burst_range.min}-{burst_range.max} min)"
        )

    async def stop(self) -> None:
        """Stop the scheduler and remove all jobs."""
        if self._scheduler.running:
            self._scheduler.remove_all_jobs()
            self._scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("Scheduler stopped — all jobs cleared")

    async def reschedule(self, config: Optional[AppConfig] = None) -> None:
        """Hot-reload scheduler with new configuration parameters."""
        if config is None:
            config = get_config()

        burst_range = config.global_settings.burst_delay_minutes
        interval_minutes = (burst_range.min + burst_range.max) / 2.0

        try:
            if self._scheduler.running:
                self._scheduler.reschedule_job(
                    BURST_JOB_ID,
                    trigger=IntervalTrigger(minutes=interval_minutes),
                )
                logger.info(
                    f"Scheduler rescheduled — bursts every ~{interval_minutes:.0f} min"
                )
            else:
                await self.start(config)
        except Exception as e:
            logger.error(f"Error rescheduling: {e}")
            # Restart from scratch
            await self.stop()
            await self.start(config)

    async def _execute_burst(self) -> None:
        """
        Internal burst execution wrapper.
        Checks conditions before firing the callback.
        """
        try:
            config = get_config()

            # Check kill switch
            if config.global_settings.kill_switch:
                logger.debug("Kill switch active — skipping scheduled burst")
                return

            # Check active hours
            if not is_within_active_hours(config):
                logger.debug("Outside active hours — skipping scheduled burst")
                return

            # Calculate dynamic delay for next execution (jitter)
            # This makes burst timing less predictable
            next_delay = calculate_burst_delay(config)
            logger.info(
                f"Executing scheduled burst — next in ~{next_delay / 60:.0f} min"
            )

            # Fire the burst callback
            if self._burst_callback:
                await self._burst_callback()

        except Exception as e:
            logger.error(f"Error executing burst: {e}", exc_info=True)

    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._is_running and self._scheduler.running

    def get_status(self) -> dict:
        """Get scheduler status for the dashboard."""
        jobs = []
        if self._scheduler.running:
            for job in self._scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })

        return {
            "is_running": self._is_running,
            "scheduler_running": self._scheduler.running,
            "jobs": jobs,
        }
