"""
SmartRecruiters ATS scraper for Job Hunter.

Uses the public SmartRecruiters Job Search API (no authentication required):
  GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings

Documentation: https://dev.smartrecruiters.com/customer-api/live-jobs-api/

The `company_id` field in companies.yml must match the SmartRecruiters company ID
(typically the company's legal name or slug, e.g., "VestasWindSystemsAS").

The API supports pagination via offset/limit parameters.
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

SMARTRECRUITERS_API_BASE = "https://api.smartrecruiters.com/v1/companies"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100  # SmartRecruiters max page size


def _parse_sr_job(raw: dict[str, Any], company: CompanyConfig) -> Job:
    """
    Parse a single job from the SmartRecruiters API response.

    Args:
        raw:     Raw job dict from the SmartRecruiters API.
        company: Company configuration for metadata.

    Returns:
        A populated Job object.
    """
    job_id = raw.get("id", "")
    title = raw.get("name", "Unknown Position")
    ref_number = raw.get("refNumber", "")

    # Build job URL
    url = raw.get("ref", "")
    if not url and job_id:
        url = f"https://careers.smartrecruiters.com/{company.company_id}/{job_id}"

    # Location
    location_data = raw.get("location", {})
    if isinstance(location_data, dict):
        city = location_data.get("city", "")
        country = location_data.get("country", company.country)
        region = location_data.get("region", "")
        remote = location_data.get("remote", False)
        if remote:
            location = f"Remote — {city}" if city else "Remote"
        else:
            parts = [p for p in [city, region, country] if p]
            location = ", ".join(parts)
    else:
        location = ""
        country = company.country

    # Department
    dept = raw.get("department", {})
    dept_name = dept.get("label", "") if isinstance(dept, dict) else ""

    # Description (not always available in list endpoint)
    description = raw.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", "")
    if isinstance(description, str):
        description = _strip_html(description)
    else:
        description = dept_name  # Use department as fallback

    # Parse dates
    published_at = None
    for date_field in ("createdon", "createdOn", "updatedOn", "publishedOn"):
        date_str = raw.get(date_field)
        if date_str:
            try:
                published_at = datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                break
            except (ValueError, AttributeError):
                continue

    external_id = job_id if job_id else (ref_number if ref_number else make_external_id(company.name, url))

    return Job(
        company=company.name,
        external_id=external_id,
        title=title,
        location=location,
        country=country,
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


class SmartRecruitersScraper(BaseScraper):
    """
    Scraper for companies using the SmartRecruiters ATS.

    Fetches all jobs via the public REST API with pagination support.
    No authentication required.

    Required config in companies.yml:
        scraper: smartrecruiters
        company_id: <SmartRecruiters company ID>  # e.g., "VestasWindSystemsAS"
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all jobs from the SmartRecruiters API for this company.

        Handles pagination automatically.

        Args:
            company: Company configuration. Must have `company_id` set.

        Returns:
            List of Job objects.
        """
        if not company.company_id:
            logger.error(
                "SmartRecruitersScraper: company_id not set for %s. "
                "Please add company_id to companies.yml.",
                company.name,
            )
            return []

        base_url = f"{SMARTRECRUITERS_API_BASE}/{company.company_id}/postings"
        all_jobs: list[Job] = []
        offset = 0

        logger.debug("SmartRecruitersScraper: fetching %s", base_url)

        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            while True:
                params = {
                    "limit": PAGE_SIZE,
                    "offset": offset,
                }

                try:
                    response = client.get(
                        base_url,
                        params=params,
                        headers={"Accept": "application/json"},
                        follow_redirects=True,
                    )
                except httpx.TimeoutException:
                    logger.error(
                        "SmartRecruitersScraper: timeout at offset %d for %s",
                        offset,
                        company.name,
                    )
                    break
                except Exception as e:
                    logger.error(
                        "SmartRecruitersScraper: error at offset %d for %s: %s",
                        offset,
                        company.name,
                        e,
                    )
                    break

                if response.status_code == 404:
                    logger.error(
                        "SmartRecruitersScraper: company_id '%s' not found for %s. "
                        "Check companies.yml.",
                        company.company_id,
                        company.name,
                    )
                    break

                try:
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.error(
                        "SmartRecruitersScraper: invalid response for %s: %s",
                        company.name,
                        e,
                    )
                    break

                raw_jobs = data.get("content", [])
                total = data.get("totalFound", 0)

                for raw in raw_jobs:
                    try:
                        job = _parse_sr_job(raw, company)
                        all_jobs.append(job)
                    except Exception as e:
                        logger.warning(
                            "SmartRecruitersScraper: error parsing job for %s: %s",
                            company.name,
                            e,
                        )
                        continue

                # Check if we've fetched all pages
                offset += len(raw_jobs)
                if not raw_jobs or offset >= total:
                    break

                logger.debug(
                    "SmartRecruitersScraper: fetched %d/%d for %s",
                    offset,
                    total,
                    company.name,
                )

        logger.debug(
            "SmartRecruitersScraper: total %d jobs for %s", len(all_jobs), company.name
        )
        return all_jobs
