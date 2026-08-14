"""
Lever ATS scraper for Job Hunter.

Uses the public Lever Postings API (no authentication required):
  GET https://api.lever.co/v0/postings/{company_id}?mode=json

Documentation: https://github.com/lever/postings-api

The `company_id` field in companies.yml must match the Lever company identifier
(e.g., for https://jobs.lever.co/acme the company ID is "acme").
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LEVER_API_BASE = "https://api.lever.co/v0/postings"
REQUEST_TIMEOUT = 30


def _parse_lever_job(raw: dict[str, Any], company: CompanyConfig) -> Job:
    """
    Parse a single job from the Lever API response.

    Args:
        raw:     Raw posting dict from the Lever Postings API.
        company: Company configuration for metadata.

    Returns:
        A populated Job object.
    """
    posting_id = raw.get("id", "")
    title = raw.get("text", "Unknown Position")
    url = raw.get("hostedUrl", "") or raw.get("applyUrl", "")

    # Location from categories
    categories = raw.get("categories", {})
    location = categories.get("location", "") or categories.get("city", "") or ""

    # Description: concatenate plain text sections
    description_parts = []
    for section in raw.get("descriptionBody", {}).get("descriptionPlain", ""):
        # descriptionPlain is a string
        pass
    # Try descriptionPlain directly
    desc_plain = raw.get("descriptionPlain", "")
    if desc_plain:
        description_parts.append(desc_plain)
    # Also try lists (additionalInfoPlain, etc.)
    lists_data = raw.get("lists", [])
    for lst in lists_data:
        if isinstance(lst, dict):
            lst_text = lst.get("content", "")
            if lst_text:
                description_parts.append(lst_text)

    description = " ".join(description_parts).strip()

    # Alternatively fall back to stripping HTML description
    if not description:
        description_html = raw.get("description", "") or raw.get("descriptionBody", "") or ""
        if isinstance(description_html, str):
            description = _strip_html(description_html)

    # Parse creation timestamp (Unix ms)
    published_at = None
    created_at_ms = raw.get("createdAt")
    if created_at_ms:
        try:
            published_at = datetime.fromtimestamp(
                int(created_at_ms) / 1000, tz=timezone.utc
            ).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass

    external_id = posting_id if posting_id else make_external_id(company.name, url)

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


def _extract_company_id_from_url(url: str) -> Optional[str]:
    """
    Extract Lever company ID from a careers URL.
    Example: "https://jobs.lever.co/acme" -> "acme"
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if "lever.co" in (parsed.hostname or ""):
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0]
    except Exception:
        pass
    return None


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


class LeverScraper(BaseScraper):
    """
    Scraper for companies using the Lever ATS.

    Fetches all postings via the public JSON API.
    No authentication required.

    Required config in companies.yml:
        scraper: lever
        company_id: <company_slug>  # e.g., "acme" for jobs.lever.co/acme
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch all jobs from the Lever API for this company.

        Args:
            company: Company configuration.

        Returns:
            List of Job objects.
        """
        company_id = company.company_id or _extract_company_id_from_url(company.careers_url)
        if not company_id:
            logger.error(
                "LeverScraper: cannot determine company_id for %s. "
                "Please add company_id to companies.yml.",
                company.name,
            )
            return []

        url = f"{LEVER_API_BASE}/{company_id}?mode=json"
        logger.debug("LeverScraper: fetching %s", url)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.get(
                    url,
                    headers={"Accept": "application/json"},
                    follow_redirects=True,
                )

            if response.status_code == 404:
                logger.error(
                    "LeverScraper: company '%s' not found for %s. "
                    "Check the company_id in companies.yml.",
                    company_id,
                    company.name,
                )
                return []

            response.raise_for_status()
            raw_jobs = response.json()

        except httpx.TimeoutException:
            logger.error("LeverScraper: request timed out for %s", company.name)
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "LeverScraper: HTTP %d for %s",
                e.response.status_code,
                company.name,
            )
            return []
        except Exception as e:
            logger.error("LeverScraper: error for %s: %s", company.name, e)
            return []

        if not isinstance(raw_jobs, list):
            logger.error(
                "LeverScraper: unexpected API response format for %s", company.name
            )
            return []

        jobs = []
        for raw in raw_jobs:
            try:
                job = _parse_lever_job(raw, company)
                jobs.append(job)
            except Exception as e:
                logger.warning(
                    "LeverScraper: error parsing job for %s: %s", company.name, e
                )
                continue

        logger.debug("LeverScraper: parsed %d jobs for %s", len(jobs), company.name)
        return jobs
