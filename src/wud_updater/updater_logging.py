"""Logging and text-file formatting helpers for the updater."""

from __future__ import annotations

import errno
import os
import re
import sys
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .command import CommandResult
from .file_ops import OwnerConfig, OwnerConfigError, apply_configured_owner
from .terminal import TerminalRenderer
from .updater_models import UpdaterError


_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_EXCLUSIVE_CREATE_ATTEMPTS = 100


class Logger:
    def __init__(
        self,
        log_file: Path,
        *,
        no_color: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.log_file = log_file
        self.no_color = no_color
        self.renderer = TerminalRenderer(no_color=no_color, environ=environ)

    def info(self, message: str) -> None:
        self._term("INFO", message)

    def warn(self, message: str) -> None:
        self._term("WARN", message)

    def error(self, message: str) -> None:
        self._term("ERROR", message, stream=sys.stderr)

    def plain(self, level: str, message: str) -> None:
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp()}] [{level}] {message}\n")

    def rich_enabled(self) -> bool:
        return self.renderer.rich_enabled()

    def _term(self, level: str, message: str, *, stream: TextIO | None = None) -> None:
        if stream is None:
            stream = sys.stdout
        stamped = timestamp()
        self.renderer.log_line(
            timestamp=stamped,
            level=level,
            message=message,
            stream=stream,
        )
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(f"[{stamped}] [{level}] {message}\n")


def prepare_log_file(log_dir: Path, owner: OwnerConfig) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    apply_configured_owner(log_dir, owner)
    log_file = log_dir / f"update-from-wud-v2-{file_timestamp()}.log"
    try:
        return _create_unique_text_file_exclusive(log_file, "", owner=owner)
    except OSError as exc:
        raise UpdaterError(f"Could not create updater log file: {exc}") from exc


def _create_unique_text_file_exclusive(
    path: Path,
    content: str,
    *,
    owner: OwnerConfig | None = None,
    encoding: str = "utf-8",
) -> Path:
    owner = owner or OwnerConfig()

    for candidate in _exclusive_text_file_candidates(path):
        try:
            _write_exclusive_text_file(
                candidate,
                content,
                owner=owner,
                encoding=encoding,
            )
        except OSError as exc:
            if _is_exclusive_create_collision(exc):
                continue
            raise
        return candidate

    raise FileExistsError(
        errno.EEXIST,
        f"could not create a unique file after {_EXCLUSIVE_CREATE_ATTEMPTS} attempts",
        str(path),
    )


def _collision_path(path: Path, attempt: int) -> Path:
    if attempt == 0:
        return path
    return path.with_name(f"{path.stem}-{attempt}{path.suffix}")


def _exclusive_text_file_candidates(path: Path) -> Iterator[Path]:
    for attempt in range(_EXCLUSIVE_CREATE_ATTEMPTS):
        yield _collision_path(path, attempt)


def _write_exclusive_text_file(
    path: Path,
    content: str,
    *,
    owner: OwnerConfig,
    encoding: str,
) -> None:
    fd = -1
    try:
        fd = os.open(path, _exclusive_create_flags(), 0o600)
        _apply_configured_fd_owner(fd, owner)
        with os.fdopen(fd, "w", encoding=encoding, newline="") as file:
            fd = -1
            file.write(content)
    finally:
        if fd != -1:
            os.close(fd)


def _exclusive_create_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    return flags | getattr(os, "O_NOFOLLOW", 0)


def _apply_configured_fd_owner(fd: int, owner: OwnerConfig) -> None:
    if not owner.configured:
        return
    if owner.uid is None or owner.gid is None:
        raise OwnerConfigError("OUT_UID and OUT_GID/OUT_GUID must be set together")
    os.fchown(fd, owner.uid, owner.gid)


def _is_exclusive_create_collision(exc: OSError) -> bool:
    return exc.errno in {errno.EEXIST, errno.ELOOP}


def safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT_RE.sub("_", value)
    return cleaned or "tag"


def _render_command_result(result: CommandResult) -> list[str]:
    content = [
        "command:\n",
        f"  cwd={result.cwd if result.cwd is not None else ''}\n",
        f"  argv={result.display}\n",
        f"  exit_code={result.returncode}\n",
        f"  stdout_tail_truncated={_bool_text(result.stdout_truncated)}\n",
        "  stdout_tail:\n",
    ]
    content.extend(_indented_block(result.stdout, "    "))
    content.append(f"  stderr_tail_truncated={_bool_text(result.stderr_truncated)}\n")
    content.append("  stderr_tail:\n")
    content.extend(_indented_block(result.stderr, "    "))
    return content


def _indented_block(value: str, prefix: str) -> list[str]:
    if not value.strip():
        return [f"{prefix}(empty)\n"]
    lines: list[str] = []
    for line in value.splitlines():
        lines.append(f"{prefix}{sanitize_stream(line)}\n")
    return lines


def _restored_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def sanitize_stream(value: str) -> str:
    return _CONTROL_RE.sub("", value.replace("\r", "\n")).strip()


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def file_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
