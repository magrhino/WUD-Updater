"""SQLite persistence helpers for WUD-Updater."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 2

ColumnSchema = tuple[str, str, int, str | None, int]

EXPECTED_SCHEMA: dict[str, tuple[ColumnSchema, ...]] = {
    "update_runs": (
        ("id", "INTEGER", 0, None, 1),
        ("started_at", "TEXT", 1, None, 0),
        ("finished_at", "TEXT", 0, None, 0),
        ("status", "TEXT", 1, None, 0),
        ("dry_run", "INTEGER", 1, "0", 0),
        ("mode", "TEXT", 1, "''", 0),
        ("wud_file", "TEXT", 1, "''", 0),
        ("log_file", "TEXT", 1, "''", 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
    "update_events": (
        ("id", "INTEGER", 0, None, 1),
        ("run_id", "INTEGER", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("service_name", "TEXT", 1, None, 0),
        ("stack_name", "TEXT", 1, "''", 0),
        ("image", "TEXT", 1, None, 0),
        ("target_image", "TEXT", 1, "''", 0),
        ("old_image_id", "TEXT", 1, "''", 0),
        ("new_image_id", "TEXT", 1, "''", 0),
        ("old_digest", "TEXT", 1, "''", 0),
        ("new_digest", "TEXT", 1, "''", 0),
        ("status", "TEXT", 1, None, 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
    "snoozes": (
        ("id", "INTEGER", 0, None, 1),
        ("service_key", "TEXT", 1, None, 0),
        ("snoozed_until", "TEXT", 1, None, 0),
        ("reason", "TEXT", 1, "''", 0),
        ("created_at", "TEXT", 1, None, 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
    "service_policy": (
        ("service_key", "TEXT", 0, None, 1),
        ("update_mode", "TEXT", 1, "''", 0),
        ("auto_update", "INTEGER", 1, "1", 0),
        ("snooze_default_seconds", "INTEGER", 0, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("updated_at", "TEXT", 1, None, 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
    "known_images": (
        ("service_key", "TEXT", 0, None, 1),
        ("image", "TEXT", 1, None, 0),
        ("image_id", "TEXT", 1, "''", 0),
        ("digest", "TEXT", 1, "''", 0),
        ("updated_at", "TEXT", 1, None, 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
    "pending_updates": (
        ("id", "INTEGER", 0, None, 1),
        ("run_id", "INTEGER", 1, None, 0),
        ("line_no", "INTEGER", 1, None, 0),
        ("raw", "TEXT", 1, None, 0),
        ("image", "TEXT", 1, None, 0),
        ("target_digest", "TEXT", 1, "''", 0),
        ("desired_tag", "TEXT", 1, "''", 0),
        ("service_key", "TEXT", 1, "''", 0),
        ("stack_name", "TEXT", 1, "''", 0),
        ("service_name", "TEXT", 1, "''", 0),
        ("status", "TEXT", 1, None, 0),
        ("status_reason", "TEXT", 1, "''", 0),
        ("created_at", "TEXT", 1, None, 0),
        ("updated_at", "TEXT", 1, None, 0),
        ("metadata_json", "TEXT", 1, "'{}'", 0),
    ),
}

EXPECTED_SCHEMA_V1 = {
    name: columns
    for name, columns in EXPECTED_SCHEMA.items()
    if name != "pending_updates"
}


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
        _validate_schema(conn)
        return
    if version == 1:
        _validate_schema(conn, expected_schema=EXPECTED_SCHEMA_V1)
        _migrate_v1_to_v2(conn)
        _validate_schema(conn)
        return
    if version != 0:
        raise DatabaseError(f"Unsupported database schema version: {version}")

    _validate_existing_schema_objects(conn)
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

            CREATE TABLE IF NOT EXISTS pending_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                raw TEXT NOT NULL,
                image TEXT NOT NULL,
                target_digest TEXT NOT NULL DEFAULT '',
                desired_tag TEXT NOT NULL DEFAULT '',
                service_key TEXT NOT NULL DEFAULT '',
                stack_name TEXT NOT NULL DEFAULT '',
                service_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                status_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (run_id, line_no),
                FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_update_events_run_id
                ON update_events (run_id);
            CREATE INDEX IF NOT EXISTS idx_snoozes_service_key_until
                ON snoozes (service_key, snoozed_until);
            CREATE INDEX IF NOT EXISTS idx_pending_updates_run_id
                ON pending_updates (run_id);
            CREATE INDEX IF NOT EXISTS idx_pending_updates_status
                ON pending_updates (status);
            CREATE INDEX IF NOT EXISTS idx_pending_updates_service_key_status
                ON pending_updates (service_key, status);
            """
        )
        _validate_schema(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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


def insert_pending_update(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    line_no: int,
    raw: str,
    image: str,
    target_digest: str = "",
    desired_tag: str = "",
    service_key: str = "",
    stack_name: str = "",
    service_name: str = "",
    status: str = "pending",
    status_reason: str = "",
    created_at: str | None = None,
    updated_at: str | None = None,
    metadata_json: str = "{}",
) -> int:
    """Insert one parsed WUD target as explicit pending/update state."""

    now = utc_timestamp()
    created = created_at or now
    updated = updated_at or created
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO pending_updates (
                run_id,
                line_no,
                raw,
                image,
                target_digest,
                desired_tag,
                service_key,
                stack_name,
                service_name,
                status,
                status_reason,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                line_no,
                raw,
                image,
                target_digest,
                desired_tag,
                service_key,
                stack_name,
                service_name,
                status,
                status_reason,
                created,
                updated,
                metadata_json,
            ),
        )
    return int(cursor.lastrowid)


def update_pending_update(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    line_no: int,
    status: str,
    status_reason: str = "",
    service_key: str | None = None,
    stack_name: str | None = None,
    service_name: str | None = None,
    updated_at: str | None = None,
) -> None:
    """Update explicit pending state for one parsed WUD target."""

    assignments = ["status = ?", "status_reason = ?", "updated_at = ?"]
    values: list[object] = [status, status_reason, updated_at or utc_timestamp()]
    if service_key is not None:
        assignments.append("service_key = ?")
        values.append(service_key)
    if stack_name is not None:
        assignments.append("stack_name = ?")
        values.append(stack_name)
    if service_name is not None:
        assignments.append("service_name = ?")
        values.append(service_name)
    values.extend([run_id, line_no])
    with conn:
        conn.execute(
            f"""
            UPDATE pending_updates
            SET {", ".join(assignments)}
            WHERE run_id = ?
              AND line_no = ?
            """,
            values,
        )


def upsert_known_image(
    conn: sqlite3.Connection,
    *,
    service_key: str,
    image: str,
    image_id: str = "",
    digest: str = "",
    updated_at: str | None = None,
    metadata_json: str = "{}",
) -> None:
    """Record the latest known image state for a service key."""

    updated = updated_at or utc_timestamp()
    with conn:
        conn.execute(
            """
            INSERT INTO known_images (
                service_key,
                image,
                image_id,
                digest,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_key) DO UPDATE SET
                image = excluded.image,
                image_id = excluded.image_id,
                digest = excluded.digest,
                updated_at = excluded.updated_at,
                metadata_json = excluded.metadata_json
            """,
            (service_key, image, image_id, digest, updated, metadata_json),
        )


def utc_timestamp() -> str:
    """Return a stable UTC timestamp format for SQLite text comparisons."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user_version(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("PRAGMA user_version")
    row = cursor.fetchone()
    return int(row[0])


def _validate_existing_schema_objects(conn: sqlite3.Connection) -> None:
    for table_name, expected_columns in EXPECTED_SCHEMA.items():
        object_type = _sqlite_object_type(conn, table_name)
        if object_type is None:
            continue
        if object_type != "table":
            raise DatabaseError(
                f"Expected {table_name} to be a table, found {object_type}"
            )
        _validate_table_columns(conn, table_name, expected_columns)


def _validate_schema(
    conn: sqlite3.Connection,
    *,
    expected_schema: dict[str, tuple[ColumnSchema, ...]] | None = None,
) -> None:
    schema = expected_schema or EXPECTED_SCHEMA
    for table_name, expected_columns in schema.items():
        object_type = _sqlite_object_type(conn, table_name)
        if object_type is None:
            raise DatabaseError(f"Missing expected table: {table_name}")
        if object_type != "table":
            raise DatabaseError(
                f"Expected {table_name} to be a table, found {object_type}"
            )
        _validate_table_columns(conn, table_name, expected_columns)


def _validate_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: tuple[ColumnSchema, ...],
) -> None:
    actual_columns = _table_columns(conn, table_name)
    actual_names = tuple(column[0] for column in actual_columns)
    expected_names = tuple(column[0] for column in expected_columns)
    if actual_names != expected_names:
        raise DatabaseError(
            f"Unexpected columns for table {table_name}: "
            f"expected {_format_column_names(expected_names)}, "
            f"found {_format_column_names(actual_names)}"
        )
    if actual_columns != expected_columns:
        raise DatabaseError(f"Unexpected column definition for table {table_name}")


def _table_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> tuple[ColumnSchema, ...]:
    cursor = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")
    return tuple(
        (
            str(row[1]),
            str(row[2]).upper(),
            int(row[3]),
            None if row[4] is None else str(row[4]),
            int(row[5]),
        )
        for row in cursor.fetchall()
    )


def _sqlite_object_type(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        """
        SELECT type
        FROM sqlite_master
        WHERE name = ?
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _format_column_names(names: tuple[str, ...]) -> str:
    if not names:
        return "<none>"
    return ", ".join(names)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    object_type = _sqlite_object_type(conn, "pending_updates")
    if object_type is not None:
        if object_type != "table":
            raise DatabaseError(
                f"Expected pending_updates to be a table, found {object_type}"
            )
        _validate_table_columns(conn, "pending_updates", EXPECTED_SCHEMA["pending_updates"])
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pending_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                raw TEXT NOT NULL,
                image TEXT NOT NULL,
                target_digest TEXT NOT NULL DEFAULT '',
                desired_tag TEXT NOT NULL DEFAULT '',
                service_key TEXT NOT NULL DEFAULT '',
                stack_name TEXT NOT NULL DEFAULT '',
                service_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                status_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (run_id, line_no),
                FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_pending_updates_run_id
                ON pending_updates (run_id);
            CREATE INDEX IF NOT EXISTS idx_pending_updates_status
                ON pending_updates (status);
            CREATE INDEX IF NOT EXISTS idx_pending_updates_service_key_status
                ON pending_updates (service_key, status);
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
