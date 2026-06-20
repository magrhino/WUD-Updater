"""CLI and environment parsing helpers for the updater."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .config import (
    COMPOSE_IGNORE_PATHS_ENV,
    DEFAULT_DIGEST_PIN_UPDATES,
    DEFAULT_MAX_WAIT,
    DEFAULT_UPDATE_MODE,
    DIGEST_PIN_UPDATES_ENV,
    ConfigError,
    parse_bool_env,
    parse_compose_ignore_paths,
)
from .images import tag_value_valid
from .naming import DB_FILENAME
from .updater_models import TagOverride, UpdaterError, UpdaterOptions


@dataclass(frozen=True)
class _ResolvedDockerPaths:
    docker_base: Path
    wud_file: Path
    log_dir: Path
    db_path: Path
    docker_base_label: str
    wud_file_label: str
    log_dir_label: str


def options_from_namespace(
    args: object, *, environ: Mapping[str, str] | None = None
) -> UpdaterOptions:
    env = os.environ if environ is None else environ
    paths = _resolve_docker_paths(args, env)
    host_docker_base_label = env.get("HOST_DOCKER_BASE") or ""
    host_docker_base = Path(host_docker_base_label) if host_docker_base_label else None
    _validate_host_docker_base_constraints(host_docker_base, paths.docker_base)
    mode, max_wait = _parse_mode_and_wait(args, env)
    tag_overrides = parse_tag_overrides(getattr(args, "tag_override", None) or ())
    allow_tag_updates = bool(getattr(args, "allow_tag_updates", False))
    if tag_overrides and not allow_tag_updates:
        raise UpdaterError("--tag-override requires --allow-tag-updates")
    try:
        compose_ignore_paths = parse_compose_ignore_paths(
            env.get(COMPOSE_IGNORE_PATHS_ENV)
        )
        digest_pin_updates = parse_bool_env(
            DIGEST_PIN_UPDATES_ENV,
            env.get(DIGEST_PIN_UPDATES_ENV),
            default=DEFAULT_DIGEST_PIN_UPDATES,
        )
    except ConfigError as exc:
        raise UpdaterError(str(exc)) from exc
    return UpdaterOptions(
        docker_base=paths.docker_base,
        wud_file=paths.wud_file,
        log_dir=paths.log_dir,
        mode=mode,
        max_wait=max_wait,
        dry_run=bool(getattr(args, "dry_run", False)),
        assume_yes=bool(getattr(args, "yes", False)),
        allow_tag_updates=allow_tag_updates,
        digest_pin_updates=digest_pin_updates,
        no_color=bool(getattr(args, "no_color", False)),
        only_lines=getattr(args, "only_lines", None) or "",
        remove_lines_before_run=getattr(args, "remove_lines_before_run", None) or "",
        tag_overrides=tag_overrides,
        exclude_tag_lines=getattr(args, "exclude_tag_lines", None) or "",
        recreate_excluded_services=bool(
            getattr(args, "recreate_excluded_services", False)
        ),
        compose_ignore_paths=compose_ignore_paths,
        db_path=paths.db_path,
        docker_base_label=paths.docker_base_label,
        host_docker_base=host_docker_base,
        host_docker_base_label=host_docker_base_label or None,
        wud_file_label=paths.wud_file_label,
        log_dir_label=paths.log_dir_label,
    )


def _resolve_docker_paths(
    args: object, env: Mapping[str, str]
) -> _ResolvedDockerPaths:
    home = env.get("HOME") or str(Path.home())
    docker_base_label = str(
        getattr(args, "base", None) or env.get("DOCKER_BASE") or f"{home}/docker"
    )
    wud_file_label = str(
        getattr(args, "file", None)
        or env.get("WUD_OUT_FILE")
        or f"{docker_base_label}/wud/out/images.todo"
    )
    log_dir_label = str(
        getattr(args, "log_dir", None) or env.get("WUD_LOG_DIR") or "./logs"
    )
    docker_base = Path(docker_base_label)
    wud_file = Path(wud_file_label)
    log_dir = Path(log_dir_label)
    db_path = Path(env.get("WUD_DB_PATH") or str(log_dir / DB_FILENAME))
    return _ResolvedDockerPaths(
        docker_base=docker_base,
        wud_file=wud_file,
        log_dir=log_dir,
        db_path=db_path,
        docker_base_label=docker_base_label,
        wud_file_label=wud_file_label,
        log_dir_label=log_dir_label,
    )


def _validate_host_docker_base_constraints(
    host_docker_base: Path | None,
    docker_base: Path,
) -> None:
    if host_docker_base is None:
        return
    if not host_docker_base.is_absolute():
        raise UpdaterError("HOST_DOCKER_BASE must be an absolute path")
    if not docker_base.is_absolute():
        raise UpdaterError(
            "DOCKER_BASE must be an absolute path when HOST_DOCKER_BASE is set"
        )


def _parse_mode_and_wait(args: object, env: Mapping[str, str]) -> tuple[str, int]:
    max_wait_value = getattr(args, "max_wait", None)
    max_wait_label = "--max-wait"
    if max_wait_value is None:
        max_wait_value = env.get("WUD_MAX_WAIT")
        max_wait_label = "WUD_MAX_WAIT"
    max_wait = parse_seconds(max_wait_value, max_wait_label)
    mode = (
        getattr(args, "mode", None)
        or env.get("WUD_UPDATE_MODE")
        or DEFAULT_UPDATE_MODE
    )
    return mode, max_wait


def parse_seconds(value: str | None, label: str) -> int:
    if value is None or value == "":
        return DEFAULT_MAX_WAIT
    if not re.fullmatch(r"\d+", str(value), flags=re.ASCII):
        raise UpdaterError(f"{label} must be an integer number of seconds")
    return int(str(value), 10)


def parse_tag_overrides(values: Sequence[str]) -> tuple[TagOverride, ...]:
    overrides: list[TagOverride] = []
    seen: set[int] = set()
    for value in values:
        line_raw, sep, tag = value.partition("=")
        if not sep or not line_raw or not tag:
            raise UpdaterError("--tag-override must use LINE=TAG")
        if not re.fullmatch(r"\d+", line_raw, flags=re.ASCII):
            raise UpdaterError("--tag-override line must be a positive integer")
        line_no = int(line_raw, 10)
        if line_no < 1:
            raise UpdaterError("--tag-override line must be a positive integer")
        if line_no in seen:
            raise UpdaterError(
                f"--tag-override line {line_no} was provided more than once"
            )
        if not tag_value_valid(tag):
            raise UpdaterError(f"--tag-override line {line_no} has invalid tag: {tag}")
        overrides.append(TagOverride(line_no=line_no, tag=tag))
        seen.add(line_no)
    return tuple(overrides)
