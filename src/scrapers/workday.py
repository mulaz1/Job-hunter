"""
Workday ATS scraper for Job Hunter.

Workday job portals use a non-public REST API that can be discovered
from the browser network tab. The endpoint pattern varies per company
but typically follows:

  POST https://{company}.wd{N}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs

This scraper uses a best-effort approach:
  1. Try the known Workday Jobs API endpoint with pagination
  2. Fall back to HTML scraping if the API endpoint is unknown

Each Workday tenant has a unique URL. The config requires:
  workday_tenant:   The company's Workday tenant ID
  workday_instance: The Workday instance number (e.g., "wd3", "wd5")

Example:
  Company URL: https://nxp.wd3.myworkdayjobs.com/careers
  tenant: nxp
  instance: wd3

Note: Workday's internal API is not officially public, so it may change.
If the API fails, the scraper falls back to the GenericScraper (Playwright).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
WORKDAY_PAGE_SIZE = 20


def _extract_tenant_from_url(url: str) -> tuple[Optional[str], Optional[str]]:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if "myworkdayjobs.com" not in hostname:
            return None, None
        # hostname format: {tenant}.{instance}.myworkdayjobs.com
        parts = hostname.split(".")
        if len(parts) >= 3:
            return parts[0], parts[1]
    except Exception:
        pass
    return None, None


def _build_workday_api_url(tenant: str, instance: str, site: str = "External") -> str:
    return (
        f"https://{tenant}.{instance}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )


def _parse_workday_job(raw: dict[str, Any], company: CompanyConfig, base_url: str) -> Job:
    # Workday uses 'externalPath' for relative job URLs
    external_path = raw.get("externalPath", "")
    job_id = raw.get("bulletFields", [None])[0] if raw.get("bulletFields") else ""

    title = raw.get("title", "Unknown Position")

    # Build absolute URL
    if external_path:
        parsed_base = urlparse(base_url)
        url = f"{parsed_base.scheme}://{parsed_base.netloc}{external_path}"
    else:
        url = ""

    # Location from locationsText or locations array
    locations_text = raw.get("locationsText", "")
    locations = raw.get("locations", [])
    if locations_text:
        location = locations_text
    elif locations:
        location_names = [loc.get("descriptor", "") for loc in locations if isinstance(loc, dict)]
        location = ", ".join(filter(None, location_names))
    else:
        location = ""

    # Description is not usually in the list response — use empty
    description = ""

    # Parse posted date
    published_at = None
    posted_on = raw.get("postedOn") or raw.get("startDate")
    if posted_on:
        try:
            published_at = datetime.fromisoformat(
                posted_on.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (ValueError, AttributeError):
            pass

    external_id = job_id if job_id else make_external_id(company.name, url or external_path)

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


def _extract_site_from_url(url: str) -> Optional[str]:
    """Extract site name from a Workday URL path (e.g. /External_Career_Site -> External_Career_Site)."""
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            return path.split("/")[0]
    except Exception:
        pass
    return None


def _try_workday_api(
    tenant: str, instance: str, company: CompanyConfig
) -> Optional[list[Job]]:
    candidate_sites: list[str] = []

    url_site = _extract_site_from_url(company.careers_url)
    if url_site:
        candidate_sites.append(url_site)

    default_sites = [
        "External",
        "careers",
        "Careers",
        "External_Career_Site",
        company.name.replace(" ", ""),
        "Jobs",
    ]
    for s in default_sites:
        if s not in candidate_sites:
            candidate_sites.append(s)

    for site in candidate_sites:
        api_url = _build_workday_api_url(tenant, instance, site)
        logger.debug("WorkdayScraper: trying API endpoint %s", api_url)

        all_jobs: list[Job] = []
        offset = 0

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                while True:
                    payload = {
                        "appliedFacets": {},
                        "limit": WORKDAY_PAGE_SIZE,
                        "offset": offset,
                        "searchText": "",
                    }
                    response = client.post(
                        api_url,
                        json=payload,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                        follow_redirects=True,
                    )

                    if response.status_code in (404, 403, 400):
                        break  # Try next site name

                    response.raise_for_status()
                    data = response.json()

                    raw_jobs = data.get("jobPostings", [])
                    total = data.get("total", 0)

                    for raw in raw_jobs:
                        try:
                            job = _parse_workday_job(
                                raw, company, f"https://{tenant}.{instance}.myworkdayjobs.com"
                            )
                            all_jobs.append(job)
                        except Exception as e:
                            logger.warning(
                                "WorkdayScraper: error parsing job for %s: %s",
                                company.name,
                                e,
                            )

                    offset += len(raw_jobs)
                    if not raw_jobs or offset >= total:
                        break

            if all_jobs:
                logger.info(
                    "WorkdayScraper: API success for %s (site=%s, %d jobs)",
                    company.name,
                    site,
                    len(all_jobs),
                )
                return all_jobs

        except httpx.TimeoutException:
            logger.warning("WorkdayScraper: timeout for %s (site=%s)", company.name, site)
        except Exception as e:
            logger.debug("WorkdayScraper: API attempt failed for site=%s: %s", site, e)
            continue

    return None  # All API attempts failed


class WorkdayScraper(BaseScraper):
    """
    Scraper for companies using the Workday ATS.

    Primary strategy: Workday internal Jobs API (JSON, paginated).
    Fallback strategy: Generic Playwright scraper.

    Required config in companies.yml:
        scraper: workday
        careers_url: https://{tenant}.{instance}.myworkdayjobs.com/...

    Optional:
        workday_tenant:   Explicit tenant override (auto-detected from URL if not set)
        workday_instance: Explicit instance override (auto-detected from URL if not set)
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        # Determine tenant and instance
        tenant = company.workday_tenant
        instance = company.workday_instance

        # Try to auto-detect from URL
        if not tenant or not instance:
            detected_tenant, detected_instance = _extract_tenant_from_url(company.careers_url)
            tenant = tenant or detected_tenant
            instance = instance or detected_instance

        if tenant and instance:
            logger.debug(
                "WorkdayScraper: trying API for %s (tenant=%s, instance=%s)",
                company.name,
                tenant,
                instance,
            )
            jobs = _try_workday_api(tenant, instance, company)
            if jobs is not None:
                return jobs
            logger.warning(
                "WorkdayScraper: API failed for %s — falling back to GenericScraper",
                company.name,
            )
        else:
            logger.warning(
                "WorkdayScraper: could not determine Workday tenant for %s — "
                "falling back to GenericScraper",
                company.name,
            )

        # Fallback: generic Playwright scraper
        from src.scrapers.generic import GenericScraper
        return GenericScraper(self.scraping_config).fetch_jobs(company)
