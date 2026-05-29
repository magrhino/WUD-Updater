"""Structured GitHub release-note metadata for the WebUI."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .db import utc_timestamp
from .images import image_repo_ref, image_tag
from .wud_file import WudTarget


SUCCESS_CACHE_TTL_SECONDS = 21_600
ERROR_CACHE_TTL_SECONDS = 900
DEFAULT_GITHUB_TIMEOUT_SECONDS = 6.0
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SEMVER_RE = re.compile(r"\bv?([0-9]+)\.([0-9]+)\.([0-9]+)(?:[._-][0-9A-Za-z]+)?\b")
BREAKING_RE = re.compile(
    r"breaking|migration|incompatible|manual step|major change|"
    r"requires [^ \n]+ [0-9]|deprecated[^.\n]*remov|remove[ds] feature",
    re.IGNORECASE,
)

ReleaseNoteStatus = Literal[
    "cached",
    "ready",
    "missing",
    "unsupported",
    "not_found",
    "error",
]


@dataclass(frozen=True)
class ReleaseNoteLink:
    label: str
    url: str
    kind: str


@dataclass(frozen=True)
class ReleaseNoteInfo:
    line_no: int
    status: ReleaseNoteStatus
    provider: str
    image_repo: str
    upstream_repo: str
    release_tag: str = ""
    title: str = ""
    published_at: str = ""
    breaking: bool = False
    breaking_reasons: list[str] = field(default_factory=list)
    links: list[ReleaseNoteLink] = field(default_factory=list)
    refreshed_at: str = ""
    error: str = ""


@dataclass(frozen=True)
class ReleaseNoteContext:
    line_no: int
    cache_key: str
    provider: str
    image_repo: str
    upstream_repo: str
    current_tag: str
    target_tag: str
    error: str = ""


class GitHubClient:
    """Small GitHub Releases API client using only the standard library."""

    def __init__(
        self,
        *,
        token: str = "",
        timeout: float = DEFAULT_GITHUB_TIMEOUT_SECONDS,
        fetch_json: Callable[[str], object] | None = None,
    ) -> None:
        self.token = token
        self.timeout = timeout
        self._fetch_json = fetch_json

    def get_json(self, url: str) -> object:
        if self._fetch_json is not None:
            return self._fetch_json(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "wud-updater-webui-release-notes/1.0",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"message": "Not Found"}
            raise


def cached_release_notes(
    conn: sqlite3.Connection,
    targets: Iterable[WudTarget],
    environ: Mapping[str, str],
) -> list[ReleaseNoteInfo]:
    """Return cached release-note metadata without touching the network."""

    contexts = release_note_contexts(targets, environ)
    return [_cached_info(conn, context) for context in contexts]


def release_note_placeholders(
    targets: Iterable[WudTarget],
    environ: Mapping[str, str],
) -> list[ReleaseNoteInfo]:
    """Return missing/unsupported metadata without requiring a database."""

    return [_placeholder_info(context) for context in release_note_contexts(targets, environ)]


def refresh_release_notes(
    conn: sqlite3.Connection,
    targets: Iterable[WudTarget],
    environ: Mapping[str, str],
    *,
    client: GitHubClient | None = None,
    now: str | None = None,
) -> list[ReleaseNoteInfo]:
    """Refresh missing or stale release-note metadata and return current rows."""

    active_client = client or GitHubClient(token=environ.get("GITHUB_TOKEN", ""))
    timestamp = now or utc_timestamp()
    infos: list[ReleaseNoteInfo] = []
    for context in release_note_contexts(targets, environ):
        cached = _cached_info(conn, context)
        if context.provider == "unsupported":
            infos.append(cached)
            continue
        if cached.status != "missing" and not _cache_stale(cached, timestamp):
            infos.append(cached)
            continue
        try:
            info = _fetch_release_note(context, active_client, timestamp)
        except Exception as exc:  # noqa: BLE001 - surfaced as structured metadata.
            info = ReleaseNoteInfo(
                line_no=context.line_no,
                status="error",
                provider=context.provider,
                image_repo=context.image_repo,
                upstream_repo=context.upstream_repo,
                refreshed_at=timestamp,
                error=str(exc),
            )
        _upsert_cache(conn, context, info, timestamp)
        infos.append(info)
    return infos


def release_note_contexts(
    targets: Iterable[WudTarget],
    environ: Mapping[str, str],
) -> list[ReleaseNoteContext]:
    upstreams = _load_upstream_map(environ)
    contexts: list[ReleaseNoteContext] = []
    for target in targets:
        current_tag = image_tag(target.first)
        target_tag = target.desired_tag
        lsio_repo = _lsio_repo(target.repo)
        if lsio_repo:
            upstream_repo = upstreams.get(lsio_repo, "")
            if not upstream_repo:
                contexts.append(
                    _context(
                        target,
                        provider="unsupported",
                        image_repo=lsio_repo,
                        upstream_repo="",
                        current_tag=current_tag,
                        target_tag=target_tag,
                        error=f"missing LSIO upstream mapping for {lsio_repo}",
                    )
                )
                continue
            contexts.append(
                _context(
                    target,
                    provider="lsio",
                    image_repo=lsio_repo,
                    upstream_repo=upstream_repo,
                    current_tag=current_tag,
                    target_tag=target_tag,
                )
            )
            continue

        ghcr_repo = _ghcr_repo(target.first)
        if ghcr_repo:
            contexts.append(
                _context(
                    target,
                    provider="github",
                    image_repo=ghcr_repo,
                    upstream_repo=ghcr_repo,
                    current_tag=current_tag,
                    target_tag=target_tag,
                )
            )
            continue

        contexts.append(
            _context(
                target,
                provider="unsupported",
                image_repo=image_repo_ref(target.first),
                upstream_repo="",
                current_tag=current_tag,
                target_tag=target_tag,
                error="no supported GitHub release source found",
            )
        )
    return contexts


def detect_breaking(body: str, current_tag: str, release_tag: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if BREAKING_RE.search(body):
        reasons.append("Release notes mention a migration, incompatibility, or removal.")
    current_major = _semver_major(current_tag)
    release_major = _semver_major(release_tag)
    if current_major is not None and release_major is not None:
        if release_major > current_major:
            reasons.append(
                f"Major version changes from {current_major} to {release_major}."
            )
    return bool(reasons), reasons


def _context(
    target: WudTarget,
    *,
    provider: str,
    image_repo: str,
    upstream_repo: str,
    current_tag: str,
    target_tag: str,
    error: str = "",
) -> ReleaseNoteContext:
    key_payload = {
        "provider": provider,
        "image_repo": image_repo,
        "upstream_repo": upstream_repo,
        "current_tag": current_tag,
        "target_tag": target_tag,
    }
    cache_key = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ReleaseNoteContext(
        line_no=target.line_no,
        cache_key=cache_key,
        provider=provider,
        image_repo=image_repo,
        upstream_repo=upstream_repo,
        current_tag=current_tag,
        target_tag=target_tag,
        error=error,
    )


def _cached_info(conn: sqlite3.Connection, context: ReleaseNoteContext) -> ReleaseNoteInfo:
    if context.provider == "unsupported":
        return _placeholder_info(context)
    row = conn.execute(
        """
        SELECT *
        FROM release_note_cache
        WHERE cache_key = ?
        """,
        (context.cache_key,),
    ).fetchone()
    if row is None:
        return _placeholder_info(context)
    return _row_to_info(row, line_no=context.line_no)


def _placeholder_info(context: ReleaseNoteContext) -> ReleaseNoteInfo:
    if context.provider == "unsupported":
        return ReleaseNoteInfo(
            line_no=context.line_no,
            status="unsupported",
            provider=context.provider,
            image_repo=context.image_repo,
            upstream_repo=context.upstream_repo,
            error=context.error,
        )
    return ReleaseNoteInfo(
        line_no=context.line_no,
        status="missing",
        provider=context.provider,
        image_repo=context.image_repo,
        upstream_repo=context.upstream_repo,
    )


def _row_to_info(row: sqlite3.Row, *, line_no: int) -> ReleaseNoteInfo:
    return ReleaseNoteInfo(
        line_no=line_no,
        status=str(row["status"]),  # type: ignore[arg-type]
        provider=str(row["provider"]),
        image_repo=str(row["image_repo"]),
        upstream_repo=str(row["upstream_repo"]),
        release_tag=str(row["release_tag"]),
        title=str(row["title"]),
        published_at=str(row["published_at"]),
        breaking=bool(row["breaking"]),
        breaking_reasons=_json_list(str(row["breaking_reasons_json"])),
        links=[
            ReleaseNoteLink(
                label=str(item.get("label", "")),
                url=str(item.get("url", "")),
                kind=str(item.get("kind", "")),
            )
            for item in _json_object_list(str(row["links_json"]))
        ],
        refreshed_at=str(row["updated_at"]),
        error=str(row["error"]),
    )


def _upsert_cache(
    conn: sqlite3.Connection,
    context: ReleaseNoteContext,
    info: ReleaseNoteInfo,
    timestamp: str,
) -> None:
    links_json = json.dumps([asdict(link) for link in info.links], sort_keys=True)
    reasons_json = json.dumps(info.breaking_reasons, sort_keys=True)
    metadata_json = json.dumps({"line_no": context.line_no}, sort_keys=True)
    with conn:
        conn.execute(
            """
            INSERT INTO release_note_cache (
                cache_key,
                provider,
                image_repo,
                upstream_repo,
                current_tag,
                target_tag,
                status,
                release_tag,
                title,
                published_at,
                breaking,
                breaking_reasons_json,
                links_json,
                error,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                provider = excluded.provider,
                image_repo = excluded.image_repo,
                upstream_repo = excluded.upstream_repo,
                current_tag = excluded.current_tag,
                target_tag = excluded.target_tag,
                status = excluded.status,
                release_tag = excluded.release_tag,
                title = excluded.title,
                published_at = excluded.published_at,
                breaking = excluded.breaking,
                breaking_reasons_json = excluded.breaking_reasons_json,
                links_json = excluded.links_json,
                error = excluded.error,
                updated_at = excluded.updated_at,
                metadata_json = excluded.metadata_json
            """,
            (
                context.cache_key,
                context.provider,
                context.image_repo,
                context.upstream_repo,
                context.current_tag,
                context.target_tag,
                info.status,
                info.release_tag,
                info.title,
                info.published_at,
                1 if info.breaking else 0,
                reasons_json,
                links_json,
                info.error,
                timestamp,
                timestamp,
                metadata_json,
            ),
        )


def _cache_stale(info: ReleaseNoteInfo, now: str) -> bool:
    if not info.refreshed_at:
        return True
    try:
        updated = datetime.fromisoformat(info.refreshed_at)
        current = datetime.fromisoformat(now)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    ttl = ERROR_CACHE_TTL_SECONDS if info.status == "error" else SUCCESS_CACHE_TTL_SECONDS
    return (current - updated).total_seconds() >= ttl


def _fetch_release_note(
    context: ReleaseNoteContext,
    client: GitHubClient,
    timestamp: str,
) -> ReleaseNoteInfo:
    if context.provider == "lsio":
        return _fetch_lsio_release_note(context, client, timestamp)
    return _fetch_github_release_note(context, client, timestamp)


def _fetch_github_release_note(
    context: ReleaseNoteContext,
    client: GitHubClient,
    timestamp: str,
) -> ReleaseNoteInfo:
    release = _fetch_release(client, context.upstream_repo, context.target_tag)
    if release is None:
        project_url = _project_url(client, context.upstream_repo)
        return ReleaseNoteInfo(
            line_no=context.line_no,
            status="not_found",
            provider=context.provider,
            image_repo=context.image_repo,
            upstream_repo=context.upstream_repo,
            release_tag=context.target_tag,
            title=f"{context.upstream_repo} releases",
            links=[ReleaseNoteLink("GitHub project", project_url, "github_project")],
            refreshed_at=timestamp,
        )
    body = str(release.get("body") or "")
    release_tag = str(release.get("tag_name") or "")
    breaking, reasons = detect_breaking(body, context.current_tag, release_tag)
    return ReleaseNoteInfo(
        line_no=context.line_no,
        status="ready",
        provider=context.provider,
        image_repo=context.image_repo,
        upstream_repo=context.upstream_repo,
        release_tag=release_tag,
        title=str(release.get("name") or release_tag),
        published_at=str(release.get("published_at") or release.get("created_at") or ""),
        breaking=breaking,
        breaking_reasons=reasons,
        links=[
            ReleaseNoteLink(
                "GitHub release",
                str(release.get("html_url") or _github_url(context.upstream_repo)),
                "github_release",
            )
        ],
        refreshed_at=timestamp,
    )


def _fetch_lsio_release_note(
    context: ReleaseNoteContext,
    client: GitHubClient,
    timestamp: str,
) -> ReleaseNoteInfo:
    lsio_release = _fetch_latest(client, context.image_repo)
    if lsio_release is None:
        return ReleaseNoteInfo(
            line_no=context.line_no,
            status="error",
            provider=context.provider,
            image_repo=context.image_repo,
            upstream_repo=context.upstream_repo,
            refreshed_at=timestamp,
            error=f"LSIO release not found for {context.image_repo}",
        )
    lsio_body = str(lsio_release.get("body") or "")
    lsio_tag = str(lsio_release.get("tag_name") or "")
    upstream_version = context.target_tag or _lsio_upstream_version(lsio_body, lsio_tag)
    upstream_release = _fetch_release(client, context.upstream_repo, upstream_version)
    links = [
        ReleaseNoteLink(
            "LSIO release",
            str(lsio_release.get("html_url") or _github_url(context.image_repo)),
            "lsio_release",
        )
    ]
    if upstream_release is None:
        links.append(
            ReleaseNoteLink(
                "Upstream project",
                _project_url(client, context.upstream_repo),
                "github_project",
            )
        )
        return ReleaseNoteInfo(
            line_no=context.line_no,
            status="not_found",
            provider=context.provider,
            image_repo=context.image_repo,
            upstream_repo=context.upstream_repo,
            release_tag=upstream_version,
            title=f"{context.image_repo} -> {context.upstream_repo}",
            links=links,
            refreshed_at=timestamp,
        )
    body = str(upstream_release.get("body") or "")
    release_tag = str(upstream_release.get("tag_name") or "")
    breaking, reasons = detect_breaking(
        "\n".join([body, lsio_body]),
        context.current_tag,
        release_tag,
    )
    links.append(
        ReleaseNoteLink(
            "Upstream release",
            str(upstream_release.get("html_url") or _github_url(context.upstream_repo)),
            "github_release",
        )
    )
    return ReleaseNoteInfo(
        line_no=context.line_no,
        status="ready",
        provider=context.provider,
        image_repo=context.image_repo,
        upstream_repo=context.upstream_repo,
        release_tag=release_tag,
        title=str(upstream_release.get("name") or release_tag),
        published_at=str(
            upstream_release.get("published_at")
            or upstream_release.get("created_at")
            or ""
        ),
        breaking=breaking,
        breaking_reasons=reasons,
        links=links,
        refreshed_at=timestamp,
    )


def _fetch_release(
    client: GitHubClient,
    repo: str,
    tag: str,
) -> dict[str, Any] | None:
    if tag:
        candidates = [tag] if tag[:1].lower() == "v" else [f"v{tag}", tag]
        for candidate in candidates:
            release = _object_or_none(
                client.get_json(f"https://api.github.com/repos/{repo}/releases/tags/{candidate}")
            )
            if release is not None:
                return release
        return None
    return _fetch_latest(client, repo)


def _fetch_latest(client: GitHubClient, repo: str) -> dict[str, Any] | None:
    return _object_or_none(
        client.get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    )


def _project_url(client: GitHubClient, repo: str) -> str:
    repo_json = _object_or_none(client.get_json(f"https://api.github.com/repos/{repo}"))
    if repo_json is not None:
        html_url = str(repo_json.get("html_url") or "")
        if html_url.startswith("https://github.com/"):
            return html_url
    return _github_url(repo)


def _object_or_none(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if str(value.get("message") or "") == "Not Found":
        return None
    return value


def _lsio_upstream_version(body: str, lsio_tag: str) -> str:
    remote = _extract_block(body, "remote changes:")
    match = re.search(r"[Uu]pdat(?:e|ing)[^0-9vV]*(v?[0-9][0-9A-Za-z._-]*)", remote)
    if match:
        found = _first_semver(match.group(1))
        if found:
            return found
    return _first_semver(lsio_tag)


def _extract_block(body: str, header: str) -> str:
    target = header.lower()
    lines = body.replace("\r", "").splitlines()
    collecting = False
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_header = bool(re.fullmatch(r"[A-Za-z0-9 _-]+:", stripped))
        if stripped.lower() == target:
            collecting = True
            result.append(line)
            continue
        if collecting and is_header:
            break
        if collecting:
            result.append(line)
    return "\n".join(result)


def _load_upstream_map(environ: Mapping[str, str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in _upstream_map_paths(environ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if _github_repo_valid(key) and _github_repo_valid(value):
                mapping[key] = value
        if mapping:
            return mapping
    return mapping


def _upstream_map_paths(environ: Mapping[str, str]) -> list[Path]:
    paths: list[Path] = []
    for name in ("WUD_WEB_UPSTREAM_MAP", "UPSTREAM_MAP"):
        value = environ.get(name, "")
        if value:
            paths.append(Path(value))
    scripts_dir = environ.get("WUD_SCRIPTS_DIR", "/managed-wud")
    if scripts_dir:
        paths.append(Path(scripts_dir) / "upstreams.txt")
    app_dir = environ.get("WUD_APP_DIR", "/app")
    if app_dir:
        paths.append(Path(app_dir) / "wud" / "upstreams.txt")
    paths.append(Path("/app/wud/upstreams.txt"))
    paths.append(Path(__file__).resolve().parents[2] / "wud" / "upstreams.txt")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _lsio_repo(repo: str) -> str:
    if not repo.startswith("linuxserver/"):
        return ""
    name = repo.split("/", 1)[1]
    if not name:
        return ""
    if name.startswith("docker-"):
        return f"linuxserver/{name}"
    return f"linuxserver/docker-{name}"


def _ghcr_repo(image: str) -> str:
    repo = image_repo_ref(image)
    if not repo.startswith("ghcr.io/"):
        return ""
    candidate = repo.removeprefix("ghcr.io/")
    return candidate if _github_repo_valid(candidate) else ""


def _github_repo_valid(value: str) -> bool:
    return bool(GITHUB_REPO_RE.fullmatch(value))


def _github_url(repo: str) -> str:
    return f"https://github.com/{repo}"


def _first_semver(value: str) -> str:
    match = SEMVER_RE.search(value)
    return match.group(0) if match else ""


def _semver_major(value: str) -> int | None:
    match = SEMVER_RE.search(value)
    if not match:
        return None
    return int(match.group(1))


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _json_object_list(raw: str) -> list[dict[str, object]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
