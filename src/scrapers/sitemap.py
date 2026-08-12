"""
Sitemap XML scraper for Job Hunter.

Used for companies whose HTML career pages are protected by WAF / Cloudflare bot management,
but whose XML sitemap (e.g. https://www.melexis.com/sitemap.xml) is publicly accessible via standard HTTP requests.

Extracts job URLs matching job-like URL patterns from <loc> elements.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

JOB_URL_REGEX = re.compile(
    r"/(?:careers|jobs|vacancies|job)/(?:\w+/)?(\d+)/?([a-z0-9-]+)?",
    re.IGNORECASE,
)


def _slug_to_title(slug: str) -> str:
    """Convert a URL slug like 'embedded-software-engineer' to 'Embedded Software Engineer'."""
    if not slug:
        return "Unknown Position"
    words = slug.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words)


class SitemapScraper(BaseScraper):
    """
    Scraper that parses an XML sitemap to extract job postings.
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all job URLs from the sitemap.xml endpoint for this company.

        Args:
            company: Company configuration. `careers_url` must point to sitemap.xml.

        Returns:
            List of Job objects.
        """
        sitemap_url = company.careers_url
        logger.debug("SitemapScraper: fetching %s for %s", sitemap_url, company.name)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/xml, text/xml, */*",
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.get(sitemap_url, headers=headers, follow_redirects=True)
                if response.status_code != 200:
                    logger.error(
                        "SitemapScraper: HTTP %d from %s",
                        response.status_code,
                        sitemap_url,
                    )
                    return []
                xml_content = response.text
        except Exception as e:
            logger.error("SitemapScraper: request error for %s: %s", company.name, e)
            return []

        soup = BeautifulSoup(xml_content, "xml")
        loc_tags = soup.find_all("loc")

        seen_urls: set[str] = set()
        jobs: list[Job] = []

        for loc in loc_tags:
            raw_url = loc.text.strip()
            if not raw_url:
                continue

            match = JOB_URL_REGEX.search(raw_url)
            if not match:
                continue

            # Convert non-English locale paths to canonical /en/ path if present
            canonical_url = re.sub(
                r"melexis\.com/[a-z]{2}/careers/", "melexis.com/en/careers/", raw_url
            )

            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)

            job_id, slug = match.group(1), match.group(2) or ""
            title = _slug_to_title(slug) if slug else "Unknown Position"
            external_id = job_id if job_id else make_external_id(company.name, canonical_url)

            job = Job(
                company=company.name,
                external_id=external_id,
                title=title,
                location="",
                country=company.country,
                url=canonical_url,
                description="",
            )
            jobs.append(job)

        logger.debug(
            "SitemapScraper: extracted %d jobs for %s", len(jobs), company.name
        )
        return jobs
