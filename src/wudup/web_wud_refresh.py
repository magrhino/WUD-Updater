"""Shared WUD API pending-source refresh helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import web_pending_sources, web_wud_api
from .web_models import WebSettings


@dataclass(frozen=True)
class WudPendingRefresh:
    source: web_pending_sources.PendingSourceResult
    watch_result: web_wud_api.WudApiWatchResult | None = None


def refresh_wud_pending_source(
    settings: WebSettings,
    *,
    include_wud_metadata: bool = True,
    force: bool = False,
    watch_all: bool = False,
    api_source: bool = False,
) -> WudPendingRefresh:
    active_settings = (
        replace(settings, pending_source="api") if api_source else settings
    )
    watch_result = web_wud_api.watch_all(active_settings) if watch_all else None
    source = web_pending_sources.resolve_pending_source(
        active_settings,
        include_wud_metadata=include_wud_metadata,
        force_api=False if watch_all else force,
    )
    return WudPendingRefresh(source=source, watch_result=watch_result)
