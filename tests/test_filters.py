"""
Tests for the job filtering logic.

Tests cover:
  - Include keyword matching (TRUE cases)
  - Exclude keyword filtering (FALSE cases)
  - Geographic filtering
  - Case insensitivity
  - Edge cases (empty text, no keywords configured)
"""

import pytest

from src.config import FiltersConfig
from src.filters import JobFilter, _normalize, _contains_keyword
from src.models import Job


# ---- Helpers ----

def make_filter(
    include=None,
    exclude=None,
    countries=None,
) -> JobFilter:
    """Create a JobFilter with specified keywords."""
    config = FiltersConfig(
        include_keywords=include or [],
        exclude_keywords=exclude or [],
        allowed_countries=countries or [],
    )
    return JobFilter(config)


def make_job(
    title="",
    description="",
    location="",
    country="",
    company="TestCo",
) -> Job:
    """Create a minimal Job for testing."""
    return Job(
        company=company,
        external_id="test-id",
        title=title,
        location=location,
        country=country,
        url="https://example.com/jobs/1",
        description=description,
    )


# ---- Default filter for most tests ----
DEFAULT_INCLUDE = [
    "hardware engineer",
    "hardware design",
    "hardware designer",
    "electronics engineer",
    "electronic design",
    "embedded engineer",
    "embedded systems",
    "embedded hardware",
    "firmware engineer",
    "pcb",
    "fpga",
    "digital design",
    "analog design",
    "mixed signal",
    "power electronics",
    "electrical engineer",
]

DEFAULT_EXCLUDE = [
    "frontend developer",
    "front-end developer",
    "frontend engineer",
    "front-end engineer",
    "backend developer",
    "back-end developer",
    "backend engineer",
    "back-end engineer",
    "web developer",
    "software developer",
    "cloud engineer",
    "devops",
    "data scientist",
    "data engineer",
    "mobile developer",
]


@pytest.fixture
def default_filter() -> JobFilter:
    return make_filter(include=DEFAULT_INCLUDE, exclude=DEFAULT_EXCLUDE)


# ============================================================
# Text normalization tests
# ============================================================

class TestNormalize:
    def test_lowercase(self):
        assert _normalize("Hardware Engineer") == "hardware engineer"

    def test_strips_whitespace(self):
        assert _normalize("  hardware  engineer  ") == "hardware engineer"

    def test_removes_accents(self):
        assert _normalize("Électronique") == "electronique"

    def test_handles_empty(self):
        assert _normalize("") == ""

    def test_handles_none_like(self):
        assert _normalize("   ") == ""


# ============================================================
# Keyword matching tests
# ============================================================

class TestContainsKeyword:
    def test_simple_match(self):
        assert _contains_keyword("hardware engineer", "hardware engineer")

    def test_partial_no_match(self):
        # "pcbs" should NOT match "pcb" as a whole word
        assert not _contains_keyword("pcbs layout design", "pcb")

    def test_exact_pcb_match(self):
        # "pcb" standalone should match
        assert _contains_keyword("pcb design and layout", "pcb")

    def test_case_sensitivity(self):
        # _contains_keyword expects pre-normalized input
        assert _contains_keyword("hardware engineer", "hardware engineer")

    def test_multi_word_keyword(self):
        assert _contains_keyword("embedded systems design", "embedded systems")

    def test_not_in_text(self):
        assert not _contains_keyword("frontend developer react", "hardware engineer")


# ============================================================
# Include keyword tests — TRUE cases
# ============================================================

class TestIncludeKeywords:
    def test_hardware_design_engineer_true(self, default_filter):
        """'Hardware Design Engineer' should match → TRUE"""
        job = make_job(title="Hardware Design Engineer")
        assert default_filter.matches_include(job) is True

    def test_embedded_hardware_engineer_true(self, default_filter):
        """'Embedded Hardware Engineer' should match → TRUE"""
        job = make_job(title="Embedded Hardware Engineer")
        assert default_filter.matches_include(job) is True

    def test_fpga_design_engineer_true(self, default_filter):
        """'FPGA Design Engineer' should match → TRUE"""
        job = make_job(title="FPGA Design Engineer")
        assert default_filter.matches_include(job) is True

    def test_embedded_systems_in_description_true(self, default_filter):
        """Keyword in description should also match → TRUE"""
        job = make_job(
            title="Senior Engineer",
            description="We are looking for an expert in embedded systems and FPGA.",
        )
        assert default_filter.matches_include(job) is True

    def test_pcb_in_title_true(self, default_filter):
        """'PCB Layout Engineer' should match → TRUE"""
        job = make_job(title="PCB Layout Engineer")
        assert default_filter.matches_include(job) is True

    def test_electrical_engineer_true(self, default_filter):
        """'Electrical Engineer' should match → TRUE"""
        job = make_job(title="Electrical Engineer")
        assert default_filter.matches_include(job) is True

    def test_analog_design_true(self, default_filter):
        """'Analog Design Engineer' should match → TRUE"""
        job = make_job(title="Analog Design Engineer")
        assert default_filter.matches_include(job) is True

    def test_power_electronics_true(self, default_filter):
        """'Power Electronics Engineer' should match → TRUE"""
        job = make_job(title="Power Electronics Engineer")
        assert default_filter.matches_include(job) is True

    def test_firmware_engineer_true(self, default_filter):
        """'Firmware Engineer' should match → TRUE"""
        job = make_job(title="Firmware Engineer")
        assert default_filter.matches_include(job) is True

    def test_case_insensitive_true(self, default_filter):
        """Keyword matching should be case-insensitive"""
        job = make_job(title="HARDWARE ENGINEER")
        assert default_filter.matches_include(job) is True

    def test_mixed_case_true(self, default_filter):
        """Mixed case title should match"""
        job = make_job(title="Senior Embedded Systems Engineer")
        assert default_filter.matches_include(job) is True


# ============================================================
# Exclude keyword tests — FALSE cases
# ============================================================

class TestExcludeKeywords:
    def test_senior_backend_engineer_false(self, default_filter):
        """'Senior Backend Engineer' should be excluded → FALSE"""
        job = make_job(title="Senior Backend Engineer")
        assert default_filter.is_interesting(job) is False

    def test_frontend_developer_false(self, default_filter):
        """'Frontend Developer' should be excluded → FALSE"""
        job = make_job(title="Frontend Developer")
        assert default_filter.is_interesting(job) is False

    def test_data_scientist_false(self, default_filter):
        """'Data Scientist' should be excluded → FALSE"""
        job = make_job(title="Data Scientist")
        assert default_filter.is_interesting(job) is False

    def test_devops_engineer_false(self, default_filter):
        """'DevOps Engineer' should be excluded"""
        job = make_job(title="DevOps Engineer")
        assert default_filter.is_interesting(job) is False

    def test_mobile_developer_false(self, default_filter):
        """'Mobile Developer' should be excluded"""
        job = make_job(title="Mobile Developer iOS")
        assert default_filter.is_interesting(job) is False

    def test_exclude_overrides_include(self, default_filter):
        """
        A job with BOTH include and exclude keywords should be rejected.
        e.g. A job titled 'Hardware Design Engineer' with a description mentioning
        'backend developer' should match include (hardware design) but be rejected
        by the exclude keyword (backend developer).
        """
        job = make_job(
            title="Hardware Design Engineer",
            description="This role also requires backend developer experience.",
        )
        # matches_include is True (hardware design)
        assert default_filter.matches_include(job) is True
        # matches_exclude is True (backend developer in description)
        assert default_filter.matches_exclude(job) is True
        # is_interesting should be False (exclude wins)
        assert default_filter.is_interesting(job) is False


# ============================================================
# Geographic filter tests
# ============================================================

class TestGeoFilter:
    def test_allowed_country_passes(self):
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=["Germany", "Italy"],
        )
        job = make_job(title="Hardware Engineer", location="Berlin", country="Germany")
        assert job_filter.matches_geo(job) is True

    def test_not_allowed_country_fails(self):
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=["Germany", "Italy"],
        )
        job = make_job(title="Hardware Engineer", location="New York", country="USA")
        assert job_filter.matches_geo(job) is False

    def test_empty_countries_accepts_all(self):
        """Empty allowed_countries means accept all locations"""
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=[],
        )
        job = make_job(title="Hardware Engineer", location="Tokyo", country="Japan")
        assert job_filter.matches_geo(job) is True

    def test_no_location_passes_geo(self):
        """Job with no location info should pass geo filter"""
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=["Germany"],
        )
        job = make_job(title="Hardware Engineer", location="", country="")
        assert job_filter.matches_geo(job) is True

    def test_country_in_location_string(self):
        """Country name in location string should match"""
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=["Netherlands"],
        )
        job = make_job(
            title="Hardware Engineer",
            location="Eindhoven, Netherlands",
            country="",
        )
        assert job_filter.matches_geo(job) is True

    def test_case_insensitive_country(self):
        """Country matching should be case-insensitive"""
        job_filter = make_filter(
            include=["hardware engineer"],
            countries=["netherlands"],
        )
        job = make_job(title="Hardware Engineer", location="Eindhoven", country="NETHERLANDS")
        assert job_filter.matches_geo(job) is True


# ============================================================
# End-to-end is_interesting() tests
# ============================================================

class TestIsInteresting:
    def test_interesting_job(self, default_filter):
        """A matching job in an allowed country is interesting"""
        job = make_job(
            title="Hardware Design Engineer",
            location="Munich, Germany",
            country="Germany",
        )
        # No country restriction in default_filter
        assert default_filter.is_interesting(job) is True

    def test_excluded_job_not_interesting(self, default_filter):
        job = make_job(title="Frontend Developer", location="Berlin", country="Germany")
        assert default_filter.is_interesting(job) is False

    def test_no_match_not_interesting(self, default_filter):
        job = make_job(title="Marketing Manager", location="Paris", country="France")
        assert default_filter.is_interesting(job) is False

    def test_with_geo_restriction(self):
        job_filter = make_filter(
            include=["hardware engineer"],
            exclude=["backend"],
            countries=["Germany"],
        )
        job_de = make_job(title="Hardware Engineer", location="Berlin", country="Germany")
        job_us = make_job(title="Hardware Engineer", location="New York", country="USA")
        assert job_filter.is_interesting(job_de) is True
        assert job_filter.is_interesting(job_us) is False

    def test_no_include_keywords_rejects_all(self):
        """If include_keywords is empty, everything is rejected"""
        job_filter = make_filter(include=[], exclude=[])
        job = make_job(title="Hardware Engineer")
        assert job_filter.is_interesting(job) is False
