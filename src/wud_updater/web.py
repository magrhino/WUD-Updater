"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import sqlite3
import sys
from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import ConfigError, UpdaterConfig, load_config
from .db import DatabaseError, SCHEMA_VERSION, connect_db, init_db, utc_timestamp
from .db import _user_version as db_user_version
from .db import _validate_schema as validate_db_schema
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

    @property
    def auth_required(self) -> bool:
        return not self.dev_no_auth


class PendingItem(BaseModel):
    line_no: int
    raw: str
    image: str
    key: str
    repo: str
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
    if not active_settings.dev_no_auth:
        app.state.web_setup_claim = _prepare_web_auth_state(active_settings)
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,
    )

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


def _pending_response(settings: WebSettings) -> PendingResponse:
    exists, parsed = _parse_pending_file(settings)
    items = [
        PendingItem(
            line_no=target.line_no,
            raw=target.raw,
            image=target.first,
            key=target.key,
            repo=target.repo,
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
