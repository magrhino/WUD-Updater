"""Release-note notification identity and history helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .db import utc_timestamp
from .web_metadata import json_object, json_object_or_empty


@dataclass(frozen=True)
class ReleaseNotificationConfig:
    mode: str = "digest"
    resend_policy: str = "remote_change"
    cooldown_seconds: int = 86_400


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


def notification_identity(
    target: Any,
    note: Any,
    metadata: Any | None = None,
) -> NotificationIdentity:
    payload = {
        "service_key": _value(target, "key"),
        "image": _value(target, "first"),
        "image_repo": _value(note, "image_repo") or _value(target, "repo"),
        "local_value": _value(target, "tag_token"),
        "remote_value": (
            _value(note, "release_tag")
            or _value(target, "desired_tag")
            or _value(target, "digest")
        ),
        "digest": _value(target, "digest"),
        "release_link": _first_link_url(note),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return NotificationIdentity(
        notification_key=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        metadata=payload,
    )


def notification_history_by_key(
    conn: sqlite3.Connection,
    keys: set[str],
) -> dict[str, NotificationHistory]:
    if not keys:
        return {}
    placeholders = ", ".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        SELECT *
        FROM release_notification_history
        WHERE notification_key IN ({placeholders})
        """,
        tuple(keys),
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
    if history.status != "sent":
        return history.status or "new", ""
    if resend:
        return "manual_resend", ""
    if config.resend_policy == "cooldown":
        if _cooldown_elapsed(history.last_sent_at, config.cooldown_seconds, now):
            return "cooldown_ready", ""
        return "skipped_cooldown", "Notification cooldown has not elapsed."
    return "skipped_duplicate", "Already sent for this update."


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


def _value(source: Any, name: str) -> str:
    if source is None:
        return ""
    value = getattr(source, name, "")
    return value if isinstance(value, str) else ""
