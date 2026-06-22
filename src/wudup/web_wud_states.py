"""Shared WUD API state literals."""

from __future__ import annotations

from .web_models import WudApiState

WUD_API_STATE_READY: WudApiState = "ready"
WUD_API_STATE_UNAVAILABLE: WudApiState = "unavailable"
WUD_API_STATE_AUTH_REQUIRED: WudApiState = "auth_required"
WUD_API_STATE_ERROR: WudApiState = "error"
WUD_API_DEGRADED_STATES: frozenset[WudApiState] = frozenset(
    {WUD_API_STATE_UNAVAILABLE, WUD_API_STATE_ERROR}
)
