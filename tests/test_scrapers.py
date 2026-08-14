"""
Tests for scrapers.

Tests cover:
  - URL normalization
  - Greenhouse API response parsing (mocked)
  - Lever API response parsing (mocked)
  - SmartRecruiters API response parsing (mocked)
  - Generic scraper HTML parsing (no real network calls)
  - Scraper registry

All HTTP calls are mocked — no real network access.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.config import CompanyConfig, ScrapingConfig
from src.models import Job, make_external_id
from src.scrapers.generic import (
    _normalize_url,
    _is_likely_job_url,
    _is_likely_job_text,
    _extract_jobs_from_html,
)
from src.scrapers.greenhouse import (
    GreenhouseScraper,
    _parse_greenhouse_job,
    _extract_board_token_from_url,
)
from src.scrapers.lever import (
    LeverScraper,
    _parse_lever_job,
    _extract_company_id_from_url as _extract_lever_id,
)
from src.scrapers.smartrecruiters import (
    SmartRecruitersScraper,
    _parse_sr_job,
    _extract_company_id_from_url as _extract_sr_id,
)
from src.scrapers.registry import get_scraper, list_scrapers


# ---- Fixtures ----

@pytest.fixture
def scraping_config() -> ScrapingConfig:
    return ScrapingConfig(
        delay_between_companies_seconds=0,
        page_timeout_seconds=30,
        max_jobs_per_company=100,
    )


@pytest.fixture
def greenhouse_company() -> CompanyConfig:
    return CompanyConfig(
        name="Acme Corp",
        country="Netherlands",
        careers_url="https://boards.greenhouse.io/acme",
        scraper="greenhouse",
        company_id="acme",
    )


@pytest.fixture
def lever_company() -> CompanyConfig:
    return CompanyConfig(
        name="LeverCo",
        country="Germany",
        careers_url="https://jobs.lever.co/leverco",
        scraper="lever",
        company_id="leverco",
    )


@pytest.fixture
def sr_company() -> CompanyConfig:
    return CompanyConfig(
        name="SRCo",
        country="Denmark",
        careers_url="https://careers.smartrecruiters.com/SRCo",
        scraper="smartrecruiters",
        company_id="SRCo",
    )


@pytest.fixture
def generic_company() -> CompanyConfig:
    return CompanyConfig(
        name="GenericCo",
        country="Italy",
        careers_url="https://www.genericco.com/careers",
        scraper="generic",
    )


# ============================================================
# URL normalization tests
# ============================================================

class TestUrlNormalization:
    BASE = "https://example.com/careers"

    def test_absolute_url_unchanged(self):
        """Absolute URL should be returned as-is (minus fragment)."""
        url = "https://example.com/jobs/123"
        result = _normalize_url(url, self.BASE)
        assert result == "https://example.com/jobs/123"

    def test_relative_url_resolved(self):
        """Relative URL should be resolved against the base URL."""
        result = _normalize_url("/jobs/456", self.BASE)
        assert result == "https://example.com/jobs/456"

    def test_fragment_removed(self):
        """URL fragment (#anchor) should be stripped."""
        result = _normalize_url("https://example.com/jobs/789#apply", self.BASE)
        assert result == "https://example.com/jobs/789"

    def test_trailing_slash_removed(self):
        """Trailing slash should be removed for consistency."""
        result = _normalize_url("https://example.com/jobs/999/", self.BASE)
        assert result == "https://example.com/jobs/999"

    def test_javascript_rejected(self):
        """JavaScript URLs should return None."""
        result = _normalize_url("javascript:void(0)", self.BASE)
        assert result is None

    def test_mailto_rejected(self):
        """Mailto URLs should return None."""
        result = _normalize_url("mailto:hr@example.com", self.BASE)
        assert result is None

    def test_empty_string_rejected(self):
        """Empty string should return None."""
        result = _normalize_url("", self.BASE)
        assert result is None

    def test_hash_only_rejected(self):
        """Hash-only URL should return None."""
        result = _normalize_url("#section", self.BASE)
        assert result is None


# ============================================================
# URL heuristic tests
# ============================================================

class TestUrlHeuristics:
    def test_job_in_url_true(self):
        assert _is_likely_job_url("https://example.com/jobs/hardware-engineer") is True

    def test_careers_in_url_true(self):
        assert _is_likely_job_url("https://example.com/careers/apply/123") is True

    def test_position_in_url_true(self):
        assert _is_likely_job_url("https://example.com/positions/456") is True

    def test_privacy_url_false(self):
        assert _is_likely_job_url("https://example.com/privacy-policy") is False

    def test_login_url_false(self):
        assert _is_likely_job_url("https://example.com/login") is False

    def test_facebook_url_false(self):
        assert _is_likely_job_url("https://facebook.com/company") is False

    def test_plain_url_false(self):
        assert _is_likely_job_url("https://example.com/about-us") is False


# ============================================================
# Text heuristic tests
# ============================================================

class TestTextHeuristics:
    def test_engineer_text_true(self):
        assert _is_likely_job_text("Hardware Design Engineer") is True

    def test_developer_text_true(self):
        assert _is_likely_job_text("Senior Software Developer") is True

    def test_apply_text_true(self):
        assert _is_likely_job_text("Apply for this position") is True

    def test_home_text_false(self):
        assert _is_likely_job_text("Home") is False

    def test_privacy_text_false(self):
        assert _is_likely_job_text("privacy") is False

    def test_empty_text_false(self):
        assert _is_likely_job_text("") is False

    def test_very_short_text_false(self):
        assert _is_likely_job_text("OK") is False


# ============================================================
# HTML extraction tests
# ============================================================

class TestHtmlExtraction:
    SAMPLE_HTML = """
    <html>
    <body>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/login">Login</a>
      </nav>
      <main>
        <h1>Open Positions</h1>
        <ul>
          <li><a href="/jobs/hardware-engineer-123">Hardware Design Engineer</a></li>
          <li><a href="/jobs/embedded-456">Embedded Systems Engineer</a></li>
          <li><a href="/jobs/fpga-789">FPGA Design Engineer</a></li>
        </ul>
      </main>
      <footer>
        <a href="/privacy">Privacy Policy</a>
        <a href="https://twitter.com/genericco">Twitter</a>
        <a href="https://linkedin.com/company/genericco">LinkedIn</a>
      </footer>
    </body>
    </html>
    """

    def test_extracts_job_links(self):
        company = CompanyConfig(
            name="GenericCo",
            country="Italy",
            careers_url="https://www.genericco.com/careers",
            scraper="generic",
        )
        jobs = _extract_jobs_from_html(
            self.SAMPLE_HTML,
            "https://www.genericco.com/careers",
            company,
        )
        urls = [j.url for j in jobs]
        # Should include job links
        assert any("hardware-engineer" in u for u in urls)
        assert any("embedded" in u for u in urls)
        assert any("fpga" in u for u in urls)

    def test_excludes_nav_links(self):
        company = CompanyConfig(
            name="GenericCo",
            country="Italy",
            careers_url="https://www.genericco.com/careers",
            scraper="generic",
        )
        jobs = _extract_jobs_from_html(
            self.SAMPLE_HTML,
            "https://www.genericco.com/careers",
            company,
        )
        urls = [j.url for j in jobs]
        # Should NOT include navigation/social/privacy links
        assert not any("privacy" in u for u in urls)
        assert not any("twitter.com" in u for u in urls)
        assert not any("linkedin.com" in u for u in urls)

    def test_deduplicates_links(self):
        """Duplicate URLs in HTML should produce only one Job."""
        html = """
        <html><body>
          <a href="/jobs/dup-123">Hardware Engineer</a>
          <a href="/jobs/dup-123">Hardware Engineer</a>
          <a href="/jobs/dup-123">Hardware Engineer</a>
        </body></html>
        """
        company = CompanyConfig(
            name="DupCo", country="Italy",
            careers_url="https://dupco.com/careers", scraper="generic"
        )
        jobs = _extract_jobs_from_html(html, "https://dupco.com/careers", company)
        assert len(jobs) == 1

    def test_empty_html(self):
        company = CompanyConfig(
            name="EmptyCo", country="Italy",
            careers_url="https://emptyco.com/careers", scraper="generic"
        )
        jobs = _extract_jobs_from_html("", "https://emptyco.com/careers", company)
        assert jobs == []


# ============================================================
# Greenhouse scraper tests (mocked)
# ============================================================

class TestGreenhouseScraper:
    def test_parse_greenhouse_job(self):
        company = CompanyConfig(
            name="Acme", country="Netherlands",
            careers_url="https://boards.greenhouse.io/acme",
            scraper="greenhouse", company_id="acme"
        )
        raw = {
            "id": 127817,
            "title": "Hardware Design Engineer",
            "updated_at": "2024-01-14T10:55:28-05:00",
            "location": {"name": "Eindhoven, NL"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/127817",
            "content": "<p>We need a hardware engineer with PCB experience.</p>",
        }
        job = _parse_greenhouse_job(raw, company)
        assert job.title == "Hardware Design Engineer"
        assert job.location == "Eindhoven, NL"
        assert job.external_id == "127817"
        assert "hardware" in job.description.lower()
        assert job.published_at is not None

    def test_extract_board_token_from_url(self):
        assert _extract_board_token_from_url("https://job-boards.eu.greenhouse.io/exeinspa") == "exeinspa"
        assert _extract_board_token_from_url("https://boards.greenhouse.io/acme") == "acme"
        assert _extract_board_token_from_url("https://boards.greenhouse.io/embed/job_board?for=acme") == "acme"
        assert _extract_board_token_from_url("https://invalid.com") is None

    def test_no_company_id_returns_empty_when_url_unparseable(self, scraping_config):
        scraper = GreenhouseScraper(scraping_config)
        company = CompanyConfig(
            name="NoCo", country="Italy",
            careers_url="https://invalid.com",
            scraper="greenhouse",
            company_id=None,  # Missing!
        )
        jobs = scraper.fetch_jobs(company)
        assert jobs == []

    @patch("httpx.Client")
    def test_fetch_jobs_success(self, mock_client_class, scraping_config, greenhouse_company):
        """Test successful Greenhouse API response parsing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "id": 111,
                    "title": "FPGA Engineer",
                    "location": {"name": "Amsterdam"},
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
                    "content": "<p>FPGA design experience required.</p>",
                    "updated_at": "2024-06-01T12:00:00Z",
                },
                {
                    "id": 222,
                    "title": "Embedded Systems Engineer",
                    "location": {"name": "Eindhoven"},
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/222",
                    "content": "<p>Embedded C experience needed.</p>",
                    "updated_at": "2024-06-02T12:00:00Z",
                },
            ]
        }
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = GreenhouseScraper(scraping_config)
        jobs = scraper.fetch_jobs(greenhouse_company)

        assert len(jobs) == 2
        titles = [j.title for j in jobs]
        assert "FPGA Engineer" in titles
        assert "Embedded Systems Engineer" in titles

    @patch("httpx.Client")
    def test_fetch_jobs_404(self, mock_client_class, scraping_config, greenhouse_company):
        """404 response should return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = GreenhouseScraper(scraping_config)
        jobs = scraper.fetch_jobs(greenhouse_company)
        assert jobs == []


# ============================================================
# Lever scraper tests (mocked)
# ============================================================

class TestLeverScraper:
    def test_parse_lever_job(self):
        company = CompanyConfig(
            name="LeverCo", country="Germany",
            careers_url="https://jobs.lever.co/leverco",
            scraper="lever", company_id="leverco"
        )
        raw = {
            "id": "abc-123",
            "text": "PCB Layout Engineer",
            "hostedUrl": "https://jobs.lever.co/leverco/abc-123",
            "categories": {"location": "Berlin, Germany"},
            "descriptionPlain": "Experience with Altium Designer required.",
            "createdAt": 1704067200000,  # 2024-01-01 in ms
            "lists": [],
        }
        job = _parse_lever_job(raw, company)
        assert job.title == "PCB Layout Engineer"
        assert job.location == "Berlin, Germany"
        assert job.external_id == "abc-123"
        assert job.published_at is not None

    def test_extract_company_id_from_url(self):
        assert _extract_lever_id("https://jobs.lever.co/leverco") == "leverco"
        assert _extract_lever_id("https://invalid.com") is None

    def test_no_company_id_returns_empty_when_url_unparseable(self, scraping_config):
        scraper = LeverScraper(scraping_config)
        company = CompanyConfig(
            name="NoCo", country="Germany",
            careers_url="https://invalid.com",
            scraper="lever", company_id=None
        )
        jobs = scraper.fetch_jobs(company)
        assert jobs == []

    @patch("httpx.Client")
    def test_fetch_jobs_success(self, mock_client_class, scraping_config, lever_company):
        """Test successful Lever API response parsing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "lever-001",
                "text": "Hardware Engineer",
                "hostedUrl": "https://jobs.lever.co/leverco/lever-001",
                "categories": {"location": "Munich"},
                "descriptionPlain": "Hardware design role.",
                "createdAt": 1704067200000,
                "lists": [],
            }
        ]
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = LeverScraper(scraping_config)
        jobs = scraper.fetch_jobs(lever_company)
        assert len(jobs) == 1
        assert jobs[0].title == "Hardware Engineer"


# ============================================================
# SmartRecruiters scraper tests (mocked)
# ============================================================

class TestSmartRecruitersScraper:
    def test_parse_sr_job(self):
        company = CompanyConfig(
            name="SRCo", country="Denmark",
            careers_url="https://careers.smartrecruiters.com/SRCo",
            scraper="smartrecruiters", company_id="SRCo"
        )
        raw = {
            "id": "sr-001",
            "name": "Embedded Hardware Engineer",
            "ref": "https://jobs.smartrecruiters.com/SRCo/sr-001",
            "location": {
                "city": "Copenhagen",
                "country": "Denmark",
                "remote": False,
            },
            "createdon": "2024-05-01T10:00:00.000Z",
        }
        job = _parse_sr_job(raw, company)
        assert job.title == "Embedded Hardware Engineer"
        assert "Copenhagen" in job.location
        assert job.external_id == "sr-001"

    def test_parse_sr_job_remote(self):
        company = CompanyConfig(
            name="SRCo", country="Denmark",
            careers_url="https://careers.smartrecruiters.com/SRCo",
            scraper="smartrecruiters", company_id="SRCo"
        )
        raw = {
            "id": "sr-002",
            "name": "PCB Designer",
            "ref": "https://jobs.smartrecruiters.com/SRCo/sr-002",
            "location": {
                "city": "Aarhus",
                "country": "Denmark",
                "remote": True,
            },
        }
        job = _parse_sr_job(raw, company)
        assert "Remote" in job.location

    def test_extract_company_id_from_url(self):
        assert _extract_sr_id("https://careers.smartrecruiters.com/SRCo") == "SRCo"
        assert _extract_sr_id("https://invalid.com") is None

    def test_no_company_id_returns_empty_when_url_unparseable(self, scraping_config):
        scraper = SmartRecruitersScraper(scraping_config)
        company = CompanyConfig(
            name="NoCo", country="Denmark",
            careers_url="https://invalid.com",
            scraper="smartrecruiters", company_id=None
        )
        jobs = scraper.fetch_jobs(company)
        assert jobs == []


# ============================================================
# Registry tests
# ============================================================

class TestRegistry:
    def test_get_generic_scraper(self, scraping_config):
        from src.scrapers.generic import GenericScraper
        ScraperClass = get_scraper("generic")
        assert ScraperClass is GenericScraper

    def test_get_greenhouse_scraper(self, scraping_config):
        from src.scrapers.greenhouse import GreenhouseScraper
        ScraperClass = get_scraper("greenhouse")
        assert ScraperClass is GreenhouseScraper

    def test_get_lever_scraper(self, scraping_config):
        from src.scrapers.lever import LeverScraper
        ScraperClass = get_scraper("lever")
        assert ScraperClass is LeverScraper

    def test_get_workday_scraper(self, scraping_config):
        from src.scrapers.workday import WorkdayScraper
        ScraperClass = get_scraper("workday")
        assert ScraperClass is WorkdayScraper

    def test_get_smartrecruiters_scraper(self, scraping_config):
        from src.scrapers.smartrecruiters import SmartRecruitersScraper
        ScraperClass = get_scraper("smartrecruiters")
        assert ScraperClass is SmartRecruitersScraper

    def test_unknown_scraper_raises(self):
        with pytest.raises(ValueError, match="Unknown scraper type"):
            get_scraper("nonexistent")

    def test_list_scrapers(self):
        scrapers = list_scrapers()
        assert "generic" in scrapers
        assert "greenhouse" in scrapers
        assert "lever" in scrapers
        assert "workday" in scrapers
        assert "smartrecruiters" in scrapers

    def test_case_insensitive_registry(self, scraping_config):
        """Registry lookup should be case-insensitive."""
        from src.scrapers.greenhouse import GreenhouseScraper
        assert get_scraper("GREENHOUSE") is GreenhouseScraper
        assert get_scraper("Greenhouse") is GreenhouseScraper


# ============================================================
# Model tests
# ============================================================

class TestModels:
    def test_external_id_deterministic(self):
        """make_external_id should return the same value for same inputs."""
        id1 = make_external_id("TestCo", "https://example.com/jobs/123")
        id2 = make_external_id("TestCo", "https://example.com/jobs/123")
        assert id1 == id2

    def test_external_id_different_for_different_inputs(self):
        id1 = make_external_id("CompanyA", "https://example.com/jobs/1")
        id2 = make_external_id("CompanyB", "https://example.com/jobs/1")
        assert id1 != id2

    def test_external_id_strips_trailing_slash(self):
        """Trailing slash in URL should not affect the ID."""
        id1 = make_external_id("TestCo", "https://example.com/jobs/123")
        id2 = make_external_id("TestCo", "https://example.com/jobs/123/")
        assert id1 == id2

    def test_job_description_hash_computed(self):
        """Description hash should be computed on __post_init__."""
        job = Job(
            company="TestCo",
            external_id="123",
            title="Engineer",
            location="Berlin",
            country="Germany",
            url="https://example.com",
            description="Test description",
        )
        assert job.description_hash != ""
        assert len(job.description_hash) == 32  # MD5 hex

    def test_job_empty_description_has_hash(self):
        """Empty description should still produce a hash."""
        job = Job(
            company="TestCo",
            external_id="123",
            title="Engineer",
            location="Berlin",
            country="Germany",
            url="https://example.com",
            description="",
        )
        assert job.description_hash is not None


# ============================================================
# Eightfold scraper tests (mocked)
# ============================================================

class TestEightfoldScraper:
    @pytest.fixture
    def eightfold_company(self) -> CompanyConfig:
        return CompanyConfig(
            name="STMicroelectronics",
            country="Italy",
            careers_url="https://stmicroelectronics.eightfold.ai/careers",
            scraper="eightfold",
            company_id="stmicroelectronics",
            eightfold_domain="stmicroelectronics.com",
        )

    def test_parse_eightfold_job(self, eightfold_company):
        from src.scrapers.eightfold import _parse_eightfold_job
        raw = {
            "id": 563637173083004,
            "name": "Hardware Design Engineer",
            "posting_name": "Hardware Design Engineer",
            "location": "Agrate Brianza, Italy",
            "locations": ["Agrate Brianza, Italy"],
            "department": "R&D",
            "business_unit": "Italy Business Unit",
            "t_create": 1704067200,
            "work_location_option": "onsite",
            "canonicalPositionUrl": "https://stmicroelectronics.eightfold.ai/careers/job/563637173083004",
        }
        job = _parse_eightfold_job(raw, eightfold_company, "stmicroelectronics")
        assert job.title == "Hardware Design Engineer"
        assert job.location == "Agrate Brianza, Italy"
        assert job.external_id == "563637173083004"
        assert job.country == "Italy"  # Resolved from location string
        assert job.url == "https://stmicroelectronics.eightfold.ai/careers/job/563637173083004"
        assert job.published_at is not None

    def test_parse_eightfold_job_hybrid(self, eightfold_company):
        """Work mode hybrid should be prepended to location."""
        from src.scrapers.eightfold import _parse_eightfold_job
        raw = {
            "id": 999,
            "name": "Embedded Systems Engineer",
            "location": "Geneva, Switzerland",
            "locations": ["Geneva, Switzerland"],
            "t_create": 1704067200,
            "work_location_option": "hybrid",
            "canonicalPositionUrl": "https://stmicroelectronics.eightfold.ai/careers/job/999",
        }
        job = _parse_eightfold_job(raw, eightfold_company, "stmicroelectronics")
        assert "Hybrid" in job.location
        assert "Geneva" in job.location

    def test_tenant_extracted_from_url(self):
        from src.scrapers.eightfold import _extract_tenant_from_url
        tenant = _extract_tenant_from_url("https://stmicroelectronics.eightfold.ai/careers")
        assert tenant == "stmicroelectronics"

    def test_tenant_not_extracted_from_non_eightfold(self):
        from src.scrapers.eightfold import _extract_tenant_from_url
        tenant = _extract_tenant_from_url("https://boards.greenhouse.io/acme")
        assert tenant is None

    def test_no_company_id_returns_empty(self):
        from src.scrapers.eightfold import EightfoldScraper
        from src.config import ScrapingConfig
        scraper = EightfoldScraper(ScrapingConfig())
        company = CompanyConfig(
            name="NoCo", country="Italy",
            careers_url="https://noco.example.com/careers",  # Not eightfold URL
            scraper="eightfold",
            company_id=None,
        )
        jobs = scraper.fetch_jobs(company)
        assert jobs == []

    @patch("httpx.Client")
    def test_fetch_jobs_success(self, mock_client_class, eightfold_company):
        from src.scrapers.eightfold import EightfoldScraper
        from src.config import ScrapingConfig

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 2,
            "positions": [
                {
                    "id": 111111,
                    "name": "PCB Design Engineer",
                    "location": "Catania, Italy",
                    "locations": ["Catania, Italy"],
                    "department": "Hardware",
                    "t_create": 1704067200,
                    "work_location_option": "onsite",
                    "canonicalPositionUrl": "https://stmicroelectronics.eightfold.ai/careers/job/111111",
                },
                {
                    "id": 222222,
                    "name": "FPGA Engineer",
                    "location": "Crolles, France",
                    "locations": ["Crolles, France"],
                    "department": "R&D",
                    "t_create": 1704067201,
                    "work_location_option": "onsite",
                    "canonicalPositionUrl": "https://stmicroelectronics.eightfold.ai/careers/job/222222",
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = EightfoldScraper(ScrapingConfig())
        jobs = scraper.fetch_jobs(eightfold_company)

        assert len(jobs) == 2
        titles = [j.title for j in jobs]
        assert "PCB Design Engineer" in titles
        assert "FPGA Engineer" in titles

    @patch("httpx.Client")
    def test_fetch_jobs_403(self, mock_client_class, eightfold_company):
        """403 response should return empty list (not crash)."""
        from src.scrapers.eightfold import EightfoldScraper
        from src.config import ScrapingConfig

        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = EightfoldScraper(ScrapingConfig())
        jobs = scraper.fetch_jobs(eightfold_company)
        assert jobs == []

    def test_eightfold_in_registry(self):
        from src.scrapers.eightfold import EightfoldScraper
        ScraperClass = get_scraper("eightfold")
        assert ScraperClass is EightfoldScraper


# ============================================================
# Workable scraper tests (mocked)
# ============================================================

class TestWorkableScraper:
    @pytest.fixture
    def workable_company(self) -> CompanyConfig:
        return CompanyConfig(
            name="Cowboy",
            country="Belgium",
            careers_url="https://apply.workable.com/cowboy/",
            scraper="workable",
            company_id="cowboy",
        )

    def test_parse_workable_job(self, workable_company):
        from src.scrapers.workable import _parse_workable_job
        raw = {
            "id": 12345,
            "shortcode": "ABCDEF123",
            "title": "Embedded Engineer",
            "location": {
                "country": "Belgium",
                "city": "Brussels",
                "region": "Brussels"
            },
            "published": "2026-07-20T00:00:00.000Z",
            "department": ["Engineering"],
            "workplace": "hybrid"
        }
        job = _parse_workable_job(raw, workable_company, "cowboy")
        assert job.title == "Embedded Engineer"
        assert job.external_id == "ABCDEF123"
        assert "Brussels" in job.location
        assert "Hybrid" in job.location
        assert job.country == "Belgium"
        assert job.url == "https://apply.workable.com/cowboy/j/ABCDEF123/"
        assert job.published_at is not None

    def test_tenant_extracted_from_url(self):
        from src.scrapers.workable import _extract_tenant_from_url
        tenant = _extract_tenant_from_url("https://apply.workable.com/cowboy/")
        assert tenant == "cowboy"

    def test_tenant_not_extracted_from_non_workable(self):
        from src.scrapers.workable import _extract_tenant_from_url
        tenant = _extract_tenant_from_url("https://boards.greenhouse.io/acme")
        assert tenant is None

    @patch("httpx.Client")
    def test_fetch_jobs_success(self, mock_client_class, workable_company):
        from src.scrapers.workable import WorkableScraper
        from src.config import ScrapingConfig

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 1,
            "results": [
                {
                    "shortcode": "XYZ987",
                    "title": "Hardware Engineer",
                    "location": {"country": "Belgium", "city": "Brussels"},
                    "published": "2026-07-20T00:00:00.000Z",
                }
            ],
        }
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = WorkableScraper(ScrapingConfig())
        jobs = scraper.fetch_jobs(workable_company)

        assert len(jobs) == 1
        assert jobs[0].title == "Hardware Engineer"

    @patch("httpx.Client")
    def test_fetch_jobs_404(self, mock_client_class, workable_company):
        from src.scrapers.workable import WorkableScraper
        from src.config import ScrapingConfig

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        scraper = WorkableScraper(ScrapingConfig())
        jobs = scraper.fetch_jobs(workable_company)
        assert jobs == []

    def test_workable_in_registry(self):
        from src.scrapers.workable import WorkableScraper
        from src.scrapers.registry import get_scraper
        ScraperClass = get_scraper("workable")
        assert ScraperClass is WorkableScraper


# ============================================================
# Workday site extraction tests
# ============================================================

class TestWorkdaySiteExtraction:
    def test_extract_site_from_url_careers(self):
        from src.scrapers.workday import _extract_site_from_url
        site = _extract_site_from_url("https://nxp.wd3.myworkdayjobs.com/careers")
        assert site == "careers"

    def test_extract_site_from_url_external_site(self):
        from src.scrapers.workday import _extract_site_from_url
        site = _extract_site_from_url("https://axis.wd3.myworkdayjobs.com/External_Career_Site")
        assert site == "External_Career_Site"


# ============================================================
# Phenom scraper tests (mocked)
# ============================================================

class TestPhenomScraper:
    @pytest.fixture
    def phenom_company(self) -> CompanyConfig:
        return CompanyConfig(
            name="Schneider Electric",
            country="France",
            careers_url="https://careers.se.com/jobs",
            scraper="phenom",
        )

    def test_parse_phenom_job(self, phenom_company):
        from src.scrapers.phenom import _parse_phenom_job
        raw = {
            "data": {
                "req_id": "129617",
                "title": "Control Tower Co-op",
                "city": "Nashville",
                "country": "United States",
                "slug": "129617",
                "description": "Co-op program.",
                "posted_date": "2026-07-01T00:00:00Z",
            }
        }
        job = _parse_phenom_job(raw, phenom_company, "https://careers.se.com")
        assert job.title == "Control Tower Co-op"
        assert job.external_id == "129617"
        assert "Nashville" in job.location
        assert job.url == "https://careers.se.com/jobs/129617"

    def test_phenom_in_registry(self):
        from src.scrapers.phenom import PhenomScraper
        from src.scrapers.registry import get_scraper
        assert get_scraper("phenom") is PhenomScraper


# ============================================================
# Sitemap scraper tests (mocked)
# ============================================================

class TestSitemapScraper:
    def test_slug_to_title(self):
        from src.scrapers.sitemap import _slug_to_title
        assert _slug_to_title("embedded-software-engineer") == "Embedded Software Engineer"

    def test_sitemap_in_registry(self):
        from src.scrapers.sitemap import SitemapScraper
        from src.scrapers.registry import get_scraper
        assert get_scraper("sitemap") is SitemapScraper


class TestTelegramAddCommand:
    def test_handle_add_command_populates_company_id(self, tmp_path):
        from unittest.mock import patch
        import yaml
        from src.telegram import TelegramNotifier, TelegramConfig
        
        config = TelegramConfig(bot_token="fake:token", chat_id="12345")
        notifier = TelegramNotifier(config)
        
        test_yaml = tmp_path / "companies.yml"
        test_yaml.write_text("companies: []\n", encoding="utf-8")
        
        with patch("src.telegram.Path", return_value=test_yaml), \
             patch.object(notifier, "send_message"):
            notifier._handle_add_command("/add Exein https://job-boards.eu.greenhouse.io/exeinspa")
            
        content = yaml.safe_load(test_yaml.read_text(encoding="utf-8"))
        companies = content.get("companies", [])
        assert len(companies) == 1
        assert companies[0]["name"] == "Exein"
        assert companies[0]["scraper"] == "greenhouse"
        assert companies[0]["company_id"] == "exeinspa"


