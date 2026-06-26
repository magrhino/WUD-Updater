"""WebUI Discord release-note notification route handlers."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import web_pending_sources, web_wud_api
from .db import DatabaseError, init_db, open_db, utc_timestamp
from .release_notes import refresh_release_notes
from .web_auth import (
    _redact_sensitive_text,
    _request_actor_type,
    _safe_exception_detail,
    _settings,
)
from .web_database import ReadOnlyDatabaseMissing, connect_readonly_db
from .web_metadata import json_object
from .web_models import (
    PendingSourceInfo,
    ReleaseNoteInfo,
    ReleaseNoteLink,
    ReleaseNotificationDestination,
    ReleaseNotificationItem,
    ReleaseNotificationPreviewRequest,
    ReleaseNotificationResponse,
    ReleaseNotificationSendRequest,
    ReleaseNotificationTrigger,
    WebSettings,
    WudApiStatus,
)
from .web_release_notes import release_note_source_resolver
from .web_settings import effective_release_notes_enabled
from .wud_file import WudTarget, parse_wud_text

DISCORD_EMBEDS_PER_MESSAGE = 10
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_WEBHOOK_TIMEOUT_SECONDS = 10.0
DISCORD_WEBHOOK_USER_AGENT = "wudup-webui-release-notifications/1.0"
DISCORD_COLOR = 0x57F287


@dataclass(frozen=True)
class _NotificationTarget:
    target: WudTarget
    service_key: str = ""
    wud_container_id: str = ""


@dataclass(frozen=True)
class _NotificationSource:
    targets: tuple[_NotificationTarget, ...]
    source_file: str
    source: PendingSourceInfo
    wud_api: WudApiStatus
    metadata_by_line: Mapping[int, web_wud_api.WudApiContainer]
    warnings: tuple[str, ...] = ()


def api_preview_release_notifications(
    payload: ReleaseNotificationPreviewRequest,
    request: Request,
) -> ReleaseNotificationResponse:
    settings = _settings(request)
    return _notification_response(settings, payload, sent=False)


def api_send_release_notifications(
    payload: ReleaseNotificationSendRequest,
    request: Request,
) -> ReleaseNotificationResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    response = _notification_response(settings, payload, sent=False)
    if not response.enabled:
        raise HTTPException(
            status_code=403,
            detail="release-note notifications are disabled",
        )
    if not response.destination.configured:
        raise HTTPException(
            status_code=422,
            detail="Discord release-note webhook is not configured",
        )
    if response.sendable_count <= 0:
        raise HTTPException(
            status_code=422,
            detail="no release-note notifications are available to send",
        )

    webhook = _discord_webhook(settings)
    assert webhook.value
    try:
        for batch in response.batches:
            _post_discord_payload(webhook.value, batch["payload"])
        audit_run_id = _insert_release_notification_audit(
            settings,
            request,
            payload,
            response,
        )
    except (OSError, urllib.error.HTTPError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not send Discord release-note notifications",
                exc,
            ),
        ) from exc
    return response.model_copy(update={"sent": True, "audit_run_id": audit_run_id})


def _notification_response(
    settings: WebSettings,
    payload: ReleaseNotificationPreviewRequest,
    *,
    sent: bool,
) -> ReleaseNotificationResponse:
    enabled = effective_release_notes_enabled(settings)
    destination = _release_notification_destination(settings)
    if not enabled:
        return ReleaseNotificationResponse(
            enabled=False,
            destination=destination,
            source_file=str(settings.config.wud_out_file),
            source=PendingSourceInfo(
                configured=settings.pending_source,
                active="file",
                label="Release notes disabled",
                fresh=True,
                degraded=False,
                detail="Release-note notifications are disabled.",
            ),
            wud_api=_disabled_wud_api_status(),
            warnings=["Release-note notifications are disabled."],
            sent=sent,
        )

    source = _notification_source(settings, payload)
    if not source.targets:
        return ReleaseNotificationResponse(
            enabled=True,
            destination=destination,
            source=source.source,
            source_file=source.source_file,
            wud_api=source.wud_api,
            warnings=list(source.warnings),
            sent=sent,
        )

    notes = _release_note_infos(settings, source)
    items, warnings = _notification_items(settings, source, notes)
    batches = _payload_batches(items)
    sendable_count = sum(1 for item in items if not item.skipped_reason)
    return ReleaseNotificationResponse(
        enabled=True,
        destination=destination,
        source=source.source,
        source_file=source.source_file,
        count=len(items),
        sendable_count=sendable_count,
        skipped_count=len(items) - sendable_count,
        batches=batches,
        items=items,
        wud_api=source.wud_api,
        warnings=[*source.warnings, *warnings],
        sent=sent,
    )


def _notification_source(
    settings: WebSettings,
    payload: ReleaseNotificationPreviewRequest,
) -> _NotificationSource:
    if payload.run_id is not None:
        return _run_notification_source(settings, payload.run_id)
    return _pending_notification_source(settings, payload.line_numbers)


def _pending_notification_source(
    settings: WebSettings,
    line_numbers: Sequence[int],
) -> _NotificationSource:
    try:
        source = web_pending_sources.resolve_pending_source(
            settings,
            include_wud_metadata=True,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(settings, "could not read pending source", exc),
        ) from exc
    requested = set(line_numbers)
    metadata_by_line = dict(source.metadata_by_line or {})
    targets_by_line = {target.line_no: target for target in source.parsed.targets}
    targets: list[_NotificationTarget] = []
    warnings = list(source.warnings)
    for line_no in line_numbers:
        target = targets_by_line.get(line_no)
        if target is None:
            warnings.append(f"Line {line_no} is not an actionable pending update.")
            continue
        metadata = metadata_by_line.get(line_no)
        targets.append(
            _NotificationTarget(
                target=target,
                service_key=target.key,
                wud_container_id="" if metadata is None else metadata.id,
            )
        )
    if not requested:
        warnings.append("No pending updates were selected.")
    return _NotificationSource(
        targets=tuple(targets),
        source_file=source.source_file,
        source=source.response_source(),
        wud_api=_wud_api_status(source.wud_snapshot.status if source.wud_snapshot else None),
        metadata_by_line=metadata_by_line,
        warnings=tuple(warnings),
    )


def _run_notification_source(settings: WebSettings, run_id: int) -> _NotificationSource:
    try:
        with closing(connect_readonly_db(settings)) as conn:
            run = conn.execute(
                """
                SELECT *
                FROM update_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            if str(run["status"]) != "success":
                raise HTTPException(
                    status_code=422,
                    detail="release notifications require a successful run",
                )
            rows = conn.execute(
                """
                SELECT *
                FROM pending_updates
                WHERE run_id = ?
                ORDER BY line_no, id
                """,
                (run_id,),
            ).fetchall()
    except ReadOnlyDatabaseMissing as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except HTTPException:
        raise
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(settings, "could not read run", exc),
        ) from exc

    targets: list[_NotificationTarget] = []
    warnings: list[str] = []
    for row in rows:
        parsed = parse_wud_text(str(row["raw"]))
        if not parsed.targets:
            warnings.append(f"Run #{run_id} line {row['line_no']} is not actionable.")
            continue
        target = parsed.targets[0]
        target = WudTarget(
            line_no=int(row["line_no"]),
            raw=target.raw,
            first=target.first,
            key=target.key,
            repo=target.repo,
            has_tag=target.has_tag,
            allow_repo=target.allow_repo,
            digest=target.digest,
            desired_tag=target.desired_tag,
            tag_token=target.tag_token,
        )
        targets.append(
            _NotificationTarget(
                target=target,
                service_key=str(row["service_key"]),
            )
        )
    return _NotificationSource(
        targets=tuple(targets),
        source_file=f"Run #{run_id}",
        source=PendingSourceInfo(
            configured=settings.pending_source,
            active="file",
            label=f"Run #{run_id}",
            fresh=True,
            degraded=False,
            detail="Release notifications built from persisted run records.",
        ),
        wud_api=_disabled_wud_api_status(),
        metadata_by_line={},
        warnings=tuple(warnings),
    )


def _release_note_infos(
    settings: WebSettings,
    source: _NotificationSource,
) -> dict[int, ReleaseNoteInfo]:
    try:
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            infos = refresh_release_notes(
                conn,
                (item.target for item in source.targets),
                settings.command_env or {},
                source_resolver=release_note_source_resolver(
                    settings,
                    wud_metadata=dict(source.metadata_by_line),
                ),
                target_tag_resolver=web_wud_api.target_tag_resolver_from_metadata(
                    source.metadata_by_line,
                ),
                redact_error=lambda value: _redact_sensitive_text(settings, value),
            )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not refresh release-note metadata",
                exc,
            ),
        ) from exc
    return {item.line_no: item for item in infos}


def _notification_items(
    settings: WebSettings,
    source: _NotificationSource,
    notes: Mapping[int, ReleaseNoteInfo],
) -> tuple[list[ReleaseNotificationItem], list[str]]:
    items: list[ReleaseNotificationItem] = []
    warnings: list[str] = []
    for target in source.targets:
        note = notes.get(target.target.line_no)
        if note is None:
            warnings.append(f"Line {target.target.line_no} has no release-note metadata.")
            continue
        triggers: list[ReleaseNotificationTrigger] = []
        if target.wud_container_id:
            triggers, trigger_warning = web_wud_api.container_triggers(
                settings,
                target.wud_container_id,
            )
            if trigger_warning:
                warnings.append(
                    f"Line {target.target.line_no} WUD triggers unavailable: "
                    f"{trigger_warning}"
                )
        title, description = _notification_copy(target, note, triggers)
        items.append(
            ReleaseNotificationItem(
                line_no=target.target.line_no,
                image=target.target.first,
                service_key=target.service_key,
                title=title,
                description=description,
                status=note.status,
                release_tag=note.release_tag,
                upstream_repo=note.upstream_repo,
                links=_release_note_links(note),
                triggers=triggers,
            )
        )
    return items, warnings


def _release_note_links(note: ReleaseNoteInfo) -> list[ReleaseNoteLink]:
    return [
        ReleaseNoteLink(
            label=str(link.label),
            url=str(link.url),
            kind=str(link.kind),
        )
        for link in note.links
    ]


def _notification_copy(
    target: _NotificationTarget,
    note: ReleaseNoteInfo,
    triggers: Sequence[ReleaseNotificationTrigger],
) -> tuple[str, str]:
    repo = note.upstream_repo or note.image_repo or target.target.repo
    tag = note.release_tag or target.target.desired_tag or target.target.tag_token
    title = note.title or (f"Release {tag} for {repo}" if tag and repo else "")
    if not title:
        title = f"Update available: {target.target.first}"
    lines = [f"`{target.target.first}`"]
    if target.service_key:
        lines.append(f"Service: `{target.service_key}`")
    if repo:
        lines.append(f"Repository: `{repo}`")
    if tag:
        lines.append(f"Release: `{tag}`")
    if note.status == "ready":
        lines.append("Release metadata is ready in WUDup.")
    elif note.status == "not_found":
        lines.append("A matching GitHub release was not found; project links are included.")
    elif note.status == "missing":
        lines.append("Release metadata was not cached before this notification.")
    elif note.error:
        lines.append(f"Release-note status: {note.error}")
    else:
        lines.append(f"Release-note status: {note.status}")
    if note.breaking:
        lines.append("Breaking-risk indicators were detected.")
        lines.extend(note.breaking_reasons[:3])
    if triggers:
        label = ", ".join(_trigger_label(trigger) for trigger in triggers[:5])
        lines.append(f"WUD triggers: {label}")
    return title, "\n".join(lines)[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _trigger_label(trigger: ReleaseNotificationTrigger) -> str:
    if trigger.type and trigger.name:
        return f"{trigger.type}/{trigger.name}"
    return trigger.name or trigger.type or trigger.id


def _payload_batches(items: Sequence[ReleaseNotificationItem]) -> list[dict[str, object]]:
    batches: list[dict[str, object]] = []
    sendable = [item for item in items if not item.skipped_reason]
    for index in range(0, len(sendable), DISCORD_EMBEDS_PER_MESSAGE):
        batch_items = sendable[index : index + DISCORD_EMBEDS_PER_MESSAGE]
        payload = {
            "username": "WUDup Release Notes",
            "allowed_mentions": {"parse": []},
            "embeds": [_discord_embed(item) for item in batch_items],
        }
        batches.append(
            {
                "index": len(batches) + 1,
                "count": len(batch_items),
                "payload": payload,
            }
        )
    return batches


def _discord_embed(item: ReleaseNotificationItem) -> dict[str, object]:
    links = [_discord_link(link.label, link.url) for link in item.links if link.url]
    fields: list[dict[str, object]] = [
        {"name": "Image", "value": f"`{item.image}`", "inline": False},
    ]
    if item.service_key:
        fields.append({"name": "Service", "value": f"`{item.service_key}`", "inline": True})
    if item.upstream_repo:
        fields.append(
            {"name": "Repository", "value": f"`{item.upstream_repo}`", "inline": True}
        )
    if links:
        fields.append({"name": "Links", "value": " - ".join(links)[:1024], "inline": False})
    if item.triggers:
        fields.append(
            {
                "name": "WUD triggers",
                "value": ", ".join(_trigger_label(trigger) for trigger in item.triggers)[:1024],
                "inline": False,
            }
        )
    embed: dict[str, object] = {
        "title": item.title[:256],
        "description": item.description[:DISCORD_EMBED_DESCRIPTION_LIMIT],
        "color": DISCORD_COLOR,
        "fields": fields[:25],
    }
    first_url = next((link.url for link in item.links if link.url), "")
    if first_url:
        embed["url"] = first_url
    return embed


def _discord_link(label: str, url: str) -> str:
    safe_label = (label or "Release link").replace("[", "").replace("]", "")
    safe_url = url.replace(")", "%29")
    return f"[{safe_label}]({safe_url})"


@dataclass(frozen=True)
class _WebhookConfig:
    value: str
    source: str


def _discord_webhook(settings: WebSettings) -> _WebhookConfig:
    env = settings.command_env or {}
    for name in ("DISCORD_RELEASES_WEBHOOK", "DISCORD_WEBHOOK"):
        value = env.get(name, "").strip()
        if value:
            return _WebhookConfig(value=value, source=name)
    return _WebhookConfig(value="", source="")


def _release_notification_destination(
    settings: WebSettings,
) -> ReleaseNotificationDestination:
    webhook = _discord_webhook(settings)
    return ReleaseNotificationDestination(
        configured=bool(webhook.value),
        source=webhook.source,
    )


def _post_discord_payload(webhook_url: str, payload: Mapping[str, object]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": DISCORD_WEBHOOK_USER_AGENT,
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=DISCORD_WEBHOOK_TIMEOUT_SECONDS,
    ) as response:
        if response.status < 200 or response.status >= 300:
            raise urllib.error.HTTPError(
                webhook_url,
                response.status,
                "Discord webhook request failed",
                response.headers,
                None,
            )


def _insert_release_notification_audit(
    settings: WebSettings,
    request: Request,
    payload: ReleaseNotificationPreviewRequest,
    response: ReleaseNotificationResponse,
) -> int:
    now = utc_timestamp()
    target: dict[str, object] = {}
    if payload.run_id is not None:
        target["run_id"] = payload.run_id
    else:
        target["line_numbers"] = list(payload.line_numbers)
    metadata = {
        "source": "webui",
        "operation": "send_release_notifications",
        "actor_type": _request_actor_type(settings, request),
        "resource_type": "release_notifications",
        "resource_id": "discord",
        "target": target,
        "destination": {
            "type": response.destination.type,
            "source": response.destination.source,
        },
        "sent_count": response.sendable_count,
        "skipped_count": response.skipped_count,
        "batch_count": len(response.batches),
    }
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO update_runs (
                    started_at,
                    finished_at,
                    status,
                    dry_run,
                    mode,
                    wud_file,
                    log_file,
                    metadata_json
                )
                VALUES (?, ?, 'success', 0, 'web-release-notifications', ?, '', ?)
                """,
                (
                    now,
                    now,
                    response.source_file or str(settings.config.wud_out_file),
                    json_object(metadata),
                ),
            )
            run_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO update_events (
                    run_id,
                    created_at,
                    service_name,
                    stack_name,
                    image,
                    target_image,
                    status,
                    metadata_json
                )
                VALUES (?, ?, 'release-notes', 'webui', 'discord', 'discord', 'success', ?)
                """,
                (
                    run_id,
                    now,
                    json_object({**metadata, "items": _audit_items(response.items)}),
                ),
            )
    return run_id


def _audit_items(items: Sequence[ReleaseNotificationItem]) -> list[dict[str, object]]:
    return [
        {
            "line_no": item.line_no,
            "image": item.image,
            "service_key": item.service_key,
            "status": item.status,
            "release_tag": item.release_tag,
            "upstream_repo": item.upstream_repo,
            "trigger_count": len(item.triggers),
            "skipped_reason": item.skipped_reason,
        }
        for item in items
    ]


def _wud_api_status(status: WudApiStatus | None) -> WudApiStatus:
    if status is not None:
        return status
    return _disabled_wud_api_status()


def _disabled_wud_api_status() -> WudApiStatus:
    return WudApiStatus(
        state="unavailable",
        available=False,
        metadata_available=False,
        last_checked_at="",
    )
