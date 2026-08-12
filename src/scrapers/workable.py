"""
Workable ATS scraper for Job Hunter.

Workable uses an internal JSON API for its hosted boards:
  POST https://apply.workable.com/api/v3/accounts/{tenant}/jobs

Requires a simple JSON payload:
  {"query": "", "department": [], "location": [], "remote": []}

Pagination is not typically an issue for single requests as it returns
a reasonable number of results, but we'll fetch them cleanly.

Required config in companies.yml:
    scraper: workable
    company_id: <workable_tenant>  # e.g., "cowboy"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from src.config import CompanyConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

WORKABLE_API_PATH = "/api/v3/accounts/{tenant}/jobs"
REQUEST_TIMEOUT = 30


def _extract_tenant_from_url(url: str) -> Optional[str]:
    """
    Extract the Workable tenant from a workable URL.
    e.g., "https://apply.workable.com/cowboy/" → "cowboy"
    """
    try:
        parsed = urlparse(url)
        if "workable.com" in parsed.hostname:
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0]
    except Exception:
        pass
    return None


def _parse_workable_job(raw: dict[str, Any], company: CompanyConfig, tenant: str) -> Job:
    """Parse a single job from the Workable API response."""
    shortcode = raw.get("shortcode", "")
    title = raw.get("title", "Unknown Position")
    
    # URL construction
    url = f"https://apply.workable.com/{tenant}/j/{shortcode}/" if shortcode else company.careers_url

    # Location parsing
    loc_dict = raw.get("location", {})
    city = loc_dict.get("city", "")
    region = loc_dict.get("region", "")
    country = loc_dict.get("country", "")
    
    parts = filter(None, [city, region, country])
    location = ", ".join(parts)

    workplace = raw.get("workplace", "")
    if workplace:
        location = f"{workplace.title()} — {location}" if location else workplace.title()

    department = ", ".join(raw.get("department", []))

    # Published date
    published_str = raw.get("published", "")
    published_at = None
    if published_str:
        try:
            # Format: "2026-07-20T00:00:00.000Z"
            published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

    external_id = shortcode if shortcode else make_external_id(company.name, url)

    return Job(
        company=company.name,
        external_id=external_id,
        title=title,
        location=location,
        country=country or company.country,
        url=url,
        description=department,
        published_at=published_at,
    )


class WorkableScraper(BaseScraper):
    """Scraper for companies using Workable."""

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        tenant = company.company_id or _extract_tenant_from_url(company.careers_url)
        if not tenant:
            logger.error("WorkableScraper: cannot determine tenant for %s", company.name)
            return []

        api_url = f"https://apply.workable.com{WORKABLE_API_PATH.format(tenant=tenant)}"
        logger.debug("WorkableScraper: fetching %s", api_url)

        all_jobs: list[Job] = []

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.post(
                    api_url,
                    json={"query": "", "department": [], "location": [], "remote": []},
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Origin": "https://apply.workable.com",
                    },
                )
                
                if response.status_code == 404:
                    logger.error("WorkableScraper: 404 Not Found for tenant %s", tenant)
                    return []
                    
                response.raise_for_status()
                data = response.json()
                
                raw_results = data.get("results", [])
                for raw in raw_results:
                    try:
                        job = _parse_workable_job(raw, company, tenant)
                        all_jobs.append(job)
                    except Exception as e:
                        logger.warning("WorkableScraper: error parsing job for %s: %s", company.name, e)
                        
        except Exception as e:
            logger.error("WorkableScraper: request error for %s: %s", company.name, e)

        logger.debug("WorkableScraper: total %d jobs for %s", len(all_jobs), company.name)
        return all_jobs
