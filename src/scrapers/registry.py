"""Scraper registry for Job Hunter."""

from __future__ import annotations

import logging
from typing import Type

from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

def _get_scrapers() -> dict[str, Type[BaseScraper]]:
    """Build and return the scraper registry."""
    from src.scrapers.generic import GenericScraper
    from src.scrapers.greenhouse import GreenhouseScraper
    from src.scrapers.lever import LeverScraper
    from src.scrapers.workday import WorkdayScraper
    from src.scrapers.smartrecruiters import SmartRecruitersScraper
    from src.scrapers.eightfold import EightfoldScraper
    from src.scrapers.workable import WorkableScraper
    from src.scrapers.phenom import PhenomScraper
    from src.scrapers.sitemap import SitemapScraper

    return {
        "generic": GenericScraper,
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
        "workday": WorkdayScraper,
        "smartrecruiters": SmartRecruitersScraper,
        "eightfold": EightfoldScraper,
        "workable": WorkableScraper,
        "phenom": PhenomScraper,
        "sitemap": SitemapScraper,
    }


def get_scraper(scraper_type: str) -> Type[BaseScraper]:
    scrapers = _get_scrapers()
    scraper_class = scrapers.get(scraper_type.lower().strip())

    if scraper_class is None:
        available = ", ".join(sorted(scrapers.keys()))
        raise ValueError(
            f"Unknown scraper type: '{scraper_type}'. "
            f"Available scrapers: {available}"
        )

    return scraper_class


def list_scrapers() -> list[str]:
    return sorted(_get_scrapers().keys())
