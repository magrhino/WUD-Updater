"""Line selection parsing ported from ``bin/docker-update-from-wud``."""

from __future__ import annotations

import re

_SHELL_SPACE_RE = re.compile(r"\s", re.ASCII)
_RANGE_RE = re.compile(r"^(\d+)-(\d+)$", re.ASCII)
_NUMBER_RE = re.compile(r"^\d+$", re.ASCII)


class LineSpecError(ValueError):
    """Raised when a line selection spec is invalid."""


def parse_line_spec(spec: str | None, max_lines: int, label: str) -> list[int]:
    """Parse a comma-separated line spec into sorted, unique line numbers."""

    cleaned = _clean_line_spec(spec, label)
    if cleaned is None:
        return []

    selected: set[int] = set()
    for part in _line_spec_parts(cleaned):
        selected.update(_parse_line_spec_part(part, spec, max_lines, label))

    return sorted(selected)


def _clean_line_spec(spec: str | None, label: str) -> str | None:
    if spec is None or spec == "":
        return None

    cleaned = _SHELL_SPACE_RE.sub("", spec)
    if cleaned == "":
        raise LineSpecError(f"{label} must not be empty")
    return cleaned


def _line_spec_parts(cleaned: str) -> list[str]:
    parts = cleaned.split(",")
    if parts[-1] == "":
        parts.pop()
    return parts


def _parse_line_spec_part(
    part: str,
    spec: str | None,
    max_lines: int,
    label: str,
) -> range | tuple[int]:
    if part == "":
        raise LineSpecError(f"Invalid {label} value: {spec}")

    range_match = _RANGE_RE.fullmatch(part)
    if range_match is not None:
        return _parse_line_range(range_match, spec, max_lines, label)

    if _NUMBER_RE.fullmatch(part) is not None:
        return (_parse_line_number(part, spec, max_lines, label),)

    raise LineSpecError(f"Invalid {label} value: {spec}")


def _parse_line_range(
    range_match: re.Match[str],
    spec: str | None,
    max_lines: int,
    label: str,
) -> range:
    start = int(range_match.group(1), 10)
    end = int(range_match.group(2), 10)
    if start < 1:
        raise LineSpecError(f"{label} line numbers must be 1 or greater: {spec}")
    if end < start:
        raise LineSpecError(f"{label} ranges must ascend: {spec}")
    _check_line_number_bounds(end, max_lines, label)
    return range(start, end + 1)


def _parse_line_number(
    part: str,
    spec: str | None,
    max_lines: int,
    label: str,
) -> int:
    line_no = int(part, 10)
    if line_no < 1:
        raise LineSpecError(f"{label} line numbers must be 1 or greater: {spec}")
    _check_line_number_bounds(line_no, max_lines, label)
    return line_no


def _check_line_number_bounds(
    line_no: int,
    max_lines: int,
    label: str,
) -> None:
    if line_no > max_lines:
        raise LineSpecError(
            f"{label} references line {line_no}, but WUD file has "
            f"{max_lines} line(s)"
        )
