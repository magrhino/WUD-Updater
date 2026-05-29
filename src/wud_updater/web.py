"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Condition, Lock
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlencode, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import (
    APIRouter,
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
from .command import CommandRunner
from .config import ConfigError, UpdaterConfig, load_config
from .db import DatabaseError, SCHEMA_VERSION, connect_db, init_db, utc_timestamp
from .db import _user_version as db_user_version
from .db import _validate_schema as validate_db_schema
from .images import image_tag, repo_key, tag_value_valid
from .locks import DirectoryLock, WudLockError
from .plans import (
    DryRunPlan,
    PlanFileMissing,
    PlanInputError,
    build_dry_run_plan,
)
from .updater import TagOverride, UpdateFromWudRunner, UpdaterOptions, js_regex_escape
from .wud_file import ParsedWudFile, parse_wud_file


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080
DEFAULT_RUN_LIMIT = 50
DEFAULT_LOG_TAIL_BYTES = 262_144
MAX_LOG_TAIL_BYTES = 1_048_576
SESSION_MAX_AGE_SECONDS = 86_400
SETUP_CLAIM_MAX_AGE_SECONDS = 86_400
PASSWORD_MIN_LENGTH = 12
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
SECURE_COOKIE_MODES = frozenset({"auto", "true", "false"})
CSRF_HEADER = "x-wud-csrf-token"
CSRF_COOKIE = "wud_csrf_token"
SESSION_COOKIE = "wud_session"
SETUP_CLAIM_HASH_KEY = "setup_claim_hash"
SETUP_CLAIM_EXPIRES_KEY = "setup_claim_expires_at"
DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
PASSWORD_HASHER = PasswordHasher()
LineNumber = Annotated[int, Field(ge=1)]
PlanStatus = Literal["ready", "empty", "blocked"]
ApplyJobStatus = Literal["queued", "running", "success", "failure"]
ServicePolicyUpdateMode = Literal["", "pause", "stop", "live"]
SnoozeState = Literal["active", "expired", "all"]
TagExclusionScope = Literal["image_repo", "service"]
TagExclusionMatchType = Literal["exact"]
TagExclusionStatus = Literal["active", "disabled"]
TagExclusionStatusFilter = Literal["active", "disabled", "all"]
TERMINAL_APPLY_JOB_STATUSES = frozenset({"success", "failure"})
JOB_STREAM_HEARTBEAT_SECONDS = 15.0


class WebConfigError(ValueError):
    """Raised when WebUI configuration is invalid."""


class ReadOnlyDatabaseMissing(RuntimeError):
    """Raised when the read-only WebUI database does not exist."""


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
    command_env: Mapping[str, str] | None = None

    @property
    def auth_required(self) -> bool:
        return not self.dev_no_auth


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


class PendingResponse(BaseModel):
    source_file: str
    exists: bool
    count: int
    items: list[PendingItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    static_spa_available: bool
    warnings: list[str] = Field(default_factory=list)


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


class AuthSessionResponse(BaseModel):
    authenticated: bool
    setup_required: bool
    auth_required: bool
    dev_auth_bypass: bool
    mutations_enabled: bool
    username: str | None = None


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


class RunDetail(RunSummary):
    pending_updates: list[PendingUpdateRecord] = Field(default_factory=list)
    events: list[RunEventRecord] = Field(default_factory=list)


class RunLogResponse(BaseModel):
    run_id: int
    log_file: str
    exists: bool
    content: str
    truncated: bool
    max_bytes: int


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
    actions: list[PlanAction] = Field(default_factory=list)
    lines: list[PlanLine] = Field(default_factory=list)


class PlanSkipped(BaseModel):
    line_no: int
    raw: str
    image: str
    desired_tag: str
    reason: str


class PlanResponse(BaseModel):
    plan_id: str
    dry_run: bool
    can_apply: bool
    status: PlanStatus
    source_file: str
    mode: str
    max_wait: int
    selected_line_numbers: list[int] = Field(default_factory=list)
    summary: PlanSummary
    targets: list[PlanTarget] = Field(default_factory=list)
    stacks: list[PlanStack] = Field(default_factory=list)
    skipped: list[PlanSkipped] = Field(default_factory=list)
    issues: list[PlanIssue] = Field(default_factory=list)


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


class ServicePolicyRecord(BaseModel):
    service_key: str
    update_mode: str
    auto_update: bool
    snooze_default_seconds: int | None
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
    if not active_settings.dev_no_auth:
        app.state.web_setup_claim = _prepare_web_auth_state(active_settings)
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,
    )

    def shutdown_apply_executor() -> None:
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
        "/pending",
        api_pending,
        methods=["GET"],
        response_model=PendingResponse,
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
        command_env=dict(env),
    )


def run_web_from_namespace(args: object) -> int:
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
    user = _verify_web_user(settings, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    session_id = _create_web_session(settings, user_id=int(user["id"]), request=request)
    _set_session_cookie(response, session_id, request, settings)
    return _auth_session_response(
        settings,
        authenticated=True,
        setup_required=False,
        username=str(user["username"]),
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


def api_status(request: Request) -> StatusResponse:
    settings = _settings(request)
    pending = _pending_response(settings)
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
        static_spa_available=_static_spa_available(settings),
        warnings=warnings,
    )


def api_pending(request: Request) -> PendingResponse:
    return _pending_response(_settings(request))


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
    return _plan_response(plan, settings)


def api_create_job(payload: ApplyPlanRequest, request: Request) -> ApplyJobResponse:
    settings = _settings(request)
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    if _active_apply_job_exists(request):
        raise HTTPException(status_code=409, detail="an apply job is already running")
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


def api_job_stream(job_id: str, request: Request) -> StreamingResponse:
    _require_apply_job(job_id, request)
    return StreamingResponse(
        _apply_job_stream(request, job_id),
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
    except ReadOnlyDatabaseMissing:
        return []
    except (OSError, sqlite3.Error, DatabaseError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not read database: {exc}",
        ) from exc
    return [_run_summary_from_row(row) for row in rows]


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

    summary = _run_summary_from_row(run)
    return RunDetail(
        **summary.model_dump(),
        pending_updates=[_pending_update_from_row(row) for row in pending],
        events=[_event_from_row(row) for row in events],
    )


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


def _build_web_plan(settings: WebSettings, payload: PlanRequest) -> DryRunPlan:
    return build_dry_run_plan(
        settings.config,
        line_numbers=payload.line_numbers,
        allow_tag_updates=payload.allow_tag_updates,
        tag_overrides=_tag_overrides_from_payload(payload),
        host_docker_base=settings.host_docker_base,
        environ=settings.command_env,
    )


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
    apply_condition: Condition = request.app.state.web_apply_condition
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    executor: ThreadPoolExecutor = request.app.state.web_apply_executor
    with apply_condition:
        if any(job.status in {"queued", "running"} for job in jobs.values()):
            raise HTTPException(status_code=409, detail="an apply job is already running")
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
            payload.allow_tag_updates,
            tuple(_tag_overrides_from_payload(payload)),
            jobs,
            apply_condition,
            job.id,
            wud_lock,
        )
        return response


def _active_apply_job_exists(request: Request) -> bool:
    apply_lock: Lock = request.app.state.web_apply_lock
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    with apply_lock:
        return any(job.status in {"queued", "running"} for job in jobs.values())


def _require_apply_job(job_id: str, request: Request) -> WebApplyJob:
    apply_lock: Lock = request.app.state.web_apply_lock
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    with apply_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="apply job not found")
        return job


def _apply_job_stream(request: Request, job_id: str) -> Iterator[str]:
    jobs: dict[str, WebApplyJob] = request.app.state.web_apply_jobs
    apply_condition: Condition = request.app.state.web_apply_condition
    last_version = -1

    while True:
        with apply_condition:
            while True:
                job = jobs.get(job_id)
                if job is None:
                    return
                if job.version != last_version:
                    response = _apply_job_response(job)
                    version = job.version
                    terminal = job.status in TERMINAL_APPLY_JOB_STATUSES
                    break
                if not apply_condition.wait(timeout=JOB_STREAM_HEARTBEAT_SECONDS):
                    response = None
                    version = last_version
                    terminal = False
                    break

        if response is None:
            yield ": heartbeat\n\n"
            continue

        yield _sse_job_event(response)
        last_version = version
        if terminal:
            return


def _run_apply_job(
    settings: WebSettings,
    plan_id: str,
    line_numbers: tuple[int, ...],
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    jobs: dict[str, WebApplyJob],
    apply_condition: Condition,
    job_id: str,
    wud_lock: DirectoryLock,
) -> None:
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
            plan_id=plan_id,
        )
        apply_env = dict(settings.command_env or {})
        apply_env["WUD_LOCK_HELD_BY_PARENT"] = "1"
        runner = UpdateFromWudRunner(
            options,
            environ=apply_env,
            command_runner=CommandRunner(env=apply_env),
        )
        status_code = runner.run()
        _update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status="success" if status_code == 0 else "failure",
            run_id=runner.audit_run_id,
            log_file=str(runner.log_file),
            finished_at=utc_timestamp(),
            error="" if status_code == 0 else f"updater exited with status {status_code}",
        )
    except Exception as exc:
        _update_apply_job(
            jobs,
            apply_condition,
            job_id,
            status="failure",
            run_id=None if runner is None else runner.audit_run_id,
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


def _apply_options(
    settings: WebSettings,
    *,
    line_numbers: tuple[int, ...],
    allow_tag_updates: bool,
    tag_overrides: tuple[TagOverride, ...],
    plan_id: str,
) -> UpdaterOptions:
    line_spec = _line_spec(line_numbers)
    metadata_json = json.dumps(
        {
            "plan_id": plan_id,
            "selected_line_numbers": list(line_numbers),
            "source": "webui",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    config = settings.config
    host_docker_base_label = (
        None if settings.host_docker_base is None else str(settings.host_docker_base)
    )
    return UpdaterOptions(
        docker_base=config.docker_base,
        wud_file=config.wud_out_file,
        log_dir=config.log_dir,
        mode=config.update_mode,
        max_wait=config.max_wait,
        dry_run=False,
        assume_yes=True,
        allow_tag_updates=allow_tag_updates,
        tag_overrides=tag_overrides,
        only_lines=line_spec,
        remove_lines_before_run=line_spec,
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
    )


def _sse_job_event(job: ApplyJobResponse) -> str:
    payload = json.dumps(
        jsonable_encoder(job),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: job\ndata: {payload}\n\n"


def _pending_response(settings: WebSettings) -> PendingResponse:
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
        warnings=list(parsed.warnings),
    )


def _plan_response(plan: DryRunPlan, settings: WebSettings) -> PlanResponse:
    payload = asdict(plan)
    payload["can_apply"] = _plan_can_apply(plan, settings)
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


def _run_summary_from_row(row: sqlite3.Row) -> RunSummary:
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
    update_mode, auto_update, snooze_default_seconds = _service_policy_upsert_values(
        payload,
        before_row,
    )
    now = utc_timestamp()
    conn.execute(
        """
        INSERT INTO service_policy (
            service_key,
            update_mode,
            auto_update,
            snooze_default_seconds,
            created_at,
            updated_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, '{}')
        ON CONFLICT(service_key) DO UPDATE SET
            update_mode = excluded.update_mode,
            auto_update = excluded.auto_update,
            snooze_default_seconds = excluded.snooze_default_seconds,
            updated_at = excluded.updated_at
        """,
        (
            service_key,
            update_mode,
            int(auto_update),
            snooze_default_seconds,
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
) -> tuple[str, bool, int | None]:
    if before_row is None:
        return payload.update_mode, payload.auto_update, payload.snooze_default_seconds

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
    return update_mode, auto_update, snooze_default_seconds


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
            detail=f"could not read web auth state: {exc}",
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
            detail=f"could not complete setup: {exc}",
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
            detail=f"could not verify credentials: {exc}",
        ) from exc


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
            detail=f"could not create session: {exc}",
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
    try:
        if not log_path.is_file():
            return RunLogResponse(
                run_id=run_id,
                log_file=raw_log_file,
                exists=False,
                content="",
                truncated=False,
                max_bytes=max_bytes,
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
    return RunLogResponse(
        run_id=run_id,
        log_file=raw_log_file,
        exists=True,
        content=content,
        truncated=truncated,
        max_bytes=max_bytes,
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
