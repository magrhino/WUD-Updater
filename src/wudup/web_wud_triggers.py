"""Service-to-service WUD trigger route handlers."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request

from . import web_pending_sources, web_release_notifications
from .images import image_has_tag, image_matches_resolved_target
from .web_auth import _settings
from .web_models import (
    ReleaseNotificationPreviewRequest,
    ReleaseNotificationSendRequest,
    WebSettings,
    WudTriggerUpdateResponse,
)

TRIGGER_TOKEN_ENV = "WUDUP_TRIGGER_TOKEN"
TRIGGER_TOKEN_FILE_ENV = "WUDUP_TRIGGER_TOKEN_FILE"
TRIGGER_ACTOR_TYPE = "wud-trigger"


def configure(app: FastAPI) -> None:
    router = APIRouter(prefix="/api/v1/wud")
    router.add_api_route(
        "/triggers/update",
        api_wud_update_trigger,
        methods=["POST"],
        response_model=WudTriggerUpdateResponse,
    )
    app.include_router(router)


def api_wud_update_trigger(
    payload: dict[str, object],
    request: Request,
    authorization: str | None = Header(default=None),
) -> WudTriggerUpdateResponse:
    settings = _settings(request)
    _require_trigger_token(settings, authorization)
    if not _update_available_true(payload):
        return WudTriggerUpdateResponse(
            ok=True,
            status="skipped",
            reason="updateAvailable is not true",
        )
    return send_wud_update_release_notifications(settings, payload, request=request)


def send_wud_update_release_notifications(
    settings: WebSettings,
    payload: Mapping[str, object],
    *,
    request: Request,
) -> WudTriggerUpdateResponse:
    api_settings: WebSettings = replace(settings, pending_source="api")
    web_release_notifications.require_release_notification_sendable(api_settings)
    source = web_pending_sources.resolve_pending_source(
        api_settings,
        include_wud_metadata=True,
        force_api=True,
    )
    if source.degraded or source.wud_snapshot is None or not source.wud_snapshot.status.metadata_available:
        raise HTTPException(
            status_code=503,
            detail=source.detail or "WUD API pending source is unavailable",
        )

    line_numbers = _matching_line_numbers(payload, source)
    if not line_numbers:
        return WudTriggerUpdateResponse(
            ok=True,
            status="skipped",
            reason="triggered container is not in current WUD API pending updates",
        )

    preview_payload = ReleaseNotificationPreviewRequest(line_numbers=list(line_numbers))
    preview = web_release_notifications.preview_release_notifications(
        api_settings,
        preview_payload,
        sent=False,
    )
    if preview.sendable_count <= 0:
        return WudTriggerUpdateResponse(
            ok=True,
            status="skipped",
            reason=(
                web_release_notifications.NO_RELEASE_NOTIFICATIONS_AVAILABLE_DETAIL
            ),
            line_numbers=list(line_numbers),
            release_notifications=preview,
        )

    sent = web_release_notifications.send_release_notifications(
        api_settings,
        ReleaseNotificationSendRequest(
            line_numbers=list(line_numbers),
            confirmation="send-release-notes",
        ),
        request=request,
        actor_type=TRIGGER_ACTOR_TYPE,
    )
    return WudTriggerUpdateResponse(
        ok=True,
        status="sent",
        line_numbers=list(line_numbers),
        release_notifications=sent,
    )


def _require_trigger_token(settings: WebSettings, authorization: str | None) -> None:
    expected = _configured_trigger_token(settings)
    scheme, separator, token = (authorization or "").partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(token, expected)
    ):
        raise HTTPException(
            status_code=401,
            detail="WUD trigger authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _configured_trigger_token(settings: WebSettings) -> str:
    env = settings.command_env or {}
    direct_value = env.get(TRIGGER_TOKEN_ENV, "").strip()
    file_value = env.get(TRIGGER_TOKEN_FILE_ENV, "").strip()
    if direct_value and file_value:
        raise HTTPException(
            status_code=503,
            detail="WUD trigger token is misconfigured",
        )
    if direct_value:
        return direct_value
    if not file_value:
        raise HTTPException(
            status_code=503,
            detail="WUD trigger token is not configured",
        )
    try:
        token = Path(file_value).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="WUD trigger token file could not be read",
        ) from exc
    if not token:
        raise HTTPException(
            status_code=503,
            detail="WUD trigger token file is empty",
        )
    return token


def _update_available_true(payload: Mapping[str, object]) -> bool:
    for key in ("updateAvailable", "update_available"):
        if key not in payload:
            continue
        value = payload[key]
        if value is True:
            return True
        if value == 1:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        return False
    return False


def _matching_line_numbers(
    payload: Mapping[str, object],
    source: web_pending_sources.PendingSourceResult,
) -> tuple[int, ...]:
    payload_ids = _payload_ids(payload)
    matched = _matching_line_numbers_by_id(payload_ids, source)
    if payload_ids:
        return _line_number_tuple(matched)
    return _line_number_tuple(_matching_line_numbers_by_name_or_image(payload, source))


def _matching_line_numbers_by_id(
    payload_ids: frozenset[str],
    source: web_pending_sources.PendingSourceResult,
) -> tuple[int, ...]:
    matched: list[int] = []
    for line_no, container_ids in (source.container_ids_by_line or {}).items():
        if any(container_id in payload_ids for container_id in container_ids):
            matched.append(line_no)
    return tuple(matched)


def _matching_line_numbers_by_name_or_image(
    payload: Mapping[str, object],
    source: web_pending_sources.PendingSourceResult,
) -> tuple[int, ...]:
    names = _payload_names(payload)
    image_ref = _payload_image_ref(payload)
    matched: list[int] = []
    for line_no, container in (source.metadata_by_line or {}).items():
        if names and any(
            name in {container.id, container.name, container.display_name}
            for name in names
        ):
            matched.append(line_no)
            continue
        if image_ref and (
            container.image == image_ref
            or image_matches_resolved_target(container.image, image_ref, True)
        ):
            matched.append(line_no)
    return tuple(matched)


def _line_number_tuple(line_numbers: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(set(line_numbers)))


def _payload_ids(payload: Mapping[str, object]) -> frozenset[str]:
    container = _object(payload.get("container"))
    return frozenset(
        value
        for value in (
            _string(payload.get("id")),
            _string(payload.get("containerId")),
            _string(payload.get("container_id")),
            _string(container.get("id")),
        )
        if value
    )


def _payload_names(payload: Mapping[str, object]) -> frozenset[str]:
    container = _object(payload.get("container"))
    return frozenset(
        value
        for value in (
            _string(payload.get("name")),
            _string(payload.get("displayName")),
            _string(payload.get("display_name")),
            _string(container.get("name")),
            _string(container.get("displayName")),
            _string(container.get("display_name")),
        )
        if value
    )


def _payload_image_ref(payload: Mapping[str, object]) -> str:
    image = _object(payload.get("image"))
    name = _string(
        image.get("name")
        or payload.get("imageName")
        or payload.get("image_name")
    )
    tag = _string(_object(image.get("tag")).get("value") or image.get("tag"))
    if name and tag and not image_has_tag(name):
        return f"{name}:{tag}"
    return name


def _object(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
