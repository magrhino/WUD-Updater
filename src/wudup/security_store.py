"""SQLite cache helpers for candidate security scan results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping

from .digest_verifier import ResolvedImageSubject
from .security_scanner import SecurityScanResult
from .security_subjects import PendingSecurityRequest, subject_id
from .web_models import (
    SecurityScanInfo,
    SecurityScanSeverityCounts,
    SecurityScanSubjectInfo,
)


def cached_scan_by_request(
    conn: sqlite3.Connection,
    request: PendingSecurityRequest,
) -> SecurityScanInfo | None:
    row = conn.execute(
        """
        SELECT *
        FROM security_scan_cache
        WHERE request_key = ?
        ORDER BY updated_at DESC, rowid DESC
        LIMIT 1
        """,
        (request.request_key,),
    ).fetchone()
    if row is None:
        return None
    return row_to_scan_info(row, request)


def upsert_scan_result(
    conn: sqlite3.Connection,
    request: PendingSecurityRequest,
    subject: ResolvedImageSubject,
    result: SecurityScanResult,
    *,
    timestamp: str,
) -> None:
    active_subject_id = subject_id(subject)
    cache_key = _cache_key(
        request.request_key,
        active_subject_id,
        result.scanner,
        result.scanner_version,
        result.scanner_schema,
        result.db_revision,
    )
    with conn:
        conn.execute(
            """
            DELETE FROM security_scan_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        )
        conn.execute(
            """
            INSERT INTO security_scan_cache (
                cache_key,
                request_key,
                subject_id,
                canonical_registry,
                canonical_repository,
                requested_ref,
                reported_digest,
                index_digest,
                manifest_digest,
                platform,
                platform_os,
                platform_architecture,
                platform_variant,
                platform_source,
                identity_status,
                state,
                verdict,
                scanner,
                scanner_version,
                scanner_schema,
                db_revision,
                db_updated_at,
                severity_counts_json,
                fixable_counts_json,
                unfixed_count,
                warnings_json,
                error_code,
                error_message,
                raw_json,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                request.request_key,
                active_subject_id,
                subject.canonical_registry,
                subject.canonical_repository,
                subject.requested_ref,
                subject.reported_digest,
                subject.index_digest,
                subject.manifest_digest,
                subject.platform,
                subject.os,
                subject.architecture,
                subject.variant,
                subject.platform_source,
                subject.identity_status,
                result.state,
                result.verdict,
                result.scanner,
                result.scanner_version,
                result.scanner_schema,
                result.db_revision,
                result.db_updated_at,
                json.dumps(dict(result.severity_counts), sort_keys=True),
                json.dumps(dict(result.fixable_counts), sort_keys=True),
                result.unfixed_count,
                json.dumps([*subject.warnings, *result.warnings], sort_keys=True),
                result.error_code,
                result.error_message,
                result.raw_json or "{}",
                timestamp,
                timestamp,
                json.dumps(
                    {
                        "line_no": request.line_no,
                        "scan_warnings": list(result.warnings),
                        "subject_warnings": list(subject.warnings),
                    },
                    sort_keys=True,
                ),
            ),
        )
        _prune_cache_rows(conn, request.request_key)


def row_to_scan_info(
    row: sqlite3.Row,
    request: PendingSecurityRequest,
) -> SecurityScanInfo:
    metadata = _json_object(str(row["metadata_json"]))
    subject_warnings = _metadata_string_list(metadata, "subject_warnings")
    return SecurityScanInfo(
        line_no=request.line_no,
        state=str(row["state"]),  # type: ignore[arg-type]
        verdict=str(row["verdict"]) or "unknown",  # type: ignore[arg-type]
        scanner=str(row["scanner"]),
        scanner_version=str(row["scanner_version"]),
        scanner_schema=str(row["scanner_schema"]),
        scanned_at=str(row["updated_at"]),
        db_revision=str(row["db_revision"]),
        db_updated_at=str(row["db_updated_at"]),
        severity_counts=_counts(str(row["severity_counts_json"])),
        fixable_counts=_counts(str(row["fixable_counts_json"])),
        unfixed_count=_safe_int(row["unfixed_count"]),
        warnings=_json_string_list(str(row["warnings_json"])),
        error_code=str(row["error_code"]),
        error_message=str(row["error_message"]),
        subject=SecurityScanSubjectInfo(
            subject_id=str(row["subject_id"]),
            line_no=request.line_no,
            raw=request.raw,
            image=request.image,
            candidate_image=request.candidate_image,
            canonical_registry=str(row["canonical_registry"]),
            canonical_repository=str(row["canonical_repository"]),
            requested_ref=str(row["requested_ref"]),
            reported_digest=str(row["reported_digest"]),
            index_digest=str(row["index_digest"]),
            manifest_digest=str(row["manifest_digest"]),
            platform=str(row["platform"]),
            platform_os=str(row["platform_os"]),
            platform_architecture=str(row["platform_architecture"]),
            platform_variant=str(row["platform_variant"]),
            platform_source=str(row["platform_source"]),
            identity_status=str(row["identity_status"]),
            warnings=subject_warnings,
        ),
    )


def _counts(value: str) -> SecurityScanSeverityCounts:
    parsed = _json_object(value)
    return SecurityScanSeverityCounts(
        critical=_safe_int(parsed.get("critical", 0)),
        high=_safe_int(parsed.get("high", 0)),
        medium=_safe_int(parsed.get("medium", 0)),
        low=_safe_int(parsed.get("low", 0)),
        unknown=_safe_int(parsed.get("unknown", 0)),
    )


def _json_object(value: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_string_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _metadata_string_list(metadata: Mapping[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cache_key(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _prune_cache_rows(
    conn: sqlite3.Connection,
    request_key: str,
    *,
    keep: int = 5,
) -> None:
    conn.execute(
        """
        DELETE FROM security_scan_cache
        WHERE request_key = ?
          AND rowid NOT IN (
            SELECT rowid
            FROM security_scan_cache
            WHERE request_key = ?
            ORDER BY updated_at DESC, rowid DESC
            LIMIT ?
          )
        """,
        (request_key, request_key, keep),
    )
