"""Read-only FastAPI WebUI foundation for WUD-Updater."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import ConfigError, UpdaterConfig, load_config
from .db import DatabaseError, SCHEMA_VERSION
from .db import _user_version as db_user_version
from .db import _validate_schema as validate_db_schema
from .wud_file import ParsedWudFile, parse_wud_file


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080
DEFAULT_RUN_LIMIT = 50
DEFAULT_LOG_TAIL_BYTES = 262_144
MAX_LOG_TAIL_BYTES = 1_048_576
SESSION_MAX_AGE_SECONDS = 86_400
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
CSRF_HEADER = "x-wud-csrf-token"
CSRF_COOKIE = "wud_csrf_token"
SESSION_COOKIE = "wud_session"


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
    mutations_enabled: bool
    static_spa_available: bool
    warnings: list[str] = Field(default_factory=list)


class CsrfResponse(BaseModel):
    csrf_token: str


class LoginRequest(BaseModel):
    token: str


class AuthSessionResponse(BaseModel):
    authenticated: bool
    auth_required: bool
    dev_auth_bypass: bool
    mutations_enabled: bool


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

    @app.middleware("http")
    async def csrf_origin_scaffold(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _requires_csrf_origin_check(request):
            error = _csrf_origin_error(request, active_settings)
            if error is not None:
                return error
        return await call_next(request)

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
    return WebSettings(
        config=config,
        auth_token=env.get("WUD_WEB_TOKEN", ""),
        dev_no_auth=_parse_bool(env.get("WUD_WEB_DEV_NO_AUTH"), default=False),
        allowed_origins=_parse_origins(env.get("WUD_WEB_ALLOWED_ORIGINS", "")),
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

    uvicorn.run(create_app(settings), host=host, port=port)
    return 0


async def require_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings = _settings(request)
    if settings.dev_no_auth:
        return
    if not settings.auth_token:
        raise HTTPException(
            status_code=503,
            detail="web auth token is not configured",
        )
    if _bearer_token_valid(settings, authorization):
        return
    if _session_cookie_valid(settings, request.cookies.get(SESSION_COOKIE, "")):
        return
    raise HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def api_auth_csrf(response: Response) -> CsrfResponse:
    csrf_token = secrets.token_urlsafe(32)
    _set_csrf_cookie(response, csrf_token)
    return CsrfResponse(csrf_token=csrf_token)


def api_auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    if settings.dev_no_auth:
        return _auth_session_response(settings, authenticated=True)
    if not settings.auth_token:
        raise HTTPException(
            status_code=503,
            detail="web auth token is not configured",
        )
    if not secrets.compare_digest(payload.token, settings.auth_token):
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _set_session_cookie(response, _make_session_cookie(settings))
    return _auth_session_response(settings, authenticated=True)


def api_auth_logout(
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = _settings(request)
    _clear_session_cookie(response)
    _clear_csrf_cookie(response)
    return _auth_session_response(settings, authenticated=settings.dev_no_auth)


def api_auth_session(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSessionResponse:
    settings = _settings(request)
    authenticated = (
        settings.dev_no_auth
        or _bearer_token_valid(settings, authorization)
        or _session_cookie_valid(settings, request.cookies.get(SESSION_COOKIE, ""))
    )
    return _auth_session_response(settings, authenticated=authenticated)


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
) -> AuthSessionResponse:
    return AuthSessionResponse(
        authenticated=authenticated,
        auth_required=settings.auth_required,
        dev_auth_bypass=settings.dev_no_auth,
        mutations_enabled=settings.mutations_enabled,
    )


def _bearer_token_valid(settings: WebSettings, authorization: str | None) -> bool:
    if not settings.auth_token:
        return False
    scheme, separator, token = (authorization or "").partition(" ")
    return (
        separator == " "
        and scheme.lower() == "bearer"
        and secrets.compare_digest(token, settings.auth_token)
    )


def _make_session_cookie(settings: WebSettings) -> str:
    payload = _b64encode_json(
        {
            "v": 1,
            "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
            "nonce": secrets.token_urlsafe(24),
        }
    )
    signature = _session_signature(settings, payload)
    return f"{payload}.{signature}"


def _session_cookie_valid(settings: WebSettings, value: str) -> bool:
    if not settings.auth_token or "." not in value:
        return False
    payload, signature = value.rsplit(".", 1)
    if not hmac.compare_digest(_session_signature(settings, payload), signature):
        return False
    try:
        decoded = json.loads(_b64decode(payload).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(decoded, dict):
        return False
    if decoded.get("v") != 1:
        return False
    expires_at = decoded.get("exp")
    if not isinstance(expires_at, int):
        return False
    return expires_at >= int(time.time())


def _session_signature(settings: WebSettings, payload: str) -> str:
    digest = hmac.new(
        settings.auth_token.encode("utf-8"),
        payload.encode("ascii"),
        "sha256",
    ).digest()
    return _b64encode(digest)


def _b64encode_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return _b64encode(payload)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
        samesite="strict",
        path="/",
    )


def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")


def _set_session_cookie(response: Response, session: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        path="/",
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


def _origin_allowed(
    request: Request,
    settings: WebSettings,
    origin: str,
) -> bool:
    if origin in settings.allowed_origins:
        return True
    host = request.headers.get("host", "")
    if not host:
        return False
    same_origin = f"{request.url.scheme}://{host}"
    return secrets.compare_digest(origin, same_origin)


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
    if settings.dev_no_auth:
        return
    if not settings.auth_token:
        raise WebConfigError(
            "WUD_WEB_TOKEN must be set unless WUD_WEB_DEV_NO_AUTH=true"
        )


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
        origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()
    )


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
