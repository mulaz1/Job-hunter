"""Job Hunter — Main entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str) -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Job Hunter starting up")
    logger.info("=" * 60)

    try:
        from src.config import load_config
        config = load_config()
    except Exception as e:
        logging.critical("Failed to load configuration: %s", e, exc_info=True)
        sys.exit(1)

    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    logger.info("Log level    : %s", config.log_level)
    logger.info("Scan interval: every %d hour(s)", config.scan_interval_hours)
    logger.info("Database     : %s", config.db_path)
    logger.info("Companies    : %d configured", len(config.companies))

    try:
        from src.database import Database
        db = Database(config.db_path)
        logger.info("Database initialized at %s", config.db_path)
    except Exception as e:
        logger.critical("Failed to initialize database: %s", e, exc_info=True)
        sys.exit(1)

    from src.telegram import TelegramNotifier
    notifier = TelegramNotifier(config.telegram)

    if config.telegram.is_configured:
        logger.info("Telegram: configured")
        notifier.test_connection()
        notifier.send_startup_message()
        notifier.start_polling()
    else:
        logger.warning(
            "Telegram: NOT configured — notifications will be skipped. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable."
        )

    try:
        stats = db.get_stats()
        logger.info(
            "Database stats: %d total jobs, %d notified, %d companies tracked",
            stats["total_jobs"],
            stats["notified_jobs"],
            stats["companies"],
        )
    except Exception as e:
        logger.warning("Could not read database stats: %s", e)

    from src.scheduler import JobHunterScheduler
    scheduler = JobHunterScheduler(config=config, db=db, notifier=notifier)

    logger.info("Starting scheduler...")
    scheduler.start()


if __name__ == "__main__":
    main()
