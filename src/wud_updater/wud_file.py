"""Read-only WUD update file parsing."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from wud_updater.images import (
    image_has_tag,
    image_key,
    normalize_digest,
    repo_key,
    tag_value_valid,
    trim,
)


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


def _split_shell_lines(text: str) -> list[str]:
    if text == "":
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


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
    for token in _rest_tokens(rest):
        if token.startswith("tag="):
            desired_tag = token.removeprefix("tag=")

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
