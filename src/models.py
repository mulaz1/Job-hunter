"""Data models for Job Hunter."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def normalize_text(text: str) -> str:
    """Normalize text for hashing and comparison."""
    if not text:
        return ""
    # Normalize unicode (decompose accents)
    text = unicodedata.normalize("NFD", text)
    # Remove combining characters (accents)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Lowercase and collapse whitespace
    text = " ".join(text.lower().split())
    return text


def compute_description_hash(description: str) -> str:
    """Compute a stable MD5 hash of the normalized description."""
    normalized = normalize_text(description)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def make_external_id(company: str, url: str) -> str:
    """Create a deterministic external ID from company name + URL."""
    normalized_company = normalize_text(company)
    # Strip URL fragments and query params for stability
    clean_url = url.split("#")[0].rstrip("/")
    raw = f"{normalized_company}::{clean_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Job:
    """Represents a single job posting."""

    company: str
    external_id: str
    title: str
    location: str
    country: str
    url: str
    description: str = ""
    published_at: Optional[datetime] = None
    first_seen_at: datetime = field(default_factory=datetime.utcnow)
    description_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.description_hash = compute_description_hash(self.description)

    def short_repr(self) -> str:
        loc = self.location or "Unknown location"
        return f"{self.title} @ {self.company} ({loc})"


@dataclass
class CompanyConfig:
    """Configuration for a single company to monitor."""

    name: str
    careers_url: str
    scraper: str
    country: Optional[str] = None
    company_id: Optional[str] = None
    workday_tenant: Optional[str] = None
    workday_instance: Optional[str] = None
    eightfold_domain: Optional[str] = None


@dataclass
class ScanStats:
    """Statistics for a single scan run."""

    companies_checked: int = 0
    companies_failed: int = 0
    jobs_found: int = 0
    jobs_new: int = 0
    jobs_matching: int = 0
    jobs_notified: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def summary(self) -> str:
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        lines = [
            f"Scan completed in {elapsed:.1f}s",
            f"  Companies checked : {self.companies_checked}",
            f"  Companies failed  : {self.companies_failed}",
            f"  Jobs found        : {self.jobs_found}",
            f"  New jobs          : {self.jobs_new}",
            f"  Matching jobs     : {self.jobs_matching}",
            f"  Telegram sent     : {self.jobs_notified}",
        ]
        if self.errors:
            lines.append(f"  Errors            : {len(self.errors)}")
        return "\n".join(lines)
