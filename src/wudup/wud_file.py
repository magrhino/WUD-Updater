"""Read-only WUD update file parsing."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from wudup.file_ops import OwnerConfig, atomic_rewrite
from wudup.images import (
    image_has_tag,
    image_key,
    normalize_digest,
    repo_key,
    tag_value_valid,
    trim,
)
from wudup.locks import DirectoryLock


_SHELL_SPACE_RE = re.compile(r"[ \t\n\r\v\f]")


@dataclass(frozen=True)
class WudLine:
    line_no: int
    actionable: bool
    raw: str


@dataclass(frozen=True)
class WudTarget:
    line_no: int
    raw: str
    first: str
    key: str
    repo: str
    has_tag: bool
    allow_repo: bool
    digest: str
    desired_tag: str
    tag_token: str = ""


@dataclass(frozen=True)
class ParsedWudFile:
    lines: tuple[WudLine, ...]
    targets: tuple[WudTarget, ...]
    warnings: tuple[str, ...]


def parse_wud_text(
    text: str,
    *,
    selected_lines: Iterable[int] | None = None,
) -> ParsedWudFile:
    """Parse WUD update file text without mutating it."""

    raw_lines = _split_shell_lines(text)
    selected = set(selected_lines) if selected_lines is not None else None
    lines: list[WudLine] = []
    targets: list[WudTarget] = []
    warnings: list[str] = []

    for line_no, raw in enumerate(raw_lines, start=1):
        trimmed = trim(raw)
        actionable = trimmed != "" and not trimmed.startswith("#")
        line = WudLine(line_no=line_no, actionable=actionable, raw=raw)
        lines.append(line)

        if not actionable:
            continue
        if selected is not None and line_no not in selected:
            continue

        target, target_warnings = _parse_target(line_no, raw, trimmed)
        targets.append(target)
        warnings.extend(target_warnings)

    return ParsedWudFile(
        lines=tuple(lines),
        targets=tuple(targets),
        warnings=tuple(warnings),
    )


def parse_wud_file(
    path: str | Path,
    *,
    selected_lines: Iterable[int] | None = None,
    encoding: str = "utf-8",
) -> ParsedWudFile:
    """Read and parse a WUD update file without mutating it."""

    with Path(path).open("r", encoding=encoding, newline="") as file:
        return parse_wud_text(file.read(), selected_lines=selected_lines)


def remove_lines_before_run(
    path: str | Path,
    parsed: ParsedWudFile,
    remove_lines: Iterable[int],
    *,
    lock: DirectoryLock | None = None,
    lock_timeout: int | str = 30,
    owner: OwnerConfig | None = None,
    encoding: str = "utf-8",
) -> bool:
    """Remove requested original lines while preserving concurrently appended extras."""

    remove = set(remove_lines)
    if not remove:
        return False

    def transform(current_lines: list[str]) -> list[str]:
        original_count: dict[str, int] = {}
        preserved: list[str] = []
        for line in parsed.lines:
            original_count[line.raw] = original_count.get(line.raw, 0) + 1
            if line.line_no not in remove:
                preserved.append(line.raw)

        current_count: dict[str, int] = {}
        for raw in current_lines:
            current_count[raw] = current_count.get(raw, 0) + 1

        extra_count: dict[str, int] = {}
        for raw, count in current_count.items():
            extra_count[raw] = max(count - original_count.get(raw, 0), 0)

        extra_seen: dict[str, int] = {}
        result = list(preserved)
        for raw in current_lines:
            seen = extra_seen.get(raw, 0)
            if seen < extra_count.get(raw, 0):
                result.append(raw)
                extra_seen[raw] = seen + 1
        return result

    _rewrite_wud_file(
        path,
        transform,
        lock=lock,
        lock_timeout=lock_timeout,
        owner=owner,
        encoding=encoding,
    )
    return True


def cleanup_successful_lines(
    path: str | Path,
    parsed: ParsedWudFile,
    successful_lines: Iterable[int],
    *,
    lock: DirectoryLock | None = None,
    lock_timeout: int | str = 30,
    owner: OwnerConfig | None = None,
    encoding: str = "utf-8",
) -> bool:
    """Remove successfully processed raw WUD entries from the current file."""

    successful = set(successful_lines)
    if not successful:
        return False

    drop_count: dict[str, int] = {}
    for line in parsed.lines:
        if line.line_no in successful:
            drop_count[line.raw] = drop_count.get(line.raw, 0) + 1

    if not drop_count:
        return False

    def transform(current_lines: list[str]) -> list[str]:
        dropped: dict[str, int] = {}
        result: list[str] = []
        for raw in current_lines:
            seen = dropped.get(raw, 0)
            if seen < drop_count.get(raw, 0):
                dropped[raw] = seen + 1
                continue
            result.append(raw)
        return result

    _rewrite_wud_file(
        path,
        transform,
        lock=lock,
        lock_timeout=lock_timeout,
        owner=owner,
        encoding=encoding,
    )
    return True


def restore_failed_lines(
    path: str | Path,
    parsed: ParsedWudFile,
    failed_lines: Iterable[int],
    *,
    lock: DirectoryLock | None = None,
    lock_timeout: int | str = 30,
    owner: OwnerConfig | None = None,
    encoding: str = "utf-8",
) -> bool:
    """Append failed original WUD entries when pre-run removal took them out."""

    failed = set(failed_lines)
    if not failed:
        return False

    needed_order: list[str] = []
    needed_count: dict[str, int] = {}
    for line in parsed.lines:
        if line.line_no in failed:
            needed_order.append(line.raw)
            needed_count[line.raw] = needed_count.get(line.raw, 0) + 1

    if not needed_order:
        return False

    def transform(current_lines: list[str]) -> list[str]:
        current_count: dict[str, int] = {}
        for raw in current_lines:
            current_count[raw] = current_count.get(raw, 0) + 1

        restored_count: dict[str, int] = {}
        result = list(current_lines)
        for raw in needed_order:
            restored = restored_count.get(raw, 0)
            if current_count.get(raw, 0) + restored < needed_count[raw]:
                result.append(raw)
                restored_count[raw] = restored + 1
        return result

    _rewrite_wud_file(
        path,
        transform,
        lock=lock,
        lock_timeout=lock_timeout,
        owner=owner,
        encoding=encoding,
    )
    return True


def _split_shell_lines(text: str) -> list[str]:
    if text == "":
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def _join_shell_lines(lines: Iterable[str]) -> str:
    raw_lines = list(lines)
    if not raw_lines:
        return ""
    return "\n".join(raw_lines) + "\n"


def _rewrite_wud_file(
    path: str | Path,
    transform: Callable[[list[str]], list[str]],
    *,
    lock: DirectoryLock | None,
    lock_timeout: int | str,
    owner: OwnerConfig | None,
    encoding: str,
) -> None:
    target = Path(path)
    active_lock = lock or DirectoryLock(target, timeout_seconds=lock_timeout)
    release_after = lock is None or (not active_lock.parent_held and not active_lock.held)

    active_lock.acquire()
    try:
        with target.open("r", encoding=encoding, newline="") as file:
            current_lines = _split_shell_lines(file.read())
        atomic_rewrite(
            target,
            _join_shell_lines(transform(current_lines)),
            metadata_source=target,
            owner=owner,
            encoding=encoding,
        )
    finally:
        if release_after:
            active_lock.release()


def _parse_target(
    line_no: int,
    raw: str,
    trimmed: str,
) -> tuple[WudTarget, list[str]]:
    first = _first_token(trimmed)
    rest = trimmed[len(first) :]

    digest = ""
    if "@sha256:" in first:
        digest = first.split("@", 1)[1]
    digest = normalize_digest(digest)

    desired_tag = ""
    tag_token = ""
    for token in _rest_tokens(rest):
        if token.startswith("tag="):
            desired_tag = token.removeprefix("tag=")
            if tag_value_valid(desired_tag):
                tag_token = desired_tag

    warnings: list[str] = []
    if desired_tag != "":
        if not tag_value_valid(desired_tag):
            warnings.append(
                f"Ignoring invalid tag value on WUD line {line_no}: {desired_tag}"
            )
            desired_tag = ""
        elif not image_has_tag(first):
            warnings.append(
                "Ignoring tag update without a tagged source image on WUD line "
                f"{line_no}: {first}"
            )
            desired_tag = ""

    has_tag = image_has_tag(first)
    allow_repo = not has_tag

    return (
        WudTarget(
            line_no=line_no,
            raw=raw,
            first=first,
            key=image_key(first),
            repo=repo_key(first),
            has_tag=has_tag,
            allow_repo=allow_repo,
            digest=digest,
            desired_tag=desired_tag,
            tag_token=tag_token,
        ),
        warnings,
    )


def _first_token(value: str) -> str:
    match = _SHELL_SPACE_RE.search(value)
    if match is None:
        return value
    return value[: match.start()]


def _rest_tokens(value: str) -> list[str]:
    stripped = trim(value)
    if stripped == "":
        return []
    return [part for part in _SHELL_SPACE_RE.split(stripped) if part != ""]
