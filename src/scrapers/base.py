"""Base scraper class for Job Hunter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    def __init__(self, scraping_config: ScrapingConfig) -> None:
        self.scraping_config = scraping_config

    @abstractmethod
    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """Fetch all available job postings for a company."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__
