"""
Phenom / Jibe ATS scraper for Job Hunter.

Phenom People (and Jibe) powers career sites such as Schneider Electric (careers.se.com).
It exposes a public JSON API endpoint at:

  GET {base_url}/api/jobs?limit={limit}&offset={offset}

The API returns a JSON payload containing:
  - `jobs`: list of job objects with `title`, `city`, `state`, `country`, `slug`, `req_id`, etc.
  - `totalCount`: total number of matching positions.

No authentication is required.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
PAGE_SIZE = 100


def _parse_phenom_job(raw: dict[str, Any], company: CompanyConfig, base_domain: str) -> Job:
    """
    Parse a single job from a Phenom/Jibe API response.

    Args:
        raw:         Raw job dict (nested under 'data').
        company:     Company configuration.
        base_domain: Base domain for constructing absolute URLs (e.g. https://careers.se.com).

    Returns:
        A populated Job object.
    """
    data = raw.get("data", raw)
    req_id = str(data.get("req_id") or data.get("slug") or "")
    title = data.get("title", "Unknown Position")

    # Location resolution
    full_location = data.get("full_location") or data.get("location_name") or ""
    city = data.get("city", "")
    country = data.get("country", "")
    if full_location:
        location = full_location
    elif city or country:
        location = f"{city}, {country}".strip(", ")
    else:
        location = ""

    # Canonical URL
    apply_url = data.get("apply_url") or ""
    slug = data.get("slug") or ""
    if slug:
        url = f"{base_domain}/jobs/{slug}"
    elif apply_url:
        url = apply_url
    else:
        url = company.careers_url

    # Description
    description = data.get("description", "") or ""

    # Published timestamp
    published_at = None
    posted_date = data.get("posted_date") or data.get("create_date")
    if posted_date:
        try:
            published_at = datetime.fromisoformat(
                posted_date.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (ValueError, AttributeError):
            pass

    external_id = req_id if req_id else make_external_id(company.name, url)

    return Job(
        company=company.name,
        external_id=external_id,
        title=title,
        location=location,
        country=country or company.country,
        url=url,
        description=description,
        published_at=published_at,
    )


class PhenomScraper(BaseScraper):
    """
    Scraper for companies using Phenom People / Jibe career portals.

    Fetches jobs via GET requests to `/api/jobs` with pagination.
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all jobs from the Phenom API for this company.

        Args:
            company: Company configuration.

        Returns:
            List of Job objects.
        """
        parsed = urlparse(company.careers_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        api_url = f"{base_domain}/api/jobs"

        logger.debug("PhenomScraper: fetching %s for %s", api_url, company.name)

        all_jobs: list[Job] = []
        offset = 0

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            while True:
                params = {"limit": PAGE_SIZE, "offset": offset}
                try:
                    response = client.get(
                        api_url,
                        params=params,
                        headers=headers,
                        follow_redirects=True,
                    )
                    if response.status_code != 200:
                        logger.error(
                            "PhenomScraper: HTTP %d from %s",
                            response.status_code,
                            api_url,
                        )
                        break

                    data = response.json()
                except httpx.TimeoutException:
                    logger.error(
                        "PhenomScraper: timeout at offset %d for %s",
                        offset,
                        company.name,
                    )
                    break
                except Exception as e:
                    logger.error(
                        "PhenomScraper: error for %s: %s", company.name, e
                    )
                    break

                raw_jobs = data.get("jobs", [])
                total = data.get("totalCount") or data.get("count", 0)

                for raw in raw_jobs:
                    try:
                        job = _parse_phenom_job(raw, company, base_domain)
                        all_jobs.append(job)
                    except Exception as e:
                        logger.warning(
                            "PhenomScraper: error parsing job for %s: %s",
                            company.name,
                            e,
                        )
                        continue

                offset += len(raw_jobs)
                if not raw_jobs or offset >= total:
                    break

                logger.debug(
                    "PhenomScraper: fetched %d/%d for %s",
                    offset,
                    total,
                    company.name,
                )

        logger.debug(
            "PhenomScraper: total %d jobs for %s", len(all_jobs), company.name
        )
        return all_jobs
