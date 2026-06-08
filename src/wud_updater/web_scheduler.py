"""WebUI automatic update scheduler for WUD-Updater."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, time as datetime_time, timedelta, timezone
from threading import Event, Thread
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from . import web_jobs
from .config import UpdaterConfig
from .db import active_snooze, init_db, open_db, utc_timestamp
from .plans import DryRunPlan, build_dry_run_plan, resolve_pending_groups
from .web_auth import _immediate_transaction
from .web_models import (
    ApplyJobResponse,
    ApplyJobStatus,
    AutoUpdatePolicy,
    AutoUpdateSelection,
    WebSettings,
)
from .wud_file import parse_wud_file

AUTO_UPDATE_POLL_SECONDS = 60.0
AUTO_UPDATE_GRACE_SECONDS = 300
AUTO_UPDATE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOGGER = logging.getLogger(__name__)


class AutoUpdateScheduleReservationError(RuntimeError):
    """Raised when an automatic update schedule slot was already claimed."""


class EffectiveConfigLoader(Protocol):
    def __call__(self, settings: WebSettings) -> UpdaterConfig: ...


def initialize_auto_update_scheduler_state(state: Any) -> None:
    state.web_auto_update_started_at = datetime.now(timezone.utc)
    state.web_auto_update_stop = Event()
    state.web_auto_update_thread = None


def shutdown_auto_update_scheduler_state(state: Any) -> None:
    stop_event: Event = state.web_auto_update_stop
    stop_event.set()
    thread = state.web_auto_update_thread
    if thread is not None:
        thread.join(timeout=1.0)


def start_auto_update_scheduler(
    app: FastAPI,
    settings: WebSettings,
    *,
    effective_config_loader: EffectiveConfigLoader,
) -> Thread | None:
    if not settings.mutations_enabled:
        return None
    stop_event: Event = app.state.web_auto_update_stop
    thread = Thread(
        target=_auto_update_scheduler_loop,
        args=(app, settings, stop_event, effective_config_loader),
        name="wud-auto-update-scheduler",
        daemon=True,
    )
    thread.start()
    return thread


def _auto_update_scheduler_loop(
    app: FastAPI,
    settings: WebSettings,
    stop_event: Event,
    effective_config_loader: EffectiveConfigLoader,
) -> None:
    while not stop_event.wait(AUTO_UPDATE_POLL_SECONDS):
        try:
            _auto_update_tick(
                app,
                settings,
                effective_config_loader=effective_config_loader,
            )
        except Exception:
            LOGGER.exception("auto update scheduler tick failed")


def _auto_update_tick(
    app: FastAPI,
    settings: WebSettings,
    *,
    effective_config_loader: EffectiveConfigLoader,
    now: datetime | None = None,
) -> ApplyJobResponse | None:
    if (
        not settings.mutations_enabled
        or web_jobs._active_apply_job_exists_in_state(app.state)
    ):
        return None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    started_at = app.state.web_auto_update_started_at
    if not isinstance(started_at, datetime):
        started_at = now_utc
    started_at_utc = started_at.astimezone(timezone.utc)

    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        candidate = _auto_update_candidate(
            conn,
            settings,
            effective_config_loader=effective_config_loader,
            now_utc=now_utc,
            started_at=started_at_utc,
        )
    if candidate is None:
        return None
    wud_lock = web_jobs._acquire_apply_wud_lock(settings)
    lock_transferred = False
    start_event: Event | None = None
    try:
        locked_now_utc = now_utc if now is not None else datetime.now(timezone.utc)
        locked_now_utc = locked_now_utc.astimezone(timezone.utc)
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            candidate = _auto_update_candidate(
                conn,
                settings,
                effective_config_loader=effective_config_loader,
                now_utc=locked_now_utc,
                started_at=started_at_utc,
            )
            if candidate is None:
                return None
            selection, plan = candidate
            with _immediate_transaction(conn):
                _reserve_auto_update_schedule_runs(conn, settings, selection)
                start_event = Event()
                response = web_jobs._submit_apply_job_state(
                    app.state,
                    settings,
                    plan,
                    allow_tag_updates=False,
                    tag_overrides=(),
                    wud_lock=wud_lock,
                    effective_config_loader=effective_config_loader,
                    auto_update_schedule_run_updater=(
                        _safe_update_auto_update_schedule_runs
                    ),
                    update_mode_override=selection.update_mode,
                    metadata_extra={
                        "source": "webui-auto",
                        "actor_type": "scheduler",
                        "auto_update_service_keys": list(selection.service_keys),
                        "auto_update_schedule_keys": list(selection.schedule_keys),
                        "auto_update_scheduled_for": selection.scheduled_for.isoformat(),
                        "timezone": settings.config.timezone_name,
                    },
                    auto_update_schedule_keys=selection.schedule_keys,
                    start_event=start_event,
                )
                lock_transferred = True
                _queue_auto_update_schedule_runs(
                    conn,
                    settings,
                    selection,
                    response.job_id,
                )
        if start_event is not None:
            start_event.set()
        return response
    except AutoUpdateScheduleReservationError:
        return None
    except Exception:
        if lock_transferred and start_event is not None:
            start_event.set()
        raise
    finally:
        if not lock_transferred:
            wud_lock.close()


def _auto_update_candidate(
    conn: sqlite3.Connection,
    settings: WebSettings,
    *,
    effective_config_loader: EffectiveConfigLoader,
    now_utc: datetime,
    started_at: datetime,
) -> tuple[AutoUpdateSelection, DryRunPlan] | None:
    try:
        parsed = parse_wud_file(settings.config.wud_out_file)
    except FileNotFoundError:
        return None

    grouping = resolve_pending_groups(
        effective_config_loader(settings),
        parsed,
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )
    if grouping.status != "ready":
        return None

    policies = _due_auto_update_policies(
        conn,
        settings,
        now_utc=now_utc,
        started_at=started_at,
    )
    selection = _auto_update_selection(settings, grouping, policies)
    if selection is None:
        return None

    plan = _build_auto_update_plan(
        settings,
        selection.line_numbers,
        update_mode_override=selection.update_mode,
        effective_config_loader=effective_config_loader,
    )
    if not _plan_can_auto_apply(plan, settings):
        return None
    return selection, plan


def _build_auto_update_plan(
    settings: WebSettings,
    line_numbers: Sequence[int],
    *,
    update_mode_override: str | None,
    effective_config_loader: EffectiveConfigLoader,
) -> DryRunPlan:
    base_config = effective_config_loader(settings)
    config = (
        base_config
        if update_mode_override is None
        else replace(base_config, update_mode=update_mode_override)
    )
    return build_dry_run_plan(
        config,
        line_numbers=line_numbers,
        allow_tag_updates=False,
        tag_overrides=(),
        digest_pin_label_rewrite_approvals=(),
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )


def _plan_can_auto_apply(plan: DryRunPlan, settings: WebSettings) -> bool:
    return (
        settings.mutations_enabled
        and plan.status == "ready"
        and not plan.skipped
        and not any(issue.severity == "error" for issue in plan.issues)
    )


def _due_auto_update_policies(
    conn: sqlite3.Connection,
    settings: WebSettings,
    *,
    now_utc: datetime,
    started_at: datetime,
) -> dict[str, AutoUpdatePolicy]:
    tz = ZoneInfo(settings.config.timezone_name)
    local_now = now_utc.astimezone(tz)
    now_text = now_utc.replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT *
        FROM service_policy
        WHERE auto_update = 1
          AND auto_update_time IS NOT NULL
        ORDER BY service_key COLLATE BINARY
        """
    ).fetchall()
    policies: dict[str, AutoUpdatePolicy] = {}
    for row in rows:
        days = _auto_update_days_from_row(row)
        update_time = str(row["auto_update_time"])
        try:
            parsed_time = datetime_time.fromisoformat(update_time)
        except ValueError:
            continue
        occurrence = _auto_update_due_occurrence(
            local_now=local_now,
            parsed_time=parsed_time,
            days=days,
            now_utc=now_utc,
            tz=tz,
        )
        if occurrence is None:
            continue
        scheduled_local, scheduled_for, window_end = occurrence
        if started_at >= window_end:
            continue
        service_key = str(row["service_key"])
        if active_snooze(conn, service_key=service_key, now=now_text) is not None:
            continue
        schedule_key = _auto_update_schedule_key(
            service_key,
            local_date=scheduled_local.date().isoformat(),
            update_time=update_time,
            timezone_name=settings.config.timezone_name,
        )
        if _auto_update_schedule_recorded(conn, schedule_key):
            continue
        policies[service_key] = AutoUpdatePolicy(
            service_key=service_key,
            update_mode=str(row["update_mode"] or settings.config.update_mode),
            auto_update_time=update_time,
            auto_update_days=days,
            schedule_key=schedule_key,
            scheduled_for=scheduled_for,
        )
    return policies


def _auto_update_due_occurrence(
    *,
    local_now: datetime,
    parsed_time: datetime_time,
    days: Sequence[str],
    now_utc: datetime,
    tz: ZoneInfo,
) -> tuple[datetime, datetime, datetime] | None:
    candidate_dates = (
        local_now.date(),
        (local_now - timedelta(days=1)).date(),
    )
    for local_date in candidate_dates:
        scheduled_local = datetime.combine(local_date, parsed_time, tzinfo=tz)
        day = AUTO_UPDATE_DAYS[scheduled_local.weekday()]
        if day not in days:
            continue
        scheduled_for = scheduled_local.astimezone(timezone.utc)
        window_end = scheduled_for + timedelta(seconds=AUTO_UPDATE_GRACE_SECONDS)
        if scheduled_for <= now_utc < window_end:
            return scheduled_local, scheduled_for, window_end
    return None


def _auto_update_selection(
    settings: WebSettings,
    grouping: Any,
    policies: Mapping[str, AutoUpdatePolicy],
) -> AutoUpdateSelection | None:
    if not policies:
        return None
    lines_by_mode: dict[str, list[int]] = {}
    services_by_mode: dict[str, set[str]] = {}
    schedules_by_mode: dict[str, set[str]] = {}
    scheduled_for_by_mode: dict[str, datetime] = {}
    for group in grouping.groups:
        for item in group.items:
            if item.desired_tag:
                continue
            service_keys = tuple(
                f"{group.name}/{service}" for service in item.services if service
            )
            if not service_keys:
                continue
            line_policies = [policies.get(service_key) for service_key in service_keys]
            if any(policy is None for policy in line_policies):
                continue
            concrete = tuple(
                policy for policy in line_policies if policy is not None
            )
            mode = concrete[0].update_mode or settings.config.update_mode
            if any(
                (policy.update_mode or settings.config.update_mode) != mode
                for policy in concrete
            ):
                continue
            lines_by_mode.setdefault(mode, []).append(item.line_no)
            services_by_mode.setdefault(mode, set()).update(service_keys)
            schedules_by_mode.setdefault(mode, set()).update(
                policy.schedule_key for policy in concrete
            )
            current = scheduled_for_by_mode.get(mode)
            scheduled_for = min(policy.scheduled_for for policy in concrete)
            scheduled_for_by_mode[mode] = (
                scheduled_for if current is None else min(current, scheduled_for)
            )
    for mode in sorted(lines_by_mode):
        line_numbers = tuple(sorted(set(lines_by_mode[mode])))
        if line_numbers:
            return AutoUpdateSelection(
                line_numbers=line_numbers,
                service_keys=tuple(sorted(services_by_mode[mode])),
                schedule_keys=tuple(sorted(schedules_by_mode[mode])),
                scheduled_for=scheduled_for_by_mode[mode],
                update_mode=mode,
            )
    return None


def _auto_update_schedule_key(
    service_key: str,
    *,
    local_date: str,
    update_time: str,
    timezone_name: str,
) -> str:
    return f"{service_key}|{local_date}|{update_time}|{timezone_name}"


def _auto_update_schedule_recorded(conn: sqlite3.Connection, schedule_key: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM auto_update_schedule_runs
        WHERE schedule_key = ?
        LIMIT 1
        """,
        (schedule_key,),
    ).fetchone()
    return row is not None


def _auto_update_schedule_metadata(
    settings: WebSettings,
    selection: AutoUpdateSelection,
    *,
    job_id: str = "",
    status: str = "reserved",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "webui-auto",
        "line_numbers": list(selection.line_numbers),
        "service_keys": list(selection.service_keys),
        "scheduled_for": selection.scheduled_for.isoformat(),
        "timezone": settings.config.timezone_name,
        "update_mode": selection.update_mode,
        "status": status,
    }
    if job_id:
        metadata["job_id"] = job_id
    return metadata


def _reserve_auto_update_schedule_runs(
    conn: sqlite3.Connection,
    settings: WebSettings,
    selection: AutoUpdateSelection,
) -> None:
    now = utc_timestamp()
    metadata = _json_object(_auto_update_schedule_metadata(settings, selection))
    for schedule_key in selection.schedule_keys:
        service_key = schedule_key.split("|", 1)[0]
        try:
            conn.execute(
                """
                INSERT INTO auto_update_schedule_runs (
                    schedule_key,
                    service_key,
                    scheduled_for,
                    run_id,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, NULL, 'reserved', ?, ?, ?)
                """,
                (
                    schedule_key,
                    service_key,
                    selection.scheduled_for.isoformat(),
                    now,
                    now,
                    metadata,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AutoUpdateScheduleReservationError(schedule_key) from exc


def _queue_auto_update_schedule_runs(
    conn: sqlite3.Connection,
    settings: WebSettings,
    selection: AutoUpdateSelection,
    job_id: str,
) -> None:
    now = utc_timestamp()
    metadata = _json_object(
        _auto_update_schedule_metadata(
            settings,
            selection,
            job_id=job_id,
            status="queued",
        )
    )
    for schedule_key in selection.schedule_keys:
        conn.execute(
            """
            UPDATE auto_update_schedule_runs
            SET status = 'queued',
                updated_at = ?,
                metadata_json = ?
            WHERE schedule_key = ?
            """,
            (now, metadata, schedule_key),
        )


def _safe_update_auto_update_schedule_runs(
    settings: WebSettings,
    schedule_keys: Sequence[str],
    *,
    status: ApplyJobStatus,
    run_id: int | None,
    error: str = "",
) -> None:
    if not schedule_keys:
        return
    try:
        _update_auto_update_schedule_runs(
            settings,
            schedule_keys,
            status=status,
            run_id=run_id,
            error=error,
        )
    except Exception:
        LOGGER.exception("failed to update auto update schedule run status")


def _update_auto_update_schedule_runs(
    settings: WebSettings,
    schedule_keys: Sequence[str],
    *,
    status: ApplyJobStatus,
    run_id: int | None,
    error: str = "",
) -> None:
    now = utc_timestamp()
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        with conn:
            for schedule_key in schedule_keys:
                metadata = _auto_update_schedule_row_metadata(conn, schedule_key)
                metadata["status"] = status
                if run_id is None:
                    metadata.pop("run_id", None)
                else:
                    metadata["run_id"] = run_id
                if error:
                    metadata["error"] = error
                else:
                    metadata.pop("error", None)
                conn.execute(
                    """
                    UPDATE auto_update_schedule_runs
                    SET run_id = ?,
                        status = ?,
                        updated_at = ?,
                        metadata_json = ?
                    WHERE schedule_key = ?
                    """,
                    (run_id, status, now, _json_object(metadata), schedule_key),
                )


def _auto_update_schedule_row_metadata(
    conn: sqlite3.Connection,
    schedule_key: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT metadata_json
        FROM auto_update_schedule_runs
        WHERE schedule_key = ?
        LIMIT 1
        """,
        (schedule_key,),
    ).fetchone()
    if row is None:
        return {}
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _auto_update_days_from_row(row: sqlite3.Row) -> tuple[str, ...]:
    raw = str(row["auto_update_days_json"] or "[]")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    days: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item in AUTO_UPDATE_DAYS and item not in days:
            days.append(item)
    return tuple(days)


def _json_object(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
