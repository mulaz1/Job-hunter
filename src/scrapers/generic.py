"""
Generic scraper using Playwright.

Designed for job pages that require JavaScript rendering.
Uses heuristics to identify job posting links and avoid navigation/social links.

Heuristic approach:
  - Collects all <a> tags from the page
  - Scores each link based on URL patterns and text content
  - Filters out known non-job URLs (privacy, login, social, etc.)
  - Returns Job objects with extracted data
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# ---- URL patterns that indicate a job posting link ----
JOB_URL_PATTERNS = [
    r"/job[s]?/",
    r"/career[s]?/",
    r"/position[s]?/",
    r"/opening[s]?/",
    r"/posting[s]?/",
    r"/vacancy",
    r"/vacancies",
    r"/role[s]?/",
    r"/apply",
    r"/requisition",
    r"job[_-]?id",
    r"req[_-]?id",
    r"jobid",
    r"/jd/",
    r"/jd-",
]

# ---- URL fragments/patterns that indicate NON-job links ----
NON_JOB_URL_PATTERNS = [
    r"privacy",
    r"cookie",
    r"terms",
    r"login",
    r"signin",
    r"sign-in",
    r"signup",
    r"register",
    r"contact",
    r"about",
    r"news",
    r"press",
    r"blog",
    r"tweet",
    r"facebook",
    r"linkedin\.com",
    r"instagram",
    r"youtube",
    r"twitter",
    r"mailto:",
    r"tel:",
    r"javascript:",
    r"#",
    r"/404",
    r"support",
    r"help",
]

# ---- Link text patterns that suggest job postings ----
JOB_TEXT_PATTERNS = [
    r"engineer",
    r"developer",
    r"designer",
    r"manager",
    r"analyst",
    r"scientist",
    r"specialist",
    r"director",
    r"lead",
    r"architect",
    r"intern",
    r"technician",
    r"coordinator",
    r"apply",
    r"view job",
    r"view position",
    r"see job",
    r"job detail",
]

# ---- Text that definitely means it's NOT a job link ----
NON_JOB_TEXT_PATTERNS = [
    r"^home$",
    r"^about$",
    r"^contact$",
    r"^privacy$",
    r"^cookies$",
    r"^terms$",
    r"^login$",
    r"^sign in$",
    r"^register$",
    r"^back$",
    r"^next$",
    r"^previous$",
    r"^search$",
    r"^menu$",
    r"^close$",
    r"^skip",
    r"read more",
    r"learn more",
    r"see all",
]


def _is_likely_job_url(url: str) -> bool:
    """
    Heuristically determine if a URL looks like a job posting.

    Args:
        url: The URL to evaluate (absolute or relative).

    Returns:
        True if the URL pattern suggests a job posting.
    """
    lower_url = url.lower()

    # Reject known non-job patterns
    for pattern in NON_JOB_URL_PATTERNS:
        if re.search(pattern, lower_url):
            return False

    # Accept known job patterns
    for pattern in JOB_URL_PATTERNS:
        if re.search(pattern, lower_url):
            return True

    return False


def _is_likely_job_text(text: str) -> bool:
    """
    Heuristically determine if link text suggests a job posting.

    Args:
        text: The anchor tag text content.

    Returns:
        True if the text suggests a job posting.
    """
    if not text or len(text.strip()) < 3:
        return False

    lower_text = text.lower().strip()

    # Reject known non-job texts
    for pattern in NON_JOB_TEXT_PATTERNS:
        if re.match(pattern, lower_text):
            return False

    # Accept if text matches job patterns
    for pattern in JOB_TEXT_PATTERNS:
        if re.search(pattern, lower_text):
            return True

    return False


def _normalize_url(url: str, base_url: str) -> Optional[str]:
    """
    Normalize and validate a URL.

    - Converts relative URLs to absolute
    - Removes fragments (#)
    - Returns None for invalid URLs

    Args:
        url:      The URL to normalize (may be relative).
        base_url: The base URL of the page being scraped.

    Returns:
        Normalized absolute URL, or None if invalid.
    """
    if not url or url.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None

    try:
        # Make absolute
        absolute = urljoin(base_url, url)
        # Parse and validate
        parsed = urlparse(absolute)
        if not parsed.scheme or not parsed.netloc:
            return None
        # Remove fragments
        clean = parsed._replace(fragment="").geturl()
        # Remove trailing slash for consistency (but keep root /)
        if clean.endswith("/") and len(clean) > len(parsed.scheme) + 3:
            clean = clean.rstrip("/")
        return clean
    except Exception:
        return None


def _extract_jobs_from_html(
    html: str,
    base_url: str,
    company: CompanyConfig,
) -> list[Job]:
    """
    Parse HTML and extract job postings using heuristics.

    Args:
        html:     Page HTML content.
        base_url: Base URL for resolving relative links.
        company:  Company configuration.

    Returns:
        List of Job objects (may be empty).
    """
    soup = BeautifulSoup(html, "lxml")
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        text = anchor.get_text(separator=" ", strip=True)

        # Normalize URL
        url = _normalize_url(href, base_url)
        if not url:
            continue

        # Deduplicate
        if url in seen_urls:
            continue

        # Apply heuristics
        url_looks_like_job = _is_likely_job_url(url)
        text_looks_like_job = _is_likely_job_text(text)

        if not url_looks_like_job and not text_looks_like_job:
            continue

        # Both signals must not be explicitly negative
        lower_url = url.lower()
        if any(re.search(p, lower_url) for p in NON_JOB_URL_PATTERNS):
            continue

        seen_urls.add(url)

        # Create job object
        external_id = make_external_id(company.name, url)
        title = text if text and len(text) > 2 else "Unknown Position"

        job = Job(
            company=company.name,
            external_id=external_id,
            title=title,
            location="",  # Not available from link text
            country=company.country,
            url=url,
            description="",
        )
        jobs.append(job)

    return jobs


class GenericScraper(BaseScraper):
    """
    JavaScript-capable scraper using Playwright.

    Loads the career page in a headless Chromium browser,
    waits for JavaScript to render, then extracts job links
    using heuristic analysis.

    Limitations:
      - Cannot always extract location or description from link lists
      - Heuristics may miss some jobs or include false positives
      - For better accuracy, use a platform-specific scraper (Greenhouse, Lever, etc.)
    """

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """
        Fetch jobs from a generic career page using Playwright.

        Args:
            company: Company configuration with careers_url.

        Returns:
            List of Job objects extracted from the page.
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

        timeout_ms = self.scraping_config.page_timeout_seconds * 1000
        url = company.careers_url

        logger.debug("GenericScraper: loading %s", url)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )

                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                try:
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                except Exception:
                    pass

                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                    if response is None:
                        logger.warning("GenericScraper: no response from %s", url)
                        return []

                    if response.status >= 400:
                        logger.warning(
                            "GenericScraper: HTTP %d from %s", response.status, url
                        )
                        return []

                    # Wait a bit for any lazy-loaded content
                    page.wait_for_timeout(3000)
                    html = page.content()

                except PlaywrightTimeout:
                    logger.error(
                        "GenericScraper: timeout loading %s (limit: %ds)",
                        url,
                        self.scraping_config.page_timeout_seconds,
                    )
                    return []
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
                    try:
                        browser.close()
                    except Exception:
                        pass

        except Exception as e:
            logger.error("GenericScraper: browser error for %s: %s", company.name, e)
            return []

        if not html:
            logger.warning("GenericScraper: empty HTML from %s", url)
            return []

        jobs = _extract_jobs_from_html(html, url, company)
        logger.debug(
            "GenericScraper: extracted %d candidate job links from %s", len(jobs), url
        )
        return jobs
