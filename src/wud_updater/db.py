"""SQLite persistence helpers for WUD-Updater."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    """Raised when the SQLite schema cannot be initialized safely."""


def connect_db(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WUD-Updater defaults applied."""

    db_path = Path(path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create or validate the current database schema."""

    version = _user_version(conn)
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise DatabaseError(f"Unsupported database schema version: {version}")

    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS update_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT '',
                wud_file TEXT NOT NULL DEFAULT '',
                log_file TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS update_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                service_name TEXT NOT NULL,
                stack_name TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL,
                target_image TEXT NOT NULL DEFAULT '',
                old_image_id TEXT NOT NULL DEFAULT '',
                new_image_id TEXT NOT NULL DEFAULT '',
                old_digest TEXT NOT NULL DEFAULT '',
                new_digest TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS snoozes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_key TEXT NOT NULL,
                snoozed_until TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS service_policy (
                service_key TEXT PRIMARY KEY,
                update_mode TEXT NOT NULL DEFAULT '',
                auto_update INTEGER NOT NULL DEFAULT 1,
                snooze_default_seconds INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS known_images (
                service_key TEXT PRIMARY KEY,
                image TEXT NOT NULL,
                image_id TEXT NOT NULL DEFAULT '',
                digest TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_update_events_run_id
                ON update_events (run_id);
            CREATE INDEX IF NOT EXISTS idx_snoozes_service_key_until
                ON snoozes (service_key, snoozed_until);
            PRAGMA user_version = 1;
            """
        )


def insert_update_run(
    conn: sqlite3.Connection,
    *,
    started_at: str | None = None,
    status: str = "started",
    dry_run: bool = False,
    mode: str = "",
    wud_file: str = "",
    log_file: str = "",
    metadata_json: str = "{}",
) -> int:
    """Insert one updater run and return its row id."""

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO update_runs (
                started_at,
                status,
                dry_run,
                mode,
                wud_file,
                log_file,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at or utc_timestamp(),
                status,
                int(dry_run),
                mode,
                wud_file,
                log_file,
                metadata_json,
            ),
        )
    return int(cursor.lastrowid)


def insert_update_event(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    service_name: str,
    image: str,
    status: str,
    created_at: str | None = None,
    stack_name: str = "",
    target_image: str = "",
    old_image_id: str = "",
    new_image_id: str = "",
    old_digest: str = "",
    new_digest: str = "",
    metadata_json: str = "{}",
) -> int:
    """Insert one per-service update event and return its row id."""

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO update_events (
                run_id,
                created_at,
                service_name,
                stack_name,
                image,
                target_image,
                old_image_id,
                new_image_id,
                old_digest,
                new_digest,
                status,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                created_at or utc_timestamp(),
                service_name,
                stack_name,
                image,
                target_image,
                old_image_id,
                new_image_id,
                old_digest,
                new_digest,
                status,
                metadata_json,
            ),
        )
    return int(cursor.lastrowid)


def insert_snooze(
    conn: sqlite3.Connection,
    *,
    service_key: str,
    snoozed_until: str,
    reason: str = "",
    created_at: str | None = None,
    metadata_json: str = "{}",
) -> int:
    """Insert one service snooze and return its row id."""

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO snoozes (
                service_key,
                snoozed_until,
                reason,
                created_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                service_key,
                snoozed_until,
                reason,
                created_at or utc_timestamp(),
                metadata_json,
            ),
        )
    return int(cursor.lastrowid)


def active_snooze(
    conn: sqlite3.Connection,
    *,
    service_key: str,
    now: str | None = None,
) -> sqlite3.Row | None:
    """Return the latest active snooze for a service, if one exists."""

    cursor = conn.execute(
        """
        SELECT *
        FROM snoozes
        WHERE service_key = ?
          AND snoozed_until > ?
        ORDER BY snoozed_until DESC, id DESC
        LIMIT 1
        """,
        (service_key, now or utc_timestamp()),
    )
    return cursor.fetchone()


def utc_timestamp() -> str:
    """Return a stable UTC timestamp format for SQLite text comparisons."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user_version(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("PRAGMA user_version")
    row = cursor.fetchone()
    return int(row[0])
