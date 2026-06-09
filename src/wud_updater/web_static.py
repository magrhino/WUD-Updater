"""WebUI static SPA discovery and mounting helpers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .web_models import WebSettings


def mount_static_spa_if_present(app: FastAPI, settings: WebSettings) -> None:
    static_dir = settings.static_dir
    if static_dir is None or not static_spa_available(settings):
        return
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="webui")


def static_spa_available(settings: WebSettings) -> bool:
    return (
        settings.static_dir is not None
        and (settings.static_dir / "index.html").is_file()
    )


def resolve_static_dir(configured: str | Path | None) -> Path | None:
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


