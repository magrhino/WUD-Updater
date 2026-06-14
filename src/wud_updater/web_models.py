"""Data models and type aliases for WebUI."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .config import UpdaterConfig

__all__ = (
    "APPLY_JOB_PROGRESS_STATUSES",
    "AdminRecoveryClaim",
    "ApplyJobLogResponse",
    "ApplyJobProgressEvent",
    "ApplyJobProgressStatus",
    "ApplyJobResponse",
    "ApplyJobStatus",
    "ApplyPlanRequest",
    "ApplyPreflightCheck",
    "ApplyPreflightResponse",
    "AuthSessionResponse",
    "AutoUpdateDay",
    "AutoUpdatePolicy",
    "AutoUpdateSelection",
    "ContainerRestartRequest",
    "ContainerRestartResponse",
    "CoreUpdateTourResponse",
    "CoreUpdateTourStatus",
    "CoreUpdateTourStep",
    "CoreUpdateTourUpdateRequest",
    "CreateSnoozeOperation",
    "CsrfResponse",
    "DEFAULT_CORE_UPDATE_TOUR_STEP",
    "DeleteServicePolicyOperation",
    "DeleteSnoozeOperation",
    "DiagnosticsSupportBundleResponse",
    "DigestTagProvenance",
    "DigestPinLabelRewriteApprovalRequest",
    "DoctorCheckResponse",
    "DoctorCheckStatus",
    "DoctorResponse",
    "DoctorSuggestionResponse",
    "HealthResponse",
    "LineNumber",
    "LogTail",
    "LoginRequest",
    "LoginThrottleEntry",
    "ManagedSettingEntry",
    "ManagedSettingSource",
    "ManagedSettingsUpdateRequest",
    "ManagedSettingsUpdateResponse",
    "OnboardingChecklistItem",
    "OnboardingChecklistResponse",
    "OnboardingDismissResponse",
    "OnboardingDocLink",
    "PASSWORD_MIN_LENGTH",
    "PendingCleanupLine",
    "PendingCleanupRemovedLine",
    "PendingCleanupRequest",
    "PendingCleanupResponse",
    "PendingDiagnostic",
    "PendingGroupedItem",
    "PendingGrouping",
    "PendingGroupingStatus",
    "PendingItem",
    "PendingRemovalPlanLine",
    "PendingRemovalPlanRequest",
    "PendingRemovalPlanResponse",
    "PendingRemovalRequest",
    "PendingResponse",
    "PendingStackGroup",
    "PendingUpdateRecord",
    "PlanAction",
    "PlanCleanup",
    "PlanCleanupItem",
    "PlanDigestPinLabelRewrite",
    "PlanDigestPinUpdate",
    "PlanDigestUnpinUpdate",
    "PlanIssue",
    "PlanLine",
    "PlanRequest",
    "PlanResponse",
    "PlanSkipped",
    "PlanStack",
    "PlanStatus",
    "PlanSummary",
    "PlanTagUpdate",
    "PlanTarget",
    "ReadyResponse",
    "ReleaseNoteInfo",
    "ReleaseNoteLink",
    "ReleaseNotesResponse",
    "ResetAdminClaimRequest",
    "RetagApplyRequest",
    "RetagChoiceRequest",
    "RetagPlanDigestPinUpdate",
    "RetagPlanIssue",
    "RetagPlanLabelRewrite",
    "RetagPlanRequest",
    "RetagPlanResponse",
    "RetagPlanStack",
    "RetagPlanStatus",
    "RunDetail",
    "RunEventRecord",
    "RunLogResponse",
    "RunSummary",
    "SELF_UPDATE_RELEASE_NOTES_CAP",
    "SecretSettingStatus",
    "SelfUpdateApplyResponse",
    "SelfUpdateAuditStatus",
    "SelfUpdatePlanResponse",
    "SelfUpdatePrepareRequest",
    "SelfUpdatePrepareResponse",
    "SelfUpdateReleaseNote",
    "SelfUpdateRequest",
    "SelfUpdateResponse",
    "SelfUpdateStatus",
    "SelfUpdateStrategy",
    "ServicePolicyRecord",
    "ServicePolicyUpdateMode",
    "SetTagExclusionStatusOperation",
    "SettingsEntry",
    "SettingsEntrySource",
    "SettingsResponse",
    "SetupClaimRequest",
    "SetupStatusResponse",
    "SnoozeRecord",
    "SnoozeState",
    "StateOperation",
    "StateOperationResponse",
    "StatusResponse",
    "TERMINAL_APPLY_JOB_STATUSES",
    "TagExclusionMatchType",
    "TagExclusionRuleRecord",
    "TagExclusionScope",
    "TagExclusionStatus",
    "TagExclusionStatusFilter",
    "TagOverrideRequest",
    "UpdateTargetItem",
    "UpdateTargetsResponse",
    "UpdateTargetsStatus",
    "UpsertServicePolicyOperation",
    "UpsertTagExclusionOperation",
    "WebApplyJob",
    "WebApplyJobProgressEvent",
    "WebSelfUpdatePlan",
    "WebSettings",
)

SELF_UPDATE_RELEASE_NOTES_CAP = 10

PASSWORD_MIN_LENGTH = 12

DEFAULT_CORE_UPDATE_TOUR_STEP = "dashboard"

LineNumber = Annotated[int, Field(ge=1)]

PlanStatus = Literal["ready", "empty", "blocked"]

PendingGroupingStatus = Literal["ready", "unavailable"]

DoctorCheckStatus = Literal["PASS", "WARN", "FAIL"]

ApplyJobStatus = Literal["queued", "running", "success", "failure"]

ApplyJobProgressStatus = Literal["running", "success", "failure", "skipped"]

SelfUpdateStatus = Literal["available", "up_to_date", "disabled", "unavailable"]

SelfUpdateStrategy = Literal["pull_image", "prepare_tag_update"]

SelfUpdateAuditStatus = Literal["image_pulled", "tag_prepared", "failure"]

SettingsEntrySource = Literal["configured", "default", "derived", "request"]

ManagedSettingSource = Literal["configured", "default"]

ServicePolicyUpdateMode = Literal["", "pause", "stop", "live"]

AutoUpdateDay = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

CoreUpdateTourStatus = Literal[
    "not_started",
    "in_progress",
    "completed",
    "dismissed",
]

CoreUpdateTourStep = Literal[
    "dashboard",
    "pending_select",
    "pending_preflight",
    "pending_apply",
    "runs_history",
]

SnoozeState = Literal["active", "expired", "all"]

TagExclusionScope = Literal["image_repo", "service"]

TagExclusionMatchType = Literal["exact"]

TagExclusionStatus = Literal["active", "disabled"]

TagExclusionStatusFilter = Literal["active", "disabled", "all"]

TERMINAL_APPLY_JOB_STATUSES = frozenset({"success", "failure"})

APPLY_JOB_PROGRESS_STATUSES = frozenset({"running", "success", "failure", "skipped"})

@dataclass(frozen=True)
class WebSettings:
    config: UpdaterConfig
    auth_token: str
    dev_no_auth: bool = False
    allowed_origins: frozenset[str] = frozenset()
    public_origin: str = ""
    allowed_hosts: frozenset[str] = frozenset()
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    secure_cookies: str = "auto"
    mutations_enabled: bool = False
    static_dir: Path | None = None
    host_docker_base: Path | None = None
    restart_container: str = ""
    command_env: Mapping[str, str] | None = None

    @property
    def auth_required(self) -> bool:
        return not self.dev_no_auth

@dataclass
class WebApplyJobProgressEvent:
    phase: str
    status: ApplyJobProgressStatus
    message: str
    created_at: str
    stack: str = ""
    services: tuple[str, ...] = ()
    line_numbers: tuple[int, ...] = ()

@dataclass
class WebApplyJob:
    id: str
    status: ApplyJobStatus
    selected_line_numbers: tuple[int, ...]
    version: int = 0
    run_id: int | None = None
    log_file: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str = ""
    progress: tuple[WebApplyJobProgressEvent, ...] = ()

@dataclass(frozen=True)
class WebSelfUpdatePlan:
    plan_id: str
    created_at: float
    wud_file: Path
    current_tag: str
    latest_tag: str
    current_image: str
    target_spec: str
    target_image: str
    restart_container: str

@dataclass
class LoginThrottleEntry:
    failures: int
    first_failed_at: float
    last_failed_at: float
    locked_until: float = 0.0

@dataclass(frozen=True)
class AutoUpdatePolicy:
    service_key: str
    update_mode: str
    auto_update_time: str
    auto_update_days: tuple[str, ...]
    schedule_key: str
    scheduled_for: datetime

@dataclass(frozen=True)
class AutoUpdateSelection:
    line_numbers: tuple[int, ...]
    service_keys: tuple[str, ...]
    schedule_keys: tuple[str, ...]
    scheduled_for: datetime
    update_mode: str

@dataclass(frozen=True)
class LogTail:
    exists: bool
    content: str
    truncated: bool

@dataclass(frozen=True)
class AdminRecoveryClaim:
    username: str
    claim: str
    expires_at: str
    revoked_sessions: int
    audit_run_id: int

class DigestTagProvenance(BaseModel):
    source_image: str
    resolved_tag: str
    watch_tag: str
    target_digest: str
    final_image: str
    provenance_source: str
    provenance_confidence: str


class PendingItem(BaseModel):
    line_no: int
    raw: str
    image: str
    key: str
    repo: str
    current_tag: str
    has_tag: bool
    allow_repo: bool
    digest: str
    desired_tag: str
    digest_provenance: DigestTagProvenance | None = None


class PendingDiagnostic(BaseModel):
    code: str
    message: str
    hint: str = ""
    stack: str = ""
    service: str = ""
    compose_file: str = ""
    found_files: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

class PendingGroupedItem(PendingItem):
    resolved_image: str
    target_image: str
    compose_images: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    action: str
    diagnostic: PendingDiagnostic | None = None

class PendingStackGroup(BaseModel):
    name: str
    directory: str
    compose_file: str
    project_directory: str
    services_label: str
    services: list[str] = Field(default_factory=list)
    line_numbers: list[int] = Field(default_factory=list)
    items: list[PendingGroupedItem] = Field(default_factory=list)

class PendingGrouping(BaseModel):
    status: PendingGroupingStatus
    groups: list[PendingStackGroup] = Field(default_factory=list)
    unmatched: list[PendingGroupedItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class PendingResponse(BaseModel):
    source_file: str
    exists: bool
    count: int
    items: list[PendingItem] = Field(default_factory=list)
    grouping: PendingGrouping = Field(
        default_factory=lambda: PendingGrouping(status="unavailable")
    )
    warnings: list[str] = Field(default_factory=list)

UpdateTargetsStatus = Literal["ready", "unavailable"]

class UpdateTargetItem(BaseModel):
    service_key: str
    stack: str
    service: str
    image: str
    image_repo: str
    current_tag: str
    directory: str
    compose_file: str
    project_directory: str

class UpdateTargetsResponse(BaseModel):
    status: UpdateTargetsStatus
    count: int
    items: list[UpdateTargetItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

RetagTargetsStatus = Literal["ready", "unavailable"]

RetagPlanStatus = Literal["ready", "empty", "blocked", "unavailable"]

class RetagTargetItem(BaseModel):
    service_key: str
    stack: str
    service: str
    image: str
    image_repo: str
    current_tag: str
    tracking_tag: str
    tracking_tag_source: str
    proposed_tag: str
    final_image: str
    retag_available: bool
    retag_reason: str
    choices: list[str] = Field(default_factory=list)
    label_key: str
    label_value: str
    directory: str
    compose_file: str
    project_directory: str
    digest_provenance: DigestTagProvenance | None = None

class RetagTargetsResponse(BaseModel):
    status: RetagTargetsStatus
    count: int
    items: list[RetagTargetItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class RetagChoiceRequest(BaseModel):
    service_key: str = Field(min_length=1, max_length=512)
    choice: Literal["keep-current", "switch-to-concrete"]

class RetagPlanRequest(BaseModel):
    choices: list[RetagChoiceRequest] = Field(min_length=1)

class RetagApplyRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    choices: list[RetagChoiceRequest] = Field(min_length=1)
    confirmation: Literal["apply-retags"]

class RetagPlanIssue(BaseModel):
    severity: str
    code: str
    message: str
    service_key: str = ""
    stack: str = ""
    service: str = ""
    hint: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

class RetagPlanLabelRewrite(BaseModel):
    service: str
    label_key: str
    current_label_value: str
    planned_tag: str
    proposed_label_value: str
    proposed_label_regex: str
    approved: bool
    reason: str

class RetagPlanDigestPinUpdate(BaseModel):
    service_key: str
    stack: str
    service: str
    source_image: str
    resolved_tag: str
    planned_digest: str
    final_image: str
    watch_tag: str
    marker: str
    label_key: str
    label_value: str
    label_rewrites: list[RetagPlanLabelRewrite] = Field(default_factory=list)
    digest_provenance: DigestTagProvenance | None = None

class RetagPlanStack(BaseModel):
    stack: str
    directory: str
    compose_file: str
    project_directory: str
    services: list[str] = Field(default_factory=list)
    digest_pin_updates: list[RetagPlanDigestPinUpdate] = Field(default_factory=list)

class RetagPlanResponse(BaseModel):
    plan_id: str
    status: RetagPlanStatus
    can_apply: bool
    external_recreate_required: bool = False
    selected_count: int = 0
    keep_current_count: int = 0
    stacks: list[RetagPlanStack] = Field(default_factory=list)
    issues: list[RetagPlanIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class ReleaseNoteLink(BaseModel):
    label: str
    url: str
    kind: str

class ReleaseNoteInfo(BaseModel):
    line_no: int
    status: str
    provider: str
    image_repo: str
    upstream_repo: str
    release_tag: str = ""
    title: str = ""
    published_at: str = ""
    breaking: bool = False
    breaking_reasons: list[str] = Field(default_factory=list)
    links: list[ReleaseNoteLink] = Field(default_factory=list)
    refreshed_at: str = ""
    error: str = ""

class ReleaseNotesResponse(BaseModel):
    source_file: str
    count: int
    items: list[ReleaseNoteInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class HealthResponse(BaseModel):
    ok: bool
    version: str

class StatusResponse(BaseModel):
    ok: bool
    version: str
    wud_file: str
    wud_file_exists: bool
    pending_count: int
    db_path: str
    db_ready: bool
    auth_required: bool
    dev_auth_bypass: bool
    setup_required: bool
    mutations_enabled: bool
    timezone: str
    auto_update_scheduler_enabled: bool
    static_spa_available: bool
    warnings: list[str] = Field(default_factory=list)

class SettingsEntry(BaseModel):
    name: str
    value: str
    default_value: str
    configured: bool
    source: SettingsEntrySource

class SecretSettingStatus(BaseModel):
    name: str
    configured: bool

class ManagedSettingEntry(BaseModel):
    key: str
    value: str
    default_value: str
    source: ManagedSettingSource
    editable: bool
    allowed_values: list[str] = Field(default_factory=list)
    restart_required: bool
    disabled_reason: str = ""

class ManagedSettingsUpdateRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)

class ManagedSettingsUpdateResponse(BaseModel):
    managed: list[ManagedSettingEntry] = Field(default_factory=list)
    audit_run_id: int

class SettingsResponse(BaseModel):
    updater: list[SettingsEntry] = Field(default_factory=list)
    webui: list[SettingsEntry] = Field(default_factory=list)
    secrets: list[SecretSettingStatus] = Field(default_factory=list)
    managed: list[ManagedSettingEntry] = Field(default_factory=list)

class DoctorSuggestionResponse(BaseModel):
    label: str
    description: str = ""
    snippet: str = ""

class DoctorCheckResponse(BaseModel):
    status: DoctorCheckStatus
    code: str
    category: str
    name: str
    detail: str = ""
    target: str = ""
    suggestions: list[DoctorSuggestionResponse] = Field(default_factory=list)

class DoctorResponse(BaseModel):
    ok: bool
    failures: int
    warnings: int
    checks: list[DoctorCheckResponse] = Field(default_factory=list)

class ReadyResponse(BaseModel):
    ok: bool
    version: str
    checks: list[DoctorCheckResponse] = Field(default_factory=list)

class ApplyPreflightCheck(BaseModel):
    status: DoctorCheckStatus
    code: str
    label: str
    detail: str = ""
    source_check_codes: list[str] = Field(default_factory=list)

class ApplyPreflightResponse(BaseModel):
    ok: bool
    failures: int
    warnings: int
    checks: list[ApplyPreflightCheck] = Field(default_factory=list)

class OnboardingDocLink(BaseModel):
    label: str
    url: str

class OnboardingChecklistItem(BaseModel):
    key: str
    title: str
    status: DoctorCheckStatus
    detail: str = ""
    check_codes: list[str] = Field(default_factory=list)
    suggestions: list[DoctorSuggestionResponse] = Field(default_factory=list)
    docs: list[OnboardingDocLink] = Field(default_factory=list)

class OnboardingChecklistResponse(BaseModel):
    dismissed: bool
    dismissed_at: str
    all_passed: bool
    visible: bool
    items: list[OnboardingChecklistItem] = Field(default_factory=list)

class OnboardingDismissResponse(BaseModel):
    dismissed: bool
    dismissed_at: str

class CoreUpdateTourResponse(BaseModel):
    status: CoreUpdateTourStatus
    step: CoreUpdateTourStep
    updated_at: str = ""

class CoreUpdateTourUpdateRequest(BaseModel):
    status: CoreUpdateTourStatus
    step: CoreUpdateTourStep = DEFAULT_CORE_UPDATE_TOUR_STEP

class CsrfResponse(BaseModel):
    csrf_token: str

class SetupStatusResponse(BaseModel):
    setup_required: bool
    claim_required: bool
    authenticated: bool
    auth_required: bool
    dev_auth_bypass: bool
    mutations_enabled: bool
    password_min_length: int

class SetupClaimRequest(BaseModel):
    claim: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=1024)

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)

class ResetAdminClaimRequest(BaseModel):
    claim: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=1024)

class AuthSessionResponse(BaseModel):
    authenticated: bool
    setup_required: bool
    auth_required: bool
    dev_auth_bypass: bool
    mutations_enabled: bool
    username: str | None = None

class RunEventRecord(BaseModel):
    id: int
    run_id: int
    created_at: str
    service_name: str
    stack_name: str
    image: str
    target_image: str
    old_image_id: str
    new_image_id: str
    old_digest: str
    new_digest: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    digest_provenance: DigestTagProvenance | None = None

class RunSummary(BaseModel):
    id: int
    started_at: str
    finished_at: str | None
    status: str
    dry_run: bool
    mode: str
    wud_file: str
    log_file: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    events: list[RunEventRecord] = Field(default_factory=list)

class PendingUpdateRecord(BaseModel):
    id: int
    run_id: int
    line_no: int
    raw: str
    image: str
    target_digest: str
    desired_tag: str
    service_key: str
    stack_name: str
    service_name: str
    status: str
    status_reason: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    digest_provenance: DigestTagProvenance | None = None

class RunDetail(RunSummary):
    pending_updates: list[PendingUpdateRecord] = Field(default_factory=list)

class RunLogResponse(BaseModel):
    run_id: int
    log_file: str
    exists: bool
    content: str
    truncated: bool
    max_bytes: int

class DiagnosticsSupportBundleResponse(BaseModel):
    wud_updater_version: str
    settings: SettingsResponse
    doctor_result: DoctorResponse
    pending_summary: PendingResponse
    last_run_status: RunSummary | None
    diagnostics_warnings: list[str] = Field(default_factory=list)
    discovery_warnings: list[str] = Field(default_factory=list)
    log_tail: LogTail | None

class TagOverrideRequest(BaseModel):
    line_no: LineNumber
    tag: str = Field(min_length=1, max_length=128)

class DigestPinLabelRewriteApprovalRequest(BaseModel):
    stack: str = Field(min_length=1, max_length=256)
    service: str = Field(min_length=1, max_length=256)
    label_key: str = Field(min_length=1, max_length=256)
    current_label_value: str = Field(min_length=1, max_length=512)
    planned_tag: str = Field(min_length=1, max_length=128)
    proposed_label_value: str = Field(min_length=1, max_length=512)

class PlanRequest(BaseModel):
    line_numbers: list[LineNumber] = Field(min_length=1)
    allow_tag_updates: bool = False
    tag_overrides: list[TagOverrideRequest] = Field(default_factory=list)
    digest_pin_label_rewrite_approvals: list[
        DigestPinLabelRewriteApprovalRequest
    ] = Field(default_factory=list)

class PlanSummary(BaseModel):
    target_count: int
    matched_target_count: int
    stack_count: int
    service_count: int
    skipped_count: int
    issue_count: int

class PlanIssue(BaseModel):
    severity: str
    code: str
    message: str
    line_no: int | None = None
    stack: str = ""
    service: str = ""
    hint: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

class PlanTarget(BaseModel):
    line_no: int
    raw: str
    image: str
    resolved_image: str
    digest: str
    desired_tag: str
    matched: bool
    action: str

class PlanLine(BaseModel):
    line_no: int
    raw: str
    image: str
    resolved_image: str
    compose_image: str
    target_image: str
    service: str
    digest: str
    desired_tag: str
    action: str
    digest_provenance: DigestTagProvenance | None = None

class PlanTagUpdate(BaseModel):
    old_image: str
    desired_tag: str
    new_image: str
    services: list[str] = Field(default_factory=list)

class PlanDigestPinLabelRewrite(BaseModel):
    service: str
    label_key: str
    current_label_value: str
    planned_tag: str
    proposed_label_value: str
    proposed_label_regex: str
    approved: bool
    reason: str

class PlanDigestPinUpdate(BaseModel):
    source_image: str
    resolved_tag: str
    planned_digest: str
    final_image: str
    watch_tag: str
    marker: str
    label_key: str
    label_value: str
    services: list[str] = Field(default_factory=list)
    label_rewrites: list[PlanDigestPinLabelRewrite] = Field(default_factory=list)
    digest_provenance: DigestTagProvenance | None = None

class PlanDigestUnpinUpdate(BaseModel):
    source_image: str
    resolved_tag: str
    tag_image: str
    current_digest: str
    target_digest: str
    watch_tag: str
    marker: str
    label_key: str
    label_value: str
    services: list[str] = Field(default_factory=list)
    digest_provenance: DigestTagProvenance | None = None

class PlanAction(BaseModel):
    kind: str
    description: str
    cwd: str
    args: list[str] = Field(default_factory=list)

class PlanStack(BaseModel):
    name: str
    directory: str
    compose_file: str
    project_directory: str
    services_label: str
    services: list[str] = Field(default_factory=list)
    pull_services: list[str] = Field(default_factory=list)
    stop_services: list[str] = Field(default_factory=list)
    force_recreate: bool
    up_no_deps: bool
    tag_updates: list[PlanTagUpdate] = Field(default_factory=list)
    digest_pin_updates: list[PlanDigestPinUpdate] = Field(default_factory=list)
    digest_unpin_updates: list[PlanDigestUnpinUpdate] = Field(default_factory=list)
    actions: list[PlanAction] = Field(default_factory=list)
    lines: list[PlanLine] = Field(default_factory=list)

class PlanSkipped(BaseModel):
    line_no: int
    raw: str
    image: str
    desired_tag: str
    reason: str

class PlanCleanupItem(BaseModel):
    line_no: int
    raw: str
    image: str
    desired_tag: str
    digest: str
    reason: str
    diagnostic: PendingDiagnostic | None = None

class PlanCleanup(BaseModel):
    cleanup_id: str = ""
    can_remove_unmatched: bool = False
    items: list[PlanCleanupItem] = Field(default_factory=list)

class PlanResponse(BaseModel):
    plan_id: str
    dry_run: bool
    can_apply: bool
    status: PlanStatus
    source_file: str
    mode: str
    max_wait: int
    digest_pin_updates: bool
    selected_line_numbers: list[int] = Field(default_factory=list)
    summary: PlanSummary
    targets: list[PlanTarget] = Field(default_factory=list)
    stacks: list[PlanStack] = Field(default_factory=list)
    skipped: list[PlanSkipped] = Field(default_factory=list)
    issues: list[PlanIssue] = Field(default_factory=list)
    cleanup: PlanCleanup = Field(default_factory=PlanCleanup)
    apply_preflight: ApplyPreflightResponse

class PendingCleanupLine(BaseModel):
    line_no: LineNumber
    raw: str

class PendingCleanupRequest(BaseModel):
    cleanup_id: str = Field(min_length=1)
    lines: list[PendingCleanupLine] = Field(min_length=1)
    confirmation: Literal["remove_unmatched"]

class PendingCleanupRemovedLine(BaseModel):
    line_no: int
    raw: str
    image: str
    reason: str

class PendingCleanupResponse(BaseModel):
    status: Literal["success"]
    audit_run_id: int
    removed_count: int
    removed: list[PendingCleanupRemovedLine] = Field(default_factory=list)

class PendingRemovalPlanRequest(BaseModel):
    line_numbers: list[LineNumber] = Field(min_length=1)

class PendingRemovalPlanLine(BaseModel):
    line_no: int
    raw: str
    image: str
    desired_tag: str = ""
    digest: str = ""

class PendingRemovalPlanResponse(BaseModel):
    removal_id: str
    source_file: str
    can_remove: bool
    selected_line_numbers: list[int] = Field(default_factory=list)
    lines: list[PendingRemovalPlanLine] = Field(default_factory=list)

class PendingRemovalRequest(BaseModel):
    removal_id: str = Field(min_length=1)
    lines: list[PendingCleanupLine] = Field(min_length=1)
    confirmation: Literal["remove_selected"]

class ApplyPlanRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    line_numbers: list[LineNumber] = Field(min_length=1)
    allow_tag_updates: bool = False
    tag_overrides: list[TagOverrideRequest] = Field(default_factory=list)
    digest_pin_label_rewrite_approvals: list[
        DigestPinLabelRewriteApprovalRequest
    ] = Field(default_factory=list)
    confirmation: Literal["apply"]

class ApplyJobResponse(BaseModel):
    job_id: str
    status: ApplyJobStatus
    run_id: int | None = None
    log_file: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str = ""
    selected_line_numbers: list[int] = Field(default_factory=list)
    progress: list["ApplyJobProgressEvent"] = Field(default_factory=list)

class ApplyJobProgressEvent(BaseModel):
    job_id: str
    phase: str
    status: ApplyJobProgressStatus
    message: str
    created_at: str
    stack: str = ""
    services: list[str] = Field(default_factory=list)
    line_numbers: list[int] = Field(default_factory=list)

class ApplyJobLogResponse(BaseModel):
    job_id: str
    log_file: str = ""
    exists: bool = False
    content: str = ""
    truncated: bool = False
    max_bytes: int
    error: str = ""

class ServicePolicyRecord(BaseModel):
    service_key: str
    update_mode: str
    auto_update: bool
    snooze_default_seconds: int | None
    auto_update_time: str | None
    auto_update_days: list[AutoUpdateDay] = Field(default_factory=list)
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class SnoozeRecord(BaseModel):
    id: int
    service_key: str
    snoozed_until: str
    reason: str
    created_at: str
    active: bool
    metadata: dict[str, Any] = Field(default_factory=dict)

class TagExclusionRuleRecord(BaseModel):
    id: int
    scope: str
    image_repo: str
    service_key: str
    match_type: str
    tag: str
    regex_fragment: str
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class UpsertServicePolicyOperation(BaseModel):
    kind: Literal["upsert_service_policy"]
    service_key: str = Field(min_length=1, max_length=512)
    update_mode: ServicePolicyUpdateMode = ""
    auto_update: bool = True
    snooze_default_seconds: int | None = Field(default=None, ge=0)
    auto_update_time: str | None = Field(default=None, max_length=5)
    auto_update_days: list[AutoUpdateDay] = Field(default_factory=list)

class DeleteServicePolicyOperation(BaseModel):
    kind: Literal["delete_service_policy"]
    service_key: str = Field(min_length=1, max_length=512)

class CreateSnoozeOperation(BaseModel):
    kind: Literal["create_snooze"]
    service_key: str = Field(min_length=1, max_length=512)
    snoozed_until: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=1024)

class DeleteSnoozeOperation(BaseModel):
    kind: Literal["delete_snooze"]
    snooze_id: int = Field(ge=1)

class UpsertTagExclusionOperation(BaseModel):
    kind: Literal["upsert_tag_exclusion"]
    scope: TagExclusionScope
    image_repo: str = Field(min_length=1, max_length=512)
    service_key: str = Field(default="", max_length=512)
    match_type: TagExclusionMatchType = "exact"
    tag: str = Field(min_length=1, max_length=128)
    status: TagExclusionStatus = "active"

class SetTagExclusionStatusOperation(BaseModel):
    kind: Literal["set_tag_exclusion_status"]
    rule_id: int = Field(ge=1)
    status: TagExclusionStatus

StateOperation = Annotated[
    UpsertServicePolicyOperation
    | DeleteServicePolicyOperation
    | CreateSnoozeOperation
    | DeleteSnoozeOperation
    | UpsertTagExclusionOperation
    | SetTagExclusionStatusOperation,
    Field(discriminator="kind"),
]

class StateOperationResponse(BaseModel):
    operation: str
    status: Literal["success"]
    audit_run_id: int
    resource_type: str
    resource_id: str
    resource: ServicePolicyRecord | SnoozeRecord | TagExclusionRuleRecord | None = None

class ContainerRestartRequest(BaseModel):
    confirmation: Literal["restart_container"]

class ContainerRestartResponse(BaseModel):
    status: Literal["scheduled"]
    audit_run_id: int
    container: str

class SelfUpdateReleaseNote(BaseModel):
    tag: str
    title: str
    published_at: str
    url: str
    body: str = ""
    body_truncated: bool = False
    breaking: bool = False
    breaking_reasons: list[str] = Field(default_factory=list)

class SelfUpdateResponse(BaseModel):
    status: SelfUpdateStatus
    strategy: SelfUpdateStrategy = "pull_image"
    current_tag: str
    latest_tag: str
    current_image: str
    target_image: str
    restart_container: str
    release_notes: list[SelfUpdateReleaseNote] = Field(default_factory=list)
    release_notes_truncated: bool = False
    release_notes_cap: int = SELF_UPDATE_RELEASE_NOTES_CAP
    can_update: bool = False
    disabled_reason: str = ""
    external_recreate_required: bool = False
    warnings: list[str] = Field(default_factory=list)

class SelfUpdateRequest(BaseModel):
    confirmation: Literal["pull_image"]
    current_tag: str
    latest_tag: str
    target_image: str
    restart_container: str

class SelfUpdatePlanResponse(BaseModel):
    strategy: Literal["prepare_tag_update"]
    plan: PlanResponse
    current_tag: str
    latest_tag: str
    current_image: str
    target_image: str
    restart_container: str
    external_recreate_required: bool = True
    warning: str = (
        "This updates the Compose image tag and pulls the image. Recreate the "
        "WUD-Updater container from outside the WebUI to run it."
    )

class SelfUpdatePrepareRequest(BaseModel):
    confirmation: Literal["prepare_tag_update"]
    plan_id: str = Field(min_length=1)
    current_tag: str
    latest_tag: str
    target_image: str
    restart_container: str

class SelfUpdateApplyResponse(BaseModel):
    status: Literal["image_pulled"]
    audit_run_id: int
    current_tag: str
    latest_tag: str
    target_image: str
    container: str

class SelfUpdatePrepareResponse(BaseModel):
    status: Literal["tag_prepared"]
    audit_run_id: int
    current_tag: str
    latest_tag: str
    target_image: str
    container: str
    external_recreate_required: bool = True
