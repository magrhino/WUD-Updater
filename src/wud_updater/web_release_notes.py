"""WebUI release-note route handlers."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException, Request

from .command import CommandError, CommandRunner
from .db import DatabaseError, init_db, open_db
from . import web_wud_api
from .docker_cli import ContainerImage, DockerCli
from .images import image_matches_resolved_target
from .release_notes import (
    OCI_SOURCE_LABEL,
    ReleaseNoteSourceResolver,
    cached_release_notes,
    github_repo_from_ghcr_image,
    github_repo_from_source,
    refresh_release_notes,
    release_note_placeholders,
)
from .web_auth import (
    _redact_sensitive_text,
    _redact_unknown_absolute_paths,
    _safe_exception_detail,
    _settings,
)
from .web_database import (
    ReadOnlyDatabaseMissing,
    connect_readonly_db as _connect_readonly_db,
)
from .web_models import ReleaseNoteInfo, ReleaseNotesResponse, WebSettings
from .web_pending import parse_pending_file
from .wud_file import WudTarget


LOGGER = logging.getLogger(__name__)
DOCKER_STDERR_LOG_LIMIT = 500


def api_release_notes(request: Request) -> ReleaseNotesResponse:
    settings = _settings(request)
    wud_snapshot = web_wud_api.get_snapshot(settings, include_containers=True)
    exists, parsed = parse_pending_file(settings)
    warnings = list(parsed.warnings)
    wud_metadata = web_wud_api.metadata_by_target(
        settings,
        parsed.targets,
        snapshot=wud_snapshot,
    )
    if not exists:
        return ReleaseNotesResponse(
            source_file=str(settings.config.wud_out_file),
            count=0,
            items=[],
            wud_api=wud_snapshot.status,
            warnings=warnings,
        )
    source_resolver = release_note_source_resolver(settings, wud_metadata=wud_metadata)
    target_tag_resolver = web_wud_api.target_tag_resolver_from_metadata(wud_metadata)
    try:
        with closing(_connect_readonly_db(settings)) as conn:
            items = cached_release_notes(
                conn,
                parsed.targets,
                settings.command_env or {},
                source_resolver=source_resolver,
                target_tag_resolver=target_tag_resolver,
            )
    except ReadOnlyDatabaseMissing:
        items = release_note_placeholders(
            parsed.targets,
            settings.command_env or {},
            source_resolver=source_resolver,
            target_tag_resolver=target_tag_resolver,
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
    return release_notes_response(settings, items, warnings, wud_api=wud_snapshot.status)


def api_refresh_release_notes(request: Request) -> ReleaseNotesResponse:
    settings = _settings(request)
    wud_snapshot = web_wud_api.get_snapshot(settings, include_containers=True)
    exists, parsed = parse_pending_file(settings)
    warnings = list(parsed.warnings)
    wud_metadata = web_wud_api.metadata_by_target(
        settings,
        parsed.targets,
        snapshot=wud_snapshot,
    )
    if not exists:
        return ReleaseNotesResponse(
            source_file=str(settings.config.wud_out_file),
            count=0,
            items=[],
            wud_api=wud_snapshot.status,
            warnings=warnings,
        )
    source_resolver = release_note_source_resolver(settings, wud_metadata=wud_metadata)
    target_tag_resolver = web_wud_api.target_tag_resolver_from_metadata(wud_metadata)
    try:
        with open_db(settings.config.db_path) as conn:
            init_db(conn)
            items = refresh_release_notes(
                conn,
                parsed.targets,
                settings.command_env or {},
                source_resolver=source_resolver,
                target_tag_resolver=target_tag_resolver,
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
    return release_notes_response(settings, items, warnings, wud_api=wud_snapshot.status)


def release_notes_response(
    settings: WebSettings,
    items: list[Any],
    warnings: list[str],
    *,
    wud_api: Any,
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
        wud_api=wud_api,
        warnings=[_redact_sensitive_text(settings, warning) for warning in warnings],
    )


def release_note_source_resolver(
    settings: WebSettings,
    *,
    wud_metadata: dict[int, web_wud_api.WudApiContainer] | None = None,
) -> ReleaseNoteSourceResolver:
    docker = DockerCli(runner=CommandRunner(env=settings.command_env))
    label_cache: dict[str, tuple[str, CommandError | None]] = {}
    container_images: list[ContainerImage] | None = None
    wud_source_resolver = web_wud_api.source_resolver_from_metadata(wud_metadata or {})

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
        wud_source = wud_source_resolver(target)
        if github_repo_from_source(wud_source):
            return wud_source

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
                sanitize_stderr(
                    settings,
                    error.result.stderr.strip() or "<empty>",
                ),
            )
        return value

    return resolve


def sanitize_stderr(settings: WebSettings, value: str) -> str:
    sanitized = _redact_unknown_absolute_paths(_redact_sensitive_text(settings, value))
    if len(sanitized) <= DOCKER_STDERR_LOG_LIMIT:
        return sanitized
    return f"{sanitized[:DOCKER_STDERR_LOG_LIMIT].rstrip()}... [truncated]"


# Compatibility aliases for callers that imported private helpers from web.py.
_release_notes_response = release_notes_response
_release_note_source_resolver = release_note_source_resolver
