"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from threading import Condition, Event, Lock, Thread
from types import SimpleNamespace
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .banner import (
    current_tag,
    fetch_latest_release_tag,
    release_check_enabled,
    release_update_available,
)
from .command import CommandError, CommandRunner
from .compose import ComposeCli, ComposeDiscoveryError
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
    SCHEMA_VERSION,
    active_snooze,
    connect_db,
    init_db,
    utc_timestamp,
)
from .db import _user_version as db_user_version
from .db import _validate_schema as validate_db_schema
from .doctor import (
    Doctor,
    DoctorCheck as DoctorDataCheck,
    DoctorConfigError,
    DoctorOptions as DoctorDataOptions,
    DoctorResult as DoctorDataResult,
    DoctorSuggestion as DoctorDataSuggestion,
    options_from_namespace as doctor_options_from_namespace,
)
from .digest_verifier import DigestVerifier, DockerManifestResolver
from .docker_cli import ContainerImage, DockerCli
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_tag,
    image_with_tag,
    normalize_digest,
    repo_key,
    tag_value_valid,
)
from .locks import DirectoryLock, WudLockError
from .plans import (
    DryRunPlan,
    DryRunPlanCleanup,
    DryRunPlanCleanupItem,
    PlanFileMissing,
    PlanInputError,
    build_dry_run_plan,
    build_unmatched_cleanup,
    resolve_pending_groups,
)
from .release_notes import (
    OCI_SOURCE_LABEL,
    ReleaseNoteSourceResolver,
    cached_release_notes,
    detect_breaking,
    github_repo_from_ghcr_image,
    github_repo_from_source,
    refresh_release_notes,
    release_note_placeholders,
)
from .self_update import current_container_image, release_self_update_target
from .updater import (
    ComposeTagRewriteError,
    DigestPinUpdate,
    TagOverride,
    TagUpdate,
    UpdaterProgressEvent,
    UpdateFromWudRunner,
    UpdaterOptions,
    apply_compose_digest_pins,
    apply_compose_tag_updates,
    digest_pin_update_from_values,
    js_regex_escape,
    _backup_compose,
)
from .file_ops import OwnerConfig
from .wud_file import ParsedWudFile, WudTarget, parse_wud_file, remove_lines_before_run


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 7417
DEFAULT_RUN_LIMIT = 50
DEFAULT_LOG_TAIL_BYTES = 262_144
DEFAULT_JOB_LOG_TAIL_BYTES = 65_536
SELF_UPDATE_RELEASE_NOTES_CAP = 10
SELF_UPDATE_RELEASES_URL = "https://api.github.com/repos/magrhino/WUD-Updater/releases"
SELF_UPDATE_PLAN_TTL_SECONDS = 30 * 60
MAX_LOG_TAIL_BYTES = 1_048_576
SESSION_MAX_AGE_SECONDS = 86_400
SETUP_CLAIM_MAX_AGE_SECONDS = 86_400
PASSWORD_MIN_LENGTH = 12
LOGIN_THROTTLE_MAX_FAILURES = 5
LOGIN_THROTTLE_COOLDOWN_SECONDS = 60.0
LOGIN_THROTTLE_MAX_ENTRIES = 1024
LOGIN_THROTTLE_MAX_CLIENT_ENTRIES = 1024
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
SECURE_COOKIE_MODES = frozenset({"auto", "true", "false"})
CSRF_HEADER = "x-wud-csrf-token"
CSRF_COOKIE = "wud_csrf_token"
SESSION_COOKIE = "wud_session"
SETUP_CLAIM_HASH_KEY = "setup_claim_hash"
SETUP_CLAIM_EXPIRES_KEY = "setup_claim_expires_at"
RESET_ADMIN_CLAIM_HASH_KEY = "reset_admin_claim_hash"
RESET_ADMIN_CLAIM_EXPIRES_KEY = "reset_admin_claim_expires_at"
RESET_ADMIN_CLAIM_USER_ID_KEY = "reset_admin_claim_user_id"
ONBOARDING_DISMISSED_AT_KEY = "onboarding_checklist_dismissed_at"
CORE_UPDATE_TOUR_KEY = "onboarding_core_update_tour"
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
CORE_UPDATE_TOUR_STATUS_VALUES = (
    "not_started",
    "in_progress",
    "completed",
    "dismissed",
)
CORE_UPDATE_TOUR_STEP_VALUES = (
    "dashboard",
    "pending_select",
    "pending_preflight",
    "pending_apply",
    "runs_history",
)
DEFAULT_CORE_UPDATE_TOUR_STEP = "dashboard"
DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SENSITIVE_ENV_KEYS = (
    "WUD_WEB_TOKEN",
    "GITHUB_TOKEN",
    "DISCORD_RELEASES_WEBHOOK",
    "DISCORD_WEBHOOK",
    "ADMIN_WEBHOOK",
)
CONTAINER_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PASSWORD_HASHER = PasswordHasher()
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
JOB_STREAM_HEARTBEAT_SECONDS = 15.0
JOB_STREAM_LOG_POLL_SECONDS = 1.0
AUTO_UPDATE_POLL_SECONDS = 60.0
AUTO_UPDATE_GRACE_SECONDS = 300
AUTO_UPDATE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOGGER = logging.getLogger(__name__)


class WebConfigError(ValueError):
    """Raised when WebUI configuration is invalid."""


class ReadOnlyDatabaseMissing(RuntimeError):
    """Raised when the read-only WebUI database does not exist."""


class WebAdminResetError(RuntimeError):
    """Raised when local admin recovery cannot be issued."""


class AutoUpdateScheduleReservationError(RuntimeError):
    """Raised when an automatic update schedule slot was already claimed."""


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


READINESS_DOCKER_ENDPOINT_CODES = frozenset({"docker-endpoint", "docker-socket"})
READINESS_REQUIRED_CODES = frozenset(
    {
        "docker-daemon-version",
        "docker-daemon-info",
        "docker-container-listing",
        "wud-out-file-directory",
        "wud-out-file",
        "webui-database",
    }
)
READINESS_INCLUDED_CODES = (
    READINESS_DOCKER_ENDPOINT_CODES | READINESS_REQUIRED_CODES | {"configuration"}
)


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


class PlanRequest(BaseModel):
    line_numbers: list[LineNumber] = Field(min_length=1)
    allow_tag_updates: bool = False
    tag_overrides: list[TagOverrideRequest] = Field(default_factory=list)


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


class PlanTagUpdate(BaseModel):
    old_image: str
    desired_tag: str
    new_image: str
    services: list[str] = Field(default_factory=list)


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
    app.state.web_apply_executor = ThreadPoolExecutor(max_workers=1)
    app.state.web_apply_lock = Lock()
    app.state.web_apply_condition = Condition(app.state.web_apply_lock)
    app.state.web_apply_jobs = {}
    app.state.web_self_update_running = False
    app.state.web_self_update_plans = {}
    app.state.web_login_throttle_lock = Lock()
    app.state.web_login_throttle = {}
    app.state.web_login_client_throttle = {}
    app.state.web_auto_update_started_at = datetime.now(timezone.utc)
    app.state.web_auto_update_stop = Event()
    app.state.web_auto_update_thread = None
    if not active_settings.dev_no_auth:
        app.state.web_setup_claim = _prepare_web_auth_state(active_settings)
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,
    )

    if active_settings.mutations_enabled:
        app.state.web_auto_update_thread = _start_auto_update_scheduler(
            app,
            active_settings,
        )

    def shutdown_apply_executor() -> None:
        app.state.web_auto_update_stop.set()
        thread = app.state.web_auto_update_thread
        if thread is not None:
            thread.join(timeout=1.0)
        app.state.web_apply_executor.shutdown(wait=False, cancel_futures=True)

    router_shutdown = getattr(getattr(app, "router", None), "on_shutdown", None)
    if isinstance(router_shutdown, list):
        router_shutdown.append(shutdown_apply_executor)

    @app.middleware("http")
    async def web_request_safety(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host_error = _host_header_error(request, active_settings)
        if host_error is not None:
            return host_error
        if _requires_csrf_origin_check(request):
            error = _csrf_origin_error(request, active_settings)
            if error is not None:
                return error
        return await call_next(request)

    app.add_api_route(
        "/healthz",
        api_healthz,
        methods=["GET"],
        response_model=HealthResponse,
    )
    app.add_api_route(
        "/readyz",
        api_readyz,
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
        api_doctor,
        methods=["POST"],
        response_model=DoctorResponse,
    )
    router.add_api_route(
        "/doctor",
        api_doctor_method_not_allowed,
        methods=["GET"],
    )
    router.add_api_route(
        "/ready",
        api_ready,
        methods=["GET"],
        response_model=ReadyResponse,
    )
    router.add_api_route(
        "/onboarding/checklist",
        api_onboarding_checklist,
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
        api_onboarding_dismiss,
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
        api_core_update_tour,
        methods=["GET"],
        response_model=CoreUpdateTourResponse,
    )
    router.add_api_route(
        "/onboarding/core-update-tour",
        api_update_core_update_tour,
        methods=["POST"],
        response_model=CoreUpdateTourResponse,
    )
    router.add_api_route(
        "/pending",
        api_pending,
        methods=["GET"],
        response_model=PendingResponse,
    )
    router.add_api_route(
        "/update-targets",
        api_update_targets,
        methods=["GET"],
        response_model=UpdateTargetsResponse,
    )
    router.add_api_route(
        "/pending/cleanup",
        api_pending_cleanup,
        methods=["POST"],
        response_model=PendingCleanupResponse,
    )
    router.add_api_route(
        "/pending/removal-plan",
        api_pending_removal_plan,
        methods=["POST"],
        response_model=PendingRemovalPlanResponse,
    )
    router.add_api_route(
        "/pending/removal",
        api_pending_removal,
        methods=["POST"],
        response_model=PendingCleanupResponse,
    )
    router.add_api_route(
        "/release-notes",
        api_release_notes,
        methods=["GET"],
        response_model=ReleaseNotesResponse,
    )
    router.add_api_route(
        "/release-notes/refresh",
        api_refresh_release_notes,
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
        api_diagnostics_support_bundle,
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
        api_self_update,
        methods=["GET"],
        response_model=SelfUpdateResponse,
    )
    router.add_api_route(
        "/self-update/plan",
        api_plan_self_update,
        methods=["POST"],
        response_model=SelfUpdatePlanResponse,
    )
    router.add_api_route(
        "/self-update/prepare",
        api_prepare_self_update,
        methods=["POST"],
        response_model=SelfUpdatePrepareResponse,
    )
    router.add_api_route(
        "/self-update",
        api_apply_self_update,
        methods=["POST"],
        response_model=SelfUpdateApplyResponse,
    )
    router.add_api_route(
        "/container/restart",
        api_restart_container,
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
        api_create_plan,
        methods=["POST"],
        response_model=PlanResponse,
    )
    router.add_api_route(
        "/jobs",
        api_create_job,
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
        api_apply_plan,
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


async def require_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings = _settings(request)
    if settings.dev_no_auth:
        return
    if _setup_required(settings):
        raise HTTPException(status_code=403, detail="setup required")
    if _bearer_token_valid(settings, authorization):
        return
    if _session_user(settings, request) is not None:
        return
    raise HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def api_setup_status(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> SetupStatusResponse:
    settings = _settings(request)
    setup_required = _setup_required(settings)
    return SetupStatusResponse(
        setup_required=setup_required,
        claim_required=setup_required and not settings.dev_no_auth,
        authenticated=_request_authenticated(settings, request, authorization),
        auth_required=settings.auth_required,
        dev_auth_bypass=settings.dev_no_auth,
        mutations_enabled=settings.mutations_enabled,
        password_min_length=PASSWORD_MIN_LENGTH,
    )


def api_setup_claim(
    payload: SetupClaimRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    if settings.dev_no_auth:
        return _auth_session_response(
            settings,
            authenticated=True,
            setup_required=False,
        )
    username = _normalize_username(payload.username)
    if not username:
        raise HTTPException(status_code=422, detail="username is required")
    user_id = _claim_initial_admin(settings, payload.claim, username, payload.password)
    session_id = _create_web_session(settings, user_id=user_id, request=request)
    _set_session_cookie(response, session_id, request, settings)
    return _auth_session_response(
        settings,
        authenticated=True,
        setup_required=False,
        username=username,
    )


def api_auth_csrf(request: Request, response: Response) -> CsrfResponse:
    csrf_token = secrets.token_urlsafe(32)
    _set_csrf_cookie(response, csrf_token, request, _settings(request))
    return CsrfResponse(csrf_token=csrf_token)


def api_auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    if settings.dev_no_auth:
        return _auth_session_response(
            settings,
            authenticated=True,
            setup_required=False,
        )
    if _setup_required(settings):
        raise HTTPException(status_code=403, detail="setup required")
    username = _normalize_username(payload.username)
    if _login_throttle_blocked(request, settings, username):
        raise _auth_failed()
    user = _verify_web_user(settings, payload.username, payload.password)
    if user is None:
        _record_login_failure(request, settings, username)
        raise _auth_failed()
    _clear_login_throttle(request, settings, username)
    session_id = _create_web_session(settings, user_id=int(user["id"]), request=request)
    _set_session_cookie(response, session_id, request, settings)
    return _auth_session_response(
        settings,
        authenticated=True,
        setup_required=False,
        username=str(user["username"]),
    )


def api_auth_reset_admin_claim(
    payload: ResetAdminClaimRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    username = _normalize_username(payload.username)
    if not username:
        raise HTTPException(status_code=422, detail="username is required")
    user_id = _redeem_admin_recovery_claim(
        settings,
        claim=payload.claim,
        username=username,
        password=payload.password,
    )
    session_id = _create_web_session(settings, user_id=user_id, request=request)
    _set_session_cookie(response, session_id, request, settings)
    return _auth_session_response(
        settings,
        authenticated=True,
        setup_required=False,
        username=username,
    )


def api_auth_logout(
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    _revoke_web_session(settings, request.cookies.get(SESSION_COOKIE, ""))
    _clear_session_cookie(response)
    _clear_csrf_cookie(response)
    return _auth_session_response(
        settings,
        authenticated=settings.dev_no_auth,
        setup_required=_setup_required(settings),
    )


def api_auth_session(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSessionResponse:
    settings = _settings(request)
    setup_required = _setup_required(settings)
    user = _session_user(settings, request)
    authenticated = (
        settings.dev_no_auth
        or (not setup_required and _bearer_token_valid(settings, authorization))
        or user is not None
    )
    return _auth_session_response(
        settings,
        authenticated=authenticated,
        setup_required=setup_required,
        username=None if user is None else str(user["username"]),
    )


def api_healthz() -> HealthResponse:
    return HealthResponse(ok=True, version=__version__)


def api_readyz(request: Request, response: Response) -> ReadyResponse | Response:
    if not _raw_client_is_loopback(request):
        return Response(status_code=404)
    return _ready_response(_settings(request), response)


def api_status(request: Request) -> StatusResponse:
    settings = _settings(request)
    pending = _pending_response(settings, include_grouping=False)
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
        with connect_db(settings.config.db_path) as conn:
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


def api_doctor(request: Request) -> DoctorResponse:
    settings = _settings(request)
    return _doctor_response(settings, _web_doctor_result(settings, request))


def api_ready(request: Request, response: Response) -> ReadyResponse:
    return _ready_response(_settings(request), response)


def api_doctor_method_not_allowed() -> JSONResponse:
    return api_post_only_method_not_allowed()


def api_post_only_method_not_allowed() -> JSONResponse:
    return JSONResponse(
        {"detail": "method not allowed"},
        status_code=405,
        headers={"Allow": "POST"},
    )


def api_onboarding_checklist(request: Request) -> OnboardingChecklistResponse:
    settings = _settings(request)
    dismissed_at = _onboarding_dismissed_at(settings)
    if dismissed_at:
        return OnboardingChecklistResponse(
            dismissed=True,
            dismissed_at=dismissed_at,
            all_passed=False,
            visible=False,
            items=[],
        )
    result = _web_doctor_result(settings, request)
    return _onboarding_checklist_response(
        settings,
        request,
        result,
        dismissed_at=dismissed_at,
    )


def api_onboarding_dismiss(request: Request) -> OnboardingDismissResponse:
    settings = _settings(request)
    dismissed_at = utc_timestamp()
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with conn:
                _set_web_setting(conn, ONBOARDING_DISMISSED_AT_KEY, dismissed_at)
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not dismiss onboarding checklist",
                exc,
            ),
        ) from exc
    return OnboardingDismissResponse(dismissed=True, dismissed_at=dismissed_at)


def api_core_update_tour(request: Request) -> CoreUpdateTourResponse:
    return _core_update_tour_response(_settings(request))


def api_update_core_update_tour(
    payload: CoreUpdateTourUpdateRequest,
    request: Request,
) -> CoreUpdateTourResponse:
    settings = _settings(request)
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with conn:
                return _set_core_update_tour_state(
                    conn,
                    status=payload.status,
                    step=payload.step,
                )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not update core update tour",
                exc,
            ),
        ) from exc


def api_diagnostics_support_bundle(request: Request) -> DiagnosticsSupportBundleResponse:
    settings = _settings(request)

    version = __version__
    settings_resp = api_settings(request)
    doctor_result = api_doctor(request)

    pending = _pending_response(settings, include_grouping=True)
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
        with closing(_connect_readonly_db(settings)) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM update_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchall()
            if rows:
                last_run = _run_summary_from_row(rows[0])
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
            log_path = _safe_log_path(settings, last_run.log_file)
            if log_path is None:
                log_tail = LogTail(exists=False, content="", truncated=False)
            else:
                log_tail = _read_log_tail(log_path, DEFAULT_JOB_LOG_TAIL_BYTES)
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


def api_pending(request: Request) -> PendingResponse:
    return _pending_response(_settings(request))


def api_update_targets(request: Request) -> UpdateTargetsResponse:
    return _update_targets_response(_settings(request))


def api_pending_cleanup(
    payload: PendingCleanupRequest,
    request: Request,
) -> PendingCleanupResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = _active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)

    payload_lines = _cleanup_payload_lines(payload)
    wud_lock = _acquire_apply_wud_lock(settings)
    try:
        try:
            parsed = parse_wud_file(settings.config.wud_out_file)
            cleanup = build_unmatched_cleanup(
                _effective_config(settings),
                line_numbers=[line.line_no for line in payload_lines],
                parsed=parsed,
                host_docker_base=settings.host_docker_base,
                environ=settings.command_env,
            )
        except (PlanInputError, PlanFileMissing) as exc:
            raise HTTPException(status_code=409, detail="cleanup is stale") from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not revalidate cleanup: {exc}",
            ) from exc

        removed = _validated_cleanup_lines(payload, payload_lines, cleanup)
        try:
            with connect_db(settings.config.db_path) as conn:
                init_db(conn)
                with _immediate_transaction(conn):
                    audit_run_id = _insert_pending_cleanup_audit(
                        conn,
                        settings,
                        request,
                        removed,
                    )
                    try:
                        remove_lines_before_run(
                            settings.config.wud_out_file,
                            parsed,
                            [item.line_no for item in removed],
                            lock=wud_lock,
                            owner=_owner_config(settings),
                        )
                    except OSError as exc:
                        raise HTTPException(
                            status_code=500,
                            detail=f"could not remove pending lines: {exc}",
                        ) from exc
        except HTTPException:
            raise
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not record cleanup audit: {exc}",
            ) from exc

        return PendingCleanupResponse(
            status="success",
            audit_run_id=audit_run_id,
            removed_count=len(removed),
            removed=[
                PendingCleanupRemovedLine(
                    line_no=item.line_no,
                    raw=item.raw,
                    image=item.image,
                    reason=item.reason,
                )
                for item in removed
            ],
        )
    finally:
        wud_lock.close()


def api_pending_removal_plan(
    payload: PendingRemovalPlanRequest,
    request: Request,
) -> PendingRemovalPlanResponse:
    settings = _settings(request)
    try:
        parsed = parse_wud_file(settings.config.wud_out_file)
        return _pending_removal_plan(settings, payload.line_numbers, parsed=parsed)
    except PlanInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="WUD file not found") from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not create removal plan: {exc}",
        ) from exc


def api_pending_removal(
    payload: PendingRemovalRequest,
    request: Request,
) -> PendingCleanupResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = _active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)

    payload_lines = _removal_payload_lines(payload)
    wud_lock = _acquire_apply_wud_lock(settings)
    try:
        try:
            parsed = parse_wud_file(settings.config.wud_out_file)
            plan = _pending_removal_plan(
                settings,
                [line.line_no for line in payload_lines],
                parsed=parsed,
            )
        except (PlanInputError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail="removal is stale") from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not revalidate removal: {exc}",
            ) from exc

        removed = _validated_removal_lines(payload, payload_lines, plan)
        try:
            with connect_db(settings.config.db_path) as conn:
                init_db(conn)
                with _immediate_transaction(conn):
                    audit_run_id = _insert_pending_removal_audit(
                        conn,
                        settings,
                        request,
                        removed,
                    )
                    try:
                        remove_lines_before_run(
                            settings.config.wud_out_file,
                            parsed,
                            [item.line_no for item in removed],
                            lock=wud_lock,
                            owner=_owner_config(settings),
                        )
                    except OSError as exc:
                        raise HTTPException(
                            status_code=500,
                            detail=f"could not remove pending lines: {exc}",
                        ) from exc
        except HTTPException:
            raise
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not record removal audit: {exc}",
            ) from exc

        return PendingCleanupResponse(
            status="success",
            audit_run_id=audit_run_id,
            removed_count=len(removed),
            removed=[
                PendingCleanupRemovedLine(
                    line_no=item.line_no,
                    raw=item.raw,
                    image=item.image,
                    reason="selected",
                )
                for item in removed
            ],
        )
    finally:
        wud_lock.close()


def api_release_notes(request: Request) -> ReleaseNotesResponse:
    settings = _settings(request)
    exists, parsed = _parse_pending_file(settings)
    warnings = list(parsed.warnings)
    if not exists:
        return ReleaseNotesResponse(
            source_file=str(settings.config.wud_out_file),
            count=0,
            items=[],
            warnings=warnings,
        )
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            items = cached_release_notes(
                conn,
                parsed.targets,
                settings.command_env or {},
                source_resolver=_release_note_source_resolver(settings),
            )
    except ReadOnlyDatabaseMissing:
        items = release_note_placeholders(
            parsed.targets,
            settings.command_env or {},
            source_resolver=_release_note_source_resolver(settings),
        )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read release-note cache",
                exc,
            ),
        ) from exc
    return _release_notes_response(settings, items, warnings)


def api_refresh_release_notes(request: Request) -> ReleaseNotesResponse:
    settings = _settings(request)
    exists, parsed = _parse_pending_file(settings)
    warnings = list(parsed.warnings)
    if not exists:
        return ReleaseNotesResponse(
            source_file=str(settings.config.wud_out_file),
            count=0,
            items=[],
            warnings=warnings,
        )
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            items = refresh_release_notes(
                conn,
                parsed.targets,
                settings.command_env or {},
                source_resolver=_release_note_source_resolver(settings),
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
    return _release_notes_response(settings, items, warnings)


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
        with connect_db(settings.config.db_path) as conn:
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


def api_self_update(request: Request) -> SelfUpdateResponse:
    return _self_update_response(_settings(request))


def api_plan_self_update(request: Request) -> SelfUpdatePlanResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = _active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)

    status = _self_update_response(settings)
    if not status.can_update:
        detail = status.disabled_reason or "self-update is not available"
        raise HTTPException(status_code=409, detail=detail)
    if status.strategy != "prepare_tag_update":
        raise HTTPException(
            status_code=409,
            detail="self-update target does not require tag update preparation",
        )

    try:
        plan, cached = _build_self_update_tag_plan(settings, status)
    except PlanInputError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not create self-update tag plan",
                exc,
            ),
        ) from exc

    plan_response = _plan_response(plan, settings, request)
    try:
        _validate_self_update_prepare_plan(plan_response)
    except HTTPException:
        _delete_self_update_plan_file(cached)
        raise
    _cache_self_update_plan(request.app.state, cached)
    return SelfUpdatePlanResponse(
        strategy="prepare_tag_update",
        plan=plan_response,
        current_tag=status.current_tag,
        latest_tag=status.latest_tag,
        current_image=status.current_image,
        target_image=status.target_image,
        restart_container=status.restart_container,
    )


def api_apply_self_update(
    payload: SelfUpdateRequest,
    request: Request,
) -> SelfUpdateApplyResponse:
    _ = payload.confirmation
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    reservation_error = _reserve_self_update(request.app.state)
    if reservation_error:
        raise HTTPException(status_code=409, detail=reservation_error)

    try:
        status = _self_update_response(settings)
        if not status.can_update:
            detail = status.disabled_reason or "self-update is not available"
            raise HTTPException(status_code=409, detail=detail)
        if status.strategy != "pull_image":
            raise HTTPException(
                status_code=409,
                detail="self-update target requires tag update preparation",
            )
        if _self_update_confirmation_stale(payload, status):
            raise HTTPException(status_code=409, detail="self-update target is stale")
        docker = DockerCli(runner=CommandRunner(env=settings.command_env))
        try:
            container_id = docker.container_id(status.restart_container)
        except CommandError as exc:
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not inspect restart container",
                    exc,
                ),
            ) from exc
        if not container_id:
            raise HTTPException(
                status_code=500,
                detail="could not inspect restart container",
            )

        try:
            with connect_db(settings.config.db_path) as conn:
                init_db(conn)
                with _immediate_transaction(conn):
                    audit_run_id = _insert_self_update_audit(
                        conn,
                        settings,
                        request,
                        status=status,
                    )
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not record self-update audit",
                    exc,
                )
            ) from exc
        try:
            docker.pull_image(status.target_image)
        except CommandError as exc:
            detail = exc.result.stderr.strip() or str(exc)
            LOGGER.error(
                "WebUI self-update image pull failed for %s -> %s: %s",
                status.target_image,
                status.restart_container,
                _redact_sensitive_text(settings, detail),
            )
            _safe_update_self_update_audit(
                settings,
                audit_run_id,
                status="failure",
                error=_redact_sensitive_text(settings, detail),
            )
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not pull self-update image",
                    exc,
                ),
            ) from exc
        _safe_update_self_update_audit(
            settings,
            audit_run_id,
            status="image_pulled",
        )
    finally:
        _release_self_update(request.app.state)

    return SelfUpdateApplyResponse(
        status="image_pulled",
        audit_run_id=audit_run_id,
        current_tag=status.current_tag,
        latest_tag=status.latest_tag,
        target_image=status.target_image,
        container=status.restart_container,
    )


def api_prepare_self_update(
    payload: SelfUpdatePrepareRequest,
    request: Request,
) -> SelfUpdatePrepareResponse:
    _ = payload.confirmation
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    reservation_error = _reserve_self_update(request.app.state)
    if reservation_error:
        raise HTTPException(status_code=409, detail=reservation_error)

    audit_run_id: int | None = None
    status: SelfUpdateResponse | None = None
    try:
        status = _self_update_response(settings)
        if not status.can_update:
            detail = status.disabled_reason or "self-update is not available"
            raise HTTPException(status_code=409, detail=detail)
        if status.strategy != "prepare_tag_update":
            raise HTTPException(
                status_code=409,
                detail="self-update target does not require tag update preparation",
            )
        if _self_update_confirmation_stale(payload, status):
            raise HTTPException(status_code=409, detail="self-update target is stale")

        cached = _require_self_update_cached_plan(
            request.app.state,
            payload.plan_id,
        )
        if _self_update_cached_plan_stale(cached, status):
            raise HTTPException(status_code=409, detail="self-update plan is stale")
        try:
            plan = _rebuild_self_update_cached_plan(settings, cached)
        except (PlanInputError, PlanFileMissing, OSError) as exc:
            raise HTTPException(
                status_code=409,
                detail="self-update plan is stale",
            ) from exc
        if plan.plan_id != payload.plan_id:
            raise HTTPException(status_code=409, detail="self-update plan is stale")
        plan_response = _plan_response(plan, settings, request)
        _validate_self_update_prepare_plan(plan_response)

        docker = DockerCli(runner=CommandRunner(env=settings.command_env))
        try:
            container_id = docker.container_id(status.restart_container)
        except CommandError as exc:
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not inspect restart container",
                    exc,
                ),
            ) from exc
        if not container_id:
            raise HTTPException(
                status_code=500,
                detail="could not inspect restart container",
            )

        try:
            with connect_db(settings.config.db_path) as conn:
                init_db(conn)
                with _immediate_transaction(conn):
                    audit_run_id = _insert_self_update_audit(
                        conn,
                        settings,
                        request,
                        status=status,
                    )
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not record self-update audit",
                    exc,
                ),
            ) from exc

        try:
            metadata = _prepare_self_update_tag_update(settings, plan_response)
        except (CommandError, ComposeTagRewriteError, OSError, RuntimeError) as exc:
            detail = _redact_sensitive_text(settings, str(exc))
            LOGGER.error(
                "WebUI self-update tag prepare failed for %s -> %s: %s",
                status.current_image,
                status.target_image,
                detail,
            )
            _safe_update_self_update_audit(
                settings,
                audit_run_id,
                status="failure",
                error=detail,
            )
            raise HTTPException(
                status_code=500,
                detail=_safe_exception_detail(
                    settings,
                    "could not prepare self-update tag update",
                    exc,
                ),
            ) from exc
        _safe_update_self_update_audit(
            settings,
            audit_run_id,
            status="tag_prepared",
            metadata_extra=metadata,
        )
    finally:
        _release_self_update(request.app.state)
        _remove_self_update_cached_plan(request.app.state, payload.plan_id)

    return SelfUpdatePrepareResponse(
        status="tag_prepared",
        audit_run_id=audit_run_id,
        current_tag=status.current_tag,
        latest_tag=status.latest_tag,
        target_image=status.target_image,
        container=status.restart_container,
        external_recreate_required=True,
    )


def api_restart_container(
    payload: ContainerRestartRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ContainerRestartResponse:
    _ = payload.confirmation
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = _active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)
    container = settings.restart_container.strip()
    if not container:
        raise HTTPException(
            status_code=409,
            detail="container restart target is not configured",
        )
    try:
        _validate_restart_container_target(container)
    except WebConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    docker = DockerCli(runner=CommandRunner(env=settings.command_env))
    try:
        container_id = docker.container_id(container)
    except CommandError as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not inspect restart container",
                exc,
            ),
        ) from exc
    if not container_id:
        raise HTTPException(
            status_code=500,
            detail="could not inspect restart container",
        )

    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with _immediate_transaction(conn):
                audit_run_id = _insert_container_restart_audit(
                    conn,
                    settings,
                    request,
                    container=container,
                )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not record container restart audit",
                exc,
            ),
        ) from exc

    background_tasks.add_task(
        _restart_container_task,
        settings,
        container,
        audit_run_id,
    )
    return ContainerRestartResponse(
        status="scheduled",
        audit_run_id=audit_run_id,
        container=container,
    )


def api_create_plan(payload: PlanRequest, request: Request) -> PlanResponse:
    settings = _settings(request)
    try:
        plan = _build_web_plan(settings, payload)
    except PlanInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PlanFileMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not create plan: {exc}",
        ) from exc
    return _plan_response(plan, settings, request)


def api_create_job(payload: ApplyPlanRequest, request: Request) -> ApplyJobResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    active_error = _active_mutation_error(request)
    if active_error:
        raise HTTPException(status_code=409, detail=active_error)
    wud_lock = _acquire_apply_wud_lock(settings)
    try:
        try:
            plan = _build_web_plan(
                settings,
                PlanRequest(
                    line_numbers=payload.line_numbers,
                    allow_tag_updates=payload.allow_tag_updates,
                    tag_overrides=payload.tag_overrides,
                ),
            )
        except (PlanInputError, PlanFileMissing) as exc:
            raise HTTPException(status_code=409, detail="plan is stale") from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not revalidate plan: {exc}",
            ) from exc

        if not secrets.compare_digest(plan.plan_id, payload.plan_id):
            raise HTTPException(status_code=409, detail="plan is stale")
        if not _plan_can_apply(plan, settings):
            raise HTTPException(status_code=409, detail="plan is not ready to apply")
        apply_preflight = _apply_preflight_response(settings, request, plan)
        if not apply_preflight.ok:
            raise HTTPException(status_code=409, detail="apply preflight failed")
        return _submit_apply_job(request, settings, plan, payload, wud_lock)
    except Exception:
        wud_lock.close()
        raise


def api_apply_plan(payload: ApplyPlanRequest, request: Request) -> ApplyJobResponse:
    return api_create_job(payload, request)


def api_job(job_id: str, request: Request) -> ApplyJobResponse:
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    apply_lock: Lock = request.app.state.web_apply_lock
    with apply_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="apply job not found")
        return _apply_job_response(job)


def api_apply_job(job_id: str, request: Request) -> ApplyJobResponse:
    return api_job(job_id, request)


def api_job_stream(
    job_id: str,
    request: Request,
    log_tail_bytes: int = Query(default=DEFAULT_JOB_LOG_TAIL_BYTES, ge=1),
) -> StreamingResponse:
    _require_apply_job(job_id, request)
    return StreamingResponse(
        _apply_job_stream(
            request,
            job_id,
            log_tail_bytes=min(log_tail_bytes, MAX_LOG_TAIL_BYTES),
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


def _settings(request: Request) -> WebSettings:
    return request.app.state.web_settings


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
            value = _web_setting(conn, MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY)
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


def _ready_response(
    settings: WebSettings,
    response: Response,
) -> ReadyResponse:
    doctor = _doctor_response(settings, _web_readiness_result(settings))
    checks = [
        check for check in doctor.checks if check.code in READINESS_INCLUDED_CODES
    ]
    missing = _missing_readiness_checks(checks)
    if missing:
        checks.append(
            DoctorCheckResponse(
                status="FAIL",
                code="readiness-missing-checks",
                category="webui",
                name="readiness checks",
                detail="missing required check(s): " + ", ".join(missing),
            )
        )
    ok = all(check.status != "FAIL" for check in checks)
    if not ok:
        response.status_code = 503
    return ReadyResponse(ok=ok, version=__version__, checks=checks)


def _missing_readiness_checks(checks: Sequence[DoctorCheckResponse]) -> list[str]:
    present = {check.code for check in checks}
    missing = [
        code.replace("-", " ")
        for code in sorted(READINESS_REQUIRED_CODES)
        if code not in present
    ]
    if not present.intersection(READINESS_DOCKER_ENDPOINT_CODES):
        missing.insert(0, "docker socket or endpoint")
    return missing


def _web_doctor_options_and_env(
    settings: WebSettings,
) -> tuple[DoctorDataOptions, dict[str, str]]:
    env = _doctor_command_env(settings)
    args = SimpleNamespace(
        base=str(settings.config.docker_base),
        file=str(settings.config.wud_out_file),
        log_dir=str(settings.config.log_dir),
        scripts_dir=env.get("WUD_SCRIPTS_DIR", ""),
        no_color=True,
    )
    return (
        doctor_options_from_namespace(
            args,
            repo_root=Path(__file__).resolve().parents[2],
            environ=env,
        ),
        env,
    )


def _doctor_configuration_result(exc: DoctorConfigError) -> DoctorDataResult:
    return DoctorDataResult(
        checks=(
            DoctorDataCheck(
                status="FAIL",
                name="configuration",
                detail=str(exc),
                code="configuration",
                category="configuration",
                suggestions=(
                    DoctorDataSuggestion(
                        label="Fix environment value",
                        description=(
                            "Set the reported variable to an accepted value "
                            "before running doctor again."
                        ),
                    ),
                ),
            ),
        )
    )


def _web_doctor_result(settings: WebSettings, request: Request) -> DoctorDataResult:
    try:
        options, env = _web_doctor_options_and_env(settings)
        result = Doctor(options, environ=env).run_result()
    except DoctorConfigError as exc:
        result = _doctor_configuration_result(exc)
    return DoctorDataResult(
        checks=(*result.checks, *_web_doctor_checks(settings, request))
    )


def _web_readiness_result(
    settings: WebSettings,
) -> DoctorDataResult:
    try:
        options, env = _web_doctor_options_and_env(settings)
        result = Doctor(options, environ=env).run_readiness_result()
    except DoctorConfigError as exc:
        result = _doctor_configuration_result(exc)
    return DoctorDataResult(
        checks=(*result.checks, _web_database_doctor_check(settings))
    )


def _doctor_command_env(settings: WebSettings) -> dict[str, str]:
    config = _effective_config(settings)
    env = dict(settings.command_env or {})
    env["DOCKER_BASE"] = str(config.docker_base)
    env["WUD_OUT_FILE"] = str(config.wud_out_file)
    env["WUD_LOG_DIR"] = str(config.log_dir)
    env[COMPOSE_IGNORE_PATHS_ENV] = format_compose_ignore_paths(
        config.compose_ignore_paths
    )
    env[DIGEST_PIN_UPDATES_ENV] = _format_bool(config.digest_pin_updates)
    return env


def _web_doctor_checks(
    settings: WebSettings,
    request: Request,
) -> tuple[DoctorDataCheck, ...]:
    checks: list[DoctorDataCheck] = []
    checks.append(_web_database_doctor_check(settings))
    checks.append(
        _web_doctor_check(
            "WARN" if settings.dev_no_auth else "PASS",
            "WebUI authentication",
            "development auth bypass is enabled"
            if settings.dev_no_auth
            else "authentication is required",
            code="webui-authentication",
            suggestions=()
            if not settings.dev_no_auth
            else (
                DoctorDataSuggestion(
                    label="Require browser authentication",
                    description=(
                        "Disable the local development auth bypass before exposing "
                        "the WebUI."
                    ),
                    snippet="WUD_WEB_DEV_NO_AUTH=false",
                ),
            ),
        )
    )
    checks.append(
        _web_doctor_check(
            "WARN" if settings.mutations_enabled else "PASS",
            "WebUI mutation gate",
            "browser mutations are enabled"
            if settings.mutations_enabled
            else "browser mutations are disabled",
            code="webui-mutation-gate",
            suggestions=()
            if not settings.mutations_enabled
            else (
                DoctorDataSuggestion(
                    label="Return to read-only mode",
                    description=(
                        "Leave browser mutations disabled unless this deployment "
                        "is intentionally allowed to apply updates."
                    ),
                    snippet="WUD_WEB_MUTATIONS_ENABLED=false",
                ),
            ),
        )
    )
    checks.append(
        _web_doctor_check(
            "PASS" if settings.allowed_hosts else "FAIL",
            "WebUI allowed hosts",
            _format_sequence(sorted(settings.allowed_hosts)) or "none configured",
            code="webui-allowed-hosts",
            suggestions=()
            if settings.allowed_hosts
            else (
                DoctorDataSuggestion(
                    label="Configure allowed hosts",
                    description=(
                        "Set the hostnames clients use to reach the WebUI."
                    ),
                    snippet="WUD_WEB_ALLOWED_HOSTS=localhost,127.0.0.1",
                ),
            ),
        )
    )
    effective_origin = _effective_origin(request, settings)
    checks.append(
        _web_doctor_check(
            "PASS" if settings.public_origin else "WARN",
            "WebUI public origin",
            settings.public_origin
            if settings.public_origin
            else f"derived from request as {effective_origin}",
            code="webui-public-origin",
            suggestions=()
            if settings.public_origin
            else (
                DoctorDataSuggestion(
                    label="Set reverse proxy origin",
                    description=(
                        "Set WUD_WEB_PUBLIC_ORIGIN when the WebUI is served "
                        "behind a reverse proxy."
                    ),
                    snippet="WUD_WEB_PUBLIC_ORIGIN=https://wud.example.test",
                ),
            ),
        )
    )
    secure_cookie = _secure_cookie(settings, request)
    checks.append(
        _web_doctor_check(
            "PASS" if secure_cookie else "WARN",
            "WebUI secure cookies",
            f"{settings.secure_cookies} mode resolves to {_format_bool(secure_cookie)}",
            code="webui-secure-cookies",
            suggestions=()
            if secure_cookie
            else (
                DoctorDataSuggestion(
                    label="Use HTTPS public origin",
                    description=(
                        "Set a HTTPS public origin or force secure cookies for "
                        "reverse-proxy deployments."
                    ),
                    snippet="WUD_WEB_PUBLIC_ORIGIN=https://wud.example.test",
                ),
            ),
        )
    )
    checks.append(
        _web_doctor_check(
            "PASS",
            "WebUI trusted proxies",
            _format_sequence(str(network) for network in settings.trusted_proxies)
            or "not configured",
            code="webui-trusted-proxies",
        )
    )
    static_available = _static_spa_available(settings)
    checks.append(
        _web_doctor_check(
            "PASS" if static_available else "WARN",
            "WebUI static SPA",
            "static assets are available"
            if static_available
            else "static assets are not mounted; API-only mode is active",
            code="webui-static-spa",
        )
    )
    return tuple(checks)


def _web_database_doctor_check(settings: WebSettings) -> DoctorDataCheck:
    db_ready, db_warning = _database_ready(settings)
    return _web_doctor_check(
        "PASS" if db_ready else "FAIL",
        "WebUI database",
        str(settings.config.db_path) if db_ready else db_warning,
        code="webui-database",
        suggestions=()
        if db_ready
        else (
            DoctorDataSuggestion(
                label="Persist WebUI database",
                description=(
                    "Mount a writable persistent directory and set WUD_DB_PATH "
                    "inside it."
                ),
                snippet="WUD_DB_PATH=/logs/wud-updater.sqlite",
            ),
        ),
    )


def _web_doctor_check(
    status: DoctorCheckStatus,
    name: str,
    detail: str,
    *,
    code: str,
    suggestions: Sequence[DoctorDataSuggestion] = (),
) -> DoctorDataCheck:
    return DoctorDataCheck(
        status=status,
        name=name,
        detail=detail,
        code=code,
        category="webui",
        suggestions=tuple(suggestions),
    )


def _doctor_response(
    settings: WebSettings,
    result: DoctorDataResult,
) -> DoctorResponse:
    return DoctorResponse(
        ok=result.ok,
        failures=result.failures,
        warnings=result.warnings,
        checks=[
            DoctorCheckResponse(
                status=check.status,  # type: ignore[arg-type]
                code=check.code,
                category=check.category,
                name=check.name,
                detail=_redact_sensitive_text(settings, check.detail),
                target=_redact_sensitive_text(settings, check.target),
                suggestions=[
                    DoctorSuggestionResponse(
                        label=suggestion.label,
                        description=_redact_sensitive_text(
                            settings,
                            suggestion.description,
                        ),
                        snippet=_redact_sensitive_text(settings, suggestion.snippet),
                    )
                    for suggestion in check.suggestions
                ],
            )
            for check in result.checks
        ],
    )


ONBOARDING_REQUIRED_KEYS = frozenset(
    {
        "admin-setup",
        "wud-output",
        "wud-scripts",
        "docker-access",
        "compose-discovery",
        "persistence",
        "browser-access",
        "mutation-mode",
    }
)
ONBOARDING_STATUS_RANK: Mapping[DoctorCheckStatus, int] = {
    "PASS": 0,
    "WARN": 1,
    "FAIL": 2,
}
ONBOARDING_DOC_BASE = "https://github.com/magrhino/WUD-Updater/blob/main/docs"


def _onboarding_checklist_response(
    settings: WebSettings,
    request: Request,
    result: DoctorDataResult,
    *,
    dismissed_at: str,
) -> OnboardingChecklistResponse:
    doctor = _doctor_response(settings, result)
    checks = doctor.checks
    items = [
        _onboarding_admin_item(settings),
        _onboarding_item_from_checks(
            key="wud-output",
            title="Shared WUD output file",
            checks=_checks_by_code(
                checks,
                {"wud-out-file-directory", "wud-out-file"},
            ),
            pass_detail=(
                "WUD_OUT_FILE points at a writable shared location that WUD can "
                "create or update."
            ),
            missing_detail="WUD_OUT_FILE readiness was not reported by doctor.",
            docs=[
                _onboarding_doc(
                    "WebUI container setup",
                    f"{ONBOARDING_DOC_BASE}/wiki/webui-container.md#start-the-webui",
                )
            ],
        ),
        _onboarding_item_from_checks(
            key="wud-scripts",
            title="WUD callback scripts",
            checks=_checks_by_code(
                checks,
                {"packaged-wud-scripts", "wud-script-sync"},
            ),
            pass_detail=(
                "Packaged WUD scripts are available and script sync can update "
                "the managed trigger directory."
            ),
            missing_detail="WUD script sync readiness was not reported by doctor.",
            docs=[
                _onboarding_doc(
                    "Script sync notes",
                    f"{ONBOARDING_DOC_BASE}/wiki/container-script-sync.md",
                )
            ],
        ),
        _onboarding_item_from_checks(
            key="docker-access",
            title="Docker daemon access",
            checks=_checks_by_code(
                checks,
                {
                    "docker-endpoint",
                    "docker-socket",
                    "docker-daemon-version",
                    "docker-daemon-info",
                    "docker-container-listing",
                },
            ),
            pass_detail="The WebUI helper can reach Docker and list containers.",
            missing_detail="Docker daemon readiness was not reported by doctor.",
            docs=[
                _onboarding_doc(
                    "Deployment Docker access",
                    f"{ONBOARDING_DOC_BASE}/DEPLOYMENT.md#requirements",
                )
            ],
        ),
        _onboarding_item_from_checks(
            key="compose-discovery",
            title="Compose stack discovery",
            checks=_compose_onboarding_checks(checks),
            pass_detail=(
                "Compose stacks render under DOCKER_BASE and any HOST_DOCKER_BASE "
                "mapping is usable."
            ),
            missing_detail="Compose discovery readiness was not reported by doctor.",
            docs=[
                _onboarding_doc(
                    "Path mapping",
                    f"{ONBOARDING_DOC_BASE}/DEPLOYMENT.md#docker-compose",
                )
            ],
        ),
        _onboarding_item_from_checks(
            key="persistence",
            title="Logs and SQLite persistence",
            checks=_checks_by_code(checks, {"wud-log-dir", "webui-database"}),
            pass_detail=(
                "The log directory is writable and the WebUI database is ready."
            ),
            missing_detail="Persistence readiness was not reported by doctor.",
            docs=[
                _onboarding_doc(
                    "First login",
                    f"{ONBOARDING_DOC_BASE}/wiki/webui-container.md#first-login",
                )
            ],
        ),
        _browser_access_onboarding_item(settings, request, checks),
        _mutation_onboarding_item(settings, checks),
    ]
    all_passed = all(
        item.status == "PASS"
        for item in items
        if item.key in ONBOARDING_REQUIRED_KEYS
    )
    dismissed = bool(dismissed_at)
    return OnboardingChecklistResponse(
        dismissed=dismissed,
        dismissed_at=dismissed_at,
        all_passed=all_passed,
        visible=not dismissed and not all_passed,
        items=items,
    )


def _onboarding_admin_item(settings: WebSettings) -> OnboardingChecklistItem:
    if settings.dev_no_auth:
        status: DoctorCheckStatus = "WARN"
        detail = (
            "Development auth bypass is active; first-admin setup is skipped for "
            "this process."
        )
    else:
        status = "PASS"
        detail = "The first admin account exists and browser authentication is active."
    return OnboardingChecklistItem(
        key="admin-setup",
        title="Admin setup",
        status=status,
        detail=detail,
        check_codes=["webui-authentication"],
        suggestions=()
        if not settings.dev_no_auth
        else [
            DoctorSuggestionResponse(
                label="Require browser authentication",
                description=(
                    "Disable the local development auth bypass before exposing "
                    "the WebUI."
                ),
                snippet="WUD_WEB_DEV_NO_AUTH=false",
            )
        ],
        docs=[
            _onboarding_doc(
                "First login",
                f"{ONBOARDING_DOC_BASE}/wiki/webui-container.md#first-login",
            )
        ],
    )


def _browser_access_onboarding_item(
    settings: WebSettings,
    request: Request,
    checks: Sequence[DoctorCheckResponse],
) -> OnboardingChecklistItem:
    relevant = _checks_by_code(
        checks,
        {
            "webui-authentication",
            "webui-allowed-hosts",
            "webui-public-origin",
            "webui-secure-cookies",
            "webui-trusted-proxies",
        },
    )
    failures = [check for check in relevant if check.status == "FAIL"]
    if failures:
        return _onboarding_item_from_checks(
            key="browser-access",
            title="Browser access safety",
            checks=relevant,
            pass_detail="Browser access safety checks passed.",
            missing_detail="Browser access readiness was not reported by doctor.",
            docs=_browser_access_docs(),
        )

    if _loopback_only_browser_access(settings):
        status: DoctorCheckStatus = "PASS"
        detail = "Browser access is limited to loopback hosts for first run."
    elif settings.public_origin:
        status = "PASS"
        detail = "Public origin and allowed hosts are configured for browser access."
    else:
        status = "WARN"
        detail = (
            "Browser origin is derived from the request. Configure "
            "WUD_WEB_PUBLIC_ORIGIN and WUD_WEB_ALLOWED_HOSTS before LAN or "
            "reverse-proxy exposure."
        )
    return OnboardingChecklistItem(
        key="browser-access",
        title="Browser access safety",
        status=status,
        detail=detail,
        check_codes=_check_codes(relevant),
        suggestions=[]
        if status == "PASS"
        else _dedupe_suggestions(
            suggestion
            for check in relevant
            for suggestion in check.suggestions
            if check.status != "PASS"
        ),
        docs=_browser_access_docs(),
    )


def _mutation_onboarding_item(
    settings: WebSettings,
    checks: Sequence[DoctorCheckResponse],
) -> OnboardingChecklistItem:
    relevant = _checks_by_code(checks, {"webui-mutation-gate"})
    check = relevant[0] if relevant else None
    suggestions = check.suggestions if check is not None else []
    return OnboardingChecklistItem(
        key="mutation-mode",
        title="Browser mutation mode",
        status="WARN" if settings.mutations_enabled else "PASS",
        detail=(
            "Browser apply controls are server-side enabled; keep this intentional."
            if settings.mutations_enabled
            else "Browser apply controls are disabled server-side, so the WebUI is read-only."
        ),
        check_codes=_check_codes(relevant) or ["webui-mutation-gate"],
        suggestions=suggestions,
        docs=[
            _onboarding_doc(
                "Read-only and mutations",
                f"{ONBOARDING_DOC_BASE}/wiki/webui-container.md#read-only-and-mutations",
            )
        ],
    )


def _onboarding_item_from_checks(
    *,
    key: str,
    title: str,
    checks: Sequence[DoctorCheckResponse],
    pass_detail: str,
    missing_detail: str,
    docs: Sequence[OnboardingDocLink],
) -> OnboardingChecklistItem:
    status = _aggregate_onboarding_status(checks)
    return OnboardingChecklistItem(
        key=key,
        title=title,
        status=status,
        detail=_onboarding_detail(checks, status, pass_detail, missing_detail),
        check_codes=_check_codes(checks),
        suggestions=_dedupe_suggestions(
            suggestion
            for check in checks
            for suggestion in check.suggestions
            if check.status != "PASS"
        ),
        docs=list(docs),
    )


def _aggregate_onboarding_status(
    checks: Sequence[DoctorCheckResponse],
) -> DoctorCheckStatus:
    if not checks:
        return "WARN"
    return max(checks, key=lambda check: ONBOARDING_STATUS_RANK[check.status]).status


def _onboarding_detail(
    checks: Sequence[DoctorCheckResponse],
    status: DoctorCheckStatus,
    pass_detail: str,
    missing_detail: str,
) -> str:
    if not checks:
        return missing_detail
    if status == "PASS":
        return pass_detail
    details = [
        f"{check.name}: {check.detail}" if check.detail else check.name
        for check in checks
        if check.status == status
    ]
    return "; ".join(details[:3]) or missing_detail


def _checks_by_code(
    checks: Sequence[DoctorCheckResponse],
    codes: set[str],
) -> list[DoctorCheckResponse]:
    return [check for check in checks if check.code in codes]


def _compose_onboarding_checks(
    checks: Sequence[DoctorCheckResponse],
) -> list[DoctorCheckResponse]:
    return [
        check
        for check in checks
        if check.category == "compose"
        or check.code.startswith("host-docker-base-mapping")
    ]


def _check_codes(checks: Sequence[DoctorCheckResponse]) -> list[str]:
    return [check.code for check in checks]


def _dedupe_suggestions(
    suggestions: Sequence[DoctorSuggestionResponse] | Iterator[DoctorSuggestionResponse],
) -> list[DoctorSuggestionResponse]:
    seen: set[tuple[str, str]] = set()
    deduped: list[DoctorSuggestionResponse] = []
    for suggestion in suggestions:
        key = (suggestion.label, suggestion.snippet)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(suggestion)
    return deduped


def _browser_access_docs() -> list[OnboardingDocLink]:
    return [
        _onboarding_doc(
            "Network exposure",
            f"{ONBOARDING_DOC_BASE}/wiki/webui-container.md#network-exposure",
        )
    ]


def _onboarding_doc(label: str, url: str) -> OnboardingDocLink:
    return OnboardingDocLink(label=label, url=url)


def _core_update_tour_response(settings: WebSettings) -> CoreUpdateTourResponse:
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            return _core_update_tour_response_from_conn(conn)
    except ReadOnlyDatabaseMissing:
        return _default_core_update_tour_response()
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read core update tour state",
                exc,
            ),
        ) from exc


def _core_update_tour_response_from_conn(
    conn: sqlite3.Connection,
) -> CoreUpdateTourResponse:
    row = conn.execute(
        """
        SELECT value, updated_at
        FROM web_settings
        WHERE key = ?
        LIMIT 1
        """,
        (CORE_UPDATE_TOUR_KEY,),
    ).fetchone()
    if row is None:
        return _default_core_update_tour_response()
    return _core_update_tour_response_from_value(
        str(row["value"]),
        str(row["updated_at"] or ""),
    )


def _default_core_update_tour_response() -> CoreUpdateTourResponse:
    return CoreUpdateTourResponse(
        status="not_started",
        step=DEFAULT_CORE_UPDATE_TOUR_STEP,
        updated_at="",
    )


def _core_update_tour_response_from_value(
    raw_value: str,
    updated_at: str,
) -> CoreUpdateTourResponse:
    try:
        decoded = json.loads(raw_value) if raw_value else {}
    except json.JSONDecodeError:
        decoded = {}
    if not isinstance(decoded, Mapping):
        decoded = {}
    status = str(decoded.get("status", ""))
    step = str(decoded.get("step", ""))
    if status not in CORE_UPDATE_TOUR_STATUS_VALUES:
        status = "not_started"
    if step not in CORE_UPDATE_TOUR_STEP_VALUES:
        step = DEFAULT_CORE_UPDATE_TOUR_STEP
    return CoreUpdateTourResponse(
        status=cast(CoreUpdateTourStatus, status),
        step=cast(CoreUpdateTourStep, step),
        updated_at=updated_at,
    )


def _set_core_update_tour_state(
    conn: sqlite3.Connection,
    *,
    status: CoreUpdateTourStatus,
    step: CoreUpdateTourStep,
) -> CoreUpdateTourResponse:
    value = json.dumps({"status": status, "step": step}, sort_keys=True)
    _set_web_setting(conn, CORE_UPDATE_TOUR_KEY, value)
    return _core_update_tour_response_from_conn(conn)


def _loopback_only_browser_access(settings: WebSettings) -> bool:
    return (
        not settings.public_origin
        and bool(settings.allowed_hosts)
        and settings.allowed_hosts.issubset(DEFAULT_ALLOWED_HOSTS)
    )


def _onboarding_dismissed_at(settings: WebSettings) -> str:
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            return _web_setting(conn, ONBOARDING_DISMISSED_AT_KEY)
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read onboarding checklist state",
                exc,
            ),
        ) from exc


def _cleanup_payload_lines(
    payload: PendingCleanupRequest,
) -> tuple[PendingCleanupLine, ...]:
    seen: set[int] = set()
    lines: list[PendingCleanupLine] = []
    for line in payload.lines:
        if line.line_no in seen:
            raise HTTPException(
                status_code=422,
                detail=f"cleanup line {line.line_no} was provided more than once",
            )
        if not line.raw:
            raise HTTPException(
                status_code=422,
                detail=f"cleanup line {line.line_no} raw value is required",
            )
        seen.add(line.line_no)
        lines.append(line)
    return tuple(lines)


def _removal_payload_lines(
    payload: PendingRemovalRequest,
) -> tuple[PendingCleanupLine, ...]:
    seen: set[int] = set()
    lines: list[PendingCleanupLine] = []
    for line in payload.lines:
        if line.line_no in seen:
            raise HTTPException(
                status_code=422,
                detail=f"removal line {line.line_no} was provided more than once",
            )
        if not line.raw:
            raise HTTPException(
                status_code=422,
                detail=f"removal line {line.line_no} raw value is required",
            )
        seen.add(line.line_no)
        lines.append(line)
    return tuple(lines)


def _validated_cleanup_lines(
    payload: PendingCleanupRequest,
    payload_lines: Sequence[PendingCleanupLine],
    cleanup: DryRunPlanCleanup,
) -> tuple[DryRunPlanCleanupItem, ...]:
    if not cleanup.items or not cleanup.cleanup_id:
        raise HTTPException(status_code=409, detail="cleanup is stale")
    if not secrets.compare_digest(cleanup.cleanup_id, payload.cleanup_id):
        raise HTTPException(status_code=409, detail="cleanup is stale")

    requested = {(line.line_no, line.raw) for line in payload_lines}
    available = {(item.line_no, item.raw): item for item in cleanup.items}
    if requested != set(available):
        raise HTTPException(status_code=409, detail="cleanup is stale")
    return tuple(available[key] for key in sorted(available))


def _pending_removal_plan(
    settings: WebSettings,
    line_numbers: Sequence[int],
    *,
    parsed: ParsedWudFile,
) -> PendingRemovalPlanResponse:
    selected = _selected_removal_line_numbers(line_numbers)
    targets_by_line = {target.line_no: target for target in parsed.targets}
    missing = [line_no for line_no in selected if line_no not in targets_by_line]
    if missing:
        raise PlanInputError(
            "line_numbers include non-pending line(s): "
            + ", ".join(str(line_no) for line_no in missing)
        )

    lines = [
        PendingRemovalPlanLine(
            line_no=target.line_no,
            raw=target.raw,
            image=target.first,
            desired_tag=target.desired_tag,
            digest=target.digest,
        )
        for target in (targets_by_line[line_no] for line_no in selected)
    ]
    return PendingRemovalPlanResponse(
        removal_id=_pending_removal_id(settings, lines),
        source_file=str(settings.config.wud_out_file),
        can_remove=settings.mutations_enabled and bool(lines),
        selected_line_numbers=list(selected),
        lines=lines,
    )


def _selected_removal_line_numbers(line_numbers: Sequence[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    selected: list[int] = []
    for line_no in line_numbers:
        if line_no in seen:
            raise PlanInputError(
                f"line_numbers line {line_no} was provided more than once"
            )
        seen.add(line_no)
        selected.append(line_no)
    return tuple(sorted(selected))


def _pending_removal_id(
    settings: WebSettings,
    lines: Sequence[PendingRemovalPlanLine],
) -> str:
    payload = {
        "version": 1,
        "source_file": str(settings.config.wud_out_file),
        "lines": [
            {
                "line_no": item.line_no,
                "raw": item.raw,
                "image": item.image,
                "desired_tag": item.desired_tag,
                "digest": item.digest,
            }
            for item in lines
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_removal_lines(
    payload: PendingRemovalRequest,
    payload_lines: Sequence[PendingCleanupLine],
    plan: PendingRemovalPlanResponse,
) -> tuple[PendingRemovalPlanLine, ...]:
    if not plan.lines or not plan.removal_id:
        raise HTTPException(status_code=409, detail="removal is stale")
    if not secrets.compare_digest(plan.removal_id, payload.removal_id):
        raise HTTPException(status_code=409, detail="removal is stale")

    requested = {(line.line_no, line.raw) for line in payload_lines}
    available = {(item.line_no, item.raw): item for item in plan.lines}
    if requested != set(available):
        raise HTTPException(status_code=409, detail="removal is stale")
    return tuple(available[key] for key in sorted(available))


def _owner_config(settings: WebSettings) -> OwnerConfig:
    return OwnerConfig(
        uid=settings.config.out_uid,
        gid=settings.config.out_gid,
    )


def _insert_pending_cleanup_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    removed: Sequence[DryRunPlanCleanupItem],
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": "webui",
        "operation": "remove_unmatched_pending",
        "actor_type": _state_actor_type(settings, request),
        "line_numbers": [item.line_no for item in removed],
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
        VALUES (?, ?, 'success', 0, 'web-pending-cleanup', ?, '', ?)
        """,
        (
            now,
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
        ),
    )
    run_id = int(cursor.lastrowid)
    for item in removed:
        item_metadata = {
            "source": "webui",
            "operation": "remove_unmatched_pending",
            "reason": item.reason,
            "diagnostic": (
                None if item.diagnostic is None else asdict(item.diagnostic)
            ),
        }
        conn.execute(
            """
            INSERT INTO pending_updates (
                run_id,
                line_no,
                raw,
                image,
                target_digest,
                desired_tag,
                service_key,
                stack_name,
                service_name,
                status,
                status_reason,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, 'resolved', 'removed-unmatched', ?, ?, ?)
            """,
            (
                run_id,
                item.line_no,
                item.raw,
                item.image,
                item.digest,
                item.desired_tag,
                "" if item.diagnostic is None else item.diagnostic.stack,
                "" if item.diagnostic is None else item.diagnostic.service,
                now,
                now,
                _json_object(item_metadata),
            ),
        )
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
            VALUES (?, ?, ?, ?, ?, '', 'success', ?)
            """,
            (
                run_id,
                now,
                (
                    item.diagnostic.service
                    if item.diagnostic is not None and item.diagnostic.service
                    else item.image
                ),
                "" if item.diagnostic is None else item.diagnostic.stack,
                item.image,
                _json_object(item_metadata),
            ),
        )
    return run_id


def _insert_pending_removal_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    removed: Sequence[PendingRemovalPlanLine],
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": "webui",
        "operation": "remove_selected_pending",
        "actor_type": _state_actor_type(settings, request),
        "line_numbers": [item.line_no for item in removed],
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
        VALUES (?, ?, 'success', 0, 'web-pending-removal', ?, '', ?)
        """,
        (
            now,
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
        ),
    )
    run_id = int(cursor.lastrowid)
    for item in removed:
        item_metadata = {
            "source": "webui",
            "operation": "remove_selected_pending",
            "reason": "selected",
        }
        conn.execute(
            """
            INSERT INTO pending_updates (
                run_id,
                line_no,
                raw,
                image,
                target_digest,
                desired_tag,
                service_key,
                stack_name,
                service_name,
                status,
                status_reason,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, '', '', '', 'resolved', 'removed-selected', ?, ?, ?)
            """,
            (
                run_id,
                item.line_no,
                item.raw,
                item.image,
                item.digest,
                item.desired_tag,
                now,
                now,
                _json_object(item_metadata),
            ),
        )
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
            VALUES (?, ?, ?, '', ?, '', 'success', ?)
            """,
            (
                run_id,
                now,
                item.image,
                item.image,
                _json_object(item_metadata),
            ),
        )
    return run_id


def _start_auto_update_scheduler(app: FastAPI, settings: WebSettings) -> Thread:
    stop_event: Event = app.state.web_auto_update_stop
    thread = Thread(
        target=_auto_update_scheduler_loop,
        args=(app, settings, stop_event),
        name="wud-auto-update-scheduler",
        daemon=True,
    )
    thread.start()
    return thread


def _auto_update_scheduler_loop(
    app: FastAPI,
    settings: WebSettings,
    stop_event: Event,
) -> None:
    while not stop_event.wait(AUTO_UPDATE_POLL_SECONDS):
        try:
            _auto_update_tick(app, settings)
        except Exception:
            LOGGER.exception("auto update scheduler tick failed")


def _auto_update_tick(
    app: FastAPI,
    settings: WebSettings,
    *,
    now: datetime | None = None,
) -> ApplyJobResponse | None:
    if not settings.mutations_enabled or _active_apply_job_exists_in_state(app.state):
        return None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    started_at = app.state.web_auto_update_started_at
    if not isinstance(started_at, datetime):
        started_at = now_utc
    started_at_utc = started_at.astimezone(timezone.utc)

    with connect_db(settings.config.db_path) as conn:
        init_db(conn)
        candidate = _auto_update_candidate(
            conn,
            settings,
            now_utc=now_utc,
            started_at=started_at_utc,
        )
    if candidate is None:
        return None
    wud_lock = _acquire_apply_wud_lock(settings)
    lock_transferred = False
    start_event: Event | None = None
    try:
        locked_now_utc = now_utc if now is not None else datetime.now(timezone.utc)
        locked_now_utc = locked_now_utc.astimezone(timezone.utc)
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            candidate = _auto_update_candidate(
                conn,
                settings,
                now_utc=locked_now_utc,
                started_at=started_at_utc,
            )
            if candidate is None:
                return None
            selection, plan = candidate
            with _immediate_transaction(conn):
                _reserve_auto_update_schedule_runs(conn, settings, selection)
                start_event = Event()
                response = _submit_apply_job_state(
                    app.state,
                    settings,
                    plan,
                    allow_tag_updates=False,
                    tag_overrides=(),
                    wud_lock=wud_lock,
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
    now_utc: datetime,
    started_at: datetime,
) -> tuple[AutoUpdateSelection, DryRunPlan] | None:
    try:
        parsed = parse_wud_file(settings.config.wud_out_file)
    except FileNotFoundError:
        return None

    grouping = resolve_pending_groups(
        _effective_config(settings),
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

    plan = _build_web_plan(
        settings,
        PlanRequest(line_numbers=list(selection.line_numbers)),
        update_mode_override=selection.update_mode,
    )
    if not _plan_can_apply(plan, settings):
        return None
    return selection, plan


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
    with connect_db(settings.config.db_path) as conn:
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


def _build_web_plan(
    settings: WebSettings,
    payload: PlanRequest,
    *,
    update_mode_override: str | None = None,
) -> DryRunPlan:
    base_config = _effective_config(settings)
    config = (
        base_config
        if update_mode_override is None
        else replace(base_config, update_mode=update_mode_override)
    )
    return build_dry_run_plan(
        config,
        line_numbers=payload.line_numbers,
        allow_tag_updates=payload.allow_tag_updates,
        tag_overrides=_tag_overrides_from_payload(payload),
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )


def _build_self_update_tag_plan(
    settings: WebSettings,
    status: SelfUpdateResponse,
) -> tuple[DryRunPlan, WebSelfUpdatePlan]:
    target_spec = release_self_update_target(
        status.current_image,
        status.current_tag,
        status.latest_tag,
    )
    if not _self_update_requires_tag_rewrite(target_spec):
        raise PlanInputError("self-update target does not require a tag update")
    wud_file = _write_self_update_tag_plan_file(settings, target_spec)
    try:
        plan = _build_self_update_plan_from_file(settings, wud_file)
    except Exception:
        _delete_self_update_plan_file_path(wud_file)
        raise
    cached = WebSelfUpdatePlan(
        plan_id=plan.plan_id,
        created_at=time.monotonic(),
        wud_file=wud_file,
        current_tag=status.current_tag,
        latest_tag=status.latest_tag,
        current_image=status.current_image,
        target_spec=target_spec,
        target_image=status.target_image,
        restart_container=status.restart_container,
    )
    return plan, cached


def _rebuild_self_update_cached_plan(
    settings: WebSettings,
    cached: WebSelfUpdatePlan,
) -> DryRunPlan:
    if not cached.wud_file.is_file():
        raise PlanFileMissing(str(cached.wud_file))
    return _build_self_update_plan_from_file(settings, cached.wud_file)


def _build_self_update_plan_from_file(
    settings: WebSettings,
    wud_file: Path,
) -> DryRunPlan:
    config = replace(_effective_config(settings), wud_out_file=wud_file)
    return build_dry_run_plan(
        config,
        line_numbers=(1,),
        allow_tag_updates=True,
        tag_overrides=(),
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )


def _write_self_update_tag_plan_file(settings: WebSettings, target_spec: str) -> Path:
    parent = settings.config.wud_out_file.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".self-update-plan.",
        suffix=".todo",
        dir=str(parent),
    )
    path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(f"{target_spec}\n")
    except Exception:
        _delete_self_update_plan_file_path(path)
        raise
    return path


def _validate_self_update_prepare_plan(plan: PlanResponse) -> None:
    if plan.status != "ready" or not plan.can_apply:
        detail = "self-update tag update plan is not ready"
        for issue in plan.issues:
            if issue.severity == "error":
                detail = issue.message
                break
        else:
            if plan.skipped:
                detail = plan.skipped[0].reason
        raise HTTPException(status_code=409, detail=detail)
    if len(plan.stacks) != 1:
        raise HTTPException(
            status_code=409,
            detail="self-update tag update must match exactly one Compose stack",
        )
    stack = plan.stacks[0]
    if not stack.tag_updates:
        raise HTTPException(
            status_code=409,
            detail="self-update tag update plan has no Compose tag update",
        )
    if not stack.services:
        raise HTTPException(
            status_code=409,
            detail="self-update tag update must match at least one Compose service",
        )


def _verify_self_update_digest_pin_updates(
    settings: WebSettings,
    updates: Sequence[DigestPinUpdate],
) -> None:
    if not updates:
        return

    command_runner = CommandRunner(env=settings.command_env)
    docker = DockerCli(runner=command_runner)
    resolver = DockerManifestResolver(docker, verbose=True)
    verifier = DigestVerifier(
        docker,
        primary_resolver=resolver,
        fallback_resolver=resolver,
    )
    for update in updates:
        current = verifier.resolve_tag_digest(update.resolved_image)
        if not current.ok:
            raise RuntimeError(
                "could not re-resolve digest-pin target "
                f"{update.resolved_image}: {current.reason}"
                + (f" ({current.error})" if current.error else "")
            )
        current_digest = normalize_digest(current.digest)
        if current_digest != update.planned_digest:
            raise RuntimeError(
                "digest-pin target moved for "
                f"{update.resolved_image}: planned {update.planned_digest}, "
                f"current {current_digest}"
            )

        digest_result = verifier.verify(update.resolved_image, update.planned_digest)
        if not digest_result.ok:
            detail = digest_result.reason
            if digest_result.error:
                detail = f"{detail} ({digest_result.error})"
            raise RuntimeError(
                "digest-pin target did not verify for "
                f"{update.resolved_image}: wanted {update.planned_digest}; {detail}"
            )


def _prepare_self_update_tag_update(
    settings: WebSettings,
    plan: PlanResponse,
) -> dict[str, Any]:
    _validate_self_update_prepare_plan(plan)
    stack = plan.stacks[0]
    compose_path = Path(stack.directory) / stack.compose_file
    updates = tuple(
        TagUpdate(
            old_image=item.old_image,
            desired_tag=item.desired_tag,
            new_image=item.new_image,
            services=tuple(item.services),
        )
        for item in stack.tag_updates
    )
    if not updates:
        raise RuntimeError("self-update tag update plan has no Compose tag update")
    digest_pin_updates = tuple(
        digest_pin_update_from_values(
            old_image=item.source_image,
            resolved_tag=item.resolved_tag,
            planned_digest=item.planned_digest,
            services=tuple(item.services),
        )
        for item in stack.digest_pin_updates
    )

    backup = _backup_compose(compose_path)
    restore_error = ""
    applied_digest_pins = ()
    try:
        applied = apply_compose_tag_updates(compose_path, updates)
        if not applied:
            raise RuntimeError("no Compose image lines were rewritten")
        compose = ComposeCli(runner=CommandRunner(env=settings.command_env))
        pull_services = tuple(stack.pull_services) or tuple(stack.services) or None
        compose.pull(
            stack.directory,
            stack.compose_file,
            pull_services,
            project_directory=stack.project_directory or None,
        )
        if digest_pin_updates:
            _verify_self_update_digest_pin_updates(settings, digest_pin_updates)
            applied_digest_pins = apply_compose_digest_pins(
                compose_path,
                digest_pin_updates,
            )
            if not applied_digest_pins:
                raise RuntimeError("no Compose image lines were digest-pinned")
    except Exception as exc:
        try:
            shutil.copy2(backup, compose_path)
        except OSError as restore_exc:
            restore_error = f"; compose rollback failed: {restore_exc}"
        raise RuntimeError(f"{exc}{restore_error}") from exc
    finally:
        _delete_self_update_plan_file_path(backup)

    return {
        "strategy": "prepare_tag_update",
        "external_recreate_required": True,
        "stack": stack.name,
        "compose_file": stack.compose_file,
        "services": list(stack.services),
        "pull_services": list(stack.pull_services),
        "tag_updates": [
            {
                "old_image": item.old_image,
                "desired_tag": item.desired_tag,
                "new_image": item.new_image,
                "services": list(item.services),
                "replacements": item.replacements,
            }
            for item in applied
        ],
        "digest_pin_updates": [
            {
                "source_image": item.old_image,
                "resolved_tag": item.resolved_tag,
                "planned_digest": item.planned_digest,
                "final_image": item.final_image,
                "watch_tag": item.watch_tag,
                "marker": item.marker,
                "label_key": item.label_key,
                "label_value": item.label_value,
                "services": list(item.services),
                "replacements": item.replacements,
            }
            for item in applied_digest_pins
        ],
    }


def _tag_overrides_from_payload(
    payload: PlanRequest | ApplyPlanRequest,
) -> tuple[TagOverride, ...]:
    overrides: list[TagOverride] = []
    seen: set[int] = set()
    for item in payload.tag_overrides:
        line_no = item.line_no
        if line_no in seen:
            raise PlanInputError(
                f"tag_overrides line {line_no} was provided more than once"
            )
        if not tag_value_valid(item.tag):
            raise PlanInputError(
                f"tag_overrides line {line_no} has invalid tag: {item.tag}"
            )
        overrides.append(TagOverride(line_no=line_no, tag=item.tag))
        seen.add(line_no)
    return tuple(overrides)


def _apply_preflight_response(
    settings: WebSettings,
    request: Request,
    plan: DryRunPlan,
) -> ApplyPreflightResponse:
    doctor = _doctor_response(settings, _web_doctor_result(settings, request))
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
    db_ready, db_warning = _database_ready(settings)
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


def _plan_can_apply(plan: DryRunPlan, settings: WebSettings) -> bool:
    return (
        settings.mutations_enabled
        and plan.status == "ready"
        and not plan.skipped
        and not any(issue.severity == "error" for issue in plan.issues)
    )


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


def _submit_apply_job(
    request: Request,
    settings: WebSettings,
    plan: DryRunPlan,
    payload: ApplyPlanRequest,
    wud_lock: DirectoryLock,
) -> ApplyJobResponse:
    return _submit_apply_job_state(
        request.app.state,
        settings,
        plan,
        allow_tag_updates=payload.allow_tag_updates,
        tag_overrides=tuple(_tag_overrides_from_payload(payload)),
        wud_lock=wud_lock,
    )


def _submit_apply_job_state(
    state: Any,
    settings: WebSettings,
    plan: DryRunPlan,
    *,
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    wud_lock: DirectoryLock,
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
            _digest_pin_updates_from_plan(plan),
            jobs,
            apply_condition,
            job.id,
            wud_lock,
            update_mode_override,
            metadata_extra,
            auto_update_schedule_keys,
            start_event,
        )
        return response


def _active_apply_job_exists(request: Request) -> bool:
    return _active_apply_job_exists_in_state(request.app.state)


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


def _cache_self_update_plan(state: Any, cached: WebSelfUpdatePlan) -> None:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        _prune_self_update_plan_cache_unlocked(state)
        plans: dict[str, WebSelfUpdatePlan] = state.web_self_update_plans
        plans[cached.plan_id] = cached


def _require_self_update_cached_plan(
    state: Any,
    plan_id: str,
) -> WebSelfUpdatePlan:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        _prune_self_update_plan_cache_unlocked(state)
        plans: dict[str, WebSelfUpdatePlan] = state.web_self_update_plans
        cached = plans.get(plan_id)
    if cached is None:
        raise HTTPException(status_code=409, detail="self-update plan is stale")
    return cached


def _remove_self_update_cached_plan(state: Any, plan_id: str) -> None:
    apply_lock: Lock = state.web_apply_lock
    with apply_lock:
        plans: dict[str, WebSelfUpdatePlan] = state.web_self_update_plans
        cached = plans.pop(plan_id, None)
    if cached is not None:
        _delete_self_update_plan_file(cached)


def _prune_self_update_plan_cache_unlocked(state: Any) -> None:
    now = time.monotonic()
    plans: dict[str, WebSelfUpdatePlan] = state.web_self_update_plans
    expired = [
        plan_id
        for plan_id, cached in plans.items()
        if now - cached.created_at > SELF_UPDATE_PLAN_TTL_SECONDS
    ]
    for plan_id in expired:
        cached = plans.pop(plan_id)
        _delete_self_update_plan_file(cached)


def _delete_self_update_plan_file(cached: WebSelfUpdatePlan) -> None:
    _delete_self_update_plan_file_path(cached.wud_file)


def _delete_self_update_plan_file_path(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning("failed to remove self-update temporary plan file: %s", path)


def _self_update_cached_plan_stale(
    cached: WebSelfUpdatePlan,
    status: SelfUpdateResponse,
) -> bool:
    return (
        cached.current_tag != status.current_tag
        or cached.latest_tag != status.latest_tag
        or cached.current_image != status.current_image
        or cached.target_image != status.target_image
        or cached.restart_container != status.restart_container
    )


def _require_apply_job(job_id: str, request: Request) -> WebApplyJob:
    apply_lock: Lock = request.app.state.web_apply_lock
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    with apply_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="apply job not found")
        return job


def _apply_job_stream(
    request: Request,
    job_id: str,
    *,
    log_tail_bytes: int,
) -> Iterator[str]:
    settings = _settings(request)
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    apply_condition: Condition = request.app.state.web_apply_condition
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
    digest_pin_plan: tuple[DigestPinUpdate, ...],
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    wud_lock: DirectoryLock,
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
            digest_pin_plan=digest_pin_plan,
            plan_id=plan_id,
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
        _safe_update_auto_update_schedule_runs(
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
        _safe_update_auto_update_schedule_runs(
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
    digest_pin_plan: tuple[DigestPinUpdate, ...] = (),
    plan_id: str,
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
    config = _effective_config(settings)
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
) -> ApplyJobLogResponse | None:
    if not job.log_file:
        return None
    try:
        log_path = _safe_log_path(settings, job.log_file)
        if log_path is None:
            return None
        tail = _read_log_tail(log_path, max_bytes)
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


def _pending_response(
    settings: WebSettings,
    *,
    include_grouping: bool = True,
) -> PendingResponse:
    exists, parsed = _parse_pending_file(settings)
    items = [
        PendingItem(
            line_no=target.line_no,
            raw=target.raw,
            image=target.first,
            key=target.key,
            repo=target.repo,
            current_tag=image_tag(target.first),
            has_tag=target.has_tag,
            allow_repo=target.allow_repo,
            digest=target.digest,
            desired_tag=target.desired_tag,
        )
        for target in parsed.targets
    ]
    return PendingResponse(
        source_file=str(settings.config.wud_out_file),
        exists=exists,
        count=len(items),
        items=items,
        grouping=(
            _pending_grouping_response(settings, parsed)
            if include_grouping
            else PendingGrouping(status="unavailable")
        ),
        warnings=list(parsed.warnings),
    )


def _pending_grouping_response(
    settings: WebSettings,
    parsed: ParsedWudFile,
) -> PendingGrouping:
    grouping = resolve_pending_groups(
        _effective_config(settings),
        parsed,
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )
    return PendingGrouping(
        status=grouping.status,
        groups=[
            PendingStackGroup(
                name=group.name,
                directory=group.directory,
                compose_file=group.compose_file,
                project_directory=group.project_directory,
                services_label=group.services_label,
                services=list(group.services),
                line_numbers=list(group.line_numbers),
                items=[_pending_grouped_item(item) for item in group.items],
            )
            for group in grouping.groups
        ],
        unmatched=[_pending_grouped_item(item) for item in grouping.unmatched],
        warnings=list(grouping.warnings),
    )


def _pending_grouped_item(item: Any) -> PendingGroupedItem:
    return PendingGroupedItem(
        line_no=item.line_no,
        raw=item.raw,
        image=item.image,
        key=item.key,
        repo=item.repo,
        current_tag=image_tag(item.image),
        has_tag=item.has_tag,
        allow_repo=item.allow_repo,
        digest=item.digest,
        desired_tag=item.desired_tag,
        resolved_image=item.resolved_image,
        target_image=item.target_image,
        compose_images=list(item.compose_images),
        services=list(item.services),
        action=item.action,
        diagnostic=(
            None if item.diagnostic is None else PendingDiagnostic.model_validate(asdict(item.diagnostic))
        ),
    )


def _update_targets_response(settings: WebSettings) -> UpdateTargetsResponse:
    config = _effective_config(settings)
    runner = (
        CommandRunner(env=settings.command_env)
        if settings.command_env is not None
        else CommandRunner()
    )
    compose = ComposeCli(runner=runner)
    try:
        stacks = compose.discover_stacks(
            config.docker_base,
            project_base=settings.host_docker_base,
            ignore_paths=config.compose_ignore_paths,
        )
    except ComposeDiscoveryError as exc:
        return UpdateTargetsResponse(
            status="unavailable",
            count=0,
            warnings=[str(exc)],
        )

    items: list[UpdateTargetItem] = []
    for stack in stacks:
        project_directory = (
            "" if stack.project_directory is None else str(stack.project_directory)
        )
        for pair in stack.service_images:
            items.append(
                UpdateTargetItem(
                    service_key=f"{stack.name}/{pair.service}",
                    stack=stack.name,
                    service=pair.service,
                    image=pair.image,
                    image_repo=repo_key(pair.image),
                    current_tag=image_tag(pair.image),
                    directory=str(stack.directory),
                    compose_file=stack.file,
                    project_directory=project_directory,
                )
            )

    return UpdateTargetsResponse(
        status="ready",
        count=len(items),
        items=items,
        warnings=[],
    )


def _release_notes_response(
    settings: WebSettings,
    items: list[Any],
    warnings: list[str],
) -> ReleaseNotesResponse:
    redacted_items: list[ReleaseNoteInfo] = []
    for item in items:
        data = asdict(item)
        data["error"] = _redact_sensitive_text(settings, str(data.get("error", "")))
        redacted_items.append(ReleaseNoteInfo.model_validate(data))
    return ReleaseNotesResponse(
        source_file=str(settings.config.wud_out_file),
        count=len(items),
        items=redacted_items,
        warnings=[_redact_sensitive_text(settings, warning) for warning in warnings],
    )


def _release_note_source_resolver(settings: WebSettings) -> ReleaseNoteSourceResolver:
    docker = DockerCli(runner=CommandRunner(env=settings.command_env))
    label_cache: dict[str, tuple[str, CommandError | None]] = {}
    container_images: list[ContainerImage] | None = None

    def source_label(image: str) -> tuple[str, CommandError | None]:
        if image not in label_cache:
            value, error = docker.try_image_label(image, OCI_SOURCE_LABEL)
            label_cache[image] = (value, error)
        return label_cache[image]

    def running_images() -> list[ContainerImage]:
        nonlocal container_images
        if container_images is None:
            container_images = docker.try_container_images()
        return container_images

    def resolve(target: WudTarget) -> str:
        value, error = source_label(target.first)
        if github_repo_from_source(value):
            return value

        repo = github_repo_from_ghcr_image(target.first)
        if repo:
            return f"https://github.com/{repo}"

        for container in running_images():
            if container.name != target.first and not image_matches_resolved_target(
                container.image,
                target.first,
                target.allow_repo,
            ):
                continue
            matched_repo = github_repo_from_ghcr_image(container.image)
            if matched_repo:
                return f"https://github.com/{matched_repo}"

        if error is not None:
            LOGGER.error(
                "WebUI release-note fallback: Docker inspect failed for %s; "
                "cannot read %s, so GitHub release links may be unavailable. "
                "Command: %s. stderr: %s",
                target.first,
                OCI_SOURCE_LABEL,
                error.result.display,
                error.result.stderr.strip() or "<empty>",
            )
        return value

    return resolve


def _plan_response(
    plan: DryRunPlan,
    settings: WebSettings,
    request: Request,
) -> PlanResponse:
    apply_preflight = _apply_preflight_response(settings, request, plan)
    payload = asdict(plan)
    payload["can_apply"] = _plan_can_apply(plan, settings) and apply_preflight.ok
    payload["cleanup"]["can_remove_unmatched"] = (
        settings.mutations_enabled and bool(plan.cleanup.items)
    )
    payload["apply_preflight"] = apply_preflight.model_dump()
    return PlanResponse.model_validate(payload)


def _parse_pending_file(settings: WebSettings) -> tuple[bool, ParsedWudFile]:
    path = settings.config.wud_out_file
    try:
        return True, parse_wud_file(path)
    except FileNotFoundError:
        return False, ParsedWudFile(lines=(), targets=(), warnings=())
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read WUD file: {exc}",
        ) from exc


def _database_ready(settings: WebSettings) -> tuple[bool, str]:
    try:
        with closing(_connect_readonly_db(settings)):
            pass
        return True, ""
    except ReadOnlyDatabaseMissing as exc:
        return False, str(exc)
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        return False, f"database is not ready: {exc}"


def _connect_readonly_db(settings: WebSettings) -> sqlite3.Connection:
    path = settings.config.db_path
    if str(path) == ":memory:" or not path.is_file():
        raise ReadOnlyDatabaseMissing(f"database file does not exist: {path}")
    conn = sqlite3.connect(_readonly_sqlite_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        _validate_readonly_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _readonly_sqlite_uri(path: Path) -> str:
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def _validate_readonly_schema(conn: sqlite3.Connection) -> None:
    version = db_user_version(conn)
    if version == 0:
        raise DatabaseError("database schema is not initialized")
    if version != SCHEMA_VERSION:
        raise DatabaseError(
            f"database schema version {version} requires migration to {SCHEMA_VERSION}"
        )
    validate_db_schema(conn)


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


def _self_update_response(settings: WebSettings) -> SelfUpdateResponse:
    env = settings.command_env or {}
    local_tag = current_tag()
    container = settings.restart_container.strip()
    current_image = current_container_image(env)
    warnings: list[str] = []

    if _parse_bool(env.get("WUD_WEB_DEMO_SELF_UPDATE"), default=False):
        return _demo_self_update_response(
            settings,
            current_image=current_image,
            restart_container=container,
        )

    if not release_check_enabled(env):
        return SelfUpdateResponse(
            status="disabled",
            strategy="pull_image",
            current_tag=local_tag,
            latest_tag="",
            current_image=current_image,
            target_image="",
            restart_container=container,
            disabled_reason="release checks are disabled",
        )

    latest_tag = fetch_latest_release_tag()
    if latest_tag is None:
        return SelfUpdateResponse(
            status="unavailable",
            strategy="pull_image",
            current_tag=local_tag,
            latest_tag="",
            current_image=current_image,
            target_image="",
            restart_container=container,
            disabled_reason="latest release could not be checked",
            warnings=["latest WUD-Updater release could not be checked"],
        )

    if not release_update_available(local_tag, latest_tag):
        return SelfUpdateResponse(
            status="up_to_date",
            strategy="pull_image",
            current_tag=local_tag,
            latest_tag=latest_tag,
            current_image=current_image,
            target_image="",
            restart_container=container,
        )

    target_spec = release_self_update_target(current_image, local_tag, latest_tag)
    target_image = _self_update_pull_image(target_spec)
    strategy: SelfUpdateStrategy = (
        "prepare_tag_update"
        if _self_update_requires_tag_rewrite(target_spec)
        else "pull_image"
    )
    release_notes, truncated, note_warnings = _fetch_self_update_release_notes(
        local_tag,
        latest_tag,
        env,
        cap=SELF_UPDATE_RELEASE_NOTES_CAP,
    )
    warnings.extend(note_warnings)
    disabled_reason = _self_update_disabled_reason(
        settings,
        target_spec=target_spec,
        target_image=target_image,
        restart_container=container,
    )
    return SelfUpdateResponse(
        status="available",
        strategy=strategy,
        current_tag=local_tag,
        latest_tag=latest_tag,
        current_image=current_image,
        target_image=target_image,
        restart_container=container,
        release_notes=release_notes,
        release_notes_truncated=truncated,
        release_notes_cap=SELF_UPDATE_RELEASE_NOTES_CAP,
        can_update=disabled_reason == "",
        disabled_reason=disabled_reason,
        external_recreate_required=strategy == "prepare_tag_update",
        warnings=warnings,
    )


def _demo_self_update_response(
    settings: WebSettings,
    *,
    current_image: str,
    restart_container: str,
) -> SelfUpdateResponse:
    demo_current_tag = "v0.25.0"
    latest_tag = "v0.26.0"
    current_image = current_image or "ghcr.io/magrhino/wud-updater:latest"
    target_image = "ghcr.io/magrhino/wud-updater:latest"
    disabled_reason = _self_update_disabled_reason(
        settings,
        target_spec="ghcr.io/magrhino/wud-updater:latest",
        target_image=target_image,
        restart_container=restart_container,
    )
    notes = [
        SelfUpdateReleaseNote(
            tag=f"v0.{minor}.0",
            title=f"v0.{minor}.0 demo release",
            published_at=f"2026-05-{day:02d}T12:00:00Z",
            url=f"https://github.com/magrhino/WUD-Updater/releases/tag/v0.{minor}.0",
            body=(
                "Adds the WebUI self-update banner, release-note review, "
                "and image pull flow."
                if minor == 26
                else "Demo release note for the capped self-update history list."
            ),
            breaking=minor == 26,
            breaking_reasons=(
                ["Review external container recreate steps."] if minor == 26 else []
            ),
        )
        for minor, day in zip(range(26, 16, -1), range(28, 18, -1), strict=True)
    ]
    return SelfUpdateResponse(
        status="available",
        strategy="pull_image",
        current_tag=demo_current_tag,
        latest_tag=latest_tag,
        current_image=current_image,
        target_image=target_image,
        restart_container=restart_container,
        release_notes=notes,
        release_notes_truncated=True,
        release_notes_cap=SELF_UPDATE_RELEASE_NOTES_CAP,
        can_update=disabled_reason == "",
        disabled_reason=disabled_reason,
        external_recreate_required=False,
    )


def _self_update_disabled_reason(
    settings: WebSettings,
    *,
    target_spec: str = "",
    target_image: str,
    restart_container: str,
) -> str:
    if not settings.mutations_enabled:
        return (
            "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on "
            "the server to update the WebUI container."
        )
    if not restart_container:
        return "container restart target is not configured"
    if not target_image:
        return "self-update image target could not be determined"
    try:
        _validate_restart_container_target(restart_container)
    except WebConfigError as exc:
        return str(exc)
    return ""


def _self_update_confirmation_stale(
    payload: SelfUpdateRequest | SelfUpdatePrepareRequest,
    status: SelfUpdateResponse,
) -> bool:
    return (
        payload.current_tag != status.current_tag
        or payload.latest_tag != status.latest_tag
        or payload.target_image != status.target_image
        or payload.restart_container != status.restart_container
    )


def _self_update_pull_image(target: str) -> str:
    parts = target.strip().split()
    if not parts:
        return ""
    image = parts[0]
    desired_tag = ""
    for token in parts[1:]:
        if token.startswith("tag="):
            desired_tag = token.removeprefix("tag=")
    if desired_tag and image_has_tag(image) and tag_value_valid(desired_tag):
        return image_with_tag(image, desired_tag)
    return image


def _self_update_requires_tag_rewrite(target: str) -> bool:
    parts = target.strip().split()
    return any(token.startswith("tag=") for token in parts[1:])


def _fetch_self_update_release_notes(
    current: str,
    latest: str,
    environ: Mapping[str, str],
    *,
    cap: int,
) -> tuple[list[SelfUpdateReleaseNote], bool, list[str]]:
    request = urllib.request.Request(
        SELF_UPDATE_RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"wud-updater-webui/{__version__}",
            **(
                {"Authorization": f"Bearer {environ['GITHUB_TOKEN']}"}
                if environ.get("GITHUB_TOKEN")
                else {}
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=6.0) as response:
            payload = response.read(262_144)
        data = json.loads(payload.decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return [], False, [f"self-update release notes unavailable: {exc}"]
    if not isinstance(data, list):
        return [], False, ["self-update release notes unavailable: invalid response"]

    matched: list[SelfUpdateReleaseNote] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag_name")
        if not isinstance(tag, str):
            continue
        normalized_tag = _normalize_self_update_tag(tag)
        if not _self_update_tag_between(normalized_tag, current, latest):
            continue
        body = str(item.get("body") or "")
        body_truncated = len(body) > 6000
        if body_truncated:
            body = body[:6000].rstrip()
        breaking, reasons = detect_breaking(body, current, normalized_tag)
        matched.append(
            SelfUpdateReleaseNote(
                tag=normalized_tag,
                title=str(item.get("name") or normalized_tag),
                published_at=str(item.get("published_at") or ""),
                url=str(item.get("html_url") or ""),
                body=body,
                body_truncated=body_truncated,
                breaking=breaking,
                breaking_reasons=reasons,
            )
        )

    matched.sort(
        key=lambda note: _self_update_semver_key(note.tag) or (0, 0, 0),
        reverse=True,
    )
    return matched[:cap], len(matched) > cap, []


def _self_update_tag_between(tag: str, current: str, latest: str) -> bool:
    tag_key = _self_update_semver_key(tag)
    current_key = _self_update_semver_key(current)
    latest_key = _self_update_semver_key(latest)
    if tag_key is None or current_key is None or latest_key is None:
        return False
    return current_key < tag_key <= latest_key


def _self_update_semver_key(tag: str) -> tuple[int, int, int] | None:
    match = re.match(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+].*)?$", tag.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _normalize_self_update_tag(tag: str) -> str:
    normalized = tag.strip()
    if not normalized:
        return ""
    return normalized if normalized.startswith("v") else f"v{normalized}"


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


def _restart_container_task(
    settings: WebSettings,
    container: str,
    audit_run_id: int,
) -> None:
    try:
        DockerCli(runner=CommandRunner(env=settings.command_env)).restart_container(
            container,
            timeout_seconds=10,
        )
    except CommandError as exc:
        detail = exc.result.stderr.strip() or str(exc)
        LOGGER.error(
            "WebUI container restart failed for %s: %s",
            container,
            _redact_sensitive_text(settings, detail),
        )
        _safe_update_container_restart_audit(
            settings,
            audit_run_id,
            status="failure",
            error=_redact_sensitive_text(settings, detail),
        )
        return

    _safe_update_container_restart_audit(
        settings,
        audit_run_id,
        status="success",
    )


def _insert_container_restart_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    *,
    container: str,
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": "webui",
        "operation": "restart_container",
        "actor_type": _state_actor_type(settings, request),
        "resource_type": "container",
        "resource_id": container,
        "target": {"container": container},
        "status": "scheduled",
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
        VALUES (?, NULL, 'scheduled', 0, 'web-container-restart', ?, '', ?)
        """,
        (
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
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
        VALUES (?, ?, 'wud-updater', '', '', ?, 'scheduled', ?)
        """,
        (
            run_id,
            now,
            container,
            _json_object(metadata),
        ),
    )
    return run_id


def _insert_self_update_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    request: Request,
    *,
    status: SelfUpdateResponse,
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": "webui",
        "operation": "self_update",
        "actor_type": _state_actor_type(settings, request),
        "resource_type": "container",
        "resource_id": status.restart_container,
        "current_tag": status.current_tag,
        "latest_tag": status.latest_tag,
        "current_image": status.current_image,
        "target_image": status.target_image,
        "strategy": status.strategy,
        "external_recreate_required": status.external_recreate_required,
        "target": {
            "container": status.restart_container,
            "image": status.target_image,
        },
        "status": "scheduled",
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
        VALUES (?, NULL, 'scheduled', 0, 'web-self-update', ?, '', ?)
        """,
        (
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
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
        VALUES (?, ?, 'wud-updater', 'webui', ?, ?, 'scheduled', ?)
        """,
        (
            run_id,
            now,
            status.current_image,
            status.target_image,
            _json_object(metadata),
        ),
    )
    return run_id


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


def _safe_update_container_restart_audit(
    settings: WebSettings,
    run_id: int,
    *,
    status: Literal["success", "failure"],
    error: str = "",
) -> None:
    try:
        _update_container_restart_audit(
            settings,
            run_id,
            status=status,
            error=error,
        )
    except (OSError, sqlite3.Error, DatabaseError):
        LOGGER.exception("failed to update WebUI container restart audit")


def _safe_update_self_update_audit(
    settings: WebSettings,
    run_id: int,
    *,
    status: SelfUpdateAuditStatus,
    error: str = "",
    metadata_extra: Mapping[str, Any] | None = None,
) -> None:
    try:
        _update_self_update_audit(
            settings,
            run_id,
            status=status,
            error=error,
            metadata_extra=metadata_extra,
        )
    except (OSError, sqlite3.Error, DatabaseError):
        LOGGER.exception("failed to update WebUI self-update audit")


def _update_self_update_audit(
    settings: WebSettings,
    run_id: int,
    *,
    status: SelfUpdateAuditStatus,
    error: str = "",
    metadata_extra: Mapping[str, Any] | None = None,
) -> None:
    now = utc_timestamp()
    with connect_db(settings.config.db_path) as conn:
        init_db(conn)
        with conn:
            metadata = _self_update_audit_metadata(conn, run_id)
            metadata["status"] = status
            if metadata_extra:
                metadata.update(metadata_extra)
            if error:
                metadata["error"] = error
            else:
                metadata.pop("error", None)
            metadata_json = _json_object(metadata)
            conn.execute(
                """
                UPDATE update_runs
                SET finished_at = ?,
                    status = ?,
                    metadata_json = ?
                WHERE id = ?
                  AND mode = 'web-self-update'
                """,
                (now, status, metadata_json, run_id),
            )
            conn.execute(
                """
                UPDATE update_events
                SET status = ?,
                    metadata_json = ?
                WHERE run_id = ?
                """,
                (status, metadata_json, run_id),
            )


def _self_update_audit_metadata(
    conn: sqlite3.Connection,
    run_id: int,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT metadata_json
        FROM update_runs
        WHERE id = ?
          AND mode = 'web-self-update'
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _update_container_restart_audit(
    settings: WebSettings,
    run_id: int,
    *,
    status: Literal["success", "failure"],
    error: str = "",
) -> None:
    now = utc_timestamp()
    with connect_db(settings.config.db_path) as conn:
        init_db(conn)
        with conn:
            metadata = _container_restart_audit_metadata(conn, run_id)
            metadata["status"] = status
            if error:
                metadata["error"] = error
            else:
                metadata.pop("error", None)
            metadata_json = _json_object(metadata)
            conn.execute(
                """
                UPDATE update_runs
                SET finished_at = ?,
                    status = ?,
                    metadata_json = ?
                WHERE id = ?
                  AND mode = 'web-container-restart'
                """,
                (now, status, metadata_json, run_id),
            )
            conn.execute(
                """
                UPDATE update_events
                SET status = ?,
                    metadata_json = ?
                WHERE run_id = ?
                """,
                (status, metadata_json, run_id),
            )


def _container_restart_audit_metadata(
    conn: sqlite3.Connection,
    run_id: int,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT metadata_json
        FROM update_runs
        WHERE id = ?
          AND mode = 'web-container-restart'
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


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


def _auth_session_response(
    settings: WebSettings,
    *,
    authenticated: bool,
    setup_required: bool,
    username: str | None = None,
) -> AuthSessionResponse:
    return AuthSessionResponse(
        authenticated=authenticated,
        setup_required=setup_required,
        auth_required=settings.auth_required,
        dev_auth_bypass=settings.dev_no_auth,
        mutations_enabled=settings.mutations_enabled,
        username=username,
    )


async def _validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(_strip_validation_inputs(exc.errors()))},
    )


def _strip_validation_inputs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_validation_inputs(item)
            for key, item in value.items()
            if key != "input"
        }
    if isinstance(value, list):
        return [_strip_validation_inputs(item) for item in value]
    return value


def _redact_sensitive_text(
    settings: WebSettings,
    value: str,
    extra_secrets: Sequence[str] = (),
) -> str:
    redacted = value
    for secret in _sensitive_redaction_values(settings, extra_secrets):
        redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _sanitize_support_bundle_value(settings: WebSettings, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_support_bundle_value(settings, item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_support_bundle_value(settings, item) for item in value]
    if isinstance(value, str):
        return _sanitize_support_bundle_text(settings, value)
    return value


def _sanitize_support_bundle_text(settings: WebSettings, value: str) -> str:
    replacements = _support_bundle_path_replacements(settings)
    redacted = _redact_sensitive_text(settings, value)
    for source, target in replacements:
        redacted = redacted.replace(source, target)
    return _redact_unknown_absolute_paths(redacted)


def _support_bundle_path_replacements(settings: WebSettings) -> list[tuple[str, str]]:
    config = settings.config
    exact_paths: list[tuple[Path, str]] = [
        (config.wud_out_file, "<WUD_OUT_FILE>"),
        (config.log_dir, "<WUD_LOG_DIR>"),
        (config.db_path, "<WUD_DB_PATH>"),
    ]
    root_paths: list[tuple[Path, str]] = [(config.docker_base, "<DOCKER_BASE>")]
    if settings.host_docker_base is not None:
        root_paths.append((settings.host_docker_base, "<HOST_DOCKER_BASE>"))

    replacements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path, label in (*exact_paths, *root_paths):
        text = str(path)
        if text and text not in seen:
            seen.add(text)
            replacements.append((text, label))

    for root, label in root_paths:
        root_text = str(root).rstrip("/")
        if not root_text or root_text in seen:
            continue
        seen.add(root_text)
        replacements.append((root_text, label))

    return sorted(replacements, key=lambda item: len(item[0]), reverse=True)


def _redact_unknown_absolute_paths(value: str) -> str:
    return re.sub(
        r"(?<![:/<>\w-])/(?:[^\s\"'`,;)\]}]+)",
        "<absolute-path-redacted>",
        value,
    )


def _sensitive_redaction_values(
    settings: WebSettings,
    extra_secrets: Sequence[str],
) -> list[str]:
    values: list[str] = []
    env = settings.command_env or {}
    values.extend(extra_secrets)
    values.append(settings.auth_token)
    values.extend(env.get(key, "") for key in SENSITIVE_ENV_KEYS)

    expanded: list[str] = []
    for value in values:
        if value:
            expanded.append(value)
            expanded.extend(_secret_url_fragments(value))

    seen: set[str] = set()
    result: list[str] = []
    for value in sorted(expanded, key=len, reverse=True):
        if len(value) < 4 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _secret_url_fragments(value: str) -> list[str]:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return []
    fragments: list[str] = []
    path = parsed.path.strip("/")
    if len(path) >= 8:
        fragments.append(path)
    fragments.extend(segment for segment in path.split("/") if len(segment) >= 8)
    if parsed.query and len(parsed.query) >= 8:
        fragments.append(parsed.query)
    return fragments


def _safe_exception_detail(
    settings: WebSettings,
    message: str,
    exc: BaseException,
) -> str:
    return f"{message}: {_redact_sensitive_text(settings, str(exc))}"


def _prepare_web_auth_state(settings: WebSettings) -> str:
    with connect_db(settings.config.db_path) as conn:
        init_db(conn)
        user_count = _web_user_count(conn)
        if user_count > 0:
            _delete_web_setting(conn, SETUP_CLAIM_HASH_KEY)
            _delete_web_setting(conn, SETUP_CLAIM_EXPIRES_KEY)
            return ""
        claim = secrets.token_urlsafe(32)
        with conn:
            _set_web_setting(conn, SETUP_CLAIM_HASH_KEY, _secret_hash(claim))
            _set_web_setting(
                conn,
                SETUP_CLAIM_EXPIRES_KEY,
                _utc_timestamp_after(SETUP_CLAIM_MAX_AGE_SECONDS),
            )
        return claim


def _setup_required(settings: WebSettings) -> bool:
    if settings.dev_no_auth:
        return False
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            return _web_user_count(conn) == 0
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not read web auth state",
                exc,
            ),
        ) from exc


def _claim_initial_admin(
    settings: WebSettings,
    claim: str,
    username: str,
    password: str,
) -> int:
    now = utc_timestamp()
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with _immediate_transaction(conn):
                if _web_user_count(conn) > 0:
                    raise HTTPException(status_code=409, detail="setup is complete")
                expected_hash = _web_setting(conn, SETUP_CLAIM_HASH_KEY)
                expires_at = _web_setting(conn, SETUP_CLAIM_EXPIRES_KEY)
                if not expected_hash or not expires_at:
                    raise HTTPException(status_code=403, detail="setup claim is invalid")
                if expires_at < now:
                    raise HTTPException(status_code=403, detail="setup claim expired")
                if not secrets.compare_digest(expected_hash, _secret_hash(claim)):
                    raise HTTPException(status_code=403, detail="setup claim is invalid")
                password_hash = PASSWORD_HASHER.hash(password)
                cursor = conn.execute(
                    """
                    INSERT INTO web_users (
                        username,
                        password_hash,
                        role,
                        created_at,
                        password_updated_at
                    )
                    VALUES (?, ?, 'admin', ?, ?)
                    """,
                    (username, password_hash, now, now),
                )
                _delete_web_setting(conn, SETUP_CLAIM_HASH_KEY)
                _delete_web_setting(conn, SETUP_CLAIM_EXPIRES_KEY)
                return int(cursor.lastrowid)
    except HTTPException:
        raise
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username is unavailable") from exc
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(settings, "could not complete setup", exc),
        ) from exc


def issue_admin_recovery_claim(
    settings: WebSettings,
    username: str,
) -> AdminRecoveryClaim:
    normalized = _normalize_username(username)
    if not normalized:
        raise WebAdminResetError("username is required")

    db_path = settings.config.db_path
    if str(db_path) != ":memory:" and not db_path.is_file():
        raise WebAdminResetError(f"database file does not exist: {db_path}")

    now = utc_timestamp()
    claim = secrets.token_urlsafe(32)
    expires_at = _utc_timestamp_after(SETUP_CLAIM_MAX_AGE_SECONDS)
    disabled_password_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(96))
    try:
        with closing(connect_db(db_path)) as conn:
            init_db(conn)
            with _immediate_transaction(conn):
                user = _active_admin_user(conn, normalized)
                if user is None:
                    if _web_user_count(conn) == 0:
                        raise WebAdminResetError("WebUI setup is not complete")
                    raise WebAdminResetError(f"active admin user not found: {normalized}")
                user_id = int(user["id"])
                conn.execute(
                    """
                    UPDATE web_users
                    SET password_hash = ?,
                        password_updated_at = ?
                    WHERE id = ?
                    """,
                    (disabled_password_hash, now, user_id),
                )
                revoked_sessions = conn.execute(
                    """
                    UPDATE web_sessions
                    SET revoked_at = ?
                    WHERE user_id = ?
                      AND revoked_at IS NULL
                    """,
                    (now, user_id),
                ).rowcount
                _set_web_setting(conn, RESET_ADMIN_CLAIM_HASH_KEY, _secret_hash(claim))
                _set_web_setting(conn, RESET_ADMIN_CLAIM_EXPIRES_KEY, expires_at)
                _set_web_setting(conn, RESET_ADMIN_CLAIM_USER_ID_KEY, str(user_id))
                audit_run_id = _insert_auth_audit(
                    conn,
                    settings,
                    source="cli",
                    operation="admin_reset_claim_issued",
                    username=normalized,
                    user_id=user_id,
                    before={
                        "password_updated_at": str(user["password_updated_at"]),
                    },
                    after={
                        "claim_expires_at": expires_at,
                        "password_invalidated": True,
                        "revoked_sessions": max(0, int(revoked_sessions)),
                    },
                )
                return AdminRecoveryClaim(
                    username=normalized,
                    claim=claim,
                    expires_at=expires_at,
                    revoked_sessions=max(0, int(revoked_sessions)),
                    audit_run_id=audit_run_id,
                )
    except WebAdminResetError:
        raise
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise WebAdminResetError(f"could not issue admin recovery claim: {exc}") from exc


def _redeem_admin_recovery_claim(
    settings: WebSettings,
    *,
    claim: str,
    username: str,
    password: str,
) -> int:
    now = utc_timestamp()
    try:
        with closing(connect_db(settings.config.db_path)) as conn:
            init_db(conn)
            with _immediate_transaction(conn):
                expected_hash = _web_setting(conn, RESET_ADMIN_CLAIM_HASH_KEY)
                expires_at = _web_setting(conn, RESET_ADMIN_CLAIM_EXPIRES_KEY)
                user_id_raw = _web_setting(conn, RESET_ADMIN_CLAIM_USER_ID_KEY)
                if not expected_hash or not expires_at or not user_id_raw:
                    raise HTTPException(
                        status_code=403,
                        detail="admin recovery claim is invalid",
                    )
                if expires_at < now:
                    raise HTTPException(
                        status_code=403,
                        detail="admin recovery claim expired",
                    )
                if not secrets.compare_digest(expected_hash, _secret_hash(claim)):
                    raise HTTPException(
                        status_code=403,
                        detail="admin recovery claim is invalid",
                    )
                try:
                    user_id = int(user_id_raw)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=403,
                        detail="admin recovery claim is invalid",
                    ) from exc
                user = conn.execute(
                    """
                    SELECT *
                    FROM web_users
                    WHERE id = ?
                      AND username = ?
                      AND role = 'admin'
                      AND disabled_at IS NULL
                    LIMIT 1
                    """,
                    (user_id, username),
                ).fetchone()
                if user is None:
                    raise HTTPException(
                        status_code=403,
                        detail="admin recovery claim is invalid",
                    )
                conn.execute(
                    """
                    UPDATE web_users
                    SET password_hash = ?,
                        password_updated_at = ?
                    WHERE id = ?
                    """,
                    (PASSWORD_HASHER.hash(password), now, user_id),
                )
                _delete_admin_recovery_claim(conn)
                _insert_auth_audit(
                    conn,
                    settings,
                    source="webui",
                    operation="admin_reset_password_changed",
                    username=username,
                    user_id=user_id,
                    before={
                        "claim_expires_at": expires_at,
                    },
                    after={
                        "password_updated_at": now,
                    },
                )
                return user_id
    except HTTPException:
        raise
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not reset admin password",
                exc,
            ),
        ) from exc


@contextmanager
def _immediate_transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _verify_web_user(
    settings: WebSettings,
    username: str,
    password: str,
) -> sqlite3.Row | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            user = conn.execute(
                """
                SELECT *
                FROM web_users
                WHERE username = ?
                  AND disabled_at IS NULL
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            if user is None:
                return None
            try:
                verified = PASSWORD_HASHER.verify(str(user["password_hash"]), password)
            except (InvalidHashError, VerificationError, VerifyMismatchError):
                return None
            if verified and PASSWORD_HASHER.check_needs_rehash(
                str(user["password_hash"])
            ):
                with conn:
                    conn.execute(
                        """
                        UPDATE web_users
                        SET password_hash = ?,
                            password_updated_at = ?
                        WHERE id = ?
                        """,
                        (PASSWORD_HASHER.hash(password), utc_timestamp(), user["id"]),
                    )
            return user
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not verify credentials",
                exc,
            ),
        ) from exc


def _auth_failed() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _login_throttle_blocked(
    request: Request,
    settings: WebSettings,
    username: str,
) -> bool:
    client_address = _request_client_address(request, settings)
    key = _login_throttle_key(username, client_address)
    now = time.monotonic()
    with request.app.state.web_login_throttle_lock:
        throttle: dict[tuple[str, str], LoginThrottleEntry] = (
            request.app.state.web_login_throttle
        )
        client_throttle: dict[str, LoginThrottleEntry] = (
            request.app.state.web_login_client_throttle
        )
        _prune_login_throttle(throttle, now)
        _prune_login_throttle(client_throttle, now)
        entry = throttle.get(key)
        client_entry = client_throttle.get(client_address)
        return (
            (entry is not None and entry.locked_until > now)
            or (client_entry is not None and client_entry.locked_until > now)
        )


def _record_login_failure(
    request: Request,
    settings: WebSettings,
    username: str,
) -> None:
    client_address = _request_client_address(request, settings)
    key = _login_throttle_key(username, client_address)
    now = time.monotonic()
    with request.app.state.web_login_throttle_lock:
        throttle: dict[tuple[str, str], LoginThrottleEntry] = (
            request.app.state.web_login_throttle
        )
        client_throttle: dict[str, LoginThrottleEntry] = (
            request.app.state.web_login_client_throttle
        )
        _prune_login_throttle(throttle, now)
        _prune_login_throttle(client_throttle, now)
        entry = throttle.get(key)
        if entry is None:
            if len(throttle) >= LOGIN_THROTTLE_MAX_ENTRIES:
                _record_login_client_failure(
                    client_throttle,
                    client_address,
                    now,
                )
                if not _evict_login_throttle_entry(throttle, now):
                    return
            entry = LoginThrottleEntry(
                failures=1,
                first_failed_at=now,
                last_failed_at=now,
            )
            throttle[key] = entry
        else:
            entry.failures += 1
            entry.last_failed_at = now
        if entry.failures >= LOGIN_THROTTLE_MAX_FAILURES:
            entry.locked_until = now + LOGIN_THROTTLE_COOLDOWN_SECONDS


def _clear_login_throttle(
    request: Request,
    settings: WebSettings,
    username: str,
) -> None:
    client_address = _request_client_address(request, settings)
    key = _login_throttle_key(username, client_address)
    with request.app.state.web_login_throttle_lock:
        request.app.state.web_login_throttle.pop(key, None)
        request.app.state.web_login_client_throttle.pop(client_address, None)


def _login_throttle_key(
    username: str,
    client_address: str,
) -> tuple[str, str]:
    return (
        _normalize_username(username).casefold(),
        client_address,
    )


def _record_login_client_failure(
    throttle: dict[str, LoginThrottleEntry],
    client_address: str,
    now: float,
) -> None:
    entry = throttle.get(client_address)
    if entry is None:
        if len(throttle) >= LOGIN_THROTTLE_MAX_CLIENT_ENTRIES:
            _evict_login_throttle_entry(throttle, now, preserve_locked=False)
        entry = LoginThrottleEntry(
            failures=1,
            first_failed_at=now,
            last_failed_at=now,
        )
        throttle[client_address] = entry
    else:
        entry.failures += 1
        entry.last_failed_at = now
    if entry.failures >= LOGIN_THROTTLE_MAX_FAILURES:
        entry.locked_until = now + LOGIN_THROTTLE_COOLDOWN_SECONDS


def _prune_login_throttle(
    throttle: dict[Any, LoginThrottleEntry],
    now: float,
) -> None:
    for key, entry in list(throttle.items()):
        if now - entry.last_failed_at >= LOGIN_THROTTLE_COOLDOWN_SECONDS:
            throttle.pop(key, None)


def _evict_login_throttle_entry(
    throttle: dict[Any, LoginThrottleEntry],
    now: float,
    *,
    preserve_locked: bool = True,
) -> bool:
    evictable = [
        (key, entry)
        for key, entry in throttle.items()
        if not preserve_locked or entry.locked_until <= now
    ]
    if not evictable:
        return False
    key, _entry = min(
        evictable,
        key=lambda item: (item[1].last_failed_at, item[1].first_failed_at),
    )
    throttle.pop(key, None)
    return True


def _create_web_session(
    settings: WebSettings,
    *,
    user_id: int,
    request: Request,
) -> str:
    session_id = secrets.token_urlsafe(48)
    now = utc_timestamp()
    expires_at = _utc_timestamp_after(SESSION_MAX_AGE_SECONDS)
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with conn:
                conn.execute(
                    """
                    INSERT INTO web_sessions (
                        id_hash,
                        user_id,
                        created_at,
                        last_seen_at,
                        expires_at,
                        user_agent_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _secret_hash(session_id),
                        user_id,
                        now,
                        now,
                        expires_at,
                        _user_agent_hash(request),
                    ),
                )
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=_safe_exception_detail(
                settings,
                "could not create session",
                exc,
            ),
        ) from exc
    return session_id


def _session_user(settings: WebSettings, request: Request) -> sqlite3.Row | None:
    session_id = request.cookies.get(SESSION_COOKIE, "")
    if not session_id:
        return None
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            row = conn.execute(
                """
                SELECT web_sessions.id_hash, web_users.*
                FROM web_sessions
                JOIN web_users ON web_users.id = web_sessions.user_id
                WHERE web_sessions.id_hash = ?
                  AND web_sessions.revoked_at IS NULL
                  AND web_sessions.expires_at >= ?
                  AND web_users.disabled_at IS NULL
                LIMIT 1
                """,
                (_secret_hash(session_id), utc_timestamp()),
            ).fetchone()
            if row is None:
                return None
            with conn:
                conn.execute(
                    """
                    UPDATE web_sessions
                    SET last_seen_at = ?
                    WHERE id_hash = ?
                    """,
                    (utc_timestamp(), row["id_hash"]),
                )
            return row
    except (OSError, sqlite3.Error, DatabaseError):
        return None


def _revoke_web_session(settings: WebSettings, session_id: str) -> None:
    if not session_id:
        return
    try:
        with connect_db(settings.config.db_path) as conn:
            init_db(conn)
            with conn:
                conn.execute(
                    """
                    UPDATE web_sessions
                    SET revoked_at = ?
                    WHERE id_hash = ?
                    """,
                    (utc_timestamp(), _secret_hash(session_id)),
                )
    except (OSError, sqlite3.Error, DatabaseError):
        return


def _request_authenticated(
    settings: WebSettings,
    request: Request,
    authorization: str | None,
) -> bool:
    if settings.dev_no_auth:
        return True
    if _setup_required(settings):
        return False
    return _bearer_token_valid(settings, authorization) or _session_user(
        settings,
        request,
    ) is not None


def _active_admin_user(
    conn: sqlite3.Connection,
    username: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM web_users
        WHERE username = ?
          AND role = 'admin'
          AND disabled_at IS NULL
        LIMIT 1
        """,
        (username,),
    ).fetchone()


def _web_user_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM web_users").fetchone()
    return int(row[0])


def _web_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute(
        """
        SELECT value
        FROM web_settings
        WHERE key = ?
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    if row is None:
        return ""
    return str(row["value"] if isinstance(row, sqlite3.Row) else row[0])


def _set_web_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO web_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, utc_timestamp()),
    )


def _delete_web_setting(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM web_settings WHERE key = ?", (key,))


def _delete_admin_recovery_claim(conn: sqlite3.Connection) -> None:
    _delete_web_setting(conn, RESET_ADMIN_CLAIM_HASH_KEY)
    _delete_web_setting(conn, RESET_ADMIN_CLAIM_EXPIRES_KEY)
    _delete_web_setting(conn, RESET_ADMIN_CLAIM_USER_ID_KEY)


def _insert_auth_audit(
    conn: sqlite3.Connection,
    settings: WebSettings,
    *,
    source: str,
    operation: str,
    username: str,
    user_id: int,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> int:
    now = utc_timestamp()
    metadata = {
        "source": source,
        "operation": operation,
        "actor_type": "cli" if source == "cli" else "reset_claim",
        "resource_type": "web_user",
        "resource_id": str(user_id),
        "target": {
            "user_id": user_id,
            "username": username,
        },
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
        VALUES (?, ?, 'success', 0, 'web-auth', ?, '', ?)
        """,
        (
            now,
            now,
            str(settings.config.wud_out_file),
            _json_object(metadata),
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
        VALUES (?, ?, ?, '', 'web_user', ?, 'success', ?)
        """,
        (
            run_id,
            now,
            username,
            str(user_id),
            _json_object({**metadata, "before": before, "after": after}),
        ),
    )
    return run_id


def _bearer_token_valid(settings: WebSettings, authorization: str | None) -> bool:
    if not settings.auth_token:
        return False
    scheme, separator, token = (authorization or "").partition(" ")
    return (
        separator == " "
        and scheme.lower() == "bearer"
        and secrets.compare_digest(token, settings.auth_token)
    )


def _normalize_username(value: str) -> str:
    return value.strip()


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_agent_hash(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "")
    return "" if not user_agent else _secret_hash(user_agent)


def _utc_timestamp_after(seconds: int) -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0)
        + timedelta(seconds=seconds)
    ).isoformat()


def _set_csrf_cookie(
    response: Response,
    csrf_token: str,
    request: Request,
    settings: WebSettings,
) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
        samesite="strict",
        path="/",
        secure=_secure_cookie(settings, request),
    )


def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")


def _set_session_cookie(
    response: Response,
    session: str,
    request: Request,
    settings: WebSettings,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        path="/",
        secure=_secure_cookie(settings, request),
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")


def _safe_log_path(settings: WebSettings, raw_log_file: str) -> Path | None:
    if not raw_log_file:
        return None
    log_dir = settings.config.log_dir
    candidate = Path(raw_log_file)
    if not candidate.is_absolute():
        candidate = log_dir / candidate
    try:
        resolved_log_dir = log_dir.resolve(strict=False)
        if candidate.exists():
            resolved_candidate = candidate.resolve(strict=True)
        else:
            resolved_candidate = candidate.resolve(strict=False)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not resolve log file: {exc}",
        ) from exc
    if not _path_is_or_under(resolved_candidate, resolved_log_dir):
        raise HTTPException(status_code=403, detail="log file is outside WUD_LOG_DIR")
    return candidate


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


def _requires_csrf_origin_check(request: Request) -> bool:
    return request.method.upper() not in SAFE_METHODS and request.url.path.startswith(
        "/api/v1/"
    )


def _csrf_origin_error(
    request: Request,
    settings: WebSettings,
) -> JSONResponse | None:
    origin = request.headers.get("origin", "")
    if not origin:
        return _forbidden("origin header is required")
    if not _origin_allowed(request, settings, origin):
        return _forbidden("origin is not allowed")
    csrf_header = request.headers.get(CSRF_HEADER, "")
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    if not csrf_header or not csrf_cookie:
        return _forbidden("csrf token is required")
    if not secrets.compare_digest(csrf_header, csrf_cookie):
        return _forbidden("csrf token is invalid")
    return None


def _host_header_error(
    request: Request,
    settings: WebSettings,
) -> JSONResponse | None:
    host = request.headers.get("host", "")
    normalized = _normalize_host(host)
    if normalized and normalized in settings.allowed_hosts:
        return None
    return JSONResponse({"detail": "host is not allowed"}, status_code=400)


def _origin_allowed(
    request: Request,
    settings: WebSettings,
    origin: str,
) -> bool:
    normalized = _normalize_origin(origin)
    if not normalized:
        return False
    if normalized in settings.allowed_origins:
        return True
    same_origin = _effective_origin(request, settings)
    return secrets.compare_digest(normalized, same_origin)


def _secure_cookie(settings: WebSettings, request: Request) -> bool:
    if settings.secure_cookies == "true":
        return True
    if settings.secure_cookies == "false":
        return False
    return _effective_origin(request, settings).startswith("https://")


def _effective_origin(request: Request, settings: WebSettings) -> str:
    if settings.public_origin:
        return settings.public_origin
    forwarded = _trusted_forwarded_origin(request, settings)
    if forwarded:
        return forwarded
    host = request.headers.get("host", "")
    return _normalize_origin(f"{request.url.scheme}://{host}")


def _trusted_forwarded_origin(request: Request, settings: WebSettings) -> str:
    if not _client_is_trusted_proxy(request, settings):
        return ""
    forwarded_origin = _origin_from_forwarded_header(request.headers.get("forwarded", ""))
    if forwarded_origin:
        return forwarded_origin
    proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if proto and host:
        return _normalize_origin(f"{proto}://{host}")
    return ""


def _request_client_address(request: Request, settings: WebSettings) -> str:
    forwarded = _trusted_forwarded_client_address(request, settings)
    if forwarded:
        return forwarded
    if request.client is None:
        return ""
    return request.client.host


def _trusted_forwarded_client_address(
    request: Request,
    settings: WebSettings,
) -> str:
    if not _client_is_trusted_proxy(request, settings):
        return ""
    forwarded = _client_address_from_forwarded_header(
        request.headers.get("forwarded", "")
    )
    if forwarded:
        return forwarded
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0]
    return _normalize_forwarded_client_address(forwarded_for)


def _client_address_from_forwarded_header(value: str) -> str:
    if not value:
        return ""
    first = value.split(",", 1)[0]
    for segment in first.split(";"):
        key, separator, raw = segment.strip().partition("=")
        if separator and key.lower() == "for":
            return _normalize_forwarded_client_address(raw)
    return ""


def _normalize_forwarded_client_address(value: str) -> str:
    raw = value.strip().strip('"')
    if not raw or raw.lower() == "unknown":
        return ""
    if raw.startswith("["):
        host, separator, _port = raw[1:].partition("]")
        return host if separator else raw
    host, separator, port = raw.rpartition(":")
    if separator and port.isdigit():
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return raw
        return host
    return raw


def _origin_from_forwarded_header(value: str) -> str:
    if not value:
        return ""
    first = value.split(",", 1)[0]
    parts: dict[str, str] = {}
    for segment in first.split(";"):
        key, separator, raw = segment.strip().partition("=")
        if separator:
            parts[key.lower()] = raw.strip().strip('"')
    proto = parts.get("proto", "")
    host = parts.get("host", "")
    if proto and host:
        return _normalize_origin(f"{proto}://{host}")
    return ""


def _client_is_trusted_proxy(request: Request, settings: WebSettings) -> bool:
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    return any(address in network for network in settings.trusted_proxies)


def _raw_client_is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _forbidden(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=403)


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
    return _managed_settings_entries_from_values(values, settings)


def _managed_settings_entries_from_conn(
    conn: sqlite3.Connection,
    settings: WebSettings,
) -> list[ManagedSettingEntry]:
    return _managed_settings_entries_from_values(
        _managed_settings_db_values(conn),
        settings,
    )


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
        return _validate_restart_container_target(configured.strip())
    if not _running_in_container():
        return ""
    return _validate_restart_container_target(env.get("HOSTNAME", "").strip())


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


def _validate_restart_container_target(value: str) -> str:
    if not value:
        return ""
    if not CONTAINER_REF_RE.fullmatch(value):
        raise WebConfigError(
            "WUD_WEB_RESTART_CONTAINER must be a Docker container name or ID"
        )
    return value


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


def _validate_startup_auth(settings: WebSettings) -> None:
    if settings.secure_cookies not in SECURE_COOKIE_MODES:
        raise WebConfigError("WUD_WEB_SECURE_COOKIES must be auto, true, or false")


def _validate_bind_host_allowed(settings: WebSettings, host: str) -> None:
    normalized = _normalize_host(host)
    if not normalized or normalized in {"0.0.0.0", "::"}:
        return
    if normalized in settings.allowed_hosts:
        return
    raise WebConfigError(
        f"WUD_WEB_ALLOWED_HOSTS must include {normalized} when binding "
        "the WebUI to that host. Set WUD_WEB_ALLOWED_HOSTS to the browser-visible "
        "hostname or IP address."
    )


def _print_setup_claim(
    settings: WebSettings,
    *,
    host: str,
    port: int,
    claim: str,
) -> None:
    setup_url = _setup_url(settings, host=host, port=port, claim=claim)
    print("WUD-Updater WebUI is not configured.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Open this one-time setup link to create the first admin account:", file=sys.stderr)
    print("", file=sys.stderr)
    print(setup_url, file=sys.stderr)
    if host in {"0.0.0.0", "::"} and not settings.public_origin:
        print("", file=sys.stderr)
        print(
            "Set WUD_WEB_PUBLIC_ORIGIN and WUD_WEB_ALLOWED_HOSTS when exposing "
            "the WebUI through a LAN address or reverse proxy.",
            file=sys.stderr,
        )


def _setup_url(settings: WebSettings, *, host: str, port: int, claim: str) -> str:
    origin = settings.public_origin
    if not origin:
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        if ":" in display_host and not display_host.startswith("["):
            display_host = f"[{display_host}]"
        origin = f"http://{display_host}:{port}"
    query = urlencode({"claim": claim})
    return f"{origin}/#/setup?{query}"


def _reset_admin_url(
    settings: WebSettings,
    *,
    host: str,
    port: int,
    claim: str,
    username: str,
) -> str:
    origin = settings.public_origin
    if not origin:
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        if ":" in display_host and not display_host.startswith("["):
            display_host = f"[{display_host}]"
        origin = f"http://{display_host}:{port}"
    query = urlencode({"claim": claim, "user": username})
    return f"{origin}/#/reset-admin?{query}"


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise WebConfigError(f"invalid boolean value: {value}")


def _parse_origins(value: str) -> frozenset[str]:
    return frozenset(
        origin
        for origin in (_normalize_origin(item) for item in value.split(","))
        if origin
    )


def _parse_public_origin(value: str) -> str:
    if not value.strip():
        return ""
    origin = _normalize_origin(value)
    if not origin:
        raise WebConfigError("WUD_WEB_PUBLIC_ORIGIN must be an http(s) origin")
    return origin


def _parse_allowed_hosts(
    value: str,
    *,
    public_origin: str,
    bind_host: str,
) -> frozenset[str]:
    hosts = set(DEFAULT_ALLOWED_HOSTS)
    if public_origin:
        public_host = _host_from_origin(public_origin)
        if public_host:
            hosts.add(public_host)
    bind = _normalize_host(bind_host)
    if bind and bind not in {"0.0.0.0", "::"}:
        hosts.add(bind)
    for item in value.split(","):
        host = _normalize_host(item)
        if host:
            hosts.add(host)
    return frozenset(hosts)


def _parse_trusted_proxies(
    value: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in value.split(","):
        raw = item.strip()
        if not raw:
            continue
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError as exc:
            raise WebConfigError(
                f"WUD_WEB_TRUSTED_PROXIES contains invalid address: {raw}"
            ) from exc
    return tuple(networks)


def _parse_secure_cookie_mode(value: str) -> str:
    normalized = value.strip().lower() or "auto"
    if normalized not in SECURE_COOKIE_MODES:
        raise WebConfigError("WUD_WEB_SECURE_COOKIES must be auto, true, or false")
    return normalized


def _normalize_origin(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return ""
    host = parsed.hostname
    if not host:
        return ""
    netloc = parsed.netloc.lower()
    return f"{parsed.scheme.lower()}://{netloc}"


def _host_from_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    return _normalize_host(parsed.hostname or "")


def _normalize_host(value: str) -> str:
    raw = value.strip().lower().rstrip(".")
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else ""
    if raw.count(":") == 1:
        host, _, port = raw.partition(":")
        if port.isdigit():
            return host
    return raw


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
