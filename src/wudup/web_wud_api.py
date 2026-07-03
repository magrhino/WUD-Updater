"""Best-effort WUD API discovery and metadata enrichment."""

from __future__ import annotations

import base64
import json
import math
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import cast

from . import web_wud_config
from .digest_verifier import DOCKER_HUB_REGISTRIES
from .web_wud_config import _auth_required_detail
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_tag,
    normalize_digest,
    strip_digest,
    tag_value_valid,
)
from .release_notes import OCI_SOURCE_LABEL, github_repo_from_source
from .platforms import ImagePlatform, parse_platform, platform_from_parts
from .web_auth import (
    WebConfigError,
    _redact_sensitive_text,
    _redact_unknown_absolute_paths,
)
from .web_models import (
    ReleaseNotificationTrigger,
    WebSettings,
    WudApiClientConfig,
    WudApiAppDiagnostics as WudApiAppDiagnostics,
    WudApiConfigurationDiagnostics,
    WudApiDiagnosticEndpointStatus as WudApiDiagnosticEndpointStatus,
    WudApiLogDiagnostics as WudApiLogDiagnostics,
    WudApiRegistryDiagnostics as WudApiRegistryDiagnostics,
    WudApiState,
    WudApiStatus,
    WudApiStoreDiagnostics as WudApiStoreDiagnostics,
    WudApiWatcherDiagnostics as WudApiWatcherDiagnostics,
    WudContainerMetadata,
)
from .wud_file import WudTarget

DEFAULT_WUD_API_BASE_URL = "http://wud:3000"
WUD_API_BASE_URL_ENV = "WUD_API_BASE_URL"
WUD_API_STARTUP_WAIT_SECONDS_ENV = "WUD_API_STARTUP_WAIT_SECONDS"
WUD_API_AUTH_BEARER_TOKEN_ENV = "WUD_API_AUTH_BEARER_TOKEN"
WUD_API_AUTH_BEARER_TOKEN_FILE_ENV = "WUD_API_AUTH_BEARER_TOKEN_FILE"
WUD_API_AUTH_BASIC_USER_ENV = "WUD_API_AUTH_BASIC_USER"
WUD_API_AUTH_BASIC_PASSWORD_ENV = "WUD_API_AUTH_BASIC_PASSWORD"
WUD_API_AUTH_BASIC_PASSWORD_FILE_ENV = "WUD_API_AUTH_BASIC_PASSWORD_FILE"
WUD_API_HEADERS_FILE_ENV = "WUD_API_HEADERS_FILE"
DEFAULT_WUD_API_STARTUP_WAIT_SECONDS = 0.0
WUD_API_TIMEOUT_SECONDS = 1.0
WUD_API_WATCH_TIMEOUT_SECONDS = 120.0
WUD_API_STARTUP_RETRY_INTERVAL_SECONDS = 0.5
WUD_API_CACHE_TTL_SECONDS = 30.0
WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS = 5.0
WUD_API_USER_AGENT = "wudup-webui-wud-api/1.0"
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

@dataclass(frozen=True)
class WudApiContainer:
    id: str
    name: str
    display_name: str
    status: str
    watcher: str
    image: str
    local_tag: str
    local_digest: str
    remote_tag: str
    remote_digest: str
    update_kind: str
    semver_diff: str
    link: str
    error: str
    labels: Mapping[str, str] = field(default_factory=dict)
    platform: ImagePlatform | None = None

    def response(self) -> WudContainerMetadata:
        platform = self.platform
        return WudContainerMetadata(
            id=self.id,
            name=self.name,
            display_name=self.display_name,
            status=self.status,
            watcher=self.watcher,
            local_tag=self.local_tag,
            local_digest=self.local_digest,
            remote_tag=self.remote_tag,
            remote_digest=self.remote_digest,
            update_kind=self.update_kind,
            semver_diff=self.semver_diff,
            link=self.link,
            error=self.error,
            platform=platform.value if platform is not None else "",
            platform_os=platform.os if platform is not None else "",
            platform_architecture=platform.architecture if platform is not None else "",
            platform_variant=platform.variant if platform is not None else "",
        )


@dataclass(frozen=True)
class WudApiSnapshot:
    status: WudApiStatus
    containers: tuple[WudApiContainer, ...] = ()
    metadata_checked: bool = False
    checked_monotonic: float = 0.0


@dataclass(frozen=True)
class WudApiWatchResult:
    snapshot: WudApiSnapshot
    watched: bool
    requested_count: int = 0
    watched_count: int = 0


WudApiConfigurationSnapshot = web_wud_config.WudApiConfigurationSnapshot
WudApiCacheKey = tuple[str, str]


_cache_lock = Lock()
_snapshot_cache: dict[WudApiCacheKey, WudApiSnapshot] = {}
_configuration_diagnostics_cache: dict[WudApiCacheKey, WudApiConfigurationSnapshot] = {}


def configured_base_url(environ: Mapping[str, str]) -> str:
    return (
        environ.get(WUD_API_BASE_URL_ENV, "").strip() or DEFAULT_WUD_API_BASE_URL
    )


def configured_startup_wait_seconds(environ: Mapping[str, str]) -> float:
    raw_value = environ.get(WUD_API_STARTUP_WAIT_SECONDS_ENV, "").strip()
    if not raw_value:
        return DEFAULT_WUD_API_STARTUP_WAIT_SECONDS
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise WebConfigError(
            f"{WUD_API_STARTUP_WAIT_SECONDS_ENV} must be a number of seconds"
        ) from exc
    if not math.isfinite(value):
        raise WebConfigError(
            f"{WUD_API_STARTUP_WAIT_SECONDS_ENV} must be a finite number of seconds"
        )
    if value < 0:
        raise WebConfigError(
            f"{WUD_API_STARTUP_WAIT_SECONDS_ENV} must be zero or greater"
        )
    return value


def configured_client_config(environ: Mapping[str, str]) -> WudApiClientConfig:
    static_headers = _configured_static_headers(environ)
    auth_header, auth_secrets = _configured_authorization_header(environ)
    if auth_header and _has_header(static_headers, "Authorization"):
        raise WebConfigError(
            f"{WUD_API_HEADERS_FILE_ENV} must not define Authorization when WUD API "
            "bearer or basic auth is configured"
        )

    header_items = static_headers
    if auth_header:
        header_items = (*header_items, ("Authorization", auth_header))
    secret_values = tuple(
        value
        for value in (
            *auth_secrets,
            *(value for _name, value in static_headers),
            auth_header,
        )
        if value
    )
    return WudApiClientConfig(
        header_items=header_items,
        secret_values=secret_values,
        fingerprint=_client_config_fingerprint(header_items),
    )


def format_startup_wait_seconds(value: float) -> str:
    numeric_value = float(value)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return str(numeric_value)


def _configured_authorization_header(
    environ: Mapping[str, str],
) -> tuple[str, tuple[str, ...]]:
    bearer_token = _configured_secret_value(
        environ,
        direct_name=WUD_API_AUTH_BEARER_TOKEN_ENV,
        file_name=WUD_API_AUTH_BEARER_TOKEN_FILE_ENV,
    )
    basic_user = environ.get(WUD_API_AUTH_BASIC_USER_ENV, "").strip()
    basic_password = _configured_secret_value(
        environ,
        direct_name=WUD_API_AUTH_BASIC_PASSWORD_ENV,
        file_name=WUD_API_AUTH_BASIC_PASSWORD_FILE_ENV,
    )
    if bearer_token and (basic_user or basic_password):
        raise WebConfigError("WUD API bearer and basic auth cannot both be configured")
    if bool(basic_user) != bool(basic_password):
        raise WebConfigError(
            f"{WUD_API_AUTH_BASIC_USER_ENV} and "
            f"{WUD_API_AUTH_BASIC_PASSWORD_ENV}/"
            f"{WUD_API_AUTH_BASIC_PASSWORD_FILE_ENV} must be set together"
        )
    if bearer_token:
        authorization = f"Bearer {bearer_token}"
        _validate_header_value("Authorization", authorization)
        return authorization, (bearer_token, authorization)
    if basic_user:
        user_password = f"{basic_user}:{basic_password}"
        token = base64.b64encode(user_password.encode("utf-8")).decode("ascii")
        authorization = f"Basic {token}"
        _validate_header_value("Authorization", authorization)
        return authorization, (basic_password, authorization)
    return "", ()


def _configured_secret_value(
    environ: Mapping[str, str],
    *,
    direct_name: str,
    file_name: str,
) -> str:
    direct_value = environ.get(direct_name, "").strip()
    file_value = environ.get(file_name, "").strip()
    if direct_value and file_value:
        raise WebConfigError(f"{direct_name} and {file_name} cannot both be set")
    if direct_value:
        return direct_value
    if not file_value:
        return ""
    return _read_secret_file(file_name, file_value)


def _read_secret_file(name: str, value: str) -> str:
    try:
        secret = Path(value).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WebConfigError(f"{name} could not be read") from exc
    if not secret:
        raise WebConfigError(f"{name} must not be empty")
    return secret


def _configured_static_headers(
    environ: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    path = environ.get(WUD_API_HEADERS_FILE_ENV, "").strip()
    if not path:
        return ()
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WebConfigError(f"{WUD_API_HEADERS_FILE_ENV} could not be read") from exc
    if not raw.strip():
        raise WebConfigError(f"{WUD_API_HEADERS_FILE_ENV} must contain a JSON object")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebConfigError(
            f"{WUD_API_HEADERS_FILE_ENV} must contain a JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise WebConfigError(f"{WUD_API_HEADERS_FILE_ENV} must contain a JSON object")

    headers: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_name, raw_value in payload.items():
        name = str(raw_name).strip()
        _validate_header_name(name)
        normalized = name.lower()
        if normalized in seen:
            raise WebConfigError(
                f"{WUD_API_HEADERS_FILE_ENV} must not define duplicate headers"
            )
        seen.add(normalized)
        if not isinstance(raw_value, str):
            raise WebConfigError(
                f"{WUD_API_HEADERS_FILE_ENV} values must be strings"
            )
        _validate_header_value(name, raw_value)
        headers.append((name, raw_value))
    return tuple(headers)


def _validate_header_name(name: str) -> None:
    if not name or not _HEADER_NAME_RE.fullmatch(name):
        raise WebConfigError(f"{WUD_API_HEADERS_FILE_ENV} contains an invalid header")


def _validate_header_value(name: str, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise WebConfigError(f"WUD API header {name} must not contain newlines")


def _has_header(headers: Sequence[tuple[str, str]], name: str) -> bool:
    normalized = name.lower()
    return any(header_name.lower() == normalized for header_name, _value in headers)


def _client_config_fingerprint(header_items: Sequence[tuple[str, str]]) -> str:
    if not header_items:
        return ""
    # Partition per configured client without deriving a reusable digest from secrets.
    return secrets.token_hex(16)


def startup_probe(settings: WebSettings) -> WudApiSnapshot:
    snapshot = _refresh_snapshot(settings, include_containers=False)
    wait_seconds = max(settings.wud_api_startup_wait_seconds, 0.0)
    if snapshot.status.state != "unavailable" or wait_seconds <= 0:
        return snapshot

    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return snapshot
        time.sleep(min(WUD_API_STARTUP_RETRY_INTERVAL_SECONDS, remaining))
        snapshot = _refresh_snapshot(settings, include_containers=False)
        if snapshot.status.state != "unavailable":
            return snapshot


def get_snapshot(
    settings: WebSettings,
    *,
    include_containers: bool = False,
    force: bool = False,
) -> WudApiSnapshot:
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    cache_key = _cache_key(settings, base_url)
    now = time.monotonic()
    with _cache_lock:
        cached = _snapshot_cache.get(cache_key)
        if (
            not force
            and cached is not None
            and now - cached.checked_monotonic < _snapshot_cache_ttl(cached)
            and (not include_containers or cached.metadata_checked)
        ):
            return cached
    return _refresh_snapshot(settings, include_containers=include_containers)


def get_configuration_diagnostics(
    settings: WebSettings,
    *,
    force: bool = False,
) -> WudApiConfigurationDiagnostics:
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    cache_key = _cache_key(settings, base_url)
    now = time.monotonic()
    with _cache_lock:
        cached = _configuration_diagnostics_cache.get(cache_key)
        if (
            not force
            and cached is not None
            and now - cached.checked_monotonic
            < web_wud_config.configuration_diagnostics_cache_ttl(
                cached,
                cache_ttl=WUD_API_CACHE_TTL_SECONDS,
                degraded_retry_interval=WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS,
            )
        ):
            return cached.diagnostics
    return _refresh_configuration_diagnostics(settings).diagnostics


def _snapshot_cache_ttl(snapshot: WudApiSnapshot) -> float:
    if snapshot.status.state in {"unavailable", "error"}:
        return WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS
    return WUD_API_CACHE_TTL_SECONDS


def _cache_key(settings: WebSettings, base_url: str) -> WudApiCacheKey:
    return (base_url, settings.wud_api_client.fingerprint)


def metadata_by_target(
    settings: WebSettings,
    targets: Sequence[WudTarget],
    *,
    snapshot: WudApiSnapshot | None = None,
) -> dict[int, WudApiContainer]:
    active_snapshot = snapshot or get_snapshot(settings, include_containers=True)
    if not active_snapshot.status.metadata_available:
        return {}
    result: dict[int, WudApiContainer] = {}
    for target in targets:
        match = _match_container(target, active_snapshot.containers)
        if match is not None:
            result[target.line_no] = match
    return result


def watch_all(settings: WebSettings) -> WudApiWatchResult:
    return _watch_paths(settings, ("/api/containers/watch",))


def watch_containers(
    settings: WebSettings,
    container_ids: Sequence[str],
) -> WudApiWatchResult:
    paths = tuple(
        f"/api/containers/{urllib.parse.quote(container_id, safe='')}/watch"
        for container_id in container_ids
    )
    if not paths:
        return WudApiWatchResult(
            snapshot=get_snapshot(settings, include_containers=True, force=True),
            watched=False,
            requested_count=0,
            watched_count=0,
        )
    return _watch_paths(settings, paths)


def metadata_response_by_line(
    metadata: Mapping[int, WudApiContainer],
) -> dict[int, WudContainerMetadata]:
    return {line_no: item.response() for line_no, item in metadata.items()}


def source_resolver_from_metadata(
    metadata: Mapping[int, WudApiContainer],
) -> Callable[[WudTarget], str]:
    def resolve(target: WudTarget) -> str:
        item = metadata.get(target.line_no)
        if item is None:
            return ""
        source_label = item.labels.get(OCI_SOURCE_LABEL, "")
        if github_repo_from_source(source_label):
            return source_label
        if github_repo_from_source(item.link):
            return item.link
        return source_label

    return resolve


def target_tag_resolver_from_metadata(
    metadata: Mapping[int, WudApiContainer],
) -> Callable[[WudTarget], str]:
    def resolve(target: WudTarget) -> str:
        item = metadata.get(target.line_no)
        if item is None or not item.remote_tag or not tag_value_valid(item.remote_tag):
            return ""
        return item.remote_tag

    return resolve


def container_triggers(
    settings: WebSettings,
    container_id: str,
) -> tuple[list[ReleaseNotificationTrigger], str]:
    if not container_id:
        return [], ""
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError as exc:
        return [], _sanitize_detail(settings, f"invalid WUD API base URL: {exc}")
    path = f"/api/containers/{urllib.parse.quote(container_id, safe='')}/triggers"
    try:
        payload = _request_json(
            _join_url(normalized_base_url, path),
            settings.wud_api_client,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return [], _auth_required_detail(
                settings,
                "WUD API trigger metadata requires authentication",
            )
        return [], _sanitize_detail(
            settings,
            f"WUD API trigger metadata returned HTTP {exc.code}",
        )
    except (OSError, ValueError) as exc:
        return [], _sanitize_detail(
            settings,
            f"WUD API trigger metadata is unavailable: {exc}",
        )
    if not isinstance(payload, list):
        return [], "WUD API trigger metadata payload was not a list"
    trigger_payloads = cast(list[object], payload)
    return [
        _parse_trigger(raw)
        for raw in trigger_payloads
        if isinstance(raw, Mapping)
    ], ""


def _refresh_snapshot(
    settings: WebSettings,
    *,
    include_containers: bool,
) -> WudApiSnapshot:
    checked_at = _utc_timestamp()
    checked_monotonic = time.monotonic()
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError as exc:
        snapshot = _snapshot(
            "error",
            available=False,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(settings, f"invalid WUD API base URL: {exc}"),
            checked_monotonic=checked_monotonic,
            metadata_checked=include_containers,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot

    try:
        _request_json(_join_url(normalized_base_url, "/health"), settings.wud_api_client)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            snapshot = _snapshot(
                "auth_required",
                available=True,
                metadata_available=False,
                checked_at=checked_at,
                detail=_auth_required_detail(
                    settings,
                    "WUD API requires authentication",
                ),
                checked_monotonic=checked_monotonic,
                metadata_checked=include_containers,
            )
        else:
            snapshot = _snapshot(
                "unavailable",
                available=False,
                metadata_available=False,
                checked_at=checked_at,
                detail=_sanitize_detail(
                    settings,
                    f"WUD API health check returned HTTP {exc.code}",
                ),
                checked_monotonic=checked_monotonic,
                metadata_checked=include_containers,
            )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot
    except (OSError, ValueError) as exc:
        snapshot = _snapshot(
            "unavailable",
            available=False,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(settings, f"WUD API is unavailable: {exc}"),
            checked_monotonic=checked_monotonic,
            metadata_checked=include_containers,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot

    if not include_containers:
        snapshot = _snapshot(
            "ready",
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail="WUD API is reachable",
            checked_monotonic=checked_monotonic,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot

    try:
        payload = _request_json(
            _join_url(normalized_base_url, "/api/containers"),
            settings.wud_api_client,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            snapshot = _snapshot(
                "auth_required",
                available=True,
                metadata_available=False,
                checked_at=checked_at,
                detail=_auth_required_detail(
                    settings,
                    "WUD API container metadata requires authentication",
                ),
                checked_monotonic=checked_monotonic,
                metadata_checked=True,
            )
        else:
            snapshot = _snapshot(
                "error",
                available=True,
                metadata_available=False,
                checked_at=checked_at,
                detail=_sanitize_detail(
                    settings,
                    f"WUD API container metadata returned HTTP {exc.code}",
                ),
                checked_monotonic=checked_monotonic,
                metadata_checked=True,
            )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot
    except (OSError, ValueError) as exc:
        snapshot = _snapshot(
            "error",
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(
                settings,
                f"WUD API container metadata is unavailable: {exc}",
            ),
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot

    if not isinstance(payload, list):
        snapshot = _snapshot(
            "error",
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail="WUD API container metadata payload was not a list",
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return snapshot

    containers = tuple(
        item
        for item in (_parse_container(raw, settings) for raw in payload)
        if item is not None
    )
    snapshot = _snapshot(
        "ready",
        available=True,
        metadata_available=True,
        checked_at=checked_at,
        detail=f"{len(containers)} WUD update metadata item(s) available",
        checked_monotonic=checked_monotonic,
        metadata_checked=True,
        containers=containers,
    )
    _store_snapshot(_cache_key(settings, base_url), snapshot)
    return snapshot


def _parse_trigger(raw: Mapping[str, object]) -> ReleaseNotificationTrigger:
    trigger_type = _string(raw.get("type") or raw.get("kind"))
    name = _string(raw.get("name"))
    trigger_id = _string(raw.get("id"))
    if not trigger_id:
        if trigger_type and name:
            trigger_id = f"{trigger_type}.{name}"
        else:
            trigger_id = name or trigger_type
    return ReleaseNotificationTrigger(
        id=trigger_id,
        type=trigger_type,
        name=name,
    )


def _refresh_configuration_diagnostics(
    settings: WebSettings,
) -> WudApiConfigurationSnapshot:
    checked_at = _utc_timestamp()
    checked_monotonic = time.monotonic()
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError as exc:
        snapshot = web_wud_config.configuration_diagnostics_for_base_url_error(
            settings,
            error=exc,
            checked_at=checked_at,
            checked_monotonic=checked_monotonic,
            sanitize_detail=_sanitize_detail,
        )
        _store_configuration_diagnostics(_cache_key(settings, base_url), snapshot)
        return snapshot

    snapshot = web_wud_config.refresh_configuration_diagnostics(
        settings,
        normalized_base_url=normalized_base_url,
        checked_at=checked_at,
        checked_monotonic=checked_monotonic,
        request_json=lambda url: _request_json(url, settings.wud_api_client),
        join_url=_join_url,
        sanitize_detail=_sanitize_detail,
    )
    _store_configuration_diagnostics(_cache_key(settings, base_url), snapshot)
    return snapshot


def _watch_paths(
    settings: WebSettings,
    paths: Sequence[str],
) -> WudApiWatchResult:
    checked_at = _utc_timestamp()
    checked_monotonic = time.monotonic()
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError as exc:
        snapshot = _snapshot(
            "error",
            available=False,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(settings, f"invalid WUD API base URL: {exc}"),
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
        _store_snapshot(_cache_key(settings, base_url), snapshot)
        return WudApiWatchResult(
            snapshot=snapshot,
            watched=False,
            requested_count=len(paths),
            watched_count=0,
        )

    preflight = get_snapshot(settings, include_containers=False, force=True)
    if preflight.status.state != "ready":
        return WudApiWatchResult(
            snapshot=preflight,
            watched=False,
            requested_count=len(paths),
            watched_count=0,
        )

    watched_count = 0
    for path in paths:
        try:
            _post_json(
                _join_url(normalized_base_url, path),
                settings.wud_api_client,
                timeout=WUD_API_WATCH_TIMEOUT_SECONDS,
            )
            watched_count += 1
        except urllib.error.HTTPError as exc:
            snapshot = _watch_http_error_snapshot(
                settings,
                base_url=base_url,
                code=exc.code,
                checked_at=_utc_timestamp(),
                checked_monotonic=time.monotonic(),
            )
            return WudApiWatchResult(
                snapshot=snapshot,
                watched=False,
                requested_count=len(paths),
                watched_count=watched_count,
            )
        except (OSError, ValueError) as exc:
            snapshot = _snapshot(
                "error",
                available=True,
                metadata_available=False,
                checked_at=_utc_timestamp(),
                detail=_sanitize_detail(
                    settings,
                    f"WUD API watch request failed: {exc}",
                ),
                checked_monotonic=time.monotonic(),
                metadata_checked=True,
            )
            _store_snapshot(_cache_key(settings, base_url), snapshot)
            return WudApiWatchResult(
                snapshot=snapshot,
                watched=False,
                requested_count=len(paths),
                watched_count=watched_count,
            )

    return WudApiWatchResult(
        snapshot=get_snapshot(settings, include_containers=True, force=True),
        watched=True,
        requested_count=len(paths),
        watched_count=watched_count,
    )


def _watch_http_error_snapshot(
    settings: WebSettings,
    *,
    base_url: str,
    code: int,
    checked_at: str,
    checked_monotonic: float,
) -> WudApiSnapshot:
    if code in {401, 403}:
        snapshot = _snapshot(
            "auth_required",
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail=_auth_required_detail(
                settings,
                "WUD API watch request requires authentication",
            ),
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
    else:
        snapshot = _snapshot(
            "error",
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(
                settings,
                f"WUD API watch request returned HTTP {code}",
            ),
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
    _store_snapshot(_cache_key(settings, base_url), snapshot)
    return snapshot


def _store_configuration_diagnostics(
    cache_key: WudApiCacheKey,
    snapshot: WudApiConfigurationSnapshot,
) -> None:
    with _cache_lock:
        _configuration_diagnostics_cache[cache_key] = snapshot


def _store_snapshot(cache_key: WudApiCacheKey, snapshot: WudApiSnapshot) -> None:
    with _cache_lock:
        _snapshot_cache[cache_key] = snapshot


def _snapshot(
    state: WudApiState,
    *,
    available: bool,
    metadata_available: bool,
    checked_at: str,
    detail: str,
    checked_monotonic: float,
    metadata_checked: bool = False,
    containers: Sequence[WudApiContainer] = (),
) -> WudApiSnapshot:
    return WudApiSnapshot(
        status=WudApiStatus(
            state=state,
            available=available,
            metadata_available=metadata_available,
            last_checked_at=checked_at,
            detail=detail,
        ),
        containers=tuple(containers),
        metadata_checked=metadata_checked,
        checked_monotonic=checked_monotonic,
    )


def _request_json(
    url: str,
    client_config: WudApiClientConfig | None = None,
) -> object:
    return _request_json_with_method(url, method="GET", client_config=client_config)


def _post_json(
    url: str,
    client_config: WudApiClientConfig | None = None,
    *,
    timeout: float = WUD_API_TIMEOUT_SECONDS,
) -> object:
    return _request_json_with_method(
        url,
        method="POST",
        client_config=client_config,
        timeout=timeout,
    )


def _request_json_with_method(
    url: str,
    *,
    method: str,
    client_config: WudApiClientConfig | None = None,
    timeout: float = WUD_API_TIMEOUT_SECONDS,
) -> object:
    request = urllib.request.Request(
        url,
        method=method,
        headers=_request_headers(client_config),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _request_headers(
    client_config: WudApiClientConfig | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": WUD_API_USER_AGENT,
    }
    if client_config is not None:
        headers.update(dict(client_config.header_items))
    return headers


def _normalize_base_url(value: str) -> str:
    stripped = value.strip()
    parsed = urllib.parse.urlsplit(stripped)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("scheme must be http or https")
    if not parsed.netloc:
        raise ValueError("host is required")
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def _parse_container(
    raw: object,
    settings: WebSettings,
) -> WudApiContainer | None:
    if not isinstance(raw, dict) or raw.get("updateAvailable") is not True:
        return None
    image = _object(raw.get("image"))
    result = _object(raw.get("result"))
    update_kind = _object(raw.get("updateKind"))
    image_ref = _image_ref(image)
    if not image_ref:
        return None
    labels = {
        **_string_mapping(image.get("labels")),
        **_string_mapping(raw.get("labels")),
    }
    return WudApiContainer(
        id=_string(raw.get("id")),
        name=_string(raw.get("name")),
        display_name=_string(raw.get("displayName")),
        status=_string(raw.get("status")),
        watcher=_string(raw.get("watcher")),
        image=image_ref,
        local_tag=_path_string(image, "tag", "value"),
        local_digest=_digest_from_value(_path_string(image, "digest", "value")),
        remote_tag=_remote_tag(result, update_kind),
        remote_digest=_remote_digest(result, update_kind),
        update_kind=_string(update_kind.get("kind")),
        semver_diff=_string(update_kind.get("semverDiff")),
        link=_string(result.get("link") or raw.get("link")),
        error=_sanitize_detail(settings, _error_message(raw.get("error"))),
        labels=labels,
        platform=_container_platform(raw, image),
    )


def _container_platform(
    raw: Mapping[str, object],
    image: Mapping[str, object],
) -> ImagePlatform | None:
    for value in (
        _string(image.get("platform")),
        _string(raw.get("platform")),
        _string(raw.get("image_platform")),
        _string(raw.get("imagePlatform")),
    ):
        platform = parse_platform(value) if value else None
        if platform is not None:
            return platform

    for source in (
        _object(image.get("platform")),
        _object(raw.get("platform")),
        image,
        raw,
        _object(raw.get("container_json")),
        _object(raw.get("containerJson")),
    ):
        platform = platform_from_parts(
            _string(source.get("os") or source.get("image_os") or source.get("imageOs")),
            _string(
                source.get("architecture")
                or source.get("arch")
                or source.get("image_architecture")
                or source.get("imageArchitecture")
            ),
            _string(source.get("variant") or source.get("image_variant") or source.get("imageVariant")),
        )
        if platform is not None:
            return platform
    return None


def _match_container(
    target: WudTarget,
    containers: Sequence[WudApiContainer],
) -> WudApiContainer | None:
    for container in containers:
        if _container_matches_target(container, target):
            return container
    return None


def _container_matches_target(container: WudApiContainer, target: WudTarget) -> bool:
    if target.first in {container.name, container.display_name, container.id}:
        return True
    if not container.image:
        return False
    allow_repo = target.allow_repo or not image_has_tag(target.first)
    return image_matches_resolved_target(container.image, target.first, allow_repo)


def _image_ref(image: Mapping[str, object]) -> str:
    name = _string(image.get("name"))
    tag = _path_string(image, "tag", "value")
    if not name:
        return ""
    registry = _registry_host(_path_string(image, "registry", "url"))
    if registry and not _image_has_registry(name):
        name = f"{registry}/{name}"
    if tag and not image_has_tag(name):
        return f"{name}:{tag}"
    return name


def _registry_host(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value if "://" in value else f"//{value}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).split("@")[-1].lower()
    return "" if host in DOCKER_HUB_REGISTRIES else host


def _image_has_registry(image: str) -> bool:
    left, sep, _rest = strip_digest(image).partition("/")
    return bool(sep and ("." in left or ":" in left or left == "localhost"))


def _remote_tag(
    result: Mapping[str, object],
    update_kind: Mapping[str, object],
) -> str:
    result_tag = _string(result.get("tag"))
    if tag_value_valid(result_tag):
        return result_tag
    if _string(update_kind.get("kind")) != "tag":
        return ""
    return _tag_from_remote_value(_string(update_kind.get("remoteValue")))


def _tag_from_remote_value(value: str) -> str:
    if not value:
        return ""
    candidate = value.split("@sha256:", 1)[0]
    if image_has_tag(candidate):
        candidate = image_tag(candidate)
    if tag_value_valid(candidate):
        return candidate
    return ""


def _remote_digest(
    result: Mapping[str, object],
    update_kind: Mapping[str, object],
) -> str:
    result_digest = _digest_from_value(_string(result.get("digest")))
    if result_digest:
        return result_digest
    if _string(update_kind.get("kind")) not in {"digest", "tag"}:
        return ""
    return _digest_from_value(_string(update_kind.get("remoteValue")))


def _digest_from_value(value: str) -> str:
    if not value:
        return ""
    if "@sha256:" in value or value.startswith("sha256:"):
        return normalize_digest(value)
    return ""


def _object(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _path_string(value: Mapping[str, object], *parts: str) -> str:
    current: object = value
    for part in parts:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return _string(current)


def _string_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _error_message(value: object) -> str:
    if isinstance(value, dict):
        return _string(value.get("message") or value.get("error"))
    return _string(value)


def _sanitize_detail(settings: WebSettings, value: str) -> str:
    if not value:
        return ""
    sanitized = _redact_sensitive_text(settings, value)
    return _redact_unknown_absolute_paths(sanitized)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
