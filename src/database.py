"""SQLite database layer for Job Hunter."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from src.models import Job

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company          TEXT    NOT NULL,
    external_id      TEXT    NOT NULL,
    title            TEXT    NOT NULL,
    location         TEXT    NOT NULL DEFAULT '',
    country          TEXT    NOT NULL DEFAULT '',
    url              TEXT    NOT NULL,
    description      TEXT    NOT NULL DEFAULT '',
    description_hash TEXT    NOT NULL DEFAULT '',
    published_at     TEXT,
    first_seen_at    TEXT    NOT NULL,
    notified         INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT,
    UNIQUE(company, external_id)
);
"""

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""

CREATE_INDEX_NOTIFIED = """
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified);
"""

CREATE_INDEX_COMPANY = """
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
"""


class Database:
    """SQLite database wrapper for Job Hunter."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: sqlite3.Connection | None = None

        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row

        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        if self._in_memory:
            # Use the persistent in-memory connection
            conn = self._persistent_conn
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(CREATE_SCHEMA_VERSION_TABLE)
            conn.execute(CREATE_JOBS_TABLE)
            conn.execute(CREATE_INDEX_NOTIFIED)
            conn.execute(CREATE_INDEX_COMPANY)
            logger.debug("Database schema initialized at %s", self.db_path)

    def is_new(self, job: Job) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM jobs WHERE company = ? AND external_id = ?",
                (job.company, job.external_id),
            )
            return cursor.fetchone() is None

    def insert(self, job: Job) -> bool:
        now = datetime.utcnow().isoformat()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs
                        (company, external_id, title, location, country, url,
                         description, description_hash, published_at, first_seen_at,
                         notified, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        job.company,
                        job.external_id,
                        job.title,
                        job.location or "",
                        job.country or "",
                        job.url,
                        job.description or "",
                        job.description_hash,
                        job.published_at.isoformat() if job.published_at else None,
                        job.first_seen_at.isoformat() if job.first_seen_at else now,
                        now,
                    ),
                )
                inserted = cursor.rowcount > 0
                if inserted:
                    logger.debug("Inserted new job: %s", job.short_repr())
                return inserted
        except sqlite3.Error as e:
            logger.error("Failed to insert job %s: %s", job.short_repr(), e)
            return False

    def is_notified(self, job: Job) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT notified FROM jobs WHERE company = ? AND external_id = ?",
                (job.company, job.external_id),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            return bool(row["notified"])

    def mark_notified(self, job: Job) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET notified = 1, updated_at = ?
                WHERE company = ? AND external_id = ?
                """,
                (now, job.company, job.external_id),
            )
            logger.debug("Marked as notified: %s", job.short_repr())

    def get_description_hash(self, job: Job) -> Optional[str]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT description_hash FROM jobs WHERE company = ? AND external_id = ?",
                (job.company, job.external_id),
            )
            row = cursor.fetchone()
            return row["description_hash"] if row else None

    def update_description(self, job: Job) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET description = ?, description_hash = ?, updated_at = ?
                WHERE company = ? AND external_id = ?
                """,
                (
                    job.description or "",
                    job.description_hash,
                    now,
                    job.company,
                    job.external_id,
                ),
            )
            logger.debug("Updated description for: %s", job.short_repr())

    def reset_notification(self, company: str, external_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET notified = 0 WHERE company = ? AND external_id = ?",
                (company, external_id),
            )

    def get_stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            notified = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE notified = 1"
            ).fetchone()[0]
            companies = conn.execute(
                "SELECT COUNT(DISTINCT company) FROM jobs"
            ).fetchone()[0]
            latest_row = conn.execute(
                "SELECT company, title, first_seen_at FROM jobs ORDER BY first_seen_at DESC LIMIT 1"
            ).fetchone()
            latest = (
                f"{latest_row['company']} — {latest_row['title']} ({latest_row['first_seen_at']})"
                if latest_row
                else "N/A"
            )
        return {
            "total_jobs": total,
            "notified_jobs": notified,
            "companies": companies,
            "latest_job": latest,
        }

    def get_pending_notifications(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT company, external_id, title, location, country, url
                FROM jobs
                WHERE notified = 0
                ORDER BY first_seen_at DESC
                LIMIT 100
                """
            ).fetchall()
            return [dict(row) for row in rows]
