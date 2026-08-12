"""Scheduler and scan orchestrator for Job Hunter."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import AppConfig
from src.database import Database
from src.filters import JobFilter
from src.models import Job, ScanStats
from src.scrapers.registry import get_scraper
from src.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

COMPANY_TIMEOUT_SECONDS = 120  # Max allowed time per company scraper call

def run_scan(config: AppConfig, db: Database, notifier: TelegramNotifier) -> ScanStats:
    stats = ScanStats()
    job_filter = JobFilter(config.filters)
    matching_jobs: list[Job] = []

    logger.info("=" * 60)
    logger.info("Starting scan at %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    logger.info("Companies to check: %d", len(config.companies))
    logger.info("=" * 60)

    for company_config in config.companies:
        company_name = company_config.name
        logger.info("Checking: %s (%s)", company_name, company_config.careers_url)

        try:
            ScraperClass = get_scraper(company_config.scraper)
            scraper = ScraperClass(config.scraping)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(scraper.fetch_jobs, company_config)
                jobs = future.result(timeout=COMPANY_TIMEOUT_SECONDS)

            if jobs is None:
                jobs = []

            if config.scraping.max_jobs_per_company > 0:
                jobs = jobs[: config.scraping.max_jobs_per_company]

            logger.info("  Found %d jobs at %s", len(jobs), company_name)
            stats.companies_checked += 1
            stats.jobs_found += len(jobs)

            for job in jobs:
                _process_job(
                    job=job,
                    db=db,
                    job_filter=job_filter,
                    config=config,
                    stats=stats,
                    matching_jobs=matching_jobs,
                )

        except FutureTimeoutError:
            stats.companies_failed += 1
            error_msg = f"{company_name}: TimeoutError: Exceeded maximum allowed time ({COMPANY_TIMEOUT_SECONDS}s)"
            stats.add_error(error_msg)
            logger.error("Error processing %s: timed out after %ds", company_name, COMPANY_TIMEOUT_SECONDS)

        except Exception as e:
            stats.companies_failed += 1
            error_msg = f"{company_name}: {type(e).__name__}: {e}"
            stats.add_error(error_msg)
            logger.error("Error processing %s: %s", company_name, e, exc_info=True)

        if config.scraping.delay_between_companies_seconds > 0:
            time.sleep(config.scraping.delay_between_companies_seconds)

    pending_rows = db.get_pending_notifications()
    for row in pending_rows:
        pending_job = Job(
            company=row["company"],
            external_id=row["external_id"],
            title=row["title"],
            location=row["location"],
            country=row["country"],
            url=row["url"],
            description="",
        )
        if job_filter.is_interesting(pending_job) and not any(
            j.external_id == pending_job.external_id and j.company == pending_job.company 
            for j in matching_jobs
        ):
            matching_jobs.append(pending_job)

    if matching_jobs:
        logger.info("Sending Telegram notifications for %d matching jobs...", len(matching_jobs))
        sent, failed = notifier.send_jobs(matching_jobs)
        stats.jobs_notified += sent

        for i, job in enumerate(matching_jobs):
            if i < sent:
                db.mark_notified(job)
            else:
                logger.warning(
                    "Job NOT marked as notified (Telegram failed): %s", job.short_repr()
                )
    else:
        logger.info("No new matching jobs found in this scan.")

    logger.info(stats.summary())

    return stats


def _process_job(
    job: Job,
    db: Database,
    job_filter: JobFilter,
    config: AppConfig,
    stats: ScanStats,
    matching_jobs: list[Job],
) -> None:
    is_new = db.is_new(job)

    if is_new:
        db.insert(job)
        stats.jobs_new += 1
        logger.debug("New job: %s", job.short_repr())

        if job_filter.is_interesting(job):
            stats.jobs_matching += 1
            matching_jobs.append(job)
            logger.info("  ✓ Matching: %s", job.short_repr())
        else:
            logger.debug("  ✗ Filtered out: %s", job.short_repr())
            # Mark filtered jobs as notified so they don't get retried by the notification system
            db.mark_notified(job)

    else:
        # Job already known — check for description changes
        stored_hash = db.get_description_hash(job)
        if stored_hash and stored_hash != job.description_hash and job.description:
            logger.info("Description changed for: %s", job.short_repr())
            db.update_description(job)

            if config.filters.notify_on_update and not db.is_notified(job):
                if job_filter.is_interesting(job):
                    matching_jobs.append(job)
                    logger.info("  ↺ Re-queued (updated): %s", job.short_repr())


class JobHunterScheduler:
    """Manages the APScheduler instance for periodic scanning."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: TelegramNotifier,
    ) -> None:
        self.config = config
        self.db = db
        self.notifier = notifier
        self.scheduler = BlockingScheduler()
        self._running = False
        self._running_scan = False

    def _scan_job(self) -> None:
        if self._running_scan:
            logger.warning("Scan already in progress, skipping this run.")
            return

        self._running_scan = True
        try:
            # Reload config to pick up any companies added via Telegram
            from src.config import load_config
            self.config = load_config()
            
            stats = run_scan(self.config, self.db, self.notifier)
        except Exception as e:
            logger.critical("Unhandled error in scan: %s", e, exc_info=True)
        finally:
            self._running_scan = False

    def start(self) -> None:
        self._running = True

        # Register signal handlers for graceful shutdown on POSIX systems
        if sys.platform != "win32":
            try:
                signal.signal(signal.SIGTERM, self._handle_shutdown)
                signal.signal(signal.SIGINT, self._handle_shutdown)
            except (ValueError, OSError):
                pass

        logger.info("Running initial scan...")
        self._scan_job()

        interval_hours = self.config.scan_interval_hours
        logger.info("Scheduling periodic scans every %d hour(s)", interval_hours)

        self.scheduler.add_job(
            self._scan_job,
            trigger=IntervalTrigger(hours=interval_hours),
            id="job_scan",
            name="Job Hunter Scan",
            max_instances=1,  # Prevent overlapping scans
            coalesce=True,    # Merge missed runs into one
        )

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")

    def _handle_shutdown(self, signum: int, frame) -> None:
        logger.info("Received signal %d — shutting down gracefully...", signum)
        self._running = False
        self.notifier.stop_polling()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        sys.exit(0)
