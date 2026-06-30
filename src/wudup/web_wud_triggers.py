"""Service-to-service WUD trigger route handlers."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from fastapi import Header, HTTPException, Request

from . import web_pending_sources, web_release_notifications
from .images import image_has_tag, image_matches_resolved_target
from .web_auth import _settings
from .web_models import (
    ReleaseNotificationPreviewRequest,
    ReleaseNotificationSendRequest,
    WebSettings,
    WudTriggerUpdateResponse,
)
from .web_settings import (
    effective_release_notification_webhook,
    effective_release_notes_enabled,
)

TRIGGER_TOKEN_ENV = "WUDUP_TRIGGER_TOKEN"
TRIGGER_TOKEN_FILE_ENV = "WUDUP_TRIGGER_TOKEN_FILE"
TRIGGER_ACTOR_TYPE = "wud-trigger"


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

    api_settings = replace(settings, pending_source="api")
    _require_release_notification_sendable(api_settings)
    source = web_pending_sources.resolve_pending_source(
        api_settings,
        include_wud_metadata=True,
        force_api=True,
    )
    if source.degraded or source.wud_snapshot is None or not source.wud_snapshot.status.metadata_available:
        return WudTriggerUpdateResponse(
            ok=False,
            status="skipped",
            reason=source.detail or "WUD API pending source is unavailable",
        )

    line_numbers = _matching_line_numbers(payload, source)
    if not line_numbers:
        return WudTriggerUpdateResponse(
            ok=True,
            status="skipped",
            reason="triggered container is not in current WUD API pending updates",
        )

    preview_payload = ReleaseNotificationPreviewRequest(line_numbers=list(line_numbers))
    preview = web_release_notifications._notification_response(
        api_settings,
        preview_payload,
        sent=False,
    )
    if preview.sendable_count <= 0:
        return WudTriggerUpdateResponse(
            ok=True,
            status="skipped",
            reason="no release-note notifications are available to send",
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


def _require_release_notification_sendable(settings: WebSettings) -> None:
    if not settings.mutations_enabled:
        raise HTTPException(status_code=403, detail="mutations are disabled")
    if not effective_release_notes_enabled(settings):
        raise HTTPException(
            status_code=403,
            detail="release-note notifications are disabled",
        )
    webhook, _source = effective_release_notification_webhook(settings)
    if not webhook:
        raise HTTPException(
            status_code=422,
            detail="Discord release-note webhook is not configured",
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
    matched: list[int] = []
    if payload_ids:
        for line_no, container_ids in (source.container_ids_by_line or {}).items():
            if any(container_id in payload_ids for container_id in container_ids):
                matched.append(line_no)
        return tuple(sorted(set(matched)))

    names = _payload_names(payload)
    image_ref = _payload_image_ref(payload)
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
    return tuple(sorted(set(matched)))


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
