"""Configuration loader for Job Hunter."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from src.models import CompanyConfig

logger = logging.getLogger(__name__)


@dataclass
class ScrapingConfig:
    """Rate limiting and scraping behaviour."""

    delay_between_companies_seconds: float = 3.0
    page_timeout_seconds: int = 60
    max_jobs_per_company: int = 200


@dataclass
class TelegramConfig:
    """Telegram Bot settings."""

    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    max_jobs_per_message: int = 10

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class FiltersConfig:
    """Keyword and geographic filter settings."""

    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    allowed_countries: list[str] = field(default_factory=list)
    notify_on_update: bool = False


@dataclass
class AppConfig:
    """Top-level application configuration."""

    companies: list[CompanyConfig]
    filters: FiltersConfig
    telegram: TelegramConfig
    scraping: ScrapingConfig
    db_path: str
    scan_interval_hours: int
    log_level: str


def _load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.debug("Loaded YAML config from %s", path)
        return data
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        return {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML config %s: %s", path, e)
        return {}


def _parse_companies(data: dict) -> list[CompanyConfig]:
    companies = []
    for entry in data.get("companies", []):
        try:
            company = CompanyConfig(
                name=entry["name"],
                country=entry.get("country", ""),
                careers_url=entry["careers_url"],
                scraper=entry.get("scraper", "generic"),
                company_id=entry.get("company_id"),
                workday_tenant=entry.get("workday_tenant"),
                workday_instance=entry.get("workday_instance"),
                eightfold_domain=entry.get("eightfold_domain"),
            )
            companies.append(company)
        except (KeyError, TypeError) as e:
            logger.warning("Skipping malformed company entry: %s — %s", entry, e)
    return companies


def _parse_filters(data: dict) -> FiltersConfig:
    return FiltersConfig(
        include_keywords=[kw.lower() for kw in data.get("include_keywords", [])],
        exclude_keywords=[kw.lower() for kw in data.get("exclude_keywords", [])],
        allowed_countries=[c.lower() for c in data.get("allowed_countries", [])],
        notify_on_update=data.get("notify_on_update", False),
    )


def _parse_scraping(data: dict) -> ScrapingConfig:
    scraping_data = data.get("scraping", {})
    return ScrapingConfig(
        delay_between_companies_seconds=float(
            scraping_data.get("delay_between_companies_seconds", 3.0)
        ),
        page_timeout_seconds=int(scraping_data.get("page_timeout_seconds", 60)),
        max_jobs_per_company=int(scraping_data.get("max_jobs_per_company", 200)),
    )


def _parse_telegram_from_yaml(data: dict) -> dict:
    telegram_data = data.get("telegram", {})
    return {"max_jobs_per_message": int(telegram_data.get("max_jobs_per_message", 10))}


def load_config() -> AppConfig:
    """Load the full application configuration."""
    load_dotenv()

    companies_path = os.getenv("COMPANIES_CONFIG", "/app/config/companies.yml")
    filters_path = os.getenv("FILTERS_CONFIG", "/app/config/filters.yml")
    db_path = os.getenv("DB_PATH", "/app/data/jobs.db")
    if db_path.startswith("/app/") and not Path("/app").exists():
        local_db_path = Path("data/jobs.db")
        local_db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path = str(local_db_path.resolve())

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    scan_interval_hours = int(os.getenv("SCAN_INTERVAL_HOURS", "6"))

    if not Path(companies_path).exists():
        local_path = Path("config/companies.yml")
        example_path = Path("config/companies.example.yml")
        if local_path.exists():
            companies_path = str(local_path)
            logger.debug("Using local companies config: %s", companies_path)
        elif example_path.exists():
            companies_path = str(example_path)
            logger.info("Using example companies config fallback: %s", companies_path)

    if not Path(filters_path).exists():
        local_path = Path("config/filters.yml")
        example_path = Path("config/filters.example.yml")
        if local_path.exists():
            filters_path = str(local_path)
            logger.debug("Using local filters config: %s", filters_path)
        elif example_path.exists():
            filters_path = str(example_path)
            logger.info("Using example filters config fallback: %s", filters_path)


    companies_data = _load_yaml(companies_path)
    filters_data = _load_yaml(filters_path)

    companies = _parse_companies(companies_data)
    filters = _parse_filters(filters_data)
    scraping = _parse_scraping(filters_data)
    telegram_yaml = _parse_telegram_from_yaml(filters_data)

    telegram = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        max_jobs_per_message=telegram_yaml["max_jobs_per_message"],
    )

    if not companies:
        logger.warning("No companies configured! Check %s", companies_path)

    if not filters.include_keywords:
        logger.warning("No include_keywords configured! All jobs will be filtered out.")

    logger.info(
        "Config loaded: %d companies, %d include keywords, %d exclude keywords",
        len(companies),
        len(filters.include_keywords),
        len(filters.exclude_keywords),
    )

    return AppConfig(
        companies=companies,
        filters=filters,
        telegram=telegram,
        scraping=scraping,
        db_path=db_path,
        scan_interval_hours=scan_interval_hours,
        log_level=log_level,
    )
