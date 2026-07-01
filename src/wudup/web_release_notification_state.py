"""Release-note notification identity and history helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .db import utc_timestamp
from .web_metadata import json_object, json_object_or_empty

SENDING_RESERVATION_TTL_SECONDS = 600
ALREADY_SENT_FOR_UPDATE_REASON = "Already sent for this update."


@dataclass(frozen=True)
class ReleaseNotificationConfig:
    mode: str = "digest"
    resend_policy: str = "remote_change"
    cooldown_seconds: int = 86_400
    verbosity: str = "summary"


@dataclass(frozen=True)
class NotificationIdentity:
    notification_key: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class NotificationHistory:
    notification_key: str
    mode: str
    status: str
    last_attempted_at: str
    last_sent_at: str
    send_count: int
    last_audit_run_id: int
    metadata: dict[str, object]


@dataclass(frozen=True)
class NotificationAnnotation:
    notification_key: str
    status: str
    last_sent_at: str
    send_count: int
    skipped_reason: str


def notification_identity(
    target: Any,
    note: Any,
    metadata: Any | None = None,
) -> NotificationIdentity:
    metadata_payload = _metadata_payload(metadata)
    remote_value = (
        _value(note, "release_tag")
        or _value(target, "desired_tag")
        or _value(target, "digest")
        or _metadata_remote_value(metadata_payload)
    )
    payload: dict[str, object] = {
        "service_key": _value(target, "key"),
        "image": _value(target, "first"),
        "image_repo": _value(note, "image_repo") or _value(target, "repo"),
        "local_value": _value(target, "tag_token"),
        "remote_value": remote_value,
        "digest": _value(target, "digest"),
        "release_link": _first_link_url(note),
    }
    stored_payload = dict(payload)
    if metadata_payload:
        stored_payload["metadata"] = metadata_payload
    hash_payload = dict(payload)
    metadata_hash_payload = _metadata_hash_payload(metadata)
    if metadata_hash_payload:
        hash_payload["metadata"] = metadata_hash_payload
    canonical = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
    return NotificationIdentity(
        notification_key=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        metadata=stored_payload,
    )


def notification_history_by_key(
    conn: sqlite3.Connection,
    keys: set[str],
) -> dict[str, NotificationHistory]:
    if not keys:
        return {}
    rows = conn.execute(
        """
        SELECT release_notification_history.*
        FROM release_notification_history
        JOIN json_each(?) AS wanted
            ON release_notification_history.notification_key = wanted.value
        """,
        (json.dumps(sorted(keys)),),
    ).fetchall()
    return {
        str(row["notification_key"]): NotificationHistory(
            notification_key=str(row["notification_key"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
            last_attempted_at=str(row["last_attempted_at"]),
            last_sent_at=str(row["last_sent_at"]),
            send_count=int(row["send_count"]),
            last_audit_run_id=int(row["last_audit_run_id"]),
            metadata=json_object_or_empty(row["metadata_json"]),
        )
        for row in rows
    }


def notification_annotations(
    conn: sqlite3.Connection,
    config: ReleaseNotificationConfig,
    identities: Mapping[int, NotificationIdentity],
    *,
    resend: bool,
) -> dict[int, NotificationAnnotation]:
    histories = notification_history_by_key(
        conn,
        {identity.notification_key for identity in identities.values()},
    )
    return notification_annotations_from_history(
        config,
        identities,
        histories,
        resend=resend,
    )


def notification_annotations_from_history(
    config: ReleaseNotificationConfig,
    identities: Mapping[int, NotificationIdentity],
    histories: Mapping[str, NotificationHistory],
    *,
    resend: bool,
) -> dict[int, NotificationAnnotation]:
    annotations: dict[int, NotificationAnnotation] = {}
    for line_no, identity in identities.items():
        history = histories.get(identity.notification_key)
        status, skipped_reason = notification_decision(
            config,
            identity,
            history,
            resend=resend,
        )
        annotations[line_no] = NotificationAnnotation(
            notification_key=identity.notification_key,
            status=status,
            last_sent_at="" if history is None else history.last_sent_at,
            send_count=0 if history is None else history.send_count,
            skipped_reason=skipped_reason,
        )
    return annotations


def notification_decision(
    config: ReleaseNotificationConfig,
    identity: NotificationIdentity,
    history: NotificationHistory | None,
    *,
    resend: bool,
    now: str | None = None,
) -> tuple[str, str]:
    if history is None:
        return "new", ""
    if history.status == "sending":
        if _sending_reservation_stale(history.last_attempted_at, now):
            if resend:
                return "manual_resend", ""
            if history.send_count > 0:
                return "skipped_duplicate", ALREADY_SENT_FOR_UPDATE_REASON
            return "new", ""
        return "sending", "Notification is already being sent."
    if history.status != "sent":
        if resend:
            return "manual_resend", ""
        if history.send_count > 0:
            return "skipped_duplicate", ALREADY_SENT_FOR_UPDATE_REASON
        return history.status or "new", ""
    if resend:
        return "manual_resend", ""
    if config.resend_policy == "cooldown":
        if _cooldown_elapsed(history.last_sent_at, config.cooldown_seconds, now):
            return "cooldown_ready", ""
        return "skipped_cooldown", "Notification cooldown has not elapsed."
    return "skipped_duplicate", ALREADY_SENT_FOR_UPDATE_REASON


def upsert_notification_history(
    conn: sqlite3.Connection,
    *,
    identity: NotificationIdentity,
    config: ReleaseNotificationConfig,
    status: str,
    audit_run_id: int,
    now: str | None = None,
) -> None:
    timestamp = now or utc_timestamp()
    sent_at = timestamp if status == "sent" else ""
    send_count_increment = 1 if status == "sent" else 0
    conn.execute(
        """
        INSERT INTO release_notification_history (
            notification_key,
            mode,
            status,
            last_attempted_at,
            last_sent_at,
            send_count,
            last_audit_run_id,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(notification_key) DO UPDATE SET
            mode = excluded.mode,
            status = excluded.status,
            last_attempted_at = excluded.last_attempted_at,
            last_sent_at = CASE
                WHEN excluded.last_sent_at != '' THEN excluded.last_sent_at
                ELSE release_notification_history.last_sent_at
            END,
            send_count = release_notification_history.send_count + ?,
            last_audit_run_id = excluded.last_audit_run_id,
            metadata_json = excluded.metadata_json
        """,
        (
            identity.notification_key,
            config.mode,
            status,
            timestamp,
            sent_at,
            send_count_increment,
            audit_run_id,
            json_object(identity.metadata),
            send_count_increment,
        ),
    )


def reserve_notification_history(
    conn: sqlite3.Connection,
    *,
    identity: NotificationIdentity,
    config: ReleaseNotificationConfig,
    audit_run_id: int,
    allow_existing: bool = False,
    now: str | None = None,
) -> bool:
    timestamp = now or utc_timestamp()
    stale_before = _timestamp_before(timestamp, SENDING_RESERVATION_TTL_SECONDS)
    metadata_json = json_object(identity.metadata)
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO release_notification_history (
            notification_key,
            mode,
            status,
            last_attempted_at,
            last_sent_at,
            send_count,
            last_audit_run_id,
            metadata_json
        )
        VALUES (?, ?, 'sending', ?, '', 0, ?, ?)
        """,
        (
            identity.notification_key,
            config.mode,
            timestamp,
            audit_run_id,
            metadata_json,
        ),
    )
    if cursor.rowcount:
        return True
    cursor = conn.execute(
        """
        UPDATE release_notification_history
        SET mode = ?,
            status = 'sending',
            last_attempted_at = ?,
            last_audit_run_id = ?,
            metadata_json = ?
        WHERE notification_key = ?
          AND (status != 'sending' OR last_attempted_at <= ?)
          AND (send_count = 0 OR ?)
        """,
        (
            config.mode,
            timestamp,
            audit_run_id,
            metadata_json,
            identity.notification_key,
            stale_before,
            int(allow_existing),
        ),
    )
    return bool(cursor.rowcount)


def _sending_reservation_stale(last_attempted_at: str, now: str | None) -> bool:
    try:
        attempted_at = datetime.fromisoformat(last_attempted_at)
        current = datetime.fromisoformat(now or utc_timestamp())
    except ValueError:
        return True
    return current >= attempted_at + timedelta(seconds=SENDING_RESERVATION_TTL_SECONDS)


def _timestamp_before(timestamp: str, seconds: int) -> str:
    return (datetime.fromisoformat(timestamp) - timedelta(seconds=seconds)).isoformat()


def _cooldown_elapsed(
    last_sent_at: str,
    cooldown_seconds: int,
    now: str | None,
) -> bool:
    try:
        sent_at = datetime.fromisoformat(last_sent_at)
        current = datetime.fromisoformat(now or utc_timestamp())
    except ValueError:
        return True
    return current >= sent_at + timedelta(seconds=cooldown_seconds)


def _first_link_url(note: Any) -> str:
    for link in getattr(note, "links", []) or []:
        value = _value(link, "url")
        if value:
            return value
    return ""


def _metadata_payload(metadata: Any | None) -> dict[str, object]:
    if metadata is None:
        return {}
    if isinstance(metadata, Mapping):
        return _json_mapping(metadata)

    payload: dict[str, object] = {}
    for name in ("local_digest", "remote_tag", "remote_digest", "link"):
        value = _value(metadata, name)
        if value:
            payload[name] = value
    labels = getattr(metadata, "labels", None)
    if isinstance(labels, Mapping):
        source_label = labels.get("org.opencontainers.image.source")
        if isinstance(source_label, str) and source_label:
            payload["source_label"] = source_label
    return payload


def _metadata_hash_payload(metadata: Any | None) -> dict[str, object]:
    # Keep WUD enrichment optional: line previews and run previews must de-dupe
    # even when WUD metadata is unavailable in one path.
    if isinstance(metadata, Mapping):
        return _json_mapping(metadata)
    return {}


def _json_mapping(metadata: Mapping[Any, Any]) -> dict[str, object]:
    value = json.loads(
        json.dumps(
            {str(key): item for key, item in metadata.items()},
            sort_keys=True,
            default=str,
        )
    )
    return value if isinstance(value, dict) else {}


def _metadata_value(metadata: Mapping[str, object], name: str) -> str:
    value = metadata.get(name, "")
    return value if isinstance(value, str) else ""


def _metadata_remote_value(metadata: Mapping[str, object]) -> str:
    remote_tag = _metadata_value(metadata, "remote_tag")
    remote_digest = _metadata_value(metadata, "remote_digest")
    if remote_tag and remote_digest:
        return f"{remote_tag}@{remote_digest}"
    return remote_tag or remote_digest


def _value(source: Any, name: str) -> str:
    if source is None:
        return ""
    value = getattr(source, name, "")
    return value if isinstance(value, str) else ""
