"""Service-to-service WUD trigger route handlers."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from pathlib import Path

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request

from .web_auth import _settings
from .web_models import (
    WebSettings,
    WudTriggerUpdateResponse,
)

TRIGGER_TOKEN_ENV = "WUDUP_TRIGGER_TOKEN"
TRIGGER_TOKEN_FILE_ENV = "WUDUP_TRIGGER_TOKEN_FILE"
TRIGGER_DELIVERY_DISABLED_DETAIL = (
    "trigger-based release notifications are not enabled"
)


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
    return WudTriggerUpdateResponse(
        ok=True,
        status="skipped",
        reason=TRIGGER_DELIVERY_DISABLED_DETAIL,
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
