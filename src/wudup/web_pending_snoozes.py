"""Display-only snoozed pending candidates for API-backed pending state."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass

from . import web_database, web_pending_sources
from .config import UpdaterConfig
from .db import DatabaseError, active_dependency_snooze_rows, active_snooze
from .images import image_tag
from .plans import resolve_pending_groups
from .web_models import PendingSnoozedCandidate, SnoozeKind, WebSettings
from .wud_file import parse_wud_text


@dataclass(frozen=True)
class _ActivePendingSnooze:
    kind: SnoozeKind
    reason: str
    snoozed_until: str | None = None
    wait_for_service_key: str = ""


def pending_snoozed_candidates(
    settings: WebSettings,
    source: web_pending_sources.PendingSourceResult,
    config: UpdaterConfig,
) -> list[PendingSnoozedCandidate]:
    snapshot = source.wud_snapshot
    if (
        source.active != "api"
        or snapshot is None
        or not snapshot.hidden_update_candidates
    ):
        return []
    lines = web_pending_sources._api_pending_lines(snapshot.hidden_update_candidates)
    if not lines:
        return []
    text = "\n".join(line.raw for line in lines)
    parsed = parse_wud_text(f"{text}\n" if text else "")
    grouping = resolve_pending_groups(
        config,
        parsed,
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
        known_digest_provenance_by_service=(
            web_database.known_digest_provenance_by_service(settings)
        ),
    )
    if grouping.status != "ready":
        return []

    candidate_metadata = {
        line_no: line.container.response()
        for line_no, line in enumerate(lines, start=1)
    }
    source_ids_by_line = {
        line_no: ",".join(line.source_ids)
        for line_no, line in enumerate(lines, start=1)
    }
    service_keys = {
        f"{group.name}/{service}"
        for group in grouping.groups
        for item in group.items
        for service in item.services
    }
    active_snoozes = _active_pending_snoozes(settings, service_keys)
    if not active_snoozes:
        return []

    candidates: list[PendingSnoozedCandidate] = []
    seen: set[str] = set()
    for group in grouping.groups:
        for item in group.items:
            metadata = candidate_metadata.get(item.line_no)
            if metadata is None:
                continue
            source_id = source_ids_by_line.get(item.line_no, "")
            for service in item.services:
                service_key = f"{group.name}/{service}"
                snooze = active_snoozes.get(service_key)
                if snooze is None:
                    continue
                key = f"{source_id}:{service_key}:{item.image}:{item.target_image}"
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    PendingSnoozedCandidate(
                        key=key,
                        service_key=service_key,
                        stack=group.name,
                        service=service,
                        image=item.image,
                        target_image=item.target_image,
                        current_tag=image_tag(item.image),
                        desired_tag=item.desired_tag,
                        digest=item.digest,
                        source_id=source_id,
                        wud_metadata=metadata,
                        snooze_kind=snooze.kind,
                        reason=snooze.reason,
                        snoozed_until=snooze.snoozed_until,
                        wait_for_service_key=snooze.wait_for_service_key,
                    )
                )
    return candidates


def _active_pending_snoozes(
    settings: WebSettings,
    service_keys: set[str],
) -> dict[str, _ActivePendingSnooze]:
    if not service_keys:
        return {}
    try:
        with closing(web_database.connect_readonly_db(settings)) as conn:
            result: dict[str, _ActivePendingSnooze] = {}
            for service_key in service_keys:
                row = active_snooze(conn, service_key=service_key)
                if row is not None:
                    result[service_key] = _ActivePendingSnooze(
                        kind="time",
                        reason=str(row["reason"]),
                        snoozed_until=str(row["snoozed_until"]),
                    )
            for row in active_dependency_snooze_rows(
                conn,
                service_keys=service_keys,
            ):
                service_key = str(row["service_key"])
                result.setdefault(
                    service_key,
                    _ActivePendingSnooze(
                        kind="dependency",
                        reason=str(row["reason"]),
                        wait_for_service_key=str(row["wait_for_service_key"]),
                    ),
                )
    except (
        OSError,
        sqlite3.Error,
        DatabaseError,
        web_database.ReadOnlyDatabaseMissing,
    ):
        return {}
    return result
