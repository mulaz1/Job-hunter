"""Job filtering logic for Job Hunter."""

from __future__ import annotations

import logging
import re
import unicodedata

from src.config import FiltersConfig
from src.models import Job

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    text = " ".join(text.split())
    return text


def _contains_keyword(text: str, keyword: str) -> bool:
    """Check if text contains the keyword as a whole phrase."""
    if not text or not keyword:
        return False
    escaped = re.escape(keyword)
    pattern = r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


class JobFilter:

    def __init__(self, config: FiltersConfig) -> None:
        self.include_keywords: list[str] = [_normalize(kw) for kw in config.include_keywords]
        self.exclude_keywords: list[str] = [_normalize(kw) for kw in config.exclude_keywords]
        self.allowed_countries: list[str] = [c.lower().strip() for c in config.allowed_countries]

    def _get_searchable_text(self, job: Job) -> str:
        parts = [
            job.title or "",
            job.description or "",
            job.location or "",
            job.country or "",
        ]
        combined = " ".join(parts)
        return _normalize(combined)

    def matches_include(self, job: Job) -> bool:
        if not self.include_keywords:
            logger.warning("No include_keywords configured — all jobs will be rejected")
            return False

        text = self._get_searchable_text(job)
        for keyword in self.include_keywords:
            if _contains_keyword(text, keyword):
                logger.debug("Job '%s' matched include keyword: '%s'", job.title, keyword)
                return True
        return False

    def matches_exclude(self, job: Job) -> bool:
        text = self._get_searchable_text(job)
        for keyword in self.exclude_keywords:
            if _contains_keyword(text, keyword):
                logger.debug("Job '%s' matched exclude keyword: '%s'", job.title, keyword)
                return True
        return False

    def matches_geo(self, job: Job) -> bool:
        if not self.allowed_countries:
            return True

        if not job.location and not job.country:
            logger.debug("Job '%s' has no location info — geo filter passes", job.title)
            return True

        location_text = " ".join([job.location or "", job.country or ""]).lower()

        for allowed in self.allowed_countries:
            if allowed in location_text:
                return True

        logger.debug(
            "Job '%s' location '%s' not in allowed countries",
            job.title,
            job.location,
        )
        return False

    def is_interesting(self, job: Job) -> bool:
        if not self.matches_geo(job):
            return False

        if not self.matches_include(job):
            return False

        if self.matches_exclude(job):
            return False

        return True
