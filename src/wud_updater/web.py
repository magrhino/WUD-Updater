"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Query,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from . import (
    __version__,
    web_diagnostics,
    web_health,
    web_jobs,
    web_onboarding,
    web_pending,
    web_plans,
    web_release_notes,
    web_retags,
    web_runs,
    web_scheduler,
    web_self_update,
    web_settings,
    web_startup,
    web_state,
    web_static,
)
from .config import (
    ConfigError,
    UpdaterConfig,
    load_config,
)
from .web_database import (
    database_ready as _database_ready,
)

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
    CreateDependencySnoozeOperation as CreateDependencySnoozeOperation,
    CreateSnoozeOperation as CreateSnoozeOperation,
    CsrfResponse,
    DEFAULT_CORE_UPDATE_TOUR_STEP as DEFAULT_CORE_UPDATE_TOUR_STEP,
    DeleteDependencySnoozeOperation as DeleteDependencySnoozeOperation,
    DeleteServicePolicyOperation as DeleteServicePolicyOperation,
    DeleteSnoozeOperation as DeleteSnoozeOperation,
    DiagnosticsSupportBundleResponse,
    DigestTagProvenance as DigestTagProvenance,
    DoctorCheckResponse as DoctorCheckResponse,
    DoctorCheckStatus as DoctorCheckStatus,
    DoctorResponse,
    DoctorSuggestionResponse as DoctorSuggestionResponse,
    HealthResponse,
    LogTail as LogTail,
    ManagedSettingEntry as ManagedSettingEntry,
    ManagedSettingsUpdateRequest as ManagedSettingsUpdateRequest,
    ManagedSettingsUpdateResponse,
    OnboardingChecklistItem as OnboardingChecklistItem,
    OnboardingChecklistResponse,
    OnboardingDismissResponse,
    OnboardingDocLink as OnboardingDocLink,
    PendingCleanupResponse,
    PendingRemovalPlanResponse,
    PendingResponse,
    PendingUpdateRecord as PendingUpdateRecord,
    PlanResponse,
    ReadyResponse,
    ReleaseNotesResponse,
    RetagPlanResponse,
    RetagTargetItem as RetagTargetItem,
    RetagTargetsResponse,
    RunDetail,
    RunEventRecord as RunEventRecord,
    RunLogResponse,
    RunSummary,
    RunVerificationContainerStatus as RunVerificationContainerStatus,
    RunVerificationHealthStatus as RunVerificationHealthStatus,
    RunVerificationImageStatus as RunVerificationImageStatus,
    RunVerificationItem as RunVerificationItem,
    RunVerificationStatus as RunVerificationStatus,
    RunVerificationSummary as RunVerificationSummary,
    RunVerificationWudStatus as RunVerificationWudStatus,
    SecretSettingStatus as SecretSettingStatus,
    SelfUpdateApplyResponse,
    SelfUpdatePlanResponse,
    SelfUpdatePrepareResponse,
    SelfUpdateResponse,
    ServicePolicyRecord,
    SetTagExclusionStatusOperation as SetTagExclusionStatusOperation,
    SettingsEntry as SettingsEntry,
    SettingsEntrySource as SettingsEntrySource,
    SettingsResponse,
    SetupStatusResponse,
    SnoozeKind as SnoozeKind,
    SnoozeRecord,
    SnoozeState as SnoozeState,
    StateOperation as StateOperation,
    StateOperationResponse,
    StatusResponse,
    TERMINAL_APPLY_JOB_STATUSES as TERMINAL_APPLY_JOB_STATUSES,
    TagExclusionRuleRecord,
    TagExclusionStatusFilter as TagExclusionStatusFilter,
    UpdateTargetsResponse,
    UpsertServicePolicyOperation as UpsertServicePolicyOperation,
    UpsertTagExclusionOperation as UpsertTagExclusionOperation,
    WebApplyJob as WebApplyJob,
    WebApplyJobProgressEvent as WebApplyJobProgressEvent,
    WebSettings,
)
from .web_auth import (
    WebAdminResetError,
    WebConfigError,
    _parse_allowed_hosts,
    _parse_bool,
    _parse_origins,
    _parse_public_origin,
    _parse_secure_cookie_mode,
    _parse_trusted_proxies,
    _prepare_web_auth_state,
    _reset_admin_url,
    _setup_required,
    _settings,
    _normalize_username,
    _validate_bind_host_allowed,
    _validate_startup_auth,
    _validation_exception_handler,
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
    PlanDigestUnpinUpdate as PlanDigestUnpinUpdate,
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
    RetagApplyRequest as RetagApplyRequest,
    RetagChoiceRequest as RetagChoiceRequest,
    RetagPlanDigestPinUpdate as RetagPlanDigestPinUpdate,
    RetagPlanIssue as RetagPlanIssue,
    RetagPlanLabelRewrite as RetagPlanLabelRewrite,
    RetagPlanRequest as RetagPlanRequest,
    RetagPlanStack as RetagPlanStack,
    RetagPlanStatus as RetagPlanStatus,
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


DEFAULT_WEB_HOST = web_settings.DEFAULT_WEB_HOST
DEFAULT_WEB_PORT = 7417
DEFAULT_RUN_LIMIT = web_runs.DEFAULT_RUN_LIMIT
DEFAULT_LOG_TAIL_BYTES = web_runs.DEFAULT_LOG_TAIL_BYTES
DEFAULT_JOB_LOG_TAIL_BYTES = web_jobs.DEFAULT_JOB_LOG_TAIL_BYTES
MAX_LOG_TAIL_BYTES = web_runs.MAX_LOG_TAIL_BYTES
MANAGED_THEME_PREFERENCE_KEY = web_settings.MANAGED_THEME_PREFERENCE_KEY
MANAGED_THEME_PREFERENCE_DB_KEY = web_settings.MANAGED_THEME_PREFERENCE_DB_KEY
MANAGED_ONBOARDING_CHECKLIST_KEY = web_settings.MANAGED_ONBOARDING_CHECKLIST_KEY
MANAGED_COMPOSE_IGNORE_PATHS_KEY = web_settings.MANAGED_COMPOSE_IGNORE_PATHS_KEY
MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY = web_settings.MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY
MANAGED_DIGEST_PIN_UPDATES_KEY = web_settings.MANAGED_DIGEST_PIN_UPDATES_KEY
MANAGED_DIGEST_PIN_UPDATES_DB_KEY = web_settings.MANAGED_DIGEST_PIN_UPDATES_DB_KEY
THEME_PREFERENCE_VALUES = web_settings.THEME_PREFERENCE_VALUES
ONBOARDING_CHECKLIST_VALUES = web_settings.ONBOARDING_CHECKLIST_VALUES
DIGEST_PIN_UPDATES_VALUES = web_settings.DIGEST_PIN_UPDATES_VALUES
JOB_STREAM_HEARTBEAT_SECONDS = web_jobs.JOB_STREAM_HEARTBEAT_SECONDS
JOB_STREAM_LOG_POLL_SECONDS = web_jobs.JOB_STREAM_LOG_POLL_SECONDS
AUTO_UPDATE_POLL_SECONDS = web_scheduler.AUTO_UPDATE_POLL_SECONDS
AUTO_UPDATE_GRACE_SECONDS = web_scheduler.AUTO_UPDATE_GRACE_SECONDS
AUTO_UPDATE_DAYS = web_scheduler.AUTO_UPDATE_DAYS
AutoUpdateScheduleReservationError = (
    web_scheduler.AutoUpdateScheduleReservationError
)


# Import-compatibility re-exports for route handlers and helpers extracted from
# this module. New code and monkeypatches should target the owning web_* module.
api_pending = web_pending.api_pending
api_update_targets = web_pending.api_update_targets
api_retag_targets = web_retags.api_retag_targets
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

api_update_managed_settings = web_settings.api_update_managed_settings
api_settings = web_settings.api_settings
_effective_config = web_settings._effective_config
_effective_compose_ignore_paths = web_settings._effective_compose_ignore_paths
_stored_compose_ignore_paths = web_settings._stored_compose_ignore_paths
_compose_ignore_env_configured = web_settings._compose_ignore_env_configured
_compose_ignore_paths_disabled_reason = (
    web_settings._compose_ignore_paths_disabled_reason
)
_effective_digest_pin_updates = web_settings._effective_digest_pin_updates
_stored_digest_pin_updates = web_settings._stored_digest_pin_updates
_digest_pin_env_configured = web_settings._digest_pin_env_configured
_digest_pin_disabled_reason = web_settings._digest_pin_disabled_reason
_managed_settings_entries = web_settings._managed_settings_entries
_managed_settings_entries_from_conn = web_settings._managed_settings_entries_from_conn
_managed_settings_db_values = web_settings._managed_settings_db_values
_managed_settings_entries_from_values = (
    web_settings._managed_settings_entries_from_values
)
_validated_managed_setting_updates = (
    web_settings._validated_managed_setting_updates
)
_apply_managed_setting_updates = web_settings._apply_managed_setting_updates
_managed_settings_audit_values = web_settings._managed_settings_audit_values
_updater_settings_entries = web_settings._updater_settings_entries
_webui_settings_entries = web_settings._webui_settings_entries
_secret_settings = web_settings._secret_settings
_config_setting_entry = web_settings._config_setting_entry
_settings_entry = web_settings._settings_entry
_config_default_value = web_settings._config_default_value
_static_config_default = web_settings._static_config_default
_config_value = web_settings._config_value
_settings_env = web_settings._settings_env
_env_configured = web_settings._env_configured
_format_bool = web_settings._format_bool
_format_sequence = web_settings._format_sequence

api_state_operation = web_state.api_state_operation
api_service_policies = web_state.api_service_policies
api_snoozes = web_state.api_snoozes
api_tag_exclusions = web_state.api_tag_exclusions
_auto_update_days_from_row = web_state._auto_update_days_from_row
_service_policy_from_row = web_state._service_policy_from_row
_snooze_from_row = web_state._snooze_from_row
_dependency_snooze_from_row = web_state._dependency_snooze_from_row
_tag_exclusion_from_row = web_state._tag_exclusion_from_row
_apply_state_operation = web_state._apply_state_operation
_upsert_service_policy = web_state._upsert_service_policy
_service_policy_upsert_values = web_state._service_policy_upsert_values
_normalized_auto_update_time = web_state._normalized_auto_update_time
_normalized_auto_update_days = web_state._normalized_auto_update_days
_delete_service_policy = web_state._delete_service_policy
_create_snooze = web_state._create_snooze
_delete_snooze = web_state._delete_snooze
_create_dependency_snooze = web_state._create_dependency_snooze
_delete_dependency_snooze = web_state._delete_dependency_snooze
_upsert_tag_exclusion = web_state._upsert_tag_exclusion
_set_tag_exclusion_status = web_state._set_tag_exclusion_status
_service_policy_row = web_state._service_policy_row
_snooze_row = web_state._snooze_row
_dependency_snooze_row = web_state._dependency_snooze_row
_tag_exclusion_row = web_state._tag_exclusion_row
_tag_exclusion_unique_row = web_state._tag_exclusion_unique_row
_required_state_text = web_state._required_state_text
_future_iso_timestamp = web_state._future_iso_timestamp
_normalized_image_repo = web_state._normalized_image_repo
_tag_exclusion_service_key = web_state._tag_exclusion_service_key
_valid_tag = web_state._valid_tag
_insert_managed_settings_audit = web_settings._insert_managed_settings_audit
_insert_state_audit = web_state._insert_state_audit
_state_actor_type = web_state._state_actor_type
_state_audit_stack_name = web_state._state_audit_stack_name
_state_audit_service_name = web_state._state_audit_service_name
_state_audit_image = web_state._state_audit_image
_service_policy_summary = web_state._service_policy_summary
_snooze_summary = web_state._snooze_summary
_dependency_snooze_summary = web_state._dependency_snooze_summary
_tag_exclusion_summary = web_state._tag_exclusion_summary
_json_object = web_state._json_object
_json_list = web_state._json_list

api_run_log = web_runs.api_run_log
api_runs = web_runs.api_runs
api_run_detail = web_runs.api_run_detail
_run_summary_from_row = web_runs._run_summary_from_row
_pending_update_from_row = web_runs._pending_update_from_row
_event_from_row = web_runs._event_from_row
_sanitize_run_summary = web_runs._sanitize_run_summary
_sanitize_run_detail = web_runs._sanitize_run_detail
_sanitize_run_event = web_runs._sanitize_run_event
_metadata_from_row = web_runs._metadata_from_row
_safe_log_path = web_runs._safe_log_path
_path_is_or_under = web_runs._path_is_or_under
_run_log_response = web_runs._run_log_response
_read_log_tail = web_runs._read_log_tail

_mount_static_spa_if_present = web_static.mount_static_spa_if_present
_static_spa_available = web_static.static_spa_available
_resolve_static_dir = web_static.resolve_static_dir

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
    web_retags.configure(effective_config_loader=_effective_config)

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
        "/retag-targets",
        web_retags.api_retag_targets,
        methods=["GET"],
        response_model=RetagTargetsResponse,
    )
    router.add_api_route(
        "/retag-plans",
        web_retags.api_create_retag_plan,
        methods=["POST"],
        response_model=RetagPlanResponse,
    )
    router.add_api_route(
        "/retag-plans/apply",
        web_retags.api_apply_retag_plan,
        methods=["POST"],
        response_model=ApplyJobResponse,
        status_code=202,
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
    web_startup.print_web_startup_summary(
        settings,
        host=host,
        port=port,
        setup_claim=setup_claim,
        environ=env,
    )
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


def api_post_only_method_not_allowed() -> JSONResponse:
    return JSONResponse(
        {"detail": "method not allowed"},
        status_code=405,
        headers={"Allow": "POST"},
    )


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
