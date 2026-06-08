"""WebUI apply-job orchestration for WUD-Updater."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Condition, Event, Lock
from typing import Any, Protocol, cast

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .command import CommandRunner
from .config import UpdaterConfig
from .db import utc_timestamp
from .locks import DirectoryLock, WudLockError
from .plans import DryRunPlan
from .updater import UpdateFromWudRunner
from .updater import digest_pin_update_from_values
from .updater_models import (
    DigestPinLabelRewriteApproval,
    DigestPinUpdate,
    TagOverride,
    UpdaterOptions,
    UpdaterProgressEvent,
)
from .web_models import (
    APPLY_JOB_PROGRESS_STATUSES,
    ApplyJobLogResponse,
    ApplyJobProgressEvent,
    ApplyJobProgressStatus,
    ApplyJobResponse,
    ApplyJobStatus,
    LogTail,
    TERMINAL_APPLY_JOB_STATUSES,
    WebApplyJob,
    WebApplyJobProgressEvent,
    WebSettings,
)

WEB_APPLY_EXECUTOR_MAX_WORKERS = 1
DEFAULT_JOB_LOG_TAIL_BYTES = 65_536
JOB_STREAM_HEARTBEAT_SECONDS = 15.0
JOB_STREAM_LOG_POLL_SECONDS = 1.0


class EffectiveConfigLoader(Protocol):
    def __call__(self, settings: WebSettings) -> UpdaterConfig: ...


class AutoUpdateScheduleRunUpdater(Protocol):
    def __call__(
        self,
        settings: WebSettings,
        schedule_keys: Sequence[str],
        *,
        status: ApplyJobStatus,
        run_id: int | None,
        error: str = "",
    ) -> None: ...


class LogPathResolver(Protocol):
    def __call__(self, settings: WebSettings, raw_log_file: str) -> Path | None: ...


class LogTailReader(Protocol):
    def __call__(self, log_path: Path, max_bytes: int) -> LogTail: ...


def initialize_apply_job_state(state: Any) -> None:
    state.web_apply_executor = ThreadPoolExecutor(
        max_workers=WEB_APPLY_EXECUTOR_MAX_WORKERS
    )
    state.web_apply_lock = Lock()
    state.web_apply_condition = Condition(state.web_apply_lock)
    state.web_apply_jobs = {}
    state.web_self_update_running = False
    state.web_self_update_plans = {}


def shutdown_apply_job_state(state: Any) -> None:
    executor: ThreadPoolExecutor = state.web_apply_executor
    executor.shutdown(wait=False, cancel_futures=True)


def _acquire_apply_wud_lock(settings: WebSettings) -> DirectoryLock:
    lock = DirectoryLock(
        settings.config.wud_out_file,
        timeout_seconds=(settings.command_env or {}).get("WUD_LOCK_TIMEOUT", "30"),
    )
    try:
        lock.acquire()
    except WudLockError as exc:
        raise HTTPException(status_code=409, detail="WUD file is locked") from exc
    return lock


def _submit_apply_job_state(
    state: Any,
    settings: WebSettings,
    plan: DryRunPlan,
    *,
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    wud_lock: DirectoryLock,
    effective_config_loader: EffectiveConfigLoader,
    auto_update_schedule_run_updater: AutoUpdateScheduleRunUpdater,
    digest_pin_label_rewrite_approvals: tuple[DigestPinLabelRewriteApproval, ...] = (),
    update_mode_override: str | None = None,
    metadata_extra: Mapping[str, Any] | None = None,
    auto_update_schedule_keys: tuple[str, ...] = (),
    start_event: Event | None = None,
) -> ApplyJobResponse:
    apply_condition: Condition = state.web_apply_condition
    jobs: dict[str, WebApplyJob] = state.web_apply_jobs
    executor: ThreadPoolExecutor = state.web_apply_executor
    with apply_condition:
        active_error = _active_mutation_error_unlocked(state)
        if active_error:
            raise HTTPException(status_code=409, detail=active_error)
        job = WebApplyJob(
            id=secrets.token_urlsafe(18),
            status="queued",
            selected_line_numbers=tuple(plan.selected_line_numbers),
        )
        jobs[job.id] = job
        response = _apply_job_response(job)
        apply_condition.notify_all()
        executor.submit(
            _run_apply_job,
            settings,
            plan.plan_id,
            tuple(plan.selected_line_numbers),
            allow_tag_updates,
            tag_overrides,
            digest_pin_label_rewrite_approvals,
            _digest_pin_updates_from_plan(plan),
            jobs,
            apply_condition,
            job.id,
            wud_lock,
            effective_config_loader,
            auto_update_schedule_run_updater,
            update_mode_override,
            metadata_extra,
            auto_update_schedule_keys,
            start_event,
        )
        return response


def _active_apply_job_exists(request: Request) -> bool:
    return _active_apply_job_exists_in_state(request.app.state)


def _active_apply_job_exists_in_state(state: Any) -> bool:
    return _active_mutation_error_in_state(state) != ""


def _active_mutation_error(request: Request) -> str:
    return _active_mutation_error_in_state(request.app.state)


def _active_mutation_error_in_state(state: Any) -> str:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        return _active_mutation_error_unlocked(state)


def _active_mutation_error_unlocked(state: Any) -> str:
    jobs: dict[str, WebApplyJob] = state.web_apply_jobs
    if any(job.status in {"queued", "running"} for job in jobs.values()):
        return "an apply job is already running"
    if bool(getattr(state, "web_self_update_running", False)):
        return "self-update is already running"
    return ""


def _reserve_self_update(state: Any) -> str:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        active_error = _active_mutation_error_unlocked(state)
        if active_error:
            return active_error
        state.web_self_update_running = True
    return ""


def _release_self_update(state: Any) -> None:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        state.web_self_update_running = False


def _require_apply_job(job_id: str, request: Request) -> WebApplyJob:
    apply_lock: Lock = request.app.state.web_apply_lock
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    with apply_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="apply job not found")
        return job


def _apply_job_response_for_request(job_id: str, request: Request) -> ApplyJobResponse:
    apply_lock: Lock = request.app.state.web_apply_lock
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    with apply_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="apply job not found")
        return _apply_job_response(job)


def _apply_job_stream(
    state: Any,
    settings: WebSettings,
    job_id: str,
    *,
    log_tail_bytes: int,
    safe_log_path: LogPathResolver,
    read_log_tail: LogTailReader,
) -> Iterator[str]:
    jobs: dict[str, WebApplyJob] = state.web_apply_jobs
    apply_condition: Condition = state.web_apply_condition
    last_version = -1
    last_log_signature: tuple[object, ...] | None = None
    terminal_log_emitted = False
    last_heartbeat = time.monotonic()
    last_progress_count = 0

    while True:
        job_snapshot: ApplyJobResponse
        response: ApplyJobResponse | None = None
        progress_events: list[ApplyJobProgressEvent] = []
        terminal = False
        with apply_condition:
            job = jobs.get(job_id)
            if job is None:
                return
            if (
                job.version == last_version
                and len(job.progress) == last_progress_count
            ):
                apply_condition.wait(timeout=JOB_STREAM_LOG_POLL_SECONDS)
                job = jobs.get(job_id)
                if job is None:
                    return
            job_snapshot = _apply_job_response(job)
            if job.version != last_version:
                response = job_snapshot
                last_version = job.version
            if len(job.progress) > last_progress_count:
                progress_events = job_snapshot.progress[last_progress_count:]
                last_progress_count = len(job.progress)
            terminal = job.status in TERMINAL_APPLY_JOB_STATUSES

        log_event = ""
        log_response = _apply_job_log_response(
            settings,
            job_snapshot,
            max_bytes=log_tail_bytes,
            safe_log_path=safe_log_path,
            read_log_tail=read_log_tail,
        )
        if log_response is not None:
            log_signature = _apply_job_log_signature(log_response)
            should_emit_log = (
                bool(log_response.content)
                or bool(log_response.error)
                or terminal
            ) and (
                log_signature != last_log_signature
                or (terminal and not terminal_log_emitted)
            )
            if should_emit_log:
                log_event = _sse_job_log_event(log_response)
                last_log_signature = log_signature
                last_heartbeat = time.monotonic()
                if terminal:
                    terminal_log_emitted = True

        if terminal and log_event:
            yield log_event

        for progress_event in progress_events:
            yield _sse_job_progress_event(progress_event)
        if progress_events:
            last_heartbeat = time.monotonic()

        if response is not None:
            yield _sse_job_event(response)

        if not terminal and log_event:
            yield log_event

        if response is not None:
            last_heartbeat = time.monotonic()

        now = time.monotonic()
        if response is None and now - last_heartbeat >= JOB_STREAM_HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        if terminal:
            return


def _run_apply_job(
    settings: WebSettings,
    plan_id: str,
    line_numbers: tuple[int, ...],
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    digest_pin_label_rewrite_approvals: tuple[DigestPinLabelRewriteApproval, ...],
    digest_pin_plan: tuple[DigestPinUpdate, ...],
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    wud_lock: DirectoryLock,
    effective_config_loader: EffectiveConfigLoader,
    auto_update_schedule_run_updater: AutoUpdateScheduleRunUpdater,
    update_mode_override: str | None = None,
    metadata_extra: Mapping[str, Any] | None = None,
    auto_update_schedule_keys: tuple[str, ...] = (),
    start_event: Event | None = None,
) -> None:
    if start_event is not None:
        start_event.wait()
    _update_apply_job(
        jobs,
        apply_condition,
        job_id,
        status="running",
        started_at=utc_timestamp(),
    )
    runner: UpdateFromWudRunner | None = None
    try:
        options = _apply_options(
            settings,
            line_numbers=line_numbers,
            allow_tag_updates=allow_tag_updates,
            tag_overrides=tag_overrides,
            digest_pin_label_rewrite_approvals=digest_pin_label_rewrite_approvals,
            digest_pin_plan=digest_pin_plan,
            plan_id=plan_id,
            effective_config_loader=effective_config_loader,
            update_mode_override=update_mode_override,
            metadata_extra=metadata_extra,
        )
        apply_env = dict(settings.command_env or {})
        apply_env["WUD_LOCK_HELD_BY_PARENT"] = "1"
        runner = UpdateFromWudRunner(
            options,
            environ=apply_env,
            command_runner=CommandRunner(env=apply_env),
            progress_callback=lambda event: _append_apply_job_progress(
                jobs,
                apply_condition,
                job_id,
                event,
            ),
        )
        _update_apply_job(
            jobs,
            apply_condition,
            job_id,
            log_file=str(runner.log_file),
        )
        status_code = runner.run()
        job_status: ApplyJobStatus = "success" if status_code == 0 else "failure"
        auto_update_schedule_run_updater(
            settings,
            auto_update_schedule_keys,
            status=job_status,
            run_id=runner.audit_run_id,
            error="" if status_code == 0 else f"updater exited with status {status_code}",
        )
        _update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status=job_status,
            run_id=runner.audit_run_id,
            log_file=str(runner.log_file),
            finished_at=utc_timestamp(),
            error="" if status_code == 0 else f"updater exited with status {status_code}",
        )
    except Exception as exc:
        run_id = None if runner is None else runner.audit_run_id
        _append_apply_job_progress(
            jobs,
            apply_condition,
            job_id,
            UpdaterProgressEvent(
                phase="completion",
                status="failure",
                message=str(exc),
            ),
        )
        auto_update_schedule_run_updater(
            settings,
            auto_update_schedule_keys,
            status="failure",
            run_id=run_id,
            error=str(exc),
        )
        _update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status="failure",
            run_id=run_id,
            log_file="" if runner is None else str(runner.log_file),
            finished_at=utc_timestamp(),
            error=str(exc),
        )
    finally:
        wud_lock.close()


def _update_apply_job(
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    **changes: object,
) -> None:
    with apply_condition:
        job = jobs.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.version += 1
        apply_condition.notify_all()


def _append_apply_job_progress(
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    event: UpdaterProgressEvent,
) -> None:
    with apply_condition:
        job = jobs.get(job_id)
        if job is None:
            return
        status = (
            event.status
            if event.status in APPLY_JOB_PROGRESS_STATUSES
            else "running"
        )
        job.progress = (
            *job.progress,
            WebApplyJobProgressEvent(
                phase=event.phase,
                status=cast(ApplyJobProgressStatus, status),
                message=event.message,
                created_at=utc_timestamp(),
                stack=event.stack,
                services=event.services,
                line_numbers=event.line_numbers,
            ),
        )
        apply_condition.notify_all()


def _apply_options(
    settings: WebSettings,
    *,
    line_numbers: tuple[int, ...],
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    plan_id: str,
    effective_config_loader: EffectiveConfigLoader,
    digest_pin_label_rewrite_approvals: tuple[DigestPinLabelRewriteApproval, ...] = (),
    digest_pin_plan: tuple[DigestPinUpdate, ...] = (),
    update_mode_override: str | None = None,
    metadata_extra: Mapping[str, Any] | None = None,
) -> UpdaterOptions:
    line_spec = _line_spec(line_numbers)
    metadata = {
        "plan_id": plan_id,
        "selected_line_numbers": list(line_numbers),
        "source": "webui",
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    metadata_json = json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
    )
    config = effective_config_loader(settings)
    host_docker_base_label = (
        None if settings.host_docker_base is None else str(settings.host_docker_base)
    )
    return UpdaterOptions(
        docker_base=config.docker_base,
        wud_file=config.wud_out_file,
        log_dir=config.log_dir,
        mode=update_mode_override or config.update_mode,
        max_wait=config.max_wait,
        dry_run=False,
        assume_yes=True,
        allow_tag_updates=allow_tag_updates,
        digest_pin_updates=config.digest_pin_updates,
        tag_overrides=tag_overrides,
        digest_pin_label_rewrite_approvals=digest_pin_label_rewrite_approvals,
        digest_pin_plan=digest_pin_plan,
        only_lines=line_spec,
        remove_lines_before_run=line_spec,
        compose_ignore_paths=config.compose_ignore_paths,
        db_path=config.db_path,
        docker_base_label=str(config.docker_base),
        host_docker_base=settings.host_docker_base,
        host_docker_base_label=host_docker_base_label,
        wud_file_label=str(config.wud_out_file),
        log_dir_label=str(config.log_dir),
        metadata_json=metadata_json,
    )


def _line_spec(line_numbers: tuple[int, ...]) -> str:
    return ",".join(str(line_no) for line_no in sorted(set(line_numbers)))


def _digest_pin_updates_from_plan(
    plan: DryRunPlan,
) -> tuple[DigestPinUpdate, ...]:
    updates: list[DigestPinUpdate] = []
    for stack in plan.stacks:
        for item in stack.digest_pin_updates:
            updates.append(
                digest_pin_update_from_values(
                    old_image=item.source_image,
                    resolved_tag=item.resolved_tag,
                    planned_digest=item.planned_digest,
                    services=tuple(item.services),
                )
            )
    return tuple(updates)


def _apply_job_response(job: WebApplyJob) -> ApplyJobResponse:
    return ApplyJobResponse(
        job_id=job.id,
        status=job.status,
        run_id=job.run_id,
        log_file=job.log_file,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        selected_line_numbers=list(job.selected_line_numbers),
        progress=[
            ApplyJobProgressEvent(
                job_id=job.id,
                phase=event.phase,
                status=event.status,
                message=event.message,
                created_at=event.created_at,
                stack=event.stack,
                services=list(event.services),
                line_numbers=list(event.line_numbers),
            )
            for event in job.progress
        ],
    )


def _sse_job_event(job: ApplyJobResponse) -> str:
    payload = json.dumps(
        jsonable_encoder(job),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: job\ndata: {payload}\n\n"


def _sse_job_progress_event(progress: ApplyJobProgressEvent) -> str:
    payload = json.dumps(
        jsonable_encoder(progress),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: progress\ndata: {payload}\n\n"


def _apply_job_log_response(
    settings: WebSettings,
    job: ApplyJobResponse,
    *,
    max_bytes: int,
    safe_log_path: LogPathResolver,
    read_log_tail: LogTailReader,
) -> ApplyJobLogResponse | None:
    if not job.log_file:
        return None
    try:
        log_path = safe_log_path(settings, job.log_file)
        if log_path is None:
            return None
        tail = read_log_tail(log_path, max_bytes)
    except HTTPException as exc:
        return ApplyJobLogResponse(
            job_id=job.job_id,
            log_file=job.log_file,
            max_bytes=max_bytes,
            error=str(exc.detail),
        )
    return ApplyJobLogResponse(
        job_id=job.job_id,
        log_file=job.log_file,
        exists=tail.exists,
        content=tail.content,
        truncated=tail.truncated,
        max_bytes=max_bytes,
    )


def _apply_job_log_signature(log: ApplyJobLogResponse) -> tuple[object, ...]:
    content_hash = hashlib.sha256(log.content.encode("utf-8")).hexdigest()
    return (
        log.job_id,
        log.log_file,
        log.exists,
        log.truncated,
        log.max_bytes,
        log.error,
        content_hash,
    )


def _sse_job_log_event(log: ApplyJobLogResponse) -> str:
    payload = json.dumps(
        jsonable_encoder(log),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: log\ndata: {payload}\n\n"
