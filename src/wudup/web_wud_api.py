"""Best-effort WUD API discovery and metadata enrichment."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock

from . import web_wud_config
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_tag,
    normalize_digest,
    tag_value_valid,
)
from .release_notes import OCI_SOURCE_LABEL, github_repo_from_source
from .web_auth import (
    WebConfigError,
    _redact_sensitive_text,
    _redact_unknown_absolute_paths,
)
from .web_models import (
    WebSettings,
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
DEFAULT_WUD_API_STARTUP_WAIT_SECONDS = 0.0
WUD_API_TIMEOUT_SECONDS = 1.0
WUD_API_STARTUP_RETRY_INTERVAL_SECONDS = 0.5
WUD_API_CACHE_TTL_SECONDS = 30.0
WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS = 5.0
WUD_API_USER_AGENT = "wudup-webui-wud-api/1.0"
WUD_API_STATE_READY: WudApiState = "ready"
WUD_API_STATE_UNAVAILABLE: WudApiState = "unavailable"
WUD_API_STATE_AUTH_REQUIRED: WudApiState = "auth_required"
WUD_API_STATE_ERROR: WudApiState = "error"
WUD_API_DEGRADED_STATES = frozenset(
    {WUD_API_STATE_UNAVAILABLE, WUD_API_STATE_ERROR}
)


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

    def response(self) -> WudContainerMetadata:
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
        )


@dataclass(frozen=True)
class WudApiSnapshot:
    status: WudApiStatus
    containers: tuple[WudApiContainer, ...] = ()
    metadata_checked: bool = False
    checked_monotonic: float = 0.0


WudApiConfigurationSnapshot = web_wud_config.WudApiConfigurationSnapshot


_cache_lock = Lock()
_snapshot_cache: dict[str, WudApiSnapshot] = {}
_configuration_diagnostics_cache: dict[str, WudApiConfigurationSnapshot] = {}


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


def format_startup_wait_seconds(value: float) -> str:
    numeric_value = float(value)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return str(numeric_value)


def startup_probe(settings: WebSettings) -> WudApiSnapshot:
    snapshot = _refresh_snapshot(settings, include_containers=False)
    wait_seconds = max(settings.wud_api_startup_wait_seconds, 0.0)
    if snapshot.status.state != WUD_API_STATE_UNAVAILABLE or wait_seconds <= 0:
        return snapshot

    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return snapshot
        time.sleep(min(WUD_API_STARTUP_RETRY_INTERVAL_SECONDS, remaining))
        snapshot = _refresh_snapshot(settings, include_containers=False)
        if snapshot.status.state != WUD_API_STATE_UNAVAILABLE:
            return snapshot


def get_snapshot(
    settings: WebSettings,
    *,
    include_containers: bool = False,
    force: bool = False,
) -> WudApiSnapshot:
    base_url = settings.wud_api_base_url or DEFAULT_WUD_API_BASE_URL
    now = time.monotonic()
    with _cache_lock:
        cached = _snapshot_cache.get(base_url)
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
    now = time.monotonic()
    with _cache_lock:
        cached = _configuration_diagnostics_cache.get(base_url)
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
    if snapshot.status.state in WUD_API_DEGRADED_STATES:
        return WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS
    return WUD_API_CACHE_TTL_SECONDS


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
            WUD_API_STATE_ERROR,
            available=False,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(settings, f"invalid WUD API base URL: {exc}"),
            checked_monotonic=checked_monotonic,
            metadata_checked=include_containers,
        )
        _store_snapshot(base_url, snapshot)
        return snapshot

    try:
        _request_json(_join_url(normalized_base_url, "/health"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            snapshot = _snapshot(
                WUD_API_STATE_AUTH_REQUIRED,
                available=True,
                metadata_available=False,
                checked_at=checked_at,
                detail="WUD API requires authentication",
                checked_monotonic=checked_monotonic,
                metadata_checked=include_containers,
            )
        else:
            snapshot = _snapshot(
                WUD_API_STATE_UNAVAILABLE,
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
        _store_snapshot(base_url, snapshot)
        return snapshot
    except (OSError, ValueError) as exc:
        snapshot = _snapshot(
            WUD_API_STATE_UNAVAILABLE,
            available=False,
            metadata_available=False,
            checked_at=checked_at,
            detail=_sanitize_detail(settings, f"WUD API is unavailable: {exc}"),
            checked_monotonic=checked_monotonic,
            metadata_checked=include_containers,
        )
        _store_snapshot(base_url, snapshot)
        return snapshot

    if not include_containers:
        snapshot = _snapshot(
            WUD_API_STATE_READY,
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail="WUD API is reachable",
            checked_monotonic=checked_monotonic,
        )
        _store_snapshot(base_url, snapshot)
        return snapshot

    try:
        payload = _request_json(_join_url(normalized_base_url, "/api/containers"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            snapshot = _snapshot(
                WUD_API_STATE_AUTH_REQUIRED,
                available=True,
                metadata_available=False,
                checked_at=checked_at,
                detail="WUD API container metadata requires authentication",
                checked_monotonic=checked_monotonic,
                metadata_checked=True,
            )
        else:
            snapshot = _snapshot(
                WUD_API_STATE_ERROR,
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
        _store_snapshot(base_url, snapshot)
        return snapshot
    except (OSError, ValueError) as exc:
        snapshot = _snapshot(
            WUD_API_STATE_ERROR,
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
        _store_snapshot(base_url, snapshot)
        return snapshot

    if not isinstance(payload, list):
        snapshot = _snapshot(
            WUD_API_STATE_ERROR,
            available=True,
            metadata_available=False,
            checked_at=checked_at,
            detail="WUD API container metadata payload was not a list",
            checked_monotonic=checked_monotonic,
            metadata_checked=True,
        )
        _store_snapshot(base_url, snapshot)
        return snapshot

    containers = tuple(
        item
        for item in (_parse_container(raw, settings) for raw in payload)
        if item is not None
    )
    snapshot = _snapshot(
        WUD_API_STATE_READY,
        available=True,
        metadata_available=True,
        checked_at=checked_at,
        detail=f"{len(containers)} WUD update metadata item(s) available",
        checked_monotonic=checked_monotonic,
        metadata_checked=True,
        containers=containers,
    )
    _store_snapshot(base_url, snapshot)
    return snapshot


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
        _store_configuration_diagnostics(base_url, snapshot)
        return snapshot

    snapshot = web_wud_config.refresh_configuration_diagnostics(
        settings,
        normalized_base_url=normalized_base_url,
        checked_at=checked_at,
        checked_monotonic=checked_monotonic,
        request_json=_request_json,
        join_url=_join_url,
        sanitize_detail=_sanitize_detail,
    )
    _store_configuration_diagnostics(base_url, snapshot)
    return snapshot


def _store_configuration_diagnostics(
    base_url: str,
    snapshot: WudApiConfigurationSnapshot,
) -> None:
    with _cache_lock:
        _configuration_diagnostics_cache[base_url] = snapshot


def _store_snapshot(base_url: str, snapshot: WudApiSnapshot) -> None:
    with _cache_lock:
        _snapshot_cache[base_url] = snapshot


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


def _request_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": WUD_API_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=WUD_API_TIMEOUT_SECONDS) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


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
    )


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
    if tag and not image_has_tag(name):
        return f"{name}:{tag}"
    return name


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
    if _string(update_kind.get("kind")) != "digest":
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
