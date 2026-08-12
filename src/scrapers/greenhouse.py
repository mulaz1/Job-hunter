"""
Greenhouse ATS scraper for Job Hunter.

Uses the public Greenhouse Job Board API (no authentication required):
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

Documentation: https://developers.greenhouse.io/job-board.html

The `company_id` field in companies.yml must match the Greenhouse board token
(e.g., for https://boards.greenhouse.io/acme the token is "acme").
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
REQUEST_TIMEOUT = 30


def _parse_greenhouse_job(raw: dict[str, Any], company: CompanyConfig) -> Job:
    """
    Parse a single job from the Greenhouse API response.

    Args:
        raw:     Raw job dict from the Greenhouse API.
        company: Company configuration for metadata.

    Returns:
        A populated Job object.
    """
    job_id = str(raw.get("id", ""))
    title = raw.get("title", "Unknown Position")
    url = raw.get("absolute_url", "")
    location_data = raw.get("location", {})
    location = location_data.get("name", "") if isinstance(location_data, dict) else ""

    # Description is HTML — strip tags for plain text
    description_html = raw.get("content", "") or ""
    description = _strip_html(description_html)

    # Parse published date
    published_at = None
    updated_at_str = raw.get("updated_at") or raw.get("published_at")
    if updated_at_str:
        try:
            published_at = datetime.fromisoformat(
                updated_at_str.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (ValueError, AttributeError):
            pass

    # Use Greenhouse job ID as external_id; fall back to URL-based ID
    external_id = job_id if job_id else make_external_id(company.name, url)

    return Job(
        company=company.name,
        external_id=external_id,
        title=title,
        location=location,
        country=company.country,
        url=url,
        description=description,
        published_at=published_at,
    )


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", " ", html).strip()


class GreenhouseScraper(BaseScraper):
    """
    Scraper for companies using the Greenhouse ATS.

    Fetches all jobs via the public JSON API endpoint.
    No authentication required.

    Required config in companies.yml:
        scraper: greenhouse
        company_id: <board_token>  # e.g., "acme" for boards.greenhouse.io/acme
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all jobs from the Greenhouse API for this company.

        Args:
            company: Company configuration. Must have `company_id` set.

        Returns:
            List of Job objects.
        """
        if not company.company_id:
            logger.error(
                "GreenhouseScraper: company_id not set for %s. "
                "Please add company_id to companies.yml.",
                company.name,
            )
            return []

        url = f"{GREENHOUSE_API_BASE}/{company.company_id}/jobs?content=true"
        logger.debug("GreenhouseScraper: fetching %s", url)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.get(
                    url,
                    headers={"Accept": "application/json"},
                    follow_redirects=True,
                )

            if response.status_code == 404:
                logger.error(
                    "GreenhouseScraper: board token '%s' not found for %s. "
                    "Check the company_id in companies.yml.",
                    company.company_id,
                    company.name,
                )
                return []

            response.raise_for_status()
            data = response.json()

        except httpx.TimeoutException:
            logger.error(
                "GreenhouseScraper: request timed out for %s", company.name
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "GreenhouseScraper: HTTP %d for %s: %s",
                e.response.status_code,
                company.name,
                str(e)[:200],
            )
            return []
        except Exception as e:
            logger.error("GreenhouseScraper: error for %s: %s", company.name, e)
            return []

        raw_jobs = data.get("jobs", [])
        if not raw_jobs:
            logger.info("GreenhouseScraper: no jobs found for %s", company.name)
            return []

        jobs = []
        for raw in raw_jobs:
            try:
                job = _parse_greenhouse_job(raw, company)
                jobs.append(job)
            except Exception as e:
                logger.warning(
                    "GreenhouseScraper: error parsing job for %s: %s", company.name, e
                )
                continue

        logger.debug("GreenhouseScraper: parsed %d jobs for %s", len(jobs), company.name)
        return jobs
