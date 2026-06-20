"""Canonical and legacy project names used across WUDup."""

from __future__ import annotations

from collections.abc import Mapping

DISPLAY_NAME = "WUDup"
TECHNICAL_NAME = "wudup"
LEGACY_TECHNICAL_NAME = "wud-updater"

REPOSITORY = "magrhino/wudup"
LEGACY_REPOSITORY = "magrhino/WUD-Updater"

IMAGE_REPOSITORY = "ghcr.io/magrhino/wudup"
LEGACY_IMAGE_REPOSITORY = "ghcr.io/magrhino/wud-updater"

CONFIG_DIR_NAME = "wudup"
LEGACY_CONFIG_DIR_NAME = "wud-updater"

DB_FILENAME = "wudup.sqlite"
LEGACY_DB_FILENAME = "wud-updater.sqlite"

DIGEST_PIN_MARKER_PREFIX = "wudup.resolved-tag="
LEGACY_DIGEST_PIN_MARKER_PREFIX = "wud-updater.resolved-tag="


def env_value(
    env: Mapping[str, str],
    canonical: str,
    legacy: str | None = None,
) -> str | None:
    """Return the canonical env value, falling back to a legacy variable."""

    value = env.get(canonical)
    if value:
        return value
    if legacy is None:
        return None
    return env.get(legacy)
