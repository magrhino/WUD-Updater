"""Shared read-only WebUI database helpers."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .db import (
    DatabaseError,
    SCHEMA_VERSION,
)
from .db import _user_version as db_user_version
from .db import _validate_schema as validate_db_schema
from .digest_provenance import DigestTagProvenance, digest_provenance_from_row
from .web_models import WebSettings


class ReadOnlyDatabaseMissing(RuntimeError):
    """Raised when the read-only WebUI database does not exist."""


@dataclass(frozen=True)
class KnownDigestState:
    image: str
    digest_provenance: DigestTagProvenance


LOGGER = logging.getLogger(__name__)


def database_ready(settings: WebSettings) -> tuple[bool, str]:
    try:
        with closing(connect_readonly_db(settings)):
            pass
        return True, ""
    except ReadOnlyDatabaseMissing as exc:
        return False, str(exc)
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        return False, f"database is not ready: {exc}"


def connect_readonly_db(settings: WebSettings) -> sqlite3.Connection:
    path = settings.config.db_path
    if str(path) == ":memory:" or not path.is_file():
        raise ReadOnlyDatabaseMissing(f"database file does not exist: {path}")
    conn = sqlite3.connect(_readonly_sqlite_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        _validate_readonly_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def known_digest_provenance_by_service(
    settings: WebSettings,
) -> dict[str, DigestTagProvenance]:
    try:
        with closing(connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT
                    service_key,
                    digest_source_image,
                    digest_resolved_tag,
                    digest_watch_tag,
                    digest_target_digest,
                    digest_final_image,
                    digest_provenance_source,
                    digest_provenance_confidence
                FROM known_images
                WHERE digest_final_image != ''
                   OR digest_resolved_tag != ''
                   OR digest_watch_tag != ''
                """
            ).fetchall()
    except ReadOnlyDatabaseMissing:
        return {}
    except Exception as exc:
        LOGGER.warning("failed to read digest provenance from database: %s", exc)
        return {}
    result: dict[str, DigestTagProvenance] = {}
    for row in rows:
        provenance = digest_provenance_from_row(row)
        if provenance is None:
            continue
        result[str(row["service_key"])] = provenance
    return result


def known_digest_state_by_service(
    settings: WebSettings,
) -> dict[str, KnownDigestState]:
    try:
        with closing(connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT
                    service_key,
                    image,
                    digest_source_image,
                    digest_resolved_tag,
                    digest_watch_tag,
                    digest_target_digest,
                    digest_final_image,
                    digest_provenance_source,
                    digest_provenance_confidence
                FROM known_images
                WHERE digest_final_image != ''
                   OR digest_resolved_tag != ''
                   OR digest_watch_tag != ''
                """
            ).fetchall()
    except ReadOnlyDatabaseMissing:
        return {}
    except Exception as exc:
        LOGGER.warning("failed to read digest state from database: %s", exc)
        return {}
    result: dict[str, KnownDigestState] = {}
    for row in rows:
        provenance = digest_provenance_from_row(row)
        if provenance is None:
            continue
        result[str(row["service_key"])] = KnownDigestState(
            image=str(row["image"]),
            digest_provenance=provenance,
        )
    return result


def _readonly_sqlite_uri(path: Path) -> str:
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def _validate_readonly_schema(conn: sqlite3.Connection) -> None:
    version = db_user_version(conn)
    if version == 0:
        raise DatabaseError("database schema is not initialized")
    if version != SCHEMA_VERSION:
        raise DatabaseError(
            f"database schema version {version} requires migration to {SCHEMA_VERSION}"
        )
    validate_db_schema(conn)
