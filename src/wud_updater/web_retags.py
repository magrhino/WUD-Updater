"""WebUI retag review route handlers."""

from __future__ import annotations

import secrets
import shutil
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Condition
from typing import Protocol

from fastapi import HTTPException, Request

from . import web_database, web_jobs
from .command import CommandError, CommandRunner
from .compose import ComposeCli, ComposeDiscoveryError, ComposeStack, ServiceImage
from .compose_rewrite import (
    WUD_TAG_INCLUDE_LABEL,
    _backup_compose,
    apply_compose_digest_pins,
    compose_unescape_dollars,
    render_compose_digest_pins,
)
from .config import ConfigError, UpdaterConfig
from .db import (
    DatabaseError,
    init_db,
    insert_update_event,
    insert_update_run,
    open_db,
    upsert_known_image,
    utc_timestamp,
)
from .digest_provenance import DigestTagProvenance, digest_from_image
from .digest_verifier import DigestVerifier
from .docker_cli import DockerCli
from .images import (
    image_has_tag,
    image_key,
    image_tag,
    image_with_digest,
    image_with_tag,
    repo_key,
    tag_value_valid,
)
from .release_notes import (
    GitHubClient,
    ReleaseNoteInfo,
    cached_release_notes,
    github_latest_candidate_from_info,
    refresh_release_notes,
)
from .updater_digest_pin import digest_pin_update_from_values
from .updater_lifecycle_health import (
    CONTAINER_SUMMARY_FORMAT,
    HEALTH_LOG_FORMAT,
    _cid_is_ok,
)
from .updater_models import (
    AppliedDigestPinUpdate,
    UpdaterProgressEvent,
)
from .web_auth import _redact_sensitive_text, _safe_exception_detail, _settings
from .web_database import ReadOnlyDatabaseMissing
from .web_models import (
    ApplyJobResponse,
    RetagApplyRequest,
    RetagChoiceRequest,
    RetagPlanIssue,
    RetagPlanLabelRewrite,
    RetagPlanRequest,
    RetagPlanResponse,
    RetagTargetItem,
    RetagTargetsResponse,
    WebApplyJob,
    WebSettings,
)
from .web_release_notes import release_note_source_resolver
from .web_metadata import json_object as _json_object
from .web_retag_plans import (
    RetagPlanBuild as _RetagPlanBuild,
    RetagPlanUpdate as _RetagPlanUpdate,
    ordered_retag_stacks as _ordered_retag_stacks,
    retag_compose_hashes as _compose_hashes,
    retag_plan_digest_update as _retag_plan_digest_update,
    retag_plan_id as _retag_plan_id,
    retag_plan_stacks as _retag_plan_stacks,
    retag_plan_status as _retag_plan_status,
    retag_update_service as _retag_update_service,
)
from .wud_file import WudTarget


KEEP_CURRENT_CHOICE = "keep-current"
SWITCH_TO_CONCRETE_CHOICE = "switch-to-concrete"
_REGEX_SPECIAL_CHARS = "\\^$.*+?()[]{}|"


@dataclass(frozen=True)
class _RetagTargetRecord:
    item: RetagTargetItem
    stack: ComposeStack
    service_image: ServiceImage
    known_image: str
    provenance: DigestTagProvenance | None


@dataclass(frozen=True)
class _RetagGitHubLatestFallback:
    provenance: DigestTagProvenance | None = None
    proposed_tag: str = ""
    warning: str = ""
    link_label: str = ""
    link_url: str = ""


class _RetagApplyFailed(RuntimeError):
    def __init__(
        self,
        message: str,
        successful_updates: Sequence[_RetagPlanUpdate],
    ) -> None:
        super().__init__(message)
        self.successful_updates = tuple(successful_updates)


class EffectiveConfigLoader(Protocol):
    def __call__(self, settings: WebSettings) -> UpdaterConfig: ...


_effective_config_loader: EffectiveConfigLoader | None = None


def configure(*, effective_config_loader: EffectiveConfigLoader) -> None:
    global _effective_config_loader
    _effective_config_loader = effective_config_loader


def api_retag_targets(
    request: Request,
    github_latest_fallback: bool = False,
) -> RetagTargetsResponse:
    return retag_targets_response(
        _settings(request),
        github_latest_fallback=github_latest_fallback,
    )


def api_refresh_retag_github_latest(request: Request) -> RetagTargetsResponse:
    settings = _settings(request)
    response = _refresh_retag_github_latest_candidates(settings)
    if response is not None:
        return response
    return retag_targets_response(settings, github_latest_fallback=True)


def api_create_retag_plan(
    payload: RetagPlanRequest,
    request: Request,
) -> RetagPlanResponse:
    return build_retag_plan(_settings(request), payload).response


def api_apply_retag_plan(
    payload: RetagApplyRequest,
    request: Request,
) -> ApplyJobResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = web_jobs._active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)

    wud_lock = web_jobs._acquire_apply_wud_lock(settings)
    try:
        build = build_retag_plan(
            settings,
            RetagPlanRequest(
                choices=payload.choices,
                github_latest_fallback=payload.github_latest_fallback,
            ),
        )
        plan = build.response
        if not secrets.compare_digest(plan.plan_id, payload.plan_id):
            raise HTTPException(status_code=409, detail="retag plan is stale")
        if not plan.can_apply or not build.updates:
            raise HTTPException(status_code=409, detail="retag plan is not ready to apply")
        return _submit_retag_apply_job(request, settings, build, wud_lock)
    except Exception:
        wud_lock.close()
        raise


def retag_targets_response(
    settings: WebSettings,
    *,
    github_latest_fallback: bool = False,
) -> RetagTargetsResponse:
    discovery = _retag_target_records(
        settings,
        github_latest_fallback=github_latest_fallback,
    )
    if isinstance(discovery, RetagTargetsResponse):
        return discovery
    items = [record.item for record in discovery]
    return RetagTargetsResponse(
        status="ready",
        count=len(items),
        items=items,
        warnings=[],
    )


def build_retag_plan(
    settings: WebSettings,
    payload: RetagPlanRequest,
) -> _RetagPlanBuild:
    records_or_response = _retag_target_records(
        settings,
        github_latest_fallback=payload.github_latest_fallback,
    )
    if isinstance(records_or_response, RetagTargetsResponse):
        plan = RetagPlanResponse(
            plan_id="",
            status="unavailable",
            can_apply=False,
            warnings=records_or_response.warnings,
            issues=[
                RetagPlanIssue(
                    severity="error",
                    code="retag-targets-unavailable",
                    message="Retag targets are unavailable.",
                    hint="Resolve Compose discovery warnings, then refresh retag targets.",
                )
            ],
        )
        plan.plan_id = _retag_plan_id(plan, updates=(), compose_hashes={})
        return _RetagPlanBuild(response=plan, updates=())

    choices = _validated_choice_map(payload.choices)
    records_by_key = {record.item.service_key: record for record in records_or_response}
    unknown = sorted(set(choices) - set(records_by_key))
    if unknown:
        values = ", ".join(unknown)
        raise HTTPException(
            status_code=422,
            detail=f"retag choices reference unknown service(s): {values}",
        )

    keep_current_count = sum(
        1 for choice in choices.values() if choice == KEEP_CURRENT_CHOICE
    )
    selected: list[_RetagPlanUpdate] = []
    issues: list[RetagPlanIssue] = []
    for service_key, choice in sorted(choices.items()):
        if choice == KEEP_CURRENT_CHOICE:
            continue
        record = records_by_key[service_key]
        item = record.item
        if not item.retag_available or record.provenance is None:
            issues.append(
                RetagPlanIssue(
                    severity="error",
                    code="retag-target-not-eligible",
                    message=(
                        f"{service_key} cannot switch to concrete tracking: "
                        f"{item.retag_reason}"
                    ),
                    service_key=service_key,
                    stack=item.stack,
                    service=item.service,
                )
            )
            continue
        update = digest_pin_update_from_values(
            old_image=item.image,
            resolved_tag=record.provenance.resolved_tag,
            planned_digest=record.provenance.target_digest,
            services=(item.service,),
        )
        if update.final_image != record.provenance.final_image:
            issues.append(
                RetagPlanIssue(
                    severity="error",
                    code="retag-provenance-mismatch",
                    message=(
                        f"{service_key} stored provenance does not match the "
                        "planned digest-pinned image."
                    ),
                    service_key=service_key,
                    stack=item.stack,
                    service=item.service,
                )
            )
            continue
        selected.append(
            _RetagPlanUpdate(
                service_key=service_key,
                stack=record.stack,
                update=update,
                provenance=record.provenance,
            )
        )

    selected, preview_issues = _preview_retag_updates(settings, selected)
    issues.extend(preview_issues)
    compose_hashes = _compose_hashes(selected)
    status = _retag_plan_status(selected, choices, issues)
    stacks = _retag_plan_stacks(selected)
    plan = RetagPlanResponse(
        plan_id="",
        status=status,
        can_apply=status == "ready" and bool(selected),
        selected_count=len(selected),
        keep_current_count=keep_current_count,
        stacks=stacks,
        issues=issues,
        warnings=[],
    )
    plan.plan_id = _retag_plan_id(plan, updates=selected, compose_hashes=compose_hashes)
    return _RetagPlanBuild(response=plan, updates=tuple(selected))


def _retag_target_records(
    settings: WebSettings,
    *,
    github_latest_fallback: bool = False,
) -> tuple[_RetagTargetRecord, ...] | RetagTargetsResponse:
    stacks_or_response = _discover_retag_stacks(settings)
    if isinstance(stacks_or_response, RetagTargetsResponse):
        return stacks_or_response
    stacks = stacks_or_response

    known_by_service = web_database.known_digest_state_by_service(settings)
    github_latest_by_service = (
        _cached_github_latest_fallback_by_service(settings, stacks, known_by_service)
        if github_latest_fallback
        else {}
    )
    records: list[_RetagTargetRecord] = []
    for stack in stacks:
        for service_image in stack.service_images:
            service_key = _retag_service_key(stack.name, service_image.service)
            records.append(
                _retag_target_record(
                    stack,
                    service_image,
                    known_by_service.get(service_key),
                    github_latest_by_service.get(service_key),
                    github_latest_fallback=github_latest_fallback,
                )
            )

    return tuple(records)


def _discover_retag_stacks(
    settings: WebSettings,
) -> tuple[ComposeStack, ...] | RetagTargetsResponse:
    config = _effective_config(settings)
    compose = ComposeCli(runner=_command_runner(settings))
    try:
        return tuple(
            compose.discover_stacks(
                config.docker_base,
                project_base=settings.host_docker_base,
                ignore_paths=config.compose_ignore_paths,
            )
        )
    except ComposeDiscoveryError as exc:
        return RetagTargetsResponse(
            status="unavailable",
            count=0,
            warnings=[
                _safe_exception_detail(
                    settings,
                    "could not discover retag targets",
                    exc,
                )
            ],
        )


def _refresh_retag_github_latest_candidates(
    settings: WebSettings,
) -> RetagTargetsResponse | None:
    stacks_or_response = _discover_retag_stacks(settings)
    if isinstance(stacks_or_response, RetagTargetsResponse):
        return stacks_or_response
    known_by_service = web_database.known_digest_state_by_service(settings)
    targets = [
        target
        for _service_key, _service_image, target in _github_latest_fallback_targets(
            stacks_or_response,
            known_by_service,
        )
    ]
    if not targets:
        return None
    try:
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            refresh_release_notes(
                conn,
                targets,
                settings.command_env or {},
                client=GitHubClient(
                    token=(settings.command_env or {}).get("GITHUB_TOKEN", ""),
                ),
                source_resolver=release_note_source_resolver(settings),
                redact_error=lambda value: _redact_sensitive_text(settings, value),
                force=True,
            )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not refresh retag GitHub latest candidates",
                exc,
            ),
        ) from exc
    return None


def _cached_github_latest_fallback_by_service(
    settings: WebSettings,
    stacks: Sequence[ComposeStack],
    known_by_service: Mapping[str, web_database.KnownDigestState],
) -> dict[str, _RetagGitHubLatestFallback]:
    target_rows = _github_latest_fallback_targets(stacks, known_by_service)
    if not target_rows:
        return {}
    missing_cache = _RetagGitHubLatestFallback(
        warning=(
            "GitHub latest fallback is enabled, but no cached GitHub release "
            "metadata is available. Refresh candidates and try again."
        )
    )
    try:
        with closing(web_database.connect_readonly_db(settings)) as conn:
            infos = cached_release_notes(
                conn,
                [target for _service_key, _service_image, target in target_rows],
                settings.command_env or {},
                source_resolver=release_note_source_resolver(settings),
            )
    except ReadOnlyDatabaseMissing:
        return {service_key: missing_cache for service_key, _image, _target in target_rows}
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        warning = _safe_exception_detail(
            settings,
            "could not read cached GitHub latest candidates",
            exc,
        )
        return {
            service_key: _RetagGitHubLatestFallback(warning=warning)
            for service_key, _image, _target in target_rows
        }

    result: dict[str, _RetagGitHubLatestFallback] = {}
    for (service_key, service_image, _target), info in zip(target_rows, infos):
        result[service_key] = _fallback_from_release_info(
            settings,
            service_image,
            info,
        )
    return result


def _github_latest_fallback_targets(
    stacks: Sequence[ComposeStack],
    known_by_service: Mapping[str, web_database.KnownDigestState],
) -> list[tuple[str, ServiceImage, WudTarget]]:
    rows: list[tuple[str, ServiceImage, WudTarget]] = []
    for stack in stacks:
        for service_image in stack.service_images:
            service_key = _retag_service_key(stack.name, service_image.service)
            if service_key in known_by_service:
                continue
            label_value = _label_value(service_image.labels, WUD_TAG_INCLUDE_LABEL)
            tracking_tag, tracking_tag_source = _tracking_tag(
                service_image.image,
                label_value=label_value,
                provenance=None,
            )
            if tracking_tag_source == "unsupported-label" or tracking_tag != "latest":
                continue
            rows.append(
                (
                    service_key,
                    service_image,
                    _release_note_target_for_service(stack.index, service_image.image),
                )
            )
    return rows


def _fallback_from_release_info(
    settings: WebSettings,
    service_image: ServiceImage,
    info: ReleaseNoteInfo,
) -> _RetagGitHubLatestFallback:
    candidate = github_latest_candidate_from_info(info)
    if candidate is None:
        return _RetagGitHubLatestFallback(
            warning=_github_latest_info_warning(info),
        )
    if not tag_value_valid(candidate.release_tag):
        return _RetagGitHubLatestFallback(
            proposed_tag=candidate.release_tag,
            warning=(
                f"GitHub latest release tag {candidate.release_tag} is not a "
                "valid Docker tag value."
            ),
            link_label=candidate.link_label,
            link_url=candidate.link_url,
        )
    resolved_image = image_with_tag(service_image.image, candidate.release_tag)
    digest_result = DigestVerifier(
        DockerCli(runner=_command_runner(settings)),
    ).resolve_tag_digest(resolved_image)
    if not digest_result.ok or not digest_result.digest:
        reason = digest_result.reason or digest_result.status
        return _RetagGitHubLatestFallback(
            proposed_tag=candidate.release_tag,
            warning=(
                f"GitHub latest release tag {candidate.release_tag} was found, "
                f"but {resolved_image} digest could not be resolved: {reason}."
            ),
            link_label=candidate.link_label,
            link_url=candidate.link_url,
        )
    digest = digest_result.digest
    return _RetagGitHubLatestFallback(
        provenance=DigestTagProvenance(
            source_image=service_image.image,
            resolved_tag=candidate.release_tag,
            watch_tag="latest",
            target_digest=digest,
            final_image=image_with_digest(service_image.image, digest),
            provenance_source="github-latest",
            provenance_confidence="recovered",
        ),
        proposed_tag=candidate.release_tag,
        warning=(
            "GitHub latest fallback will update latest tracking to "
            f"{candidate.release_tag}."
        ),
        link_label=candidate.link_label,
        link_url=candidate.link_url,
    )


def _github_latest_info_warning(info: ReleaseNoteInfo) -> str:
    provider = str(getattr(info, "provider", ""))
    status = str(getattr(info, "status", ""))
    error = str(getattr(info, "error", ""))
    if provider == "lsio":
        return "GitHub latest fallback does not support LSIO upstream retag candidates."
    if status == "missing":
        return (
            "GitHub latest fallback is enabled, but no cached GitHub release "
            "metadata is available. Refresh candidates and try again."
        )
    if status == "unsupported":
        return error or "No supported GitHub release source was found."
    if status == "not_found":
        return "No GitHub latest release was found for this image source."
    if status == "error":
        return error or "GitHub latest release metadata could not be refreshed."
    return "GitHub latest release metadata is not ready for this service."


def _release_note_target_for_service(line_no: int, image: str) -> WudTarget:
    return WudTarget(
        line_no=line_no,
        raw=image,
        first=image,
        key=image_key(image),
        repo=repo_key(image),
        has_tag=image_has_tag(image),
        allow_repo=False,
        digest="",
        desired_tag="",
    )


def _command_runner(settings: WebSettings) -> CommandRunner:
    if settings.command_env is not None:
        return CommandRunner(env=settings.command_env)
    return CommandRunner()


def _retag_service_key(stack_name: str, service_name: str) -> str:
    return f"{stack_name}/{service_name}"


def _retag_target_record(
    stack: ComposeStack,
    service_image: ServiceImage,
    known: web_database.KnownDigestState | None,
    github_latest: _RetagGitHubLatestFallback | None,
    *,
    github_latest_fallback: bool,
) -> _RetagTargetRecord:
    service_key = _retag_service_key(stack.name, service_image.service)
    provenance = None if known is None else known.digest_provenance
    if provenance is None and github_latest is not None:
        provenance = github_latest.provenance
    known_image = "" if known is None else known.image
    item = _retag_target_item(
        service_key=service_key,
        stack=stack.name,
        service_image=service_image,
        directory=str(stack.directory),
        compose_file=stack.file,
        project_directory=(
            "" if stack.project_directory is None else str(stack.project_directory)
        ),
        known_image=known_image,
        provenance=provenance,
        github_latest=github_latest,
        github_latest_fallback=github_latest_fallback,
    )
    return _RetagTargetRecord(
        item=item,
        stack=stack,
        service_image=service_image,
        known_image=known_image,
        provenance=provenance,
    )


def _validated_choice_map(
    choices: Sequence[RetagChoiceRequest],
) -> dict[str, str]:
    values: dict[str, str] = {}
    duplicates: list[str] = []
    for item in choices:
        if item.service_key in values:
            duplicates.append(item.service_key)
            continue
        values[item.service_key] = item.choice
    if duplicates:
        duplicate_list = ", ".join(sorted(set(duplicates)))
        raise HTTPException(
            status_code=422,
            detail=f"retag choices contain duplicate service(s): {duplicate_list}",
        )
    return values


def _preview_retag_updates(
    settings: WebSettings,
    selected: Sequence[_RetagPlanUpdate],
) -> tuple[tuple[_RetagPlanUpdate, ...], list[RetagPlanIssue]]:
    issues: list[RetagPlanIssue] = []
    updated_by_key = {item.service_key: item for item in selected}
    for stack in _ordered_retag_stacks(selected):
        stack_updates = [item for item in selected if item.stack.index == stack.index]
        updated, stack_issues = _preview_retag_stack(settings, stack, stack_updates)
        issues.extend(stack_issues)
        for item in updated:
            updated_by_key[item.service_key] = item
    return (
        tuple(updated_by_key[item.service_key] for item in selected),
        issues,
    )


def _preview_retag_stack(
    settings: WebSettings,
    stack: ComposeStack,
    stack_updates: Sequence[_RetagPlanUpdate],
) -> tuple[list[_RetagPlanUpdate], list[RetagPlanIssue]]:
    issues: list[RetagPlanIssue] = []
    updated: list[_RetagPlanUpdate] = []
    try:
        _rendered, applied = render_compose_digest_pins(
            stack.directory / stack.file,
            tuple(item.update for item in stack_updates),
            stack_name=stack.name,
        )
    except Exception as exc:
        return [], _retag_preview_failed_issues(settings, stack, stack_updates, exc)

    applied_by_service = {
        _retag_service_key(stack.name, service): applied_item
        for applied_item in applied
        for service in applied_item.services
    }
    for item in stack_updates:
        applied_item = applied_by_service.get(item.service_key)
        if applied_item is None:
            issues.append(_retag_preview_empty_issue(stack, item))
            continue
        updated.append(_retag_update_with_label_rewrites(item, applied_item))
    return updated, issues


def _retag_preview_failed_issues(
    settings: WebSettings,
    stack: ComposeStack,
    stack_updates: Sequence[_RetagPlanUpdate],
    exc: Exception,
) -> list[RetagPlanIssue]:
    return [
        RetagPlanIssue(
            severity="error",
            code="retag-compose-preview-failed",
            message=_safe_exception_detail(
                settings,
                f"Could not safely preview retag for {item.service_key}",
                exc,
            ),
            service_key=item.service_key,
            stack=stack.name,
            service=_retag_update_service(item),
        )
        for item in stack_updates
    ]


def _retag_preview_empty_issue(
    stack: ComposeStack,
    item: _RetagPlanUpdate,
) -> RetagPlanIssue:
    return RetagPlanIssue(
        severity="error",
        code="retag-compose-preview-empty",
        message=f"Could not preview a Compose rewrite for {item.service_key}.",
        service_key=item.service_key,
        stack=stack.name,
        service=_retag_update_service(item),
    )


def _retag_update_with_label_rewrites(
    item: _RetagPlanUpdate,
    applied_item: AppliedDigestPinUpdate,
) -> _RetagPlanUpdate:
    return _RetagPlanUpdate(
        service_key=item.service_key,
        stack=item.stack,
        update=item.update,
        provenance=item.provenance,
        label_rewrites=tuple(
            RetagPlanLabelRewrite(
                service=rewrite.service,
                label_key=rewrite.label_key,
                current_label_value=rewrite.current_label_value,
                planned_tag=rewrite.planned_tag,
                proposed_label_value=rewrite.proposed_label_value,
                proposed_label_regex=rewrite.proposed_label_regex,
                approved=rewrite.approved,
                reason=rewrite.reason,
            )
            for rewrite in applied_item.label_rewrites
        ),
    )


def _submit_retag_apply_job(
    request: Request,
    settings: WebSettings,
    build: _RetagPlanBuild,
    wud_lock: object,
) -> ApplyJobResponse:
    state = request.app.state
    apply_condition: Condition = state.web_apply_condition
    jobs: dict[str, WebApplyJob] = state.web_apply_jobs
    executor = state.web_apply_executor
    with apply_condition:
        active_error = web_jobs._active_mutation_error_unlocked(state)
        if active_error:
            raise HTTPException(status_code=409, detail=active_error)
        job = WebApplyJob(
            id=secrets.token_urlsafe(18),
            status="queued",
            selected_line_numbers=(),
        )
        jobs[job.id] = job
        response = web_jobs._apply_job_response(job)
        apply_condition.notify_all()
        try:
            executor.submit(
                _run_retag_apply_job,
                settings,
                build,
                jobs,
                apply_condition,
                job.id,
                wud_lock,
            )
        except Exception:
            del jobs[job.id]
            apply_condition.notify_all()
            raise
        return response


def _run_retag_apply_job(
    settings: WebSettings,
    build: _RetagPlanBuild,
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    wud_lock: object,
) -> None:
    web_jobs._update_apply_job(
        jobs,
        apply_condition,
        job_id,
        status="running",
        started_at=utc_timestamp(),
    )
    run_id: int | None = None
    successful_updates: tuple[_RetagPlanUpdate, ...] = ()
    try:
        run_id = _insert_retag_audit_run(settings, build, status="running")
        successful_updates = _apply_retag_updates(
            settings,
            build,
            jobs,
            apply_condition,
            job_id,
        )
        _finish_retag_audit_run(settings, run_id, build, status="success")
        web_jobs._append_apply_job_progress(
            jobs,
            apply_condition,
            job_id,
            UpdaterProgressEvent(
                phase="completion",
                status="success",
                message="Retag changes applied.",
            ),
        )
        web_jobs._update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status="success",
            run_id=run_id,
            finished_at=utc_timestamp(),
        )
    except Exception as exc:
        if isinstance(exc, _RetagApplyFailed):
            successful_updates = exc.successful_updates
        safe_error = _safe_retag_apply_error(settings, exc)
        web_jobs._append_apply_job_progress(
            jobs,
            apply_condition,
            job_id,
            UpdaterProgressEvent(
                phase="completion",
                status="failure",
                message=safe_error,
            ),
        )
        web_jobs._update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status="failure",
            run_id=run_id,
            finished_at=utc_timestamp(),
            error=safe_error,
        )
        if run_id is not None:
            _finish_retag_audit_run(
                settings,
                run_id,
                build,
                status="failure",
                error=safe_error,
                successful_updates=successful_updates,
            )
    finally:
        close = getattr(wud_lock, "close", None)
        if close is not None:
            close()


def _apply_retag_updates(
    settings: WebSettings,
    build: _RetagPlanBuild,
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
) -> tuple[_RetagPlanUpdate, ...]:
    env = settings.command_env
    runner = CommandRunner(env=env) if env is not None else CommandRunner()
    compose = ComposeCli(runner=runner)
    docker = DockerCli(runner=runner)
    config = _effective_config(settings)
    successful_updates: list[_RetagPlanUpdate] = []
    for stack in _ordered_retag_stacks(build.updates):
        stack_updates = [item for item in build.updates if item.stack.index == stack.index]
        services = tuple(
            sorted(
                {
                    service
                    for item in stack_updates
                    for service in item.update.services
                }
            )
        )
        backup: Path | None = None
        try:
            _progress(
                jobs,
                apply_condition,
                job_id,
                "compose-digest-pin",
                "running",
                f"[{stack.name}] Writing retag Compose metadata.",
                stack=stack.name,
                services=services,
            )
            compose_path = stack.directory / stack.file
            backup = _backup_compose(compose_path)
            applied = apply_compose_digest_pins(
                compose_path,
                tuple(item.update for item in stack_updates),
                stack_name=stack.name,
            )
            if not applied:
                raise RuntimeError("no Compose image lines were retagged")
            _progress(
                jobs,
                apply_condition,
                job_id,
                "compose-digest-pin",
                "success",
                f"[{stack.name}] Compose retag metadata was written.",
                stack=stack.name,
                services=services,
            )

            _progress(
                jobs,
                apply_condition,
                job_id,
                "pull",
                "running",
                f"[{stack.name}] Pulling retagged service image(s).",
                stack=stack.name,
                services=services,
            )
            compose.pull(
                stack.directory,
                stack.file,
                services,
                project_directory=stack.project_directory,
            )
            _progress(
                jobs,
                apply_condition,
                job_id,
                "pull",
                "success",
                f"[{stack.name}] Retagged service image(s) pulled.",
                stack=stack.name,
                services=services,
            )

            _recreate_retag_services(
                compose,
                docker,
                config,
                stack,
                services,
                jobs,
                apply_condition,
                job_id,
            )
            _record_successful_retag_known_images(settings, stack_updates)
            if backup is not None:
                _delete_path(backup)
                backup = None
            successful_updates.extend(stack_updates)
        except Exception as exc:
            if backup is not None:
                try:
                    _restore_retag_compose(
                        compose,
                        docker,
                        config,
                        stack,
                        services,
                        backup,
                        jobs,
                        apply_condition,
                        job_id,
                        original_error=str(exc),
                    )
                except Exception as restore_exc:
                    raise _RetagApplyFailed(
                        str(restore_exc),
                        successful_updates,
                    ) from restore_exc
                backup = None
            raise _RetagApplyFailed(str(exc), successful_updates) from exc
    return tuple(successful_updates)


def _recreate_retag_services(
    compose: ComposeCli,
    docker: DockerCli,
    config: UpdaterConfig,
    stack: ComposeStack,
    services: Sequence[str],
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
) -> None:
    _progress(
        jobs,
        apply_condition,
        job_id,
        "recreate",
        "running",
        f"[{stack.name}] Recreating retagged service container(s).",
        stack=stack.name,
        services=services,
    )
    pre_up_error: CommandError | None = None
    if config.update_mode == "pause":
        try:
            compose.pause(
                stack.directory,
                stack.file,
                services,
                project_directory=stack.project_directory,
            )
        except CommandError:
            pass
    elif config.update_mode == "stop":
        try:
            compose.stop(
                stack.directory,
                stack.file,
                services,
                project_directory=stack.project_directory,
            )
        except CommandError as exc:
            pre_up_error = exc

    if config.update_mode == "pause":
        try:
            wait_handled = _compose_up_retag_services(compose, stack, services, config)
        except Exception:
            compose.unpause(
                stack.directory,
                stack.file,
                services,
                project_directory=stack.project_directory,
            )
            raise
        compose.unpause(
            stack.directory,
            stack.file,
            services,
            project_directory=stack.project_directory,
        )
    else:
        wait_handled = _compose_up_retag_services(compose, stack, services, config)
    if pre_up_error is not None:
        raise pre_up_error

    _progress(
        jobs,
        apply_condition,
        job_id,
        "recreate",
        "success",
        f"[{stack.name}] Retagged service container(s) recreated.",
        stack=stack.name,
        services=services,
    )
    if wait_handled:
        _progress(
            jobs,
            apply_condition,
            job_id,
            "health",
            "success",
            f"[{stack.name}] Compose reported healthy retagged service container(s).",
            stack=stack.name,
            services=services,
        )
        return
    _wait_for_retag_health(
        compose,
        docker,
        config,
        stack,
        services,
        jobs,
        apply_condition,
        job_id,
    )


def _compose_up_retag_services(
    compose: ComposeCli,
    stack: ComposeStack,
    services: Sequence[str],
    config: UpdaterConfig,
) -> bool:
    wait = (
        config.update_mode != "pause"
        and compose.up_wait_supported(
            stack.directory,
            stack.file,
            project_directory=stack.project_directory,
        )
    )
    compose.up(
        stack.directory,
        stack.file,
        services,
        wait=wait,
        wait_timeout=config.max_wait if wait else None,
        force_recreate=True,
        no_deps=True,
        project_directory=stack.project_directory,
    )
    return wait


def _wait_for_retag_health(
    compose: ComposeCli,
    docker: DockerCli,
    config: UpdaterConfig,
    stack: ComposeStack,
    services: Sequence[str],
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
) -> None:
    _progress(
        jobs,
        apply_condition,
        job_id,
        "health",
        "running",
        f"[{stack.name}] Waiting up to {config.max_wait}s for retagged service health.",
        stack=stack.name,
        services=services,
    )
    start = time.monotonic()
    if config.max_wait > 0:
        time.sleep(2)
    while True:
        cids = compose.ps_quiet(
            stack.directory,
            stack.file,
            services,
            project_directory=stack.project_directory,
        )
        ok = bool(cids)
        for cid in cids:
            summary = _first_nonblank(
                docker.try_inspect(cid, CONTAINER_SUMMARY_FORMAT)
            )
            if not summary or not _cid_is_ok(summary):
                ok = False
        elapsed = int(time.monotonic() - start)
        if ok:
            _progress(
                jobs,
                apply_condition,
                job_id,
                "health",
                "success",
                f"[{stack.name}] Retagged service health wait succeeded in {elapsed}s.",
                stack=stack.name,
                services=services,
            )
            return
        if elapsed >= config.max_wait:
            detail = _retag_health_details(compose, docker, stack, services)
            raise RuntimeError(
                f"[{stack.name}] retagged service health wait failed after {elapsed}s"
                + (f": {detail}" if detail else "")
            )
        time.sleep(2)


def _restore_retag_compose(
    compose: ComposeCli,
    docker: DockerCli,
    config: UpdaterConfig,
    stack: ComposeStack,
    services: Sequence[str],
    backup: Path,
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    *,
    original_error: str,
) -> None:
    try:
        shutil.copy2(backup, stack.directory / stack.file)
        wait_handled = _compose_up_retag_services(compose, stack, services, config)
        if not wait_handled:
            _wait_for_retag_health(
                compose,
                docker,
                config,
                stack,
                services,
                jobs,
                apply_condition,
                job_id,
            )
        _delete_path(backup)
    except Exception as rollback_exc:
        raise RuntimeError(
            f"{original_error}; compose rollback failed: {rollback_exc}; "
            f"backup retained at {backup}"
        ) from rollback_exc


def _record_successful_retag_known_images(
    settings: WebSettings,
    updates: Sequence[_RetagPlanUpdate],
) -> None:
    if not updates:
        return
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        for item in updates:
            upsert_known_image(
                conn,
                service_key=item.service_key,
                image=item.update.final_image,
                digest=digest_from_image(item.update.final_image),
                metadata_json=_json_object(
                    {
                        "source": "webui",
                        "operation": "retag",
                    }
                ),
                digest_provenance=DigestTagProvenance(
                    source_image=item.update.old_image,
                    resolved_tag=item.update.resolved_tag,
                    watch_tag=item.update.watch_tag,
                    target_digest=item.update.planned_digest,
                    final_image=item.update.final_image,
                    provenance_source="retag",
                    provenance_confidence="verified",
                ),
            )


def _insert_retag_audit_run(
    settings: WebSettings,
    build: _RetagPlanBuild,
    *,
    status: str,
) -> int:
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        return insert_update_run(
            conn,
            status=status,
            dry_run=False,
            mode="web-retag",
            wud_file=str(settings.config.wud_out_file),
            metadata_json=_json_object(_retag_audit_metadata(build, status=status)),
        )


def _finish_retag_audit_run(
    settings: WebSettings,
    run_id: int,
    build: _RetagPlanBuild,
    *,
    status: str,
    error: str = "",
    successful_updates: Sequence[_RetagPlanUpdate] = (),
) -> None:
    metadata = _retag_audit_metadata(build, status=status, error=error)
    successful_service_keys = {item.service_key for item in successful_updates}
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        now = utc_timestamp()
        for item in build.updates:
            item_status = (
                "success"
                if status == "success" or item.service_key in successful_service_keys
                else "failure"
            )
            insert_update_event(
                conn,
                run_id=run_id,
                created_at=now,
                service_name=item.update.services[0] if item.update.services else "",
                stack_name=item.stack.name,
                image=item.update.old_image,
                target_image=item.update.final_image,
                status=item_status,
                metadata_json=_json_object(
                    {
                        "source": "webui",
                        "operation": "retag",
                        "service_key": item.service_key,
                        "resolved_tag": item.update.resolved_tag,
                        "watch_tag": item.update.watch_tag,
                    }
                ),
                digest_provenance=DigestTagProvenance(
                    source_image=item.update.old_image,
                    resolved_tag=item.update.resolved_tag,
                    watch_tag=item.update.watch_tag,
                    target_digest=item.update.planned_digest,
                    final_image=item.update.final_image,
                    provenance_source="retag",
                    provenance_confidence=(
                        "verified" if item_status == "success" else "planned"
                    ),
                ),
            )
        conn.execute(
            """
            UPDATE update_runs
            SET finished_at = ?, status = ?, metadata_json = ?
            WHERE id = ?
            """,
            (now, status, _json_object(metadata), run_id),
        )
        conn.commit()


def _retag_audit_metadata(
    build: _RetagPlanBuild,
    *,
    status: str,
    error: str = "",
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source": "webui",
        "operation": "retag",
        "status": status,
        "plan_id": build.response.plan_id,
        "services": [item.service_key for item in build.updates],
        "external_recreate_required": False,
        "digest_pin_updates": [
            _retag_plan_digest_update(item).model_dump(mode="json")
            for item in build.updates
        ],
    }
    if error:
        metadata["error"] = error
    return metadata


def _safe_retag_apply_error(settings: WebSettings, exc: BaseException) -> str:
    return _safe_exception_detail(settings, "retag apply failed", exc)


def _progress(
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    phase: str,
    status: str,
    message: str,
    *,
    stack: str = "",
    services: Sequence[str] = (),
) -> None:
    web_jobs._append_apply_job_progress(
        jobs,
        apply_condition,
        job_id,
        UpdaterProgressEvent(
            phase=phase,
            status=status,
            message=message,
            stack=stack,
            services=tuple(services),
        ),
    )


def _first_nonblank(values: Sequence[str]) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""


def _retag_health_details(
    compose: ComposeCli,
    docker: DockerCli,
    stack: ComposeStack,
    services: Sequence[str],
) -> str:
    cids = compose.ps_quiet(
        stack.directory,
        stack.file,
        services,
        project_directory=stack.project_directory,
    )
    details: list[str] = []
    if not cids:
        details.append("docker compose ps -q returned no containers")
    for cid in cids:
        summary = _first_nonblank(docker.try_inspect(cid, CONTAINER_SUMMARY_FORMAT))
        if summary:
            details.append(summary)
        for output in docker.try_inspect(cid, HEALTH_LOG_FORMAT):
            if output.strip():
                details.append(output.strip())
    return "; ".join(details)


def _delete_path(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _effective_config(settings: WebSettings) -> UpdaterConfig:
    if _effective_config_loader is None:
        return settings.config
    try:
        return _effective_config_loader(settings)
    except ConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail=_safe_exception_detail(
                settings,
                "could not read effective config",
                exc,
            ),
        ) from exc


def _retag_target_item(
    *,
    service_key: str,
    stack: str,
    service_image: ServiceImage,
    directory: str,
    compose_file: str,
    project_directory: str,
    known_image: str,
    provenance: DigestTagProvenance | None,
    github_latest: _RetagGitHubLatestFallback | None,
    github_latest_fallback: bool,
) -> RetagTargetItem:
    label_value = _label_value(service_image.labels, WUD_TAG_INCLUDE_LABEL)
    tracking_tag, tracking_tag_source = _tracking_tag(
        service_image.image,
        label_value=label_value,
        provenance=provenance,
    )
    retag_available, retag_reason = _retag_eligibility(
        service_image.image,
        known_image=known_image,
        tracking_tag=tracking_tag,
        tracking_tag_source=tracking_tag_source,
        label_value=label_value,
        provenance=provenance,
    )
    choices = [KEEP_CURRENT_CHOICE]
    if retag_available:
        choices.append(SWITCH_TO_CONCRETE_CHOICE)
    proposed_tag = "" if provenance is None else provenance.resolved_tag
    final_image = "" if provenance is None else provenance.final_image
    candidate_source = "provenance" if provenance is not None else ""
    candidate_warning = ""
    candidate_link_label = ""
    candidate_link_url = ""
    if github_latest is not None:
        candidate_source = "github-latest"
        candidate_warning = github_latest.warning
        candidate_link_label = github_latest.link_label
        candidate_link_url = github_latest.link_url
        if not proposed_tag:
            proposed_tag = github_latest.proposed_tag
    elif (
        github_latest_fallback
        and provenance is None
        and tracking_tag == "latest"
        and retag_reason == "missing-provenance"
    ):
        candidate_source = "github-latest"
        candidate_warning = (
            "GitHub latest fallback is enabled, but no cached GitHub release "
            "metadata is available. Refresh candidates and try again."
        )
    return RetagTargetItem(
        service_key=service_key,
        stack=stack,
        service=service_image.service,
        image=service_image.image,
        image_repo=repo_key(service_image.image),
        current_tag=image_tag(service_image.image),
        tracking_tag=tracking_tag,
        tracking_tag_source=tracking_tag_source,
        proposed_tag=proposed_tag,
        final_image=final_image,
        candidate_source=candidate_source,
        candidate_warning=candidate_warning,
        candidate_link_label=candidate_link_label,
        candidate_link_url=candidate_link_url,
        retag_available=retag_available,
        retag_reason=retag_reason,
        choices=choices,
        label_key=WUD_TAG_INCLUDE_LABEL,
        label_value=label_value,
        directory=directory,
        compose_file=compose_file,
        project_directory=project_directory,
        digest_provenance=(
            None if provenance is None else asdict(provenance)
        ),
    )


def _tracking_tag(
    image: str,
    *,
    label_value: str,
    provenance: DigestTagProvenance | None,
) -> tuple[str, str]:
    if label_value:
        label_tag = _single_exact_tag(label_value)
        if label_tag:
            return label_tag, "label"
        return "", "unsupported-label"
    if provenance is not None and provenance.watch_tag:
        return provenance.watch_tag, "provenance"
    tag = image_tag(image)
    if tag:
        return tag, "image"
    return "", ""


def _retag_eligibility(
    image: str,
    *,
    known_image: str,
    tracking_tag: str,
    tracking_tag_source: str,
    label_value: str,
    provenance: DigestTagProvenance | None,
) -> tuple[bool, str]:
    if tracking_tag_source == "unsupported-label":
        return False, "unsupported-tracking-label"
    if tracking_tag != "latest":
        return False, "not-latest-tracking"
    if provenance is None:
        return False, "missing-provenance"
    if not _provenance_matches_image(
        image,
        known_image=known_image,
        provenance=provenance,
    ):
        return False, "stale-provenance"
    if not provenance.resolved_tag or provenance.resolved_tag == "latest":
        return False, "missing-concrete-tag"
    if not tag_value_valid(provenance.resolved_tag):
        return False, "invalid-candidate-tag"
    if not provenance.target_digest or not provenance.final_image:
        return False, "missing-final-image"
    if label_value and not _single_exact_tag(label_value):
        return False, "unsupported-tracking-label"
    return True, "eligible"


def _provenance_matches_image(
    image: str,
    *,
    known_image: str,
    provenance: DigestTagProvenance,
) -> bool:
    return image in {known_image, provenance.source_image, provenance.final_image}


def _label_value(labels: tuple[tuple[str, str], ...], key: str) -> str:
    values: Mapping[str, str] = dict(labels)
    return values.get(key, "")


def _single_exact_tag(value: str) -> str:
    normalized = compose_unescape_dollars(value)
    if tag_value_valid(normalized):
        return normalized
    if not normalized.startswith("^") or not normalized.endswith("$"):
        return ""
    tag_chars: list[str] = []
    index = 1
    end = len(normalized) - 1
    while index < end:
        char = normalized[index]
        if char == "\\":
            index += 1
            if index >= end:
                return ""
            escaped = normalized[index]
            if escaped not in _REGEX_SPECIAL_CHARS:
                return ""
            tag_chars.append(escaped)
            index += 1
            continue
        if char in _REGEX_SPECIAL_CHARS:
            return ""
        tag_chars.append(char)
        index += 1
    tag = "".join(tag_chars)
    return tag if tag_value_valid(tag) else ""
