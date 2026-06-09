"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time as time
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import replace
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import (
    __version__,
    web_diagnostics,
    web_health,
    web_jobs,
    web_onboarding,
    web_pending,
    web_plans,
    web_release_notes,
    web_scheduler,
    web_self_update,
)
from .config import (
    COMPOSE_IGNORE_PATHS_ENV,
    DEFAULT_COMPOSE_IGNORE_PATHS,
    DEFAULT_DIGEST_PIN_UPDATES,
    DEFAULT_LOCK_TIMEOUT,
    DEFAULT_MAX_WAIT,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_MODE,
    DIGEST_PIN_UPDATES_ENV,
    ConfigError,
    UpdaterConfig,
    format_compose_ignore_paths,
    load_config,
    parse_bool_env,
    parse_compose_ignore_paths,
)
from .db import (
    DatabaseError,
    open_db,
    init_db,
    utc_timestamp,
)
from .images import (
    repo_key,
    tag_value_valid,
)
from .updater import js_regex_escape
from .web_database import (
    ReadOnlyDatabaseMissing,
    connect_readonly_db as _connect_readonly_db,
    database_ready as _database_ready,
)
from .web_onboarding import ONBOARDING_DISMISSED_AT_KEY

from .web_models import (
    APPLY_JOB_PROGRESS_STATUSES as APPLY_JOB_PROGRESS_STATUSES,
    ApplyJobLogResponse as ApplyJobLogResponse,
    ApplyJobProgressEvent as ApplyJobProgressEvent,
    ApplyJobProgressStatus as ApplyJobProgressStatus,
    ApplyJobResponse,
    ApplyJobStatus as ApplyJobStatus,
    ApplyPreflightCheck as ApplyPreflightCheck,
    ApplyPreflightResponse as ApplyPreflightResponse,
    AuthSessionResponse,
    AutoUpdatePolicy as AutoUpdatePolicy,
    AutoUpdateSelection as AutoUpdateSelection,
    ContainerRestartResponse,
    CoreUpdateTourResponse,
    CoreUpdateTourStatus as CoreUpdateTourStatus,
    CoreUpdateTourStep as CoreUpdateTourStep,
    CoreUpdateTourUpdateRequest as CoreUpdateTourUpdateRequest,
    CreateSnoozeOperation,
    CsrfResponse,
    DEFAULT_CORE_UPDATE_TOUR_STEP as DEFAULT_CORE_UPDATE_TOUR_STEP,
    DeleteServicePolicyOperation,
    DeleteSnoozeOperation,
    DiagnosticsSupportBundleResponse,
    DoctorCheckResponse as DoctorCheckResponse,
    DoctorCheckStatus as DoctorCheckStatus,
    DoctorResponse,
    DoctorSuggestionResponse as DoctorSuggestionResponse,
    HealthResponse,
    LogTail,
    ManagedSettingEntry,
    ManagedSettingsUpdateRequest,
    ManagedSettingsUpdateResponse,
    OnboardingChecklistItem as OnboardingChecklistItem,
    OnboardingChecklistResponse,
    OnboardingDismissResponse,
    OnboardingDocLink as OnboardingDocLink,
    PendingCleanupResponse,
    PendingRemovalPlanResponse,
    PendingResponse,
    PendingUpdateRecord,
    PlanResponse,
    ReadyResponse,
    ReleaseNotesResponse,
    RunDetail,
    RunEventRecord,
    RunLogResponse,
    RunSummary,
    SecretSettingStatus,
    SelfUpdateApplyResponse,
    SelfUpdatePlanResponse,
    SelfUpdatePrepareResponse,
    SelfUpdateResponse,
    ServicePolicyRecord,
    SetTagExclusionStatusOperation,
    SettingsEntry,
    SettingsEntrySource,
    SettingsResponse,
    SetupStatusResponse,
    SnoozeRecord,
    SnoozeState,
    StateOperation,
    StateOperationResponse,
    StatusResponse,
    TERMINAL_APPLY_JOB_STATUSES as TERMINAL_APPLY_JOB_STATUSES,
    TagExclusionRuleRecord,
    TagExclusionStatusFilter,
    UpdateTargetsResponse,
    UpsertServicePolicyOperation,
    UpsertTagExclusionOperation,
    WebApplyJob as WebApplyJob,
    WebApplyJobProgressEvent as WebApplyJobProgressEvent,
    WebSettings,
)
from .web_auth import (
    SENSITIVE_ENV_KEYS,
    SESSION_COOKIE,
    WebAdminResetError,
    WebConfigError,
    _bearer_token_valid,
    _delete_web_setting,
    _immediate_transaction,
    _parse_allowed_hosts,
    _parse_bool,
    _parse_origins,
    _parse_public_origin,
    _parse_secure_cookie_mode,
    _parse_trusted_proxies,
    _prepare_web_auth_state,
    _print_setup_claim,
    _reset_admin_url,
    _safe_exception_detail,
    _sanitize_support_bundle_value,
    _secure_cookie,
    _set_web_setting,
    _setup_required,
    _settings,
    _normalize_username,
    _validate_bind_host_allowed,
    _validate_startup_auth,
    _validation_exception_handler,
    _web_setting,
    _web_setting_or_none,
    api_auth_csrf,
    api_auth_login,
    api_auth_logout,
    api_auth_reset_admin_claim,
    api_auth_session,
    api_setup_claim,
    api_setup_status,
    issue_admin_recovery_claim,
    request_safety_middleware,
    require_auth,
)
from .web_auth import (
    CSRF_COOKIE as CSRF_COOKIE,
    CSRF_HEADER as CSRF_HEADER,
    LOGIN_THROTTLE_COOLDOWN_SECONDS as LOGIN_THROTTLE_COOLDOWN_SECONDS,
    LOGIN_THROTTLE_MAX_CLIENT_ENTRIES as LOGIN_THROTTLE_MAX_CLIENT_ENTRIES,
    LOGIN_THROTTLE_MAX_ENTRIES as LOGIN_THROTTLE_MAX_ENTRIES,
    LOGIN_THROTTLE_MAX_FAILURES as LOGIN_THROTTLE_MAX_FAILURES,
    PASSWORD_HASHER as PASSWORD_HASHER,
    RESET_ADMIN_CLAIM_EXPIRES_KEY as RESET_ADMIN_CLAIM_EXPIRES_KEY,
    RESET_ADMIN_CLAIM_HASH_KEY as RESET_ADMIN_CLAIM_HASH_KEY,
    RESET_ADMIN_CLAIM_USER_ID_KEY as RESET_ADMIN_CLAIM_USER_ID_KEY,
    SESSION_MAX_AGE_SECONDS as SESSION_MAX_AGE_SECONDS,
    SETUP_CLAIM_EXPIRES_KEY as SETUP_CLAIM_EXPIRES_KEY,
    SETUP_CLAIM_HASH_KEY as SETUP_CLAIM_HASH_KEY,
    _claim_initial_admin as _claim_initial_admin,
    _record_login_failure as _record_login_failure,
    _session_user as _session_user,
)

# Compatibility re-exports for callers that imported WebUI schemas from this
# module before web_models.py became their canonical owner.
from .web_models import (
    AdminRecoveryClaim as AdminRecoveryClaim,
    ApplyPlanRequest as ApplyPlanRequest,
    AutoUpdateDay as AutoUpdateDay,
    DigestPinLabelRewriteApprovalRequest as DigestPinLabelRewriteApprovalRequest,
    LineNumber as LineNumber,
    LoginRequest as LoginRequest,
    LoginThrottleEntry as LoginThrottleEntry,
    ManagedSettingSource as ManagedSettingSource,
    PASSWORD_MIN_LENGTH as PASSWORD_MIN_LENGTH,
    PendingCleanupLine as PendingCleanupLine,
    PendingCleanupRemovedLine as PendingCleanupRemovedLine,
    PendingCleanupRequest as PendingCleanupRequest,
    PendingDiagnostic as PendingDiagnostic,
    PendingGroupedItem as PendingGroupedItem,
    PendingGroupingStatus as PendingGroupingStatus,
    PendingGrouping as PendingGrouping,
    PendingItem as PendingItem,
    PendingRemovalPlanLine as PendingRemovalPlanLine,
    PendingRemovalPlanRequest as PendingRemovalPlanRequest,
    PendingRemovalRequest as PendingRemovalRequest,
    PendingStackGroup as PendingStackGroup,
    PlanAction as PlanAction,
    PlanCleanup as PlanCleanup,
    PlanCleanupItem as PlanCleanupItem,
    PlanDigestPinLabelRewrite as PlanDigestPinLabelRewrite,
    PlanDigestPinUpdate as PlanDigestPinUpdate,
    PlanIssue as PlanIssue,
    PlanLine as PlanLine,
    PlanSkipped as PlanSkipped,
    PlanStack as PlanStack,
    PlanStatus as PlanStatus,
    PlanSummary as PlanSummary,
    PlanTagUpdate as PlanTagUpdate,
    PlanTarget as PlanTarget,
    PlanRequest as PlanRequest,
    ReleaseNoteInfo as ReleaseNoteInfo,
    ReleaseNoteLink as ReleaseNoteLink,
    ResetAdminClaimRequest as ResetAdminClaimRequest,
    ContainerRestartRequest as ContainerRestartRequest,
    SELF_UPDATE_RELEASE_NOTES_CAP as SELF_UPDATE_RELEASE_NOTES_CAP,
    SelfUpdateAuditStatus as SelfUpdateAuditStatus,
    SelfUpdatePrepareRequest as SelfUpdatePrepareRequest,
    SelfUpdateReleaseNote as SelfUpdateReleaseNote,
    SelfUpdateRequest as SelfUpdateRequest,
    SelfUpdateStatus as SelfUpdateStatus,
    SelfUpdateStrategy as SelfUpdateStrategy,
    ServicePolicyUpdateMode as ServicePolicyUpdateMode,
    TagExclusionMatchType as TagExclusionMatchType,
    TagExclusionScope as TagExclusionScope,
    TagExclusionStatus as TagExclusionStatus,
    TagOverrideRequest as TagOverrideRequest,
    UpdateTargetItem as UpdateTargetItem,
    UpdateTargetsStatus as UpdateTargetsStatus,
    SetupClaimRequest as SetupClaimRequest,
    WebSelfUpdatePlan as WebSelfUpdatePlan,
)


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 7417
DEFAULT_RUN_LIMIT = 50
DEFAULT_LOG_TAIL_BYTES = 262_144
DEFAULT_JOB_LOG_TAIL_BYTES = web_jobs.DEFAULT_JOB_LOG_TAIL_BYTES
MAX_LOG_TAIL_BYTES = 1_048_576
MANAGED_THEME_PREFERENCE_KEY = "theme_preference"
MANAGED_THEME_PREFERENCE_DB_KEY = "ui.theme_preference"
MANAGED_ONBOARDING_CHECKLIST_KEY = "onboarding_checklist"
MANAGED_COMPOSE_IGNORE_PATHS_KEY = "compose_ignore_paths"
MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY = "compose.ignore_paths"
MANAGED_DIGEST_PIN_UPDATES_KEY = "digest_pin_updates"
MANAGED_DIGEST_PIN_UPDATES_DB_KEY = "compose.digest_pin_updates"
THEME_PREFERENCE_VALUES = ("system", "light", "dark")
ONBOARDING_CHECKLIST_VALUES = ("visible", "dismissed")
DIGEST_PIN_UPDATES_VALUES = ("false", "true")
JOB_STREAM_HEARTBEAT_SECONDS = web_jobs.JOB_STREAM_HEARTBEAT_SECONDS
JOB_STREAM_LOG_POLL_SECONDS = web_jobs.JOB_STREAM_LOG_POLL_SECONDS
AUTO_UPDATE_POLL_SECONDS = web_scheduler.AUTO_UPDATE_POLL_SECONDS
AUTO_UPDATE_GRACE_SECONDS = web_scheduler.AUTO_UPDATE_GRACE_SECONDS
AUTO_UPDATE_DAYS = web_scheduler.AUTO_UPDATE_DAYS
AutoUpdateScheduleReservationError = (
    web_scheduler.AutoUpdateScheduleReservationError
)
LOGGER = logging.getLogger(__name__)

# Compatibility re-exports for route handlers and helpers extracted from this
# module. New code should import from the owning web_* module directly.
api_pending = web_pending.api_pending
api_update_targets = web_pending.api_update_targets
api_pending_cleanup = web_pending.api_pending_cleanup
api_pending_removal_plan = web_pending.api_pending_removal_plan
api_pending_removal = web_pending.api_pending_removal
_pending_response = web_pending.pending_response
_update_targets_response = web_pending.update_targets_response
_pending_removal_plan = web_pending.pending_removal_plan
_parse_pending_file = web_pending.parse_pending_file

api_create_plan = web_plans.api_create_plan
api_create_job = web_plans.api_create_job
api_apply_plan = web_plans.api_apply_plan
_build_web_plan = web_plans.build_web_plan
_tag_overrides_from_payload = web_plans.tag_overrides_from_payload
_digest_pin_label_rewrite_approvals_from_payload = (
    web_plans.digest_pin_label_rewrite_approvals_from_payload
)
_plan_can_apply = web_plans.plan_can_apply
_plan_response = web_plans.plan_response
_submit_apply_job = web_plans.submit_apply_job

api_release_notes = web_release_notes.api_release_notes
api_refresh_release_notes = web_release_notes.api_refresh_release_notes
_release_notes_response = web_release_notes.release_notes_response
_release_note_source_resolver = web_release_notes.release_note_source_resolver

def create_app(
    settings: WebSettings | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    """Create the read-only WebUI ASGI app."""

    active_settings = settings or load_web_settings(environ)
    app = FastAPI(
        title="WUD-Updater WebUI",
        version=__version__,
        docs_url=None,
        openapi_url=None,
        redoc_url=None,
    )
    app.state.web_settings = active_settings
    app.state.web_setup_claim = ""
    web_jobs.initialize_apply_job_state(app.state)
    app.state.web_login_throttle_lock = Lock()
    app.state.web_login_throttle = {}
    app.state.web_login_client_throttle = {}
    web_scheduler.initialize_auto_update_scheduler_state(app.state)
    if not active_settings.dev_no_auth:
        app.state.web_setup_claim = _prepare_web_auth_state(active_settings)
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,
    )

    if active_settings.mutations_enabled:
        app.state.web_auto_update_thread = web_scheduler.start_auto_update_scheduler(
            app,
            active_settings,
            effective_config_loader=_effective_config,
        )

    def shutdown_apply_executor() -> None:
        web_scheduler.shutdown_auto_update_scheduler_state(app.state)
        web_jobs.shutdown_apply_job_state(app.state)

    router_shutdown = getattr(getattr(app, "router", None), "on_shutdown", None)
    if isinstance(router_shutdown, list):
        router_shutdown.append(shutdown_apply_executor)

    @app.middleware("http")
    async def web_request_safety(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await request_safety_middleware(request, call_next, active_settings)

    web_health.configure(
        effective_config_loader=_effective_config,
        static_spa_available_checker=_static_spa_available,
    )
    web_pending.configure(effective_config_loader=_effective_config)
    web_plans.configure(effective_config_loader=_effective_config)
    web_diagnostics.configure(
        settings_response_builder=api_settings,
        pending_response_builder=(
            lambda settings, include_grouping: web_pending.pending_response(
                settings,
                include_grouping=include_grouping,
            )
        ),
        run_summary_builder=_run_summary_from_row,
        safe_log_path=_safe_log_path,
        read_log_tail=_read_log_tail,
        default_job_log_tail_bytes=DEFAULT_JOB_LOG_TAIL_BYTES,
    )

    app.add_api_route(
        "/healthz",
        web_health.api_healthz,
        methods=["GET"],
        response_model=HealthResponse,
    )
    app.add_api_route(
        "/readyz",
        web_health.api_readyz,
        methods=["GET"],
        response_model=ReadyResponse,
    )

    setup_router = APIRouter(prefix="/api/v1/setup")
    setup_router.add_api_route(
        "/status",
        api_setup_status,
        methods=["GET"],
        response_model=SetupStatusResponse,
    )
    setup_router.add_api_route(
        "/claim",
        api_setup_claim,
        methods=["POST"],
        response_model=AuthSessionResponse,
    )
    app.include_router(setup_router)

    auth_router = APIRouter(prefix="/api/v1/auth")
    auth_router.add_api_route(
        "/csrf",
        api_auth_csrf,
        methods=["GET"],
        response_model=CsrfResponse,
    )
    auth_router.add_api_route(
        "/login",
        api_auth_login,
        methods=["POST"],
        response_model=AuthSessionResponse,
    )
    auth_router.add_api_route(
        "/reset-admin/claim",
        api_auth_reset_admin_claim,
        methods=["POST"],
        response_model=AuthSessionResponse,
    )
    auth_router.add_api_route(
        "/logout",
        api_auth_logout,
        methods=["POST"],
        response_model=AuthSessionResponse,
    )
    auth_router.add_api_route(
        "/session",
        api_auth_session,
        methods=["GET"],
        response_model=AuthSessionResponse,
    )
    app.include_router(auth_router)

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    web_self_update.configure(
        effective_config_loader=_effective_config,
        plan_response_builder=web_plans.plan_response,
    )
    router.add_api_route(
        "/status",
        api_status,
        methods=["GET"],
        response_model=StatusResponse,
    )
    router.add_api_route(
        "/settings",
        api_settings,
        methods=["GET"],
        response_model=SettingsResponse,
    )
    router.add_api_route(
        "/settings/managed",
        api_update_managed_settings,
        methods=["POST"],
        response_model=ManagedSettingsUpdateResponse,
    )
    router.add_api_route(
        "/settings/managed",
        api_post_only_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/doctor",
        web_health.api_doctor,
        methods=["POST"],
        response_model=DoctorResponse,
    )
    router.add_api_route(
        "/doctor",
        api_post_only_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/ready",
        web_health.api_ready,
        methods=["GET"],
        response_model=ReadyResponse,
    )
    router.add_api_route(
        "/onboarding/checklist",
        web_onboarding.api_onboarding_checklist,
        methods=["POST"],
        response_model=OnboardingChecklistResponse,
    )
    router.add_api_route(
        "/onboarding/checklist",
        api_post_only_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/onboarding/dismiss",
        web_onboarding.api_onboarding_dismiss,
        methods=["POST"],
        response_model=OnboardingDismissResponse,
    )
    router.add_api_route(
        "/onboarding/dismiss",
        api_post_only_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/onboarding/core-update-tour",
        web_onboarding.api_core_update_tour,
        methods=["GET"],
        response_model=CoreUpdateTourResponse,
    )
    router.add_api_route(
        "/onboarding/core-update-tour",
        web_onboarding.api_update_core_update_tour,
        methods=["POST"],
        response_model=CoreUpdateTourResponse,
    )
    router.add_api_route(
        "/pending",
        web_pending.api_pending,
        methods=["GET"],
        response_model=PendingResponse,
    )
    router.add_api_route(
        "/update-targets",
        web_pending.api_update_targets,
        methods=["GET"],
        response_model=UpdateTargetsResponse,
    )
    router.add_api_route(
        "/pending/cleanup",
        web_pending.api_pending_cleanup,
        methods=["POST"],
        response_model=PendingCleanupResponse,
    )
    router.add_api_route(
        "/pending/removal-plan",
        web_pending.api_pending_removal_plan,
        methods=["POST"],
        response_model=PendingRemovalPlanResponse,
    )
    router.add_api_route(
        "/pending/removal",
        web_pending.api_pending_removal,
        methods=["POST"],
        response_model=PendingCleanupResponse,
    )
    router.add_api_route(
        "/release-notes",
        web_release_notes.api_release_notes,
        methods=["GET"],
        response_model=ReleaseNotesResponse,
    )
    router.add_api_route(
        "/release-notes/refresh",
        web_release_notes.api_refresh_release_notes,
        methods=["POST"],
        response_model=ReleaseNotesResponse,
    )
    router.add_api_route(
        "/service-policies",
        api_service_policies,
        methods=["GET"],
        response_model=list[ServicePolicyRecord],
    )
    router.add_api_route(
        "/snoozes",
        api_snoozes,
        methods=["GET"],
        response_model=list[SnoozeRecord],
    )
    router.add_api_route(
        "/diagnostics/support-bundle",
        web_diagnostics.api_diagnostics_support_bundle,
        methods=["GET"],
        response_model=DiagnosticsSupportBundleResponse,
    )
    router.add_api_route(
        "/tag-exclusions",
        api_tag_exclusions,
        methods=["GET"],
        response_model=list[TagExclusionRuleRecord],
    )
    router.add_api_route(
        "/state/operations",
        api_state_operation,
        methods=["POST"],
        response_model=StateOperationResponse,
    )
    router.add_api_route(
        "/self-update",
        web_self_update.api_self_update,
        methods=["GET"],
        response_model=SelfUpdateResponse,
    )
    router.add_api_route(
        "/self-update/plan",
        web_self_update.api_plan_self_update,
        methods=["POST"],
        response_model=SelfUpdatePlanResponse,
    )
    router.add_api_route(
        "/self-update/prepare",
        web_self_update.api_prepare_self_update,
        methods=["POST"],
        response_model=SelfUpdatePrepareResponse,
    )
    router.add_api_route(
        "/self-update",
        web_self_update.api_apply_self_update,
        methods=["POST"],
        response_model=SelfUpdateApplyResponse,
    )
    router.add_api_route(
        "/container/restart",
        web_self_update.api_restart_container,
        methods=["POST"],
        response_model=ContainerRestartResponse,
        status_code=202,
    )
    router.add_api_route(
        "/container/restart",
        api_post_only_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/plans",
        web_plans.api_create_plan,
        methods=["POST"],
        response_model=PlanResponse,
    )
    router.add_api_route(
        "/jobs",
        web_plans.api_create_job,
        methods=["POST"],
        response_model=ApplyJobResponse,
        status_code=202,
    )
    router.add_api_route(
        "/jobs/{job_id}",
        api_job,
        methods=["GET"],
        response_model=ApplyJobResponse,
    )
    router.add_api_route(
        "/jobs/{job_id}/stream",
        api_job_stream,
        methods=["GET"],
    )
    router.add_api_route(
        "/plans/apply",
        web_plans.api_apply_plan,
        methods=["POST"],
        response_model=ApplyJobResponse,
        status_code=202,
    )
    router.add_api_route(
        "/apply-jobs/{job_id}",
        api_apply_job,
        methods=["GET"],
        response_model=ApplyJobResponse,
    )
    router.add_api_route(
        "/runs",
        api_runs,
        methods=["GET"],
        response_model=list[RunSummary],
    )
    router.add_api_route(
        "/runs/{run_id}",
        api_run_detail,
        methods=["GET"],
        response_model=RunDetail,
    )
    router.add_api_route(
        "/runs/{run_id}/log",
        api_run_log,
        methods=["GET"],
        response_model=RunLogResponse,
    )
    app.include_router(router)
    _mount_static_spa_if_present(app, active_settings)
    return app


def load_web_settings(
    environ: Mapping[str, str] | None = None,
    *,
    static_dir: str | Path | None = None,
) -> WebSettings:
    env = os.environ if environ is None else environ
    config = load_config(env)
    configured_static = static_dir or env.get("WUD_WEB_STATIC_DIR") or None
    public_origin = _parse_public_origin(env.get("WUD_WEB_PUBLIC_ORIGIN", ""))
    host_docker_base = _parse_host_docker_base(env, config)
    return WebSettings(
        config=config,
        auth_token=env.get("WUD_WEB_TOKEN", ""),
        dev_no_auth=_parse_bool(env.get("WUD_WEB_DEV_NO_AUTH"), default=False),
        allowed_origins=_parse_origins(env.get("WUD_WEB_ALLOWED_ORIGINS", "")),
        public_origin=public_origin,
        allowed_hosts=_parse_allowed_hosts(
            env.get("WUD_WEB_ALLOWED_HOSTS", ""),
            public_origin=public_origin,
            bind_host=env.get("WUD_WEB_HOST", DEFAULT_WEB_HOST),
        ),
        trusted_proxies=_parse_trusted_proxies(
            env.get("WUD_WEB_TRUSTED_PROXIES", "")
        ),
        secure_cookies=_parse_secure_cookie_mode(
            env.get("WUD_WEB_SECURE_COOKIES", "auto")
        ),
        mutations_enabled=_parse_bool(
            env.get("WUD_WEB_MUTATIONS_ENABLED"),
            default=False,
        ),
        static_dir=_resolve_static_dir(configured_static),
        host_docker_base=host_docker_base,
        restart_container=_resolve_restart_container(env),
        command_env=dict(env),
    )


def run_web_from_namespace(args: object) -> int:
    if getattr(args, "web_command", None) == "reset-admin":
        return run_web_reset_admin_from_namespace(args)
    if getattr(args, "user", None):
        print("--user is only valid with web reset-admin", file=sys.stderr)
        return 1

    env = _environment_with_cli_overrides(args, os.environ)
    try:
        settings = load_web_settings(
            env,
            static_dir=getattr(args, "static_dir", None),
        )
        _validate_startup_auth(settings)
        host = str(
            getattr(args, "host", None)
            or env.get("WUD_WEB_HOST")
            or DEFAULT_WEB_HOST
        )
        _validate_bind_host_allowed(settings, host)
        port = _parse_port(getattr(args, "port", None) or env.get("WUD_WEB_PORT"))
    except (ConfigError, WebConfigError) as exc:
        print(exc, file=sys.stderr)
        return 1

    import uvicorn

    app = create_app(settings)
    setup_claim = str(getattr(app.state, "web_setup_claim", ""))
    if setup_claim:
        _print_setup_claim(settings, host=host, port=port, claim=setup_claim)
    uvicorn.run(app, host=host, port=port)
    return 0


def run_web_reset_admin_from_namespace(args: object) -> int:
    username = _normalize_username(str(getattr(args, "user", "") or ""))
    if not username:
        print("web reset-admin requires --user USERNAME", file=sys.stderr)
        return 1

    env = _environment_with_cli_overrides(args, os.environ)
    try:
        settings = load_web_settings(env)
        _validate_startup_auth(settings)
        host = str(
            getattr(args, "host", None)
            or env.get("WUD_WEB_HOST")
            or DEFAULT_WEB_HOST
        )
        _validate_bind_host_allowed(settings, host)
        port = _parse_port(getattr(args, "port", None) or env.get("WUD_WEB_PORT"))
        recovery = issue_admin_recovery_claim(settings, username)
    except (ConfigError, WebConfigError, WebAdminResetError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(
        _reset_admin_url(
            settings,
            host=host,
            port=port,
            claim=recovery.claim,
            username=recovery.username,
        )
    )
    return 0


def api_status(request: Request) -> StatusResponse:
    settings = _settings(request)
    pending = web_pending.pending_response(settings, include_grouping=False)
    db_ready, db_warning = _database_ready(settings)
    warnings = list(pending.warnings)
    if db_warning:
        warnings.append(db_warning)
    return StatusResponse(
        ok=db_ready,
        version=__version__,
        wud_file=str(settings.config.wud_out_file),
        wud_file_exists=pending.exists,
        pending_count=pending.count,
        db_path=str(settings.config.db_path),
        db_ready=db_ready,
        auth_required=settings.auth_required,
        dev_auth_bypass=settings.dev_no_auth,
        setup_required=_setup_required(settings),
        mutations_enabled=settings.mutations_enabled,
        timezone=settings.config.timezone_name,
        auto_update_scheduler_enabled=settings.mutations_enabled,
        static_spa_available=_static_spa_available(settings),
        warnings=warnings,
    )


def api_settings(request: Request) -> SettingsResponse:
    settings = _settings(request)
    return SettingsResponse(
        updater=_updater_settings_entries(settings),
        webui=_webui_settings_entries(settings, request),
        secrets=_secret_settings(settings),
        managed=_managed_settings_entries(settings),
    )


def api_update_managed_settings(
    payload: ManagedSettingsUpdateRequest,
    request: Request,
) -> ManagedSettingsUpdateResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")

    updates = _validated_managed_setting_updates(payload, settings)
    try:
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            with conn:
                before = _managed_settings_entries_from_conn(conn, settings)
                _apply_managed_setting_updates(conn, updates)
                after = _managed_settings_entries_from_conn(conn, settings)
                audit_run_id = _insert_managed_settings_audit(
                    conn,
                    settings,
                    request,
                    updated_keys=tuple(updates),
                    before=_managed_settings_audit_values(before),
                    after=_managed_settings_audit_values(after),
                )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not update managed settings",
                exc,
            ),
        ) from exc

    return ManagedSettingsUpdateResponse(managed=after, audit_run_id=audit_run_id)


def api_post_only_method_not_allowed() -> JSONResponse:
    return JSONResponse(
        {"detail": "method not allowed"},
        status_code=405,
        headers={"Allow": "POST"},
    )


def api_service_policies(request: Request) -> list[ServicePolicyRecord]:
    settings = _settings(request)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM service_policy
                ORDER BY service_key COLLATE BINARY
                """
            ).fetchall()
    except ReadOnlyDatabaseMissing:
        return []
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc
    return [_service_policy_from_row(row) for row in rows]


def api_snoozes(
    request: Request,
    state: SnoozeState = Query(default="active"),
) -> list[SnoozeRecord]:
    settings = _settings(request)
    now = utc_timestamp()
    where = ""
    params: tuple[object, ...] = ()
    if state == "active":
        where = "WHERE snoozed_until > ?"
        params = (now,)
    elif state == "expired":
        where = "WHERE snoozed_until <= ?"
        params = (now,)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM snoozes
                {where}
                ORDER BY snoozed_until DESC, id DESC
                """,
                params,
            ).fetchall()
    except ReadOnlyDatabaseMissing:
        return []
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc
    return [_snooze_from_row(row, now=now) for row in rows]


def api_tag_exclusions(
    request: Request,
    status: TagExclusionStatusFilter = Query(default="active"),
) -> list[TagExclusionRuleRecord]:
    settings = _settings(request)
    where = ""
    params: tuple[object, ...] = ()
    if status != "all":
        where = "WHERE status = ?"
        params = (status,)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM tag_exclusion_rules
                {where}
                ORDER BY image_repo COLLATE BINARY,
                         scope COLLATE BINARY,
                         service_key COLLATE BINARY,
                         match_type COLLATE BINARY,
                         tag COLLATE BINARY,
                         id
                """,
                params,
            ).fetchall()
    except ReadOnlyDatabaseMissing:
        return []
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc
    return [_tag_exclusion_from_row(row) for row in rows]


def api_state_operation(
    payload: StateOperation,
    request: Request,
) -> StateOperationResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    try:
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            with _immediate_transaction(conn):
                return _apply_state_operation(conn, settings, request, payload)
    except HTTPException:
        raise
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not update database: {exc}",
        ) from exc


def api_job(job_id: str, request: Request) -> ApplyJobResponse:
    return web_jobs._apply_job_response_for_request(job_id, request)


def api_apply_job(job_id: str, request: Request) -> ApplyJobResponse:
    return api_job(job_id, request)


def api_job_stream(
    job_id: str,
    request: Request,
    log_tail_bytes: int = Query(default=DEFAULT_JOB_LOG_TAIL_BYTES, ge=1),
) -> StreamingResponse:
    settings = _settings(request)
    web_jobs._require_apply_job(job_id, request)
    return StreamingResponse(
        web_jobs._apply_job_stream(
            request.app.state,
            settings,
            job_id,
            log_tail_bytes=min(log_tail_bytes, MAX_LOG_TAIL_BYTES),
            safe_log_path=_safe_log_path,
            read_log_tail=_read_log_tail,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def api_runs(request: Request) -> list[RunSummary]:
    settings = _settings(request)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM update_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (DEFAULT_RUN_LIMIT,),
            ).fetchall()

            run_ids = [row["id"] for row in rows]
            events_by_run: dict[int, list[RunEventRecord]] = {}
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                event_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM update_events
                    WHERE run_id IN ({placeholders})
                    ORDER BY id
                    """,
                    tuple(run_ids),
                ).fetchall()
                for e in event_rows:
                    event = _event_from_row(e)
                    events_by_run.setdefault(event.run_id, []).append(event)
    except ReadOnlyDatabaseMissing:
        return []
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc
    return [
        _sanitize_run_summary(
            settings,
            _run_summary_from_row(row, events=events_by_run.get(row["id"], [])),
        )
        for row in rows
    ]


def api_run_detail(run_id: int, request: Request) -> RunDetail:
    settings = _settings(request)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
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
            pending = conn.execute(
                """
                SELECT *
                FROM pending_updates
                WHERE run_id = ?
                ORDER BY line_no, id
                """,
                (run_id,),
            ).fetchall()
            events = conn.execute(
                """
                SELECT *
                FROM update_events
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
    except ReadOnlyDatabaseMissing as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc

    summary = _run_summary_from_row(
        run,
        events=[_event_from_row(row) for row in events],
    )
    detail = RunDetail(
        **summary.model_dump(),
        pending_updates=[_pending_update_from_row(row) for row in pending],
    )
    return _sanitize_run_detail(settings, detail)


def api_run_log(
    run_id: int,
    request: Request,
    tail_bytes: int = Query(default=DEFAULT_LOG_TAIL_BYTES, ge=1),
) -> RunLogResponse:
    settings = _settings(request)
    max_bytes = min(tail_bytes, MAX_LOG_TAIL_BYTES)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            run = conn.execute(
                """
                SELECT id, log_file
                FROM update_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
    except ReadOnlyDatabaseMissing as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc

    raw_log_file = str(run["log_file"] or "")
    log_path = _safe_log_path(settings, raw_log_file)
    if log_path is None:
        return RunLogResponse(
            run_id=run_id,
            log_file=raw_log_file,
            exists=False,
            content="",
            truncated=False,
            max_bytes=max_bytes,
        )
    return _run_log_response(run_id, raw_log_file, log_path, max_bytes)


def _effective_config(settings: WebSettings) -> UpdaterConfig:
    return replace(
        settings.config,
        compose_ignore_paths=_effective_compose_ignore_paths(settings),
        digest_pin_updates=_effective_digest_pin_updates(settings),
    )


def _effective_compose_ignore_paths(settings: WebSettings) -> tuple[Path, ...]:
    if _compose_ignore_env_configured(settings):
        return settings.config.compose_ignore_paths
    return _stored_compose_ignore_paths(settings)


def _stored_compose_ignore_paths(settings: WebSettings) -> tuple[Path, ...]:
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            value = _web_setting_or_none(conn, MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY)
    except ReadOnlyDatabaseMissing:
        return DEFAULT_COMPOSE_IGNORE_PATHS
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read compose ignore paths",
                exc,
            ),
        ) from exc

    try:
        return parse_compose_ignore_paths(
            value,
            name=MANAGED_COMPOSE_IGNORE_PATHS_KEY,
        )
    except ConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"stored {MANAGED_COMPOSE_IGNORE_PATHS_KEY} is invalid: {exc}",
        ) from exc


def _compose_ignore_env_configured(settings: WebSettings) -> bool:
    return COMPOSE_IGNORE_PATHS_ENV in _settings_env(settings)


def _compose_ignore_paths_disabled_reason(settings: WebSettings) -> str:
    if not _compose_ignore_env_configured(settings):
        return ""
    return (
        f"{COMPOSE_IGNORE_PATHS_ENV} is configured in the server environment. "
        "Unset it to manage compose ignore paths in the WebUI."
    )


def _effective_digest_pin_updates(settings: WebSettings) -> bool:
    if _digest_pin_env_configured(settings):
        return settings.config.digest_pin_updates
    return _stored_digest_pin_updates(settings)


def _stored_digest_pin_updates(settings: WebSettings) -> bool:
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            value = _web_setting(conn, MANAGED_DIGEST_PIN_UPDATES_DB_KEY)
    except ReadOnlyDatabaseMissing:
        return DEFAULT_DIGEST_PIN_UPDATES
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read digest-pin setting",
                exc,
            ),
        ) from exc
    try:
        return parse_bool_env(
            MANAGED_DIGEST_PIN_UPDATES_KEY,
            value,
            default=DEFAULT_DIGEST_PIN_UPDATES,
        )
    except ConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"stored {MANAGED_DIGEST_PIN_UPDATES_KEY} is invalid: {exc}",
        ) from exc


def _digest_pin_env_configured(settings: WebSettings) -> bool:
    return DIGEST_PIN_UPDATES_ENV in _settings_env(settings)


def _digest_pin_disabled_reason(settings: WebSettings) -> str:
    if not _digest_pin_env_configured(settings):
        return ""
    return (
        f"{DIGEST_PIN_UPDATES_ENV} is configured in the server environment. "
        "Unset it to manage digest-pin updates in the WebUI."
    )


def _auto_update_tick(
    app: FastAPI,
    settings: WebSettings,
    *,
    now: datetime | None = None,
) -> ApplyJobResponse | None:
    return web_scheduler._auto_update_tick(
        app,
        settings,
        effective_config_loader=_effective_config,
        now=now,
    )


def _start_auto_update_scheduler(app: FastAPI, settings: WebSettings) -> Any:
    return web_scheduler.start_auto_update_scheduler(
        app,
        settings,
        effective_config_loader=_effective_config,
    )


_safe_update_auto_update_schedule_runs = (
    web_scheduler._safe_update_auto_update_schedule_runs
)


def _run_summary_from_row(
    row: sqlite3.Row,
    events: list[RunEventRecord] | None = None,
) -> RunSummary:
    return RunSummary(
        id=int(row["id"]),
        started_at=str(row["started_at"]),
        finished_at=row["finished_at"],
        status=str(row["status"]),
        dry_run=bool(row["dry_run"]),
        mode=str(row["mode"]),
        wud_file=str(row["wud_file"]),
        log_file=str(row["log_file"]),
        metadata=_metadata_from_row(row),
        events=events or [],
    )


def _pending_update_from_row(row: sqlite3.Row) -> PendingUpdateRecord:
    return PendingUpdateRecord(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        line_no=int(row["line_no"]),
        raw=str(row["raw"]),
        image=str(row["image"]),
        target_digest=str(row["target_digest"]),
        desired_tag=str(row["desired_tag"]),
        service_key=str(row["service_key"]),
        stack_name=str(row["stack_name"]),
        service_name=str(row["service_name"]),
        status=str(row["status"]),
        status_reason=str(row["status_reason"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=_metadata_from_row(row),
    )


def _event_from_row(row: sqlite3.Row) -> RunEventRecord:
    return RunEventRecord(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        created_at=str(row["created_at"]),
        service_name=str(row["service_name"]),
        stack_name=str(row["stack_name"]),
        image=str(row["image"]),
        target_image=str(row["target_image"]),
        old_image_id=str(row["old_image_id"]),
        new_image_id=str(row["new_image_id"]),
        old_digest=str(row["old_digest"]),
        new_digest=str(row["new_digest"]),
        status=str(row["status"]),
        metadata=_metadata_from_row(row),
    )


def _sanitize_run_summary(settings: WebSettings, run: RunSummary) -> RunSummary:
    payload = run.model_dump(mode="json")
    payload["metadata"] = _sanitize_support_bundle_value(settings, payload["metadata"])
    payload["events"] = [
        _sanitize_run_event(settings, event).model_dump(mode="json")
        for event in run.events
    ]
    return RunSummary.model_validate(payload)


def _sanitize_run_detail(settings: WebSettings, run: RunDetail) -> RunDetail:
    payload = run.model_dump(mode="json")
    payload["metadata"] = _sanitize_support_bundle_value(settings, payload["metadata"])
    payload["events"] = [
        _sanitize_run_event(settings, event).model_dump(mode="json")
        for event in run.events
    ]
    return RunDetail.model_validate(payload)


def _sanitize_run_event(
    settings: WebSettings,
    event: RunEventRecord,
) -> RunEventRecord:
    payload = event.model_dump(mode="json")
    payload["metadata"] = _sanitize_support_bundle_value(settings, payload["metadata"])
    return RunEventRecord.model_validate(payload)


def _auto_update_days_from_row(row: sqlite3.Row) -> tuple[str, ...]:
    return web_scheduler._auto_update_days_from_row(row)


def _service_policy_from_row(row: sqlite3.Row) -> ServicePolicyRecord:
    return ServicePolicyRecord(
        service_key=str(row["service_key"]),
        update_mode=str(row["update_mode"]),
        auto_update=bool(row["auto_update"]),
        snooze_default_seconds=(
            None
            if row["snooze_default_seconds"] is None
            else int(row["snooze_default_seconds"])
        ),
        auto_update_time=(
            None if row["auto_update_time"] is None else str(row["auto_update_time"])
        ),
        auto_update_days=list(_auto_update_days_from_row(row)),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=_metadata_from_row(row),
    )


def _snooze_from_row(row: sqlite3.Row, *, now: str) -> SnoozeRecord:
    return SnoozeRecord(
        id=int(row["id"]),
        service_key=str(row["service_key"]),
        snoozed_until=str(row["snoozed_until"]),
        reason=str(row["reason"]),
        created_at=str(row["created_at"]),
        active=str(row["snoozed_until"]) > now,
        metadata=_metadata_from_row(row),
    )


def _tag_exclusion_from_row(row: sqlite3.Row) -> TagExclusionRuleRecord:
    return TagExclusionRuleRecord(
        id=int(row["id"]),
        scope=str(row["scope"]),
        image_repo=str(row["image_repo"]),
        service_key=str(row["service_key"]),
        match_type=str(row["match_type"]),
        tag=str(row["tag"]),
        regex_fragment=str(row["regex_fragment"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=_metadata_from_row(row),
    )


def _apply_state_operation(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: StateOperation,
) -> StateOperationResponse:
    if isinstance(payload, UpsertServicePolicyOperation):
        return _upsert_service_policy(conn, settings, request, payload)
    if isinstance(payload, DeleteServicePolicyOperation):
        return _delete_service_policy(conn, settings, request, payload)
    if isinstance(payload, CreateSnoozeOperation):
        return _create_snooze(conn, settings, request, payload)
    if isinstance(payload, DeleteSnoozeOperation):
        return _delete_snooze(conn, settings, request, payload)
    if isinstance(payload, UpsertTagExclusionOperation):
        return _upsert_tag_exclusion(conn, settings, request, payload)
    if isinstance(payload, SetTagExclusionStatusOperation):
        return _set_tag_exclusion_status(conn, settings, request, payload)
    raise HTTPException(status_code=422, detail="unsupported operation")


def _upsert_service_policy(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: UpsertServicePolicyOperation,
) -> StateOperationResponse:
    service_key = _required_state_text(payload.service_key, "service_key")
    before_row = _service_policy_row(conn, service_key)
    (
        update_mode,
        auto_update,
        snooze_default_seconds,
        auto_update_time,
        auto_update_days,
    ) = _service_policy_upsert_values(payload, before_row)
    now = utc_timestamp()
    conn.execute(
        """
        INSERT INTO service_policy (
            service_key,
            update_mode,
            auto_update,
            snooze_default_seconds,
            auto_update_time,
            auto_update_days_json,
            created_at,
            updated_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
        ON CONFLICT(service_key) DO UPDATE SET
            update_mode = excluded.update_mode,
            auto_update = excluded.auto_update,
            snooze_default_seconds = excluded.snooze_default_seconds,
            auto_update_time = excluded.auto_update_time,
            auto_update_days_json = excluded.auto_update_days_json,
            updated_at = excluded.updated_at
        """,
        (
            service_key,
            update_mode,
            int(auto_update),
            snooze_default_seconds,
            auto_update_time,
            _json_list(auto_update_days),
            now,
            now,
        ),
    )
    after_row = _service_policy_row(conn, service_key)
    if after_row is None:
        raise HTTPException(status_code=500, detail="service policy was not saved")
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="service_policy",
        resource_id=service_key,
        target={"service_key": service_key},
        before=_service_policy_summary(before_row),
        after=_service_policy_summary(after_row),
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="service_policy",
        resource_id=service_key,
        resource=_service_policy_from_row(after_row),
    )


def _service_policy_upsert_values(
    payload: UpsertServicePolicyOperation,
    before_row: sqlite3.Row | None,
) -> tuple[str, bool, int | None, str | None, tuple[str, ...]]:
    if before_row is None:
        return (
            payload.update_mode,
            payload.auto_update,
            payload.snooze_default_seconds,
            _normalized_auto_update_time(payload.auto_update_time),
            _normalized_auto_update_days(payload.auto_update_days),
        )

    fields_set = payload.model_fields_set
    update_mode = (
        payload.update_mode
        if "update_mode" in fields_set
        else str(before_row["update_mode"])
    )
    auto_update = (
        payload.auto_update
        if "auto_update" in fields_set
        else bool(before_row["auto_update"])
    )
    snooze_default_seconds = (
        payload.snooze_default_seconds
        if "snooze_default_seconds" in fields_set
        else (
            None
            if before_row["snooze_default_seconds"] is None
            else int(before_row["snooze_default_seconds"])
        )
    )
    auto_update_time = (
        _normalized_auto_update_time(payload.auto_update_time)
        if "auto_update_time" in fields_set
        else (
            None
            if before_row["auto_update_time"] is None
            else str(before_row["auto_update_time"])
        )
    )
    auto_update_days = (
        _normalized_auto_update_days(payload.auto_update_days)
        if "auto_update_days" in fields_set
        else _auto_update_days_from_row(before_row)
    )
    return (
        update_mode,
        auto_update,
        snooze_default_seconds,
        auto_update_time,
        auto_update_days,
    )


def _normalized_auto_update_time(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    try:
        datetime_time.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="auto_update_time must use HH:MM 24-hour format",
        ) from exc
    if len(text) != 5 or text[2] != ":":
        raise HTTPException(
            status_code=422,
            detail="auto_update_time must use HH:MM 24-hour format",
        )
    return text


def _normalized_auto_update_days(values: Sequence[str]) -> tuple[str, ...]:
    days: list[str] = []
    for value in values:
        if value not in AUTO_UPDATE_DAYS:
            raise HTTPException(status_code=422, detail="auto_update_days is invalid")
        if value not in days:
            days.append(value)
    return tuple(days)


def _delete_service_policy(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: DeleteServicePolicyOperation,
) -> StateOperationResponse:
    service_key = _required_state_text(payload.service_key, "service_key")
    before_row = _service_policy_row(conn, service_key)
    if before_row is None:
        raise HTTPException(status_code=404, detail="service policy not found")
    conn.execute("DELETE FROM service_policy WHERE service_key = ?", (service_key,))
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="service_policy",
        resource_id=service_key,
        target={"service_key": service_key},
        before=_service_policy_summary(before_row),
        after=None,
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="service_policy",
        resource_id=service_key,
    )


def _create_snooze(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: CreateSnoozeOperation,
) -> StateOperationResponse:
    service_key = _required_state_text(payload.service_key, "service_key")
    snoozed_until = _future_iso_timestamp(payload.snoozed_until, "snoozed_until")
    reason = payload.reason.strip()
    cursor = conn.execute(
        """
        INSERT INTO snoozes (
            service_key,
            snoozed_until,
            reason,
            created_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, '{}')
        """,
        (service_key, snoozed_until, reason, utc_timestamp()),
    )
    snooze_id = int(cursor.lastrowid)
    after_row = _snooze_row(conn, snooze_id)
    if after_row is None:
        raise HTTPException(status_code=500, detail="snooze was not saved")
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="snooze",
        resource_id=str(snooze_id),
        target={"id": snooze_id, "service_key": service_key},
        before=None,
        after=_snooze_summary(after_row),
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="snooze",
        resource_id=str(snooze_id),
        resource=_snooze_from_row(after_row, now=utc_timestamp()),
    )


def _delete_snooze(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: DeleteSnoozeOperation,
) -> StateOperationResponse:
    before_row = _snooze_row(conn, payload.snooze_id)
    if before_row is None:
        raise HTTPException(status_code=404, detail="snooze not found")
    conn.execute("DELETE FROM snoozes WHERE id = ?", (payload.snooze_id,))
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="snooze",
        resource_id=str(payload.snooze_id),
        target={
            "id": payload.snooze_id,
            "service_key": str(before_row["service_key"]),
        },
        before=_snooze_summary(before_row),
        after=None,
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="snooze",
        resource_id=str(payload.snooze_id),
    )


def _upsert_tag_exclusion(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: UpsertTagExclusionOperation,
) -> StateOperationResponse:
    image_repo = _normalized_image_repo(payload.image_repo)
    service_key = _tag_exclusion_service_key(payload.scope, payload.service_key)
    tag = _valid_tag(payload.tag)
    before_row = _tag_exclusion_unique_row(
        conn,
        scope=payload.scope,
        image_repo=image_repo,
        service_key=service_key,
        match_type=payload.match_type,
        tag=tag,
    )
    now = utc_timestamp()
    conn.execute(
        """
        INSERT INTO tag_exclusion_rules (
            scope,
            image_repo,
            service_key,
            match_type,
            tag,
            regex_fragment,
            status,
            created_at,
            updated_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
        ON CONFLICT(scope, image_repo, service_key, match_type, tag)
        DO UPDATE SET
            regex_fragment = excluded.regex_fragment,
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (
            payload.scope,
            image_repo,
            service_key,
            payload.match_type,
            tag,
            js_regex_escape(tag),
            payload.status,
            now,
            now,
        ),
    )
    after_row = _tag_exclusion_unique_row(
        conn,
        scope=payload.scope,
        image_repo=image_repo,
        service_key=service_key,
        match_type=payload.match_type,
        tag=tag,
    )
    if after_row is None:
        raise HTTPException(status_code=500, detail="tag exclusion was not saved")
    resource_id = str(after_row["id"])
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="tag_exclusion",
        resource_id=resource_id,
        target={
            "id": int(after_row["id"]),
            "scope": payload.scope,
            "image_repo": image_repo,
            "service_key": service_key,
            "match_type": payload.match_type,
            "tag": tag,
        },
        before=_tag_exclusion_summary(before_row),
        after=_tag_exclusion_summary(after_row),
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="tag_exclusion",
        resource_id=resource_id,
        resource=_tag_exclusion_from_row(after_row),
    )


def _set_tag_exclusion_status(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    payload: SetTagExclusionStatusOperation,
) -> StateOperationResponse:
    before_row = _tag_exclusion_row(conn, payload.rule_id)
    if before_row is None:
        raise HTTPException(status_code=404, detail="tag exclusion not found")
    conn.execute(
        """
        UPDATE tag_exclusion_rules
        SET status = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (payload.status, utc_timestamp(), payload.rule_id),
    )
    after_row = _tag_exclusion_row(conn, payload.rule_id)
    if after_row is None:
        raise HTTPException(status_code=500, detail="tag exclusion was not saved")
    audit_run_id = _insert_state_audit(
        conn,
        settings,
        request,
        operation=payload.kind,
        resource_type="tag_exclusion",
        resource_id=str(payload.rule_id),
        target={
            "id": payload.rule_id,
            "scope": str(before_row["scope"]),
            "image_repo": str(before_row["image_repo"]),
            "service_key": str(before_row["service_key"]),
            "match_type": str(before_row["match_type"]),
            "tag": str(before_row["tag"]),
        },
        before=_tag_exclusion_summary(before_row),
        after=_tag_exclusion_summary(after_row),
    )
    return StateOperationResponse(
        operation=payload.kind,
        status="success",
        audit_run_id=audit_run_id,
        resource_type="tag_exclusion",
        resource_id=str(payload.rule_id),
        resource=_tag_exclusion_from_row(after_row),
    )


def _service_policy_row(
    conn: sqlite3.Connection,
    service_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM service_policy
        WHERE service_key = ?
        LIMIT 1
        """,
        (service_key,),
    ).fetchone()


def _snooze_row(conn: sqlite3.Connection, snooze_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM snoozes
        WHERE id = ?
        LIMIT 1
        """,
        (snooze_id,),
    ).fetchone()


def _tag_exclusion_row(
    conn: sqlite3.Connection,
    rule_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM tag_exclusion_rules
        WHERE id = ?
        LIMIT 1
        """,
        (rule_id,),
    ).fetchone()


def _tag_exclusion_unique_row(
    conn: sqlite3.Connection,
    *,
    scope: str,
    image_repo: str,
    service_key: str,
    match_type: str,
    tag: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM tag_exclusion_rules
        WHERE scope = ?
          AND image_repo = ?
          AND service_key = ?
          AND match_type = ?
          AND tag = ?
        LIMIT 1
        """,
        (scope, image_repo, service_key, match_type, tag),
    ).fetchone()


def _required_state_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return cleaned


def _future_iso_timestamp(value: str, field_name: str) -> str:
    raw = _required_state_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a valid ISO timestamp",
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must include a timezone",
        )
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if normalized <= now:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be in the future",
        )
    return normalized.isoformat()


def _normalized_image_repo(value: str) -> str:
    cleaned = _required_state_text(value, "image_repo")
    if any(character.isspace() for character in cleaned):
        raise HTTPException(status_code=422, detail="image_repo must not contain spaces")
    normalized = repo_key(cleaned)
    if not normalized:
        raise HTTPException(status_code=422, detail="image_repo is required")
    return normalized


def _tag_exclusion_service_key(scope: str, service_key: str) -> str:
    cleaned = service_key.strip()
    if scope == "service":
        if not cleaned:
            raise HTTPException(
                status_code=422,
                detail="service_key is required for service tag exclusions",
            )
        return cleaned
    if cleaned:
        raise HTTPException(
            status_code=422,
            detail="service_key is only valid for service tag exclusions",
        )
    return ""


def _valid_tag(value: str) -> str:
    tag = _required_state_text(value, "tag")
    if not tag_value_valid(tag):
        raise HTTPException(status_code=422, detail=f"tag is invalid: {tag}")
    return tag


def _insert_managed_settings_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    *,
    updated_keys: Sequence[str],
    before: dict[str, str],
    after: dict[str, str],
) -> int:
    now = utc_timestamp()
    target = {"keys": sorted(updated_keys)}
    metadata = {
        "source": "webui",
        "operation": "update_managed_settings",
        "actor_type": _state_actor_type(settings, request),
        "resource_type": "managed_settings",
        "resource_id": "webui_preferences",
        "target": target,
    }
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
        VALUES (?, ?, 'success', 0, 'web-settings', ?, '', ?)
        """,
        (
            now,
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
        ),
    )
    run_id = int(cursor.lastrowid)
    event_metadata = {
        **metadata,
        "before": before,
        "after": after,
    }
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
        VALUES (?, ?, 'settings', 'webui', 'managed-settings', 'webui-preferences', 'success', ?)
        """,
        (
            run_id,
            now,
            _json_object(event_metadata),
        ),
    )
    return run_id


def _insert_state_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    *,
    operation: str,
    resource_type: str,
    resource_id: str,
    target: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": "webui",
        "operation": operation,
        "actor_type": _state_actor_type(settings, request),
        "resource_type": resource_type,
        "resource_id": resource_id,
        "target": target,
    }
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
        VALUES (?, ?, 'success', 0, 'web-state', ?, '', ?)
        """,
        (
            now,
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
        ),
    )
    run_id = int(cursor.lastrowid)
    event_metadata = {
        **metadata,
        "before": before,
        "after": after,
    }
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
        VALUES (?, ?, ?, ?, ?, ?, 'success', ?)
        """,
        (
            run_id,
            now,
            _state_audit_service_name(target, resource_type),
            _state_audit_stack_name(target),
            _state_audit_image(target, resource_type, resource_id),
            resource_id,
            _json_object(event_metadata),
        ),
    )
    return run_id


def _state_actor_type(settings: WebSettings, request: Request) -> str:
    if settings.dev_no_auth:
        return "dev"
    authorization = request.headers.get("authorization")
    if _bearer_token_valid(settings, authorization):
        return "bearer"
    if request.cookies.get(SESSION_COOKIE):
        return "session"
    return "unknown"


def _state_audit_stack_name(target: Mapping[str, Any]) -> str:
    service_key = str(target.get("service_key") or "")
    if "/" not in service_key:
        return ""
    return service_key.split("/", 1)[0]


def _state_audit_service_name(
    target: Mapping[str, Any],
    resource_type: str,
) -> str:
    service_key = str(target.get("service_key") or "")
    if "/" in service_key:
        return service_key.split("/", 1)[1]
    if service_key:
        return service_key
    return str(target.get("image_repo") or resource_type)


def _state_audit_image(
    target: Mapping[str, Any],
    resource_type: str,
    resource_id: str,
) -> str:
    return str(
        target.get("image_repo")
        or target.get("service_key")
        or resource_id
        or resource_type
    )


def _service_policy_summary(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "service_key": str(row["service_key"]),
        "update_mode": str(row["update_mode"]),
        "auto_update": bool(row["auto_update"]),
        "snooze_default_seconds": (
            None
            if row["snooze_default_seconds"] is None
            else int(row["snooze_default_seconds"])
        ),
        "auto_update_time": (
            None if row["auto_update_time"] is None else str(row["auto_update_time"])
        ),
        "auto_update_days": list(_auto_update_days_from_row(row)),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _snooze_summary(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "service_key": str(row["service_key"]),
        "snoozed_until": str(row["snoozed_until"]),
        "reason": str(row["reason"]),
        "created_at": str(row["created_at"]),
    }


def _tag_exclusion_summary(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "scope": str(row["scope"]),
        "image_repo": str(row["image_repo"]),
        "service_key": str(row["service_key"]),
        "match_type": str(row["match_type"]),
        "tag": str(row["tag"]),
        "regex_fragment": str(row["regex_fragment"]),
        "status": str(row["status"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _json_object(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_list(value: Sequence[str]) -> str:
    return json.dumps(list(value), separators=(",", ":"))


def _metadata_from_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = str(row["metadata_json"] or "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail="invalid metadata JSON in database",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=500,
            detail="metadata JSON must be an object",
        )
    return value


def _safe_log_path(settings: WebSettings, raw_log_file: str) -> Path | None:
    if not raw_log_file:
        return None
    log_dir = settings.config.log_dir
    candidate = Path(raw_log_file)
    if not candidate.is_absolute():
        candidate = log_dir / candidate
    try:
        resolved_log_dir = log_dir.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="log file not found") from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not resolve log file: {exc}",
        ) from exc
    if not _path_is_or_under(resolved_candidate, resolved_log_dir):
        raise HTTPException(status_code=403, detail="log file is outside WUD_LOG_DIR")
    return resolved_candidate


def _path_is_or_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _run_log_response(
    run_id: int,
    raw_log_file: str,
    log_path: Path,
    max_bytes: int,
) -> RunLogResponse:
    tail = _read_log_tail(log_path, max_bytes)
    return RunLogResponse(
        run_id=run_id,
        log_file=raw_log_file,
        exists=tail.exists,
        content=tail.content,
        truncated=tail.truncated,
        max_bytes=max_bytes,
    )


def _read_log_tail(log_path: Path, max_bytes: int) -> LogTail:
    try:
        if not log_path.is_file():
            return LogTail(
                exists=False,
                content="",
                truncated=False,
            )
        size = log_path.stat().st_size
        truncated = size > max_bytes
        with log_path.open("rb") as file:
            if truncated:
                file.seek(-max_bytes, os.SEEK_END)
            content = file.read(max_bytes).decode("utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read log file: {exc}",
        ) from exc
    return LogTail(
        exists=True,
        content=content,
        truncated=truncated,
    )


def _mount_static_spa_if_present(app: FastAPI, settings: WebSettings) -> None:
    static_dir = settings.static_dir
    if static_dir is None or not _static_spa_available(settings):
        return
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="webui")


def _static_spa_available(settings: WebSettings) -> bool:
    return (
        settings.static_dir is not None
        and (settings.static_dir / "index.html").is_file()
    )


def _resolve_static_dir(configured: str | Path | None) -> Path | None:
    if configured:
        return Path(configured)
    candidates = (
        Path(__file__).resolve().parents[2] / "webui" / "dist",
        Path(__file__).resolve().parent / "web_static",
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _managed_settings_entries(settings: WebSettings) -> list[ManagedSettingEntry]:
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            values = _managed_settings_db_values(conn)
    except ReadOnlyDatabaseMissing:
        values = {}
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read managed settings",
                exc,
            ),
        ) from exc
    try:
        return _managed_settings_entries_from_values(values, settings)
    except ConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read managed settings",
                exc,
            ),
        ) from exc


def _managed_settings_entries_from_conn(
    conn: sqlite3.Connection,
    settings: WebSettings,
) -> list[ManagedSettingEntry]:
    try:
        return _managed_settings_entries_from_values(
            _managed_settings_db_values(conn),
            settings,
        )
    except ConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read managed settings",
                exc,
            ),
        ) from exc


def _managed_settings_db_values(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT key, value
        FROM web_settings
        WHERE key IN (?, ?, ?, ?)
        """,
        (
            MANAGED_THEME_PREFERENCE_DB_KEY,
            ONBOARDING_DISMISSED_AT_KEY,
            MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY,
            MANAGED_DIGEST_PIN_UPDATES_DB_KEY,
        ),
    ).fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def _managed_settings_entries_from_values(
    values: Mapping[str, str],
    settings: WebSettings,
) -> list[ManagedSettingEntry]:
    theme_value = values.get(MANAGED_THEME_PREFERENCE_DB_KEY, "")
    theme_configured = theme_value in THEME_PREFERENCE_VALUES
    onboarding_dismissed_at = values.get(ONBOARDING_DISMISSED_AT_KEY, "")
    compose_disabled_reason = _compose_ignore_paths_disabled_reason(settings)
    digest_disabled_reason = _digest_pin_disabled_reason(settings)
    if _compose_ignore_env_configured(settings):
        compose_ignore_paths = settings.config.compose_ignore_paths
        compose_configured = True
    else:
        compose_configured = MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY in values
        compose_value = (
            values.get(MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY, "")
            if compose_configured
            else None
        )
        compose_ignore_paths = parse_compose_ignore_paths(
            compose_value,
            name=MANAGED_COMPOSE_IGNORE_PATHS_KEY,
        )
    if _digest_pin_env_configured(settings):
        digest_pin_updates = settings.config.digest_pin_updates
        digest_configured = True
    else:
        digest_configured = MANAGED_DIGEST_PIN_UPDATES_DB_KEY in values
        digest_pin_updates = parse_bool_env(
            MANAGED_DIGEST_PIN_UPDATES_KEY,
            values.get(MANAGED_DIGEST_PIN_UPDATES_DB_KEY, ""),
            default=DEFAULT_DIGEST_PIN_UPDATES,
        )
    return [
        ManagedSettingEntry(
            key=MANAGED_THEME_PREFERENCE_KEY,
            value=theme_value if theme_configured else "system",
            default_value="system",
            source="configured" if theme_configured else "default",
            editable=True,
            allowed_values=list(THEME_PREFERENCE_VALUES),
            restart_required=False,
        ),
        ManagedSettingEntry(
            key=MANAGED_ONBOARDING_CHECKLIST_KEY,
            value="dismissed" if onboarding_dismissed_at else "visible",
            default_value="visible",
            source="configured" if onboarding_dismissed_at else "default",
            editable=True,
            allowed_values=list(ONBOARDING_CHECKLIST_VALUES),
            restart_required=False,
        ),
        ManagedSettingEntry(
            key=MANAGED_COMPOSE_IGNORE_PATHS_KEY,
            value=format_compose_ignore_paths(compose_ignore_paths),
            default_value=format_compose_ignore_paths(DEFAULT_COMPOSE_IGNORE_PATHS),
            source="configured" if compose_configured else "default",
            editable=not compose_disabled_reason,
            allowed_values=[],
            restart_required=False,
            disabled_reason=compose_disabled_reason,
        ),
        ManagedSettingEntry(
            key=MANAGED_DIGEST_PIN_UPDATES_KEY,
            value=_format_bool(digest_pin_updates),
            default_value=_format_bool(DEFAULT_DIGEST_PIN_UPDATES),
            source="configured" if digest_configured else "default",
            editable=not digest_disabled_reason,
            allowed_values=list(DIGEST_PIN_UPDATES_VALUES),
            restart_required=False,
            disabled_reason=digest_disabled_reason,
        ),
    ]


def _validated_managed_setting_updates(
    payload: ManagedSettingsUpdateRequest,
    settings: WebSettings,
) -> dict[str, str]:
    if not payload.values:
        raise HTTPException(
            status_code=422,
            detail="at least one managed setting is required",
        )

    allowed_values = {
        MANAGED_THEME_PREFERENCE_KEY: THEME_PREFERENCE_VALUES,
        MANAGED_ONBOARDING_CHECKLIST_KEY: ONBOARDING_CHECKLIST_VALUES,
        MANAGED_DIGEST_PIN_UPDATES_KEY: DIGEST_PIN_UPDATES_VALUES,
    }
    updates: dict[str, str] = {}
    for key, raw_value in payload.values.items():
        if key == MANAGED_COMPOSE_IGNORE_PATHS_KEY:
            if _compose_ignore_env_configured(settings):
                raise HTTPException(
                    status_code=422,
                    detail=_compose_ignore_paths_disabled_reason(settings),
                )
            try:
                updates[key] = format_compose_ignore_paths(
                    parse_compose_ignore_paths(
                        raw_value.strip(),
                        name=MANAGED_COMPOSE_IGNORE_PATHS_KEY,
                    )
                )
            except ConfigError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            continue
        if key == MANAGED_DIGEST_PIN_UPDATES_KEY and _digest_pin_env_configured(settings):
            raise HTTPException(
                status_code=422,
                detail=_digest_pin_disabled_reason(settings),
            )
        if key not in allowed_values:
            raise HTTPException(
                status_code=422,
                detail=f"managed setting is not editable: {key}",
            )
        value = raw_value.strip()
        if value not in allowed_values[key]:
            options = ", ".join(allowed_values[key])
            raise HTTPException(
                status_code=422,
                detail=f"{key} must be one of: {options}",
            )
        updates[key] = value
    return updates


def _apply_managed_setting_updates(
    conn: sqlite3.Connection,
    updates: Mapping[str, str],
) -> None:
    for key, value in updates.items():
        if key == MANAGED_THEME_PREFERENCE_KEY:
            _set_web_setting(conn, MANAGED_THEME_PREFERENCE_DB_KEY, value)
        elif key == MANAGED_ONBOARDING_CHECKLIST_KEY:
            if value == "dismissed":
                current = _web_setting(conn, ONBOARDING_DISMISSED_AT_KEY)
                _set_web_setting(
                    conn,
                    ONBOARDING_DISMISSED_AT_KEY,
                    current or utc_timestamp(),
                )
            else:
                _delete_web_setting(conn, ONBOARDING_DISMISSED_AT_KEY)
        elif key == MANAGED_COMPOSE_IGNORE_PATHS_KEY:
            _set_web_setting(conn, MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY, value)
        elif key == MANAGED_DIGEST_PIN_UPDATES_KEY:
            _set_web_setting(conn, MANAGED_DIGEST_PIN_UPDATES_DB_KEY, value)


def _managed_settings_audit_values(
    entries: Sequence[ManagedSettingEntry],
) -> dict[str, str]:
    return {entry.key: entry.value for entry in entries}


def _updater_settings_entries(settings: WebSettings) -> list[SettingsEntry]:
    config = settings.config
    return [
        _config_setting_entry(settings, "DOCKER_BASE", str(config.docker_base)),
        _settings_entry(
            "HOST_DOCKER_BASE",
            "" if settings.host_docker_base is None else str(settings.host_docker_base),
            "",
            _env_configured(settings, "HOST_DOCKER_BASE"),
        ),
        _config_setting_entry(settings, "WUD_OUT_FILE", str(config.wud_out_file)),
        _config_setting_entry(settings, "WUD_LOG_DIR", str(config.log_dir)),
        _config_setting_entry(settings, "WUD_DB_PATH", str(config.db_path)),
        _config_setting_entry(settings, "WUD_UPDATE_MODE", config.update_mode),
        _config_setting_entry(settings, "WUD_MAX_WAIT", str(config.max_wait)),
        _config_setting_entry(settings, "WUD_LOCK_TIMEOUT", str(config.lock_timeout)),
        _config_setting_entry(settings, "WUD_TIMEZONE", config.timezone_name),
        _config_setting_entry(
            settings,
            COMPOSE_IGNORE_PATHS_ENV,
            format_compose_ignore_paths(config.compose_ignore_paths),
        ),
        _config_setting_entry(
            settings,
            DIGEST_PIN_UPDATES_ENV,
            _format_bool(config.digest_pin_updates),
        ),
    ]


def _webui_settings_entries(
    settings: WebSettings,
    request: Request,
) -> list[SettingsEntry]:
    env = _settings_env(settings)
    bind_host = env.get("WUD_WEB_HOST", DEFAULT_WEB_HOST)
    default_allowed_hosts = _parse_allowed_hosts(
        "",
        public_origin=settings.public_origin,
        bind_host=bind_host,
    )
    default_static_settings = replace(settings, static_dir=_resolve_static_dir(None))
    default_secure_settings = replace(settings, secure_cookies="auto")
    return [
        _settings_entry(
            "WUD_WEB_AUTH_REQUIRED",
            _format_bool(settings.auth_required),
            "true",
            False,
            source="derived",
        ),
        _settings_entry(
            "WUD_WEB_DEV_NO_AUTH",
            _format_bool(settings.dev_no_auth),
            "false",
            _env_configured(settings, "WUD_WEB_DEV_NO_AUTH"),
        ),
        _settings_entry(
            "WUD_WEB_PUBLIC_ORIGIN",
            settings.public_origin,
            "",
            _env_configured(settings, "WUD_WEB_PUBLIC_ORIGIN"),
        ),
        _settings_entry(
            "WUD_WEB_ALLOWED_ORIGINS",
            _format_sequence(sorted(settings.allowed_origins)),
            "",
            _env_configured(settings, "WUD_WEB_ALLOWED_ORIGINS"),
        ),
        _settings_entry(
            "WUD_WEB_ALLOWED_HOSTS",
            _format_sequence(sorted(settings.allowed_hosts)),
            _format_sequence(sorted(default_allowed_hosts)),
            _env_configured(settings, "WUD_WEB_ALLOWED_HOSTS"),
            source="derived",
        ),
        _settings_entry(
            "WUD_WEB_TRUSTED_PROXIES",
            _format_sequence(str(network) for network in settings.trusted_proxies),
            "",
            _env_configured(settings, "WUD_WEB_TRUSTED_PROXIES"),
        ),
        _settings_entry(
            "WUD_WEB_SECURE_COOKIES",
            settings.secure_cookies,
            "auto",
            _env_configured(settings, "WUD_WEB_SECURE_COOKIES"),
        ),
        _settings_entry(
            "WUD_WEB_SECURE_COOKIES_EFFECTIVE",
            _format_bool(_secure_cookie(settings, request)),
            _format_bool(_secure_cookie(default_secure_settings, request)),
            False,
            source="request",
        ),
        _settings_entry(
            "WUD_WEB_STATIC_SPA_AVAILABLE",
            _format_bool(_static_spa_available(settings)),
            _format_bool(_static_spa_available(default_static_settings)),
            _env_configured(settings, "WUD_WEB_STATIC_DIR"),
            source="derived",
        ),
        _settings_entry(
            "WUD_WEB_MUTATIONS_ENABLED",
            _format_bool(settings.mutations_enabled),
            "false",
            _env_configured(settings, "WUD_WEB_MUTATIONS_ENABLED"),
        ),
        _settings_entry(
            "WUD_WEB_RESTART_CONTAINER",
            settings.restart_container,
            "",
            _env_configured(settings, "WUD_WEB_RESTART_CONTAINER"),
            source="derived" if settings.restart_container else None,
        ),
        _settings_entry(
            "WUD_WEB_AUTO_UPDATE_SCHEDULER_ENABLED",
            _format_bool(settings.mutations_enabled),
            "false",
            False,
            source="derived",
        ),
    ]


def _secret_settings(settings: WebSettings) -> list[SecretSettingStatus]:
    env = _settings_env(settings)
    return [
        SecretSettingStatus(
            name=name,
            configured=bool(settings.auth_token.strip())
            if name == "WUD_WEB_TOKEN"
            else bool(env.get(name, "").strip()),
        )
        for name in SENSITIVE_ENV_KEYS
    ]


def _config_setting_entry(
    settings: WebSettings,
    name: str,
    value: str,
) -> SettingsEntry:
    configured = _env_configured(settings, name)
    return _settings_entry(
        name,
        value,
        _config_default_value(settings, name),
        configured,
    )


def _settings_entry(
    name: str,
    value: str,
    default_value: str,
    configured: bool,
    *,
    source: SettingsEntrySource | None = None,
) -> SettingsEntry:
    return SettingsEntry(
        name=name,
        value=value,
        default_value=default_value,
        configured=configured,
        source="configured" if configured else source or "default",
    )


def _config_default_value(settings: WebSettings, name: str) -> str:
    env = dict(_settings_env(settings))
    env.pop(name, None)
    try:
        config = load_config(env)
    except ConfigError:
        return _static_config_default(name)
    return _config_value(config, name)


def _static_config_default(name: str) -> str:
    defaults = {
        "WUD_UPDATE_MODE": DEFAULT_UPDATE_MODE,
        "WUD_MAX_WAIT": str(DEFAULT_MAX_WAIT),
        "WUD_LOCK_TIMEOUT": str(DEFAULT_LOCK_TIMEOUT),
        "WUD_TIMEZONE": DEFAULT_TIMEZONE,
        COMPOSE_IGNORE_PATHS_ENV: format_compose_ignore_paths(
            DEFAULT_COMPOSE_IGNORE_PATHS
        ),
        DIGEST_PIN_UPDATES_ENV: _format_bool(DEFAULT_DIGEST_PIN_UPDATES),
    }
    return defaults.get(name, "")


def _config_value(config: UpdaterConfig, name: str) -> str:
    values = {
        "DOCKER_BASE": str(config.docker_base),
        "WUD_OUT_FILE": str(config.wud_out_file),
        "WUD_LOG_DIR": str(config.log_dir),
        "WUD_DB_PATH": str(config.db_path),
        "WUD_UPDATE_MODE": config.update_mode,
        "WUD_MAX_WAIT": str(config.max_wait),
        "WUD_LOCK_TIMEOUT": str(config.lock_timeout),
        "WUD_TIMEZONE": config.timezone_name,
        COMPOSE_IGNORE_PATHS_ENV: format_compose_ignore_paths(
            config.compose_ignore_paths
        ),
        DIGEST_PIN_UPDATES_ENV: _format_bool(config.digest_pin_updates),
    }
    return values.get(name, "")


def _settings_env(settings: WebSettings) -> Mapping[str, str]:
    return settings.command_env or {}


def _env_configured(settings: WebSettings, name: str) -> bool:
    if name in {COMPOSE_IGNORE_PATHS_ENV, DIGEST_PIN_UPDATES_ENV}:
        return name in _settings_env(settings)
    return bool(_settings_env(settings).get(name, "").strip())


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_sequence(values: Sequence[str] | Iterator[str]) -> str:
    return ", ".join(item for item in values if item)


def _resolve_restart_container(env: Mapping[str, str]) -> str:
    configured = env.get("WUD_WEB_RESTART_CONTAINER")
    if configured is not None:
        return web_self_update._validate_restart_container_target(configured.strip())
    if not _running_in_container():
        return ""
    return web_self_update._validate_restart_container_target(
        env.get("HOSTNAME", "").strip()
    )


def _running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        marker in cgroup
        for marker in ("/docker/", "/kubepods/", "/containerd/")
    )


def _parse_host_docker_base(
    env: Mapping[str, str],
    config: UpdaterConfig,
) -> Path | None:
    value = env.get("HOST_DOCKER_BASE") or ""
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise WebConfigError("HOST_DOCKER_BASE must be an absolute path")
    if not config.docker_base.is_absolute():
        raise WebConfigError(
            "DOCKER_BASE must be an absolute path when HOST_DOCKER_BASE is set"
        )
    return path


def _environment_with_cli_overrides(
    args: object,
    environ: Mapping[str, str],
) -> dict[str, str]:
    env = dict(environ)
    for attr, name in (
        ("base", "DOCKER_BASE"),
        ("file", "WUD_OUT_FILE"),
        ("log_dir", "WUD_LOG_DIR"),
        ("db_path", "WUD_DB_PATH"),
    ):
        value = getattr(args, attr, None)
        if value:
            env[name] = str(value)
    return env


def _parse_port(value: object) -> int:
    if value is None or value == "":
        return DEFAULT_WEB_PORT
    try:
        port = int(str(value), 10)
    except ValueError as exc:
        raise WebConfigError("WUD_WEB_PORT must be an integer") from exc
    if port < 1 or port > 65535:
        raise WebConfigError("WUD_WEB_PORT must be between 1 and 65535")
    return port
