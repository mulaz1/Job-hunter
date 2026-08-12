"""
Tests for the database layer.

Uses in-memory SQLite (':memory:') for fast, isolated tests.
No file system access required.

Tests cover:
  - Schema initialization
  - Job insertion
  - Duplicate detection
  - Notification state management
  - Description change detection
  - Statistics retrieval
  - Persistence behavior
"""

import pytest
from datetime import datetime

from src.database import Database
from src.models import Job


# ---- Fixtures ----

@pytest.fixture
def db() -> Database:
    """Create a fresh in-memory database for each test."""
    return Database(":memory:")


def make_job(
    company="TestCo",
    external_id="job-001",
    title="Hardware Engineer",
    location="Munich, Germany",
    country="Germany",
    url="https://example.com/jobs/1",
    description="We need an embedded hardware engineer.",
) -> Job:
    """Create a test Job with sensible defaults."""
    return Job(
        company=company,
        external_id=external_id,
        title=title,
        location=location,
        country=country,
        url=url,
        description=description,
    )


# ============================================================
# Schema initialization
# ============================================================

class TestSchemaInit:
    def test_db_initializes(self, db):
        """Database should initialize without errors."""
        assert db is not None

    def test_empty_db_stats(self, db):
        """Empty database should return zero stats."""
        stats = db.get_stats()
        assert stats["total_jobs"] == 0
        assert stats["notified_jobs"] == 0
        assert stats["companies"] == 0

    def test_in_memory_path(self):
        """In-memory database should be created successfully."""
        db = Database(":memory:")
        assert db is not None


# ============================================================
# Insert tests
# ============================================================

class TestInsert:
    def test_insert_new_job(self, db):
        """Inserting a new job should return True."""
        job = make_job()
        result = db.insert(job)
        assert result is True

    def test_insert_duplicate_returns_false(self, db):
        """Inserting the same job twice should return False the second time."""
        job = make_job()
        assert db.insert(job) is True
        assert db.insert(job) is False

    def test_insert_different_company_same_external_id(self, db):
        """Same external_id but different company should be a new job."""
        job1 = make_job(company="CompanyA", external_id="job-123")
        job2 = make_job(company="CompanyB", external_id="job-123")
        assert db.insert(job1) is True
        assert db.insert(job2) is True

    def test_insert_multiple_jobs(self, db):
        """Multiple distinct jobs should all be inserted."""
        jobs = [
            make_job(external_id=f"job-{i}", url=f"https://example.com/jobs/{i}")
            for i in range(5)
        ]
        for job in jobs:
            assert db.insert(job) is True

        stats = db.get_stats()
        assert stats["total_jobs"] == 5

    def test_insert_job_without_description(self, db):
        """Job without description should insert successfully."""
        job = make_job(description="")
        assert db.insert(job) is True

    def test_insert_job_without_published_at(self, db):
        """Job without published_at should insert successfully."""
        job = make_job()
        job.published_at = None
        assert db.insert(job) is True


# ============================================================
# Duplicate detection (is_new)
# ============================================================

class TestIsNew:
    def test_new_job_is_new(self, db):
        """A job not in the database should be new."""
        job = make_job()
        assert db.is_new(job) is True

    def test_inserted_job_not_new(self, db):
        """After insertion, the same job should not be new."""
        job = make_job()
        db.insert(job)
        assert db.is_new(job) is False

    def test_different_external_id_is_new(self, db):
        """Different external_id = different job."""
        job1 = make_job(external_id="job-001")
        job2 = make_job(external_id="job-002", url="https://example.com/jobs/2")
        db.insert(job1)
        assert db.is_new(job2) is True

    def test_same_company_different_job_is_new(self, db):
        """Same company but different job ID = new."""
        job1 = make_job(external_id="job-001", url="https://example.com/jobs/1")
        job2 = make_job(external_id="job-002", url="https://example.com/jobs/2")
        db.insert(job1)
        assert db.is_new(job2) is True


# ============================================================
# Notification state tests
# ============================================================

class TestNotificationState:
    def test_new_job_not_notified(self, db):
        """Newly inserted job should not be notified."""
        job = make_job()
        db.insert(job)
        assert db.is_notified(job) is False

    def test_mark_notified(self, db):
        """After mark_notified, is_notified should return True."""
        job = make_job()
        db.insert(job)
        db.mark_notified(job)
        assert db.is_notified(job) is True

    def test_non_existent_job_not_notified(self, db):
        """A job not in the database should return False for is_notified."""
        job = make_job()
        assert db.is_notified(job) is False

    def test_notified_count_in_stats(self, db):
        """Stats should correctly count notified jobs."""
        job1 = make_job(external_id="job-001")
        job2 = make_job(external_id="job-002", url="https://example.com/jobs/2")
        db.insert(job1)
        db.insert(job2)
        db.mark_notified(job1)

        stats = db.get_stats()
        assert stats["total_jobs"] == 2
        assert stats["notified_jobs"] == 1

    def test_reset_notification(self, db):
        """reset_notification should set notified back to 0."""
        job = make_job()
        db.insert(job)
        db.mark_notified(job)
        assert db.is_notified(job) is True

        db.reset_notification(job.company, job.external_id)
        assert db.is_notified(job) is False


# ============================================================
# Description hash / update tests
# ============================================================

class TestDescriptionHash:
    def test_description_hash_stored(self, db):
        """Description hash should be stored and retrievable."""
        job = make_job(description="Hardware engineer required.")
        db.insert(job)
        stored_hash = db.get_description_hash(job)
        assert stored_hash == job.description_hash

    def test_no_hash_for_unknown_job(self, db):
        """get_description_hash for unknown job returns None."""
        job = make_job()
        assert db.get_description_hash(job) is None

    def test_update_description(self, db):
        """update_description should change the stored hash."""
        job = make_job(description="Original description.")
        db.insert(job)
        original_hash = db.get_description_hash(job)

        # Create same job with updated description
        updated_job = make_job(description="Completely new description, different content.")
        assert updated_job.description_hash != original_hash

        db.update_description(updated_job)
        new_hash = db.get_description_hash(updated_job)
        assert new_hash == updated_job.description_hash
        assert new_hash != original_hash

    def test_same_description_same_hash(self):
        """Two jobs with the same description should have the same hash."""
        job1 = make_job(description="The exact same description text.")
        job2 = make_job(
            external_id="other-id",
            url="https://other.com/job/2",
            description="The exact same description text.",
        )
        assert job1.description_hash == job2.description_hash

    def test_different_description_different_hash(self):
        """Two jobs with different descriptions should have different hashes."""
        job1 = make_job(description="Description one.")
        job2 = make_job(
            external_id="other-id",
            url="https://other.com/job/2",
            description="Description two.",
        )
        assert job1.description_hash != job2.description_hash


# ============================================================
# Statistics tests
# ============================================================

class TestStats:
    def test_stats_after_inserts(self, db):
        for i in range(3):
            db.insert(make_job(
                company=f"Company{i}",
                external_id=f"job-{i}",
                url=f"https://example.com/{i}",
            ))
        stats = db.get_stats()
        assert stats["total_jobs"] == 3
        assert stats["companies"] == 3

    def test_latest_job_in_stats(self, db):
        job = make_job(title="FPGA Engineer")
        db.insert(job)
        stats = db.get_stats()
        assert "FPGA Engineer" in stats["latest_job"]


# ============================================================
# Pending notifications tests
# ============================================================

class TestPendingNotifications:
    def test_pending_notifications_empty(self, db):
        """No pending notifications when db is empty."""
        assert db.get_pending_notifications() == []

    def test_unnotified_jobs_are_pending(self, db):
        """Inserted but unnotified jobs appear in pending."""
        job = make_job()
        db.insert(job)
        pending = db.get_pending_notifications()
        assert len(pending) == 1
        assert pending[0]["title"] == "Hardware Engineer"

    def test_notified_jobs_not_pending(self, db):
        """Notified jobs should not appear in pending."""
        job = make_job()
        db.insert(job)
        db.mark_notified(job)
        pending = db.get_pending_notifications()
        assert len(pending) == 0
