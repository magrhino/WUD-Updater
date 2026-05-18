"""Defaults and environment parsing for the Python updater."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


DEFAULT_UPDATE_MODE = "stop"
DEFAULT_MAX_WAIT = 180
DEFAULT_LOCK_TIMEOUT = 30
DEFAULT_LOG_DIR = "./logs"
VALID_UPDATE_MODES = frozenset({"pause", "stop", "live"})


class ConfigError(ValueError):
    """Raised when environment-derived configuration is invalid."""


@dataclass(frozen=True)
class UpdaterConfig:
    docker_base: Path
    wud_out_file: Path
    log_dir: Path
    update_mode: str
    max_wait: int
    lock_timeout: int
    out_uid: int | None
    out_gid: int | None


def _parse_non_negative_int(name: str, value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer number of seconds") from exc
    if parsed < 0:
        raise ConfigError(f"{name} must be zero or greater")
    return parsed


def _parse_optional_numeric_id(name: str, value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ConfigError(f"{name} must be numeric") from exc
    if parsed < 0:
        raise ConfigError(f"{name} must be zero or greater")
    return parsed


def _env_or_default(env: Mapping[str, str], name: str, default: str) -> str:
    return env.get(name) or default


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    home: str | Path | None = None,
) -> UpdaterConfig:
    """Parse updater defaults from environment variables.

    This intentionally does not read config files or command-line arguments.
    """

    env = os.environ if environ is None else environ
    home_dir = Path(
        home if home is not None else _env_or_default(env, "HOME", str(Path.home()))
    )

    docker_base = Path(_env_or_default(env, "DOCKER_BASE", str(home_dir / "docker")))
    wud_out_file = Path(
        _env_or_default(
            env,
            "WUD_OUT_FILE",
            str(docker_base / "wud" / "out" / "images.todo"),
        )
    )
    log_dir = Path(_env_or_default(env, "WUD_LOG_DIR", DEFAULT_LOG_DIR))

    update_mode = _env_or_default(env, "WUD_UPDATE_MODE", DEFAULT_UPDATE_MODE)
    if update_mode not in VALID_UPDATE_MODES:
        raise ConfigError("WUD_UPDATE_MODE must be pause, stop, or live")

    max_wait = _parse_non_negative_int(
        "WUD_MAX_WAIT",
        env.get("WUD_MAX_WAIT"),
        DEFAULT_MAX_WAIT,
    )
    lock_timeout = _parse_non_negative_int(
        "WUD_LOCK_TIMEOUT",
        env.get("WUD_LOCK_TIMEOUT"),
        DEFAULT_LOCK_TIMEOUT,
    )

    out_uid = _parse_optional_numeric_id("OUT_UID", env.get("OUT_UID"))
    out_gid_value = env.get("OUT_GID") or env.get("OUT_GUID")
    out_gid = _parse_optional_numeric_id("OUT_GID/OUT_GUID", out_gid_value)
    if (out_uid is None) != (out_gid is None):
        raise ConfigError("OUT_UID and OUT_GID/OUT_GUID must be set together")

    return UpdaterConfig(
        docker_base=docker_base,
        wud_out_file=wud_out_file,
        log_dir=log_dir,
        update_mode=update_mode,
        max_wait=max_wait,
        lock_timeout=lock_timeout,
        out_uid=out_uid,
        out_gid=out_gid,
    )
