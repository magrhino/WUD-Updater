"""WebUI diagnostics support bundle and apply preflight behavior."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from . import __version__
from . import web_jobs, web_pending, web_runs, web_settings
from .db import DatabaseError
from .plans import DryRunPlan
from .web_auth import (
    _redact_sensitive_text,
    _sanitize_support_bundle_value,
    _settings,
)
from .web_database import (
    ReadOnlyDatabaseMissing,
    connect_readonly_db,
    database_ready,
)
from .web_health import doctor_response, web_doctor_result
from .web_models import (
    ApplyPreflightCheck,
    ApplyPreflightResponse,
    DiagnosticsSupportBundleResponse,
    DoctorCheckResponse,
    DoctorCheckStatus,
    LogTail,
    WebSettings,
)


def api_diagnostics_support_bundle(request: Request) -> DiagnosticsSupportBundleResponse:
    settings = _settings(request)

    version = __version__
    settings_resp = web_settings.settings_response(settings, request)
    doctor_result = doctor_response(settings, web_doctor_result(settings, request))

    pending = web_pending.pending_response(settings, include_grouping=True)
    for item in pending.items:
        item.raw = ""
    if pending.grouping:
        for group in pending.grouping.groups:
            for gi in group.items:
                gi.raw = ""
        for ui in pending.grouping.unmatched:
            ui.raw = ""

    last_run = None
    diagnostics_warnings: list[str] = []
    try:
        with closing(connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM update_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchall()
            if rows:
                last_run = web_runs._run_summary_from_row(rows[0])
    except ReadOnlyDatabaseMissing as exc:
        diagnostics_warnings.append(f"last run status unavailable: {exc}")
    except HTTPException as exc:
        diagnostics_warnings.append(f"last run status unavailable: {exc.detail}")
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        diagnostics_warnings.append(f"last run status unavailable: {exc}")

    discovery_warnings = list(pending.warnings)

    log_tail = None
    if last_run and last_run.log_file:
        try:
            log_path = web_runs._safe_log_path(settings, last_run.log_file)
            if log_path is None:
                log_tail = LogTail(exists=False, content="", truncated=False)
            else:
                log_tail = web_runs._read_log_tail(
                    log_path,
                    web_jobs.DEFAULT_JOB_LOG_TAIL_BYTES,
                )
        except HTTPException as exc:
            diagnostics_warnings.append(f"log tail unavailable: {exc.detail}")

    bundle = DiagnosticsSupportBundleResponse(
        wud_updater_version=version,
        settings=settings_resp,
        doctor_result=doctor_result,
        pending_summary=pending,
        last_run_status=last_run,
        diagnostics_warnings=diagnostics_warnings,
        discovery_warnings=discovery_warnings,
        log_tail=log_tail,
    )
    return DiagnosticsSupportBundleResponse.model_validate(
        _sanitize_support_bundle_value(settings, bundle.model_dump(mode="json"))
    )


def apply_preflight_response(
    settings: WebSettings,
    request: Request,
    plan: DryRunPlan,
) -> ApplyPreflightResponse:
    doctor = doctor_response(settings, web_doctor_result(settings, request))
    doctor_checks = doctor.checks
    checks = [
        _docker_reachable_apply_preflight_check(settings, doctor_checks),
        _doctor_apply_preflight_check(
            settings,
            "compose-renders",
            "Compose renders",
            _compose_render_checks(doctor_checks, plan),
            missing_detail="Compose rendering readiness was not reported.",
        ),
        _doctor_apply_preflight_check(
            settings,
            "wud-file-writable",
            "WUD file writable",
            _doctor_checks_by_code(
                doctor_checks,
                {"wud-out-file-directory", "wud-out-file"},
            ),
            missing_detail="WUD output file readiness was not reported.",
        ),
        _database_apply_preflight_check(settings),
        _doctor_apply_preflight_check(
            settings,
            "logs-writable",
            "Logs writable",
            _doctor_checks_by_code(doctor_checks, {"wud-log-dir"}),
            missing_detail="Log directory readiness was not reported.",
        ),
        _mutation_apply_preflight_check(settings),
        _bind_mount_apply_preflight_check(settings, plan),
        _selected_services_apply_preflight_check(settings, plan),
    ]
    failures = sum(1 for check in checks if check.status == "FAIL")
    warnings = sum(1 for check in checks if check.status == "WARN")
    return ApplyPreflightResponse(
        ok=failures == 0,
        failures=failures,
        warnings=warnings,
        checks=checks,
    )


def _doctor_checks_by_code(
    checks: Sequence[DoctorCheckResponse],
    codes: set[str] | frozenset[str],
) -> list[DoctorCheckResponse]:
    return [check for check in checks if check.code in codes]


def _compose_render_checks(
    checks: Sequence[DoctorCheckResponse],
    plan: DryRunPlan,
) -> list[DoctorCheckResponse]:
    render_checks = [
        check
        for check in checks
        if check.code == "compose-discovery" or check.code.startswith("compose-config")
    ]
    selected_compose_labels = {
        f"compose config {Path(stack.directory) / stack.compose_file}"
        for stack in plan.stacks
    }
    if not selected_compose_labels:
        return render_checks
    return [
        check for check in render_checks if check.name in selected_compose_labels
    ]


def _docker_reachable_apply_preflight_check(
    settings: WebSettings,
    checks: Sequence[DoctorCheckResponse],
) -> ApplyPreflightCheck:
    source_checks = _doctor_checks_by_code(
        checks,
        {
            "docker-endpoint",
            "docker-socket",
            "docker-daemon-version",
            "docker-daemon-info",
            "docker-container-listing",
        },
    )
    present = {check.code for check in source_checks}
    missing = [
        code.replace("-", " ")
        for code in (
            "docker-daemon-version",
            "docker-daemon-info",
            "docker-container-listing",
        )
        if code not in present
    ]
    if not present.intersection({"docker-endpoint", "docker-socket"}):
        missing.insert(0, "docker socket or endpoint")
    missing_detail = (
        "Missing Docker readiness check(s): " + ", ".join(missing) if missing else ""
    )
    if missing_detail:
        return ApplyPreflightCheck(
            status="FAIL",
            code="docker-reachable",
            label="Docker reachable",
            detail=_redact_sensitive_text(settings, missing_detail),
            source_check_codes=[check.code for check in source_checks],
        )
    return _doctor_apply_preflight_check(
        settings,
        "docker-reachable",
        "Docker reachable",
        source_checks,
        missing_detail=missing_detail,
    )


def _doctor_apply_preflight_check(
    settings: WebSettings,
    code: str,
    label: str,
    source_checks: Sequence[DoctorCheckResponse],
    *,
    missing_detail: str,
) -> ApplyPreflightCheck:
    source_check_codes = [check.code for check in source_checks]
    if not source_checks:
        return ApplyPreflightCheck(
            status="FAIL",
            code=code,
            label=label,
            detail=_redact_sensitive_text(
                settings,
                missing_detail or "No readiness check was reported.",
            ),
            source_check_codes=source_check_codes,
        )
    status = _aggregate_apply_preflight_status(source_checks)
    return ApplyPreflightCheck(
        status=status,
        code=code,
        label=label,
        detail=(
            ""
            if status == "PASS"
            else _apply_preflight_check_detail(settings, source_checks, status)
        ),
        source_check_codes=source_check_codes,
    )


def _aggregate_apply_preflight_status(
    checks: Sequence[DoctorCheckResponse],
) -> DoctorCheckStatus:
    if any(check.status == "FAIL" for check in checks):
        return "FAIL"
    if any(check.status == "WARN" for check in checks):
        return "WARN"
    return "PASS"


def _apply_preflight_check_detail(
    settings: WebSettings,
    checks: Sequence[DoctorCheckResponse],
    status: DoctorCheckStatus,
) -> str:
    problems = [check for check in checks if check.status == status]
    if not problems and status == "WARN":
        problems = [check for check in checks if check.status == "FAIL"]
    if not problems:
        return ""
    first = problems[0]
    detail = first.detail or first.name
    if len(problems) > 1:
        detail = f"{detail}; +{len(problems) - 1} more"
    return _redact_sensitive_text(settings, detail)


def _mutation_apply_preflight_check(settings: WebSettings) -> ApplyPreflightCheck:
    if settings.mutations_enabled:
        return ApplyPreflightCheck(
            status="PASS",
            code="mutations-enabled",
            label="Mutations enabled",
            source_check_codes=["webui-mutation-gate"],
        )
    return ApplyPreflightCheck(
        status="FAIL",
        code="mutations-enabled",
        label="Mutations enabled",
        detail="Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.",
        source_check_codes=["webui-mutation-gate"],
    )


def _database_apply_preflight_check(settings: WebSettings) -> ApplyPreflightCheck:
    db_ready, db_warning = database_ready(settings)
    if db_ready:
        return ApplyPreflightCheck(
            status="PASS",
            code="database-ready",
            label="Database ready",
            source_check_codes=["webui-database"],
        )

    path = settings.config.db_path
    if str(path) != ":memory:" and not path.exists():
        parent = path.parent
        if parent.is_dir() and os.access(parent, os.W_OK | os.X_OK):
            return ApplyPreflightCheck(
                status="PASS",
                code="database-ready",
                label="Database ready",
                source_check_codes=["webui-database"],
            )

    return ApplyPreflightCheck(
        status="FAIL",
        code="database-ready",
        label="Database ready",
        detail=_redact_sensitive_text(settings, db_warning),
        source_check_codes=["webui-database"],
    )


def _bind_mount_apply_preflight_check(
    settings: WebSettings,
    plan: DryRunPlan,
) -> ApplyPreflightCheck:
    issues = [
        issue for issue in plan.issues if issue.code == "bind-mount-path-invalid"
    ]
    if not issues:
        return ApplyPreflightCheck(
            status="PASS",
            code="bind-mounts-safe",
            label="Bind mounts safe",
            source_check_codes=["bind-mount-path-invalid"],
        )
    return ApplyPreflightCheck(
        status="FAIL",
        code="bind-mounts-safe",
        label="Bind mounts safe",
        detail=_apply_preflight_issue_detail(settings, issues),
        source_check_codes=["bind-mount-path-invalid"],
    )


def _selected_services_apply_preflight_check(
    settings: WebSettings,
    plan: DryRunPlan,
) -> ApplyPreflightCheck:
    if (
        plan.status == "ready"
        and not plan.skipped
        and plan.summary.matched_target_count == plan.summary.target_count
        and plan.summary.service_count > 0
    ):
        return ApplyPreflightCheck(
            status="PASS",
            code="selected-services-matched",
            label="Selected services matched",
            source_check_codes=["selected-services"],
        )

    detail = "Selected updates are not ready to apply."
    if plan.status == "empty":
        detail = "No selected services need changes."
    elif plan.skipped:
        detail = plan.skipped[0].reason
    elif plan.issues:
        detail = _apply_preflight_issue_detail(settings, plan.issues)
    elif plan.summary.matched_target_count != plan.summary.target_count:
        detail = (
            f"{plan.summary.matched_target_count} of "
            f"{plan.summary.target_count} selected target(s) matched services."
        )

    return ApplyPreflightCheck(
        status="FAIL",
        code="selected-services-matched",
        label="Selected services matched",
        detail=_redact_sensitive_text(settings, detail),
        source_check_codes=["selected-services"],
    )


def _apply_preflight_issue_detail(
    settings: WebSettings,
    issues: Sequence[Any],
) -> str:
    if not issues:
        return ""
    first = issues[0]
    detail = str(getattr(first, "message", "") or getattr(first, "reason", ""))
    hint = str(getattr(first, "hint", "") or "")
    if hint:
        detail = f"{detail} {hint}".strip()
    if len(issues) > 1:
        detail = f"{detail}; +{len(issues) - 1} more"
    return _redact_sensitive_text(settings, detail)
