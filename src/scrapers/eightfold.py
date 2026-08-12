"""
Eightfold AI ATS scraper for Job Hunter.

Eightfold AI (eightfold.ai) is used by STMicroelectronics and other companies.
It exposes a discoverable internal API endpoint at:

  GET https://{tenant}.eightfold.ai/api/apply/v2/jobs

Parameters:
  domain: The company's domain (e.g., "stmicroelectronics.com")
  start:  Pagination offset (0-based)
  num:    Page size (max ~100)
  src:    Always "JB_TNT"

The API returns JSON with a `positions` array and a `count` total.
No authentication required for public job boards.

Required config in companies.yml:
    scraper: eightfold
    company_id: <eightfold_tenant>       # e.g., "stmicroelectronics"
    eightfold_domain: <company_domain>   # e.g., "stmicroelectronics.com"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

EIGHTFOLD_API_PATH = "/api/apply/v2/jobs"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100


def _extract_tenant_from_url(url: str) -> Optional[str]:
    """
    Extract the Eightfold tenant from an eightfold.ai URL.

    e.g., "https://stmicroelectronics.eightfold.ai/careers" → "stmicroelectronics"

    Args:
        url: The Eightfold careers URL.

    Returns:
        Tenant string or None if not an Eightfold URL.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if "eightfold.ai" in hostname:
            # hostname format: {tenant}.eightfold.ai
            return hostname.split(".")[0]
    except Exception:
        pass
    return None


def _parse_eightfold_job(raw: dict[str, Any], company: CompanyConfig, tenant: str) -> Job:
    """
    Parse a single job from the Eightfold API response.

    Args:
        raw:     Raw position dict from the Eightfold API.
        company: Company configuration for metadata.
        tenant:  Eightfold tenant ID (for URL construction).

    Returns:
        A populated Job object.
    """
    job_id = str(raw.get("id", ""))
    title = raw.get("name") or raw.get("posting_name") or "Unknown Position"

    # Location: single string or first of list
    location = raw.get("location", "")
    locations = raw.get("locations", [])
    if not location and locations:
        location = locations[0] if isinstance(locations[0], str) else ""

    # Work mode: onsite / hybrid / remote
    work_mode = raw.get("work_location_option", "")
    if work_mode and work_mode != "onsite":
        location = f"{work_mode.title()} — {location}" if location else work_mode.title()

    # Canonical URL
    url = raw.get("canonicalPositionUrl", "")
    if not url and job_id:
        url = f"https://{tenant}.eightfold.ai/careers/job/{job_id}"

    # Department / description metadata (description is usually empty in list)
    department = raw.get("department", "")
    business_unit = raw.get("business_unit", "")
    job_desc = raw.get("job_description", "")
    description = " | ".join(filter(None, [department, business_unit, job_desc]))

    # Parse creation timestamp (Unix seconds)
    published_at = None
    for ts_field in ("t_create", "t_update"):
        ts = raw.get(ts_field)
        if ts:
            try:
                published_at = datetime.fromtimestamp(
                    int(ts), tz=timezone.utc
                ).replace(tzinfo=None)
                break
            except (ValueError, TypeError):
                continue

    # Resolve country from location string (e.g., "Agrate Brianza, Italy" → "Italy")
    resolved_country = company.country
    if location and "," in location:
        parts = [p.strip() for p in location.split(",")]
        if len(parts) >= 2:
            resolved_country = parts[-1]

    external_id = job_id if job_id else make_external_id(company.name, url)

    return Job(
        company=company.name,
        external_id=external_id,
        title=title,
        location=location,
        country=resolved_country,
        url=url,
        description=description,
        published_at=published_at,
    )


class EightfoldScraper(BaseScraper):
    """
    Scraper for companies using the Eightfold AI ATS platform.

    Fetches all jobs via the internal Eightfold API with pagination.
    No authentication required for public career boards.

    Known companies using Eightfold AI:
      - STMicroelectronics (stmicroelectronics.eightfold.ai)

    Required config in companies.yml:
        scraper: eightfold
        careers_url: https://{tenant}.eightfold.ai/careers
        company_id: <eightfold_tenant>        # e.g., "stmicroelectronics"
        eightfold_domain: <company_domain>    # e.g., "stmicroelectronics.com"

    If eightfold_domain is not set, it defaults to "{company_id}.com".
    If company_id is not set, it's auto-detected from the careers_url.
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all jobs from the Eightfold API for this company.

        Args:
            company: Company configuration.

        Returns:
            List of Job objects.
        """
        # Determine tenant
        tenant = company.company_id
        if not tenant:
            tenant = _extract_tenant_from_url(company.careers_url)

        if not tenant:
            logger.error(
                "EightfoldScraper: cannot determine tenant for %s. "
                "Set company_id in companies.yml.",
                company.name,
            )
            return []

        # Determine domain for API parameter
        # Check for custom eightfold_domain attribute
        eightfold_domain = getattr(company, "eightfold_domain", None) or f"{tenant}.com"

        api_url = f"https://{tenant}.eightfold.ai{EIGHTFOLD_API_PATH}"
        logger.debug(
            "EightfoldScraper: fetching %s (domain=%s)", api_url, eightfold_domain
        )

        all_jobs: list[Job] = []
        start = 0

        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            while True:
                params = {
                    "domain": eightfold_domain,
                    "start": start,
                    "num": PAGE_SIZE,
                    "src": "JB_TNT",
                }
                try:
                    response = client.get(
                        api_url,
                        params=params,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "User-Agent": (
                                "Mozilla/5.0 (X11; Linux x86_64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36"
                            ),
                            "Referer": company.careers_url,
                        },
                        follow_redirects=True,
                    )
                except httpx.TimeoutException:
                    logger.error(
                        "EightfoldScraper: timeout at offset %d for %s",
                        start,
                        company.name,
                    )
                    break
                except Exception as e:
                    logger.error(
                        "EightfoldScraper: request error for %s: %s",
                        company.name,
                        e,
                    )
                    break

                if response.status_code == 403:
                    logger.error(
                        "EightfoldScraper: 403 Forbidden for %s — "
                        "this tenant may restrict API access.",
                        company.name,
                    )
                    break

                if response.status_code == 404:
                    logger.error(
                        "EightfoldScraper: tenant '%s' not found for %s. "
                        "Check company_id in companies.yml.",
                        tenant,
                        company.name,
                    )
                    break

                try:
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.error(
                        "EightfoldScraper: invalid response for %s: %s",
                        company.name,
                        e,
                    )
                    break

                raw_positions = data.get("positions", [])
                total = data.get("count", 0)

                for raw in raw_positions:
                    try:
                        job = _parse_eightfold_job(raw, company, tenant)
                        all_jobs.append(job)
                    except Exception as e:
                        logger.warning(
                            "EightfoldScraper: error parsing job for %s: %s",
                            company.name,
                            e,
                        )
                        continue

                start += len(raw_positions)
                if not raw_positions or start >= total:
                    break

                logger.debug(
                    "EightfoldScraper: fetched %d/%d for %s",
                    start,
                    total,
                    company.name,
                )

        logger.debug(
            "EightfoldScraper: total %d jobs for %s", len(all_jobs), company.name
        )
        return all_jobs
