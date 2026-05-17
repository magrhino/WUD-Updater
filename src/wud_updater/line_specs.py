"""Line selection parsing ported from ``bin/docker-update-from-wud``."""

from __future__ import annotations

import re


_SHELL_SPACE_RE = re.compile(r"[ \t\n\r\v\f]")
_RANGE_RE = re.compile(r"^([0-9]+)-([0-9]+)$")
_NUMBER_RE = re.compile(r"^[0-9]+$")


class LineSpecError(ValueError):
    """Raised when a line selection spec is invalid."""


def parse_line_spec(spec: str | None, max_lines: int, label: str) -> list[int]:
    """Parse a comma-separated line spec into sorted, unique line numbers."""

    if spec is None or spec == "":
        return []

    cleaned = _SHELL_SPACE_RE.sub("", spec)
    if cleaned == "":
        raise LineSpecError(f"{label} must not be empty")

    parts = cleaned.split(",")
    if parts[-1] == "":
        parts.pop()

    selected: set[int] = set()
    for part in parts:
        if part == "":
            raise LineSpecError(f"Invalid {label} value: {spec}")

        range_match = _RANGE_RE.fullmatch(part)
        if range_match is not None:
            start = int(range_match.group(1), 10)
            end = int(range_match.group(2), 10)
            if start < 1:
                raise LineSpecError(
                    f"{label} line numbers must be 1 or greater: {spec}"
                )
            if end < start:
                raise LineSpecError(f"{label} ranges must ascend: {spec}")
            if end > max_lines:
                raise LineSpecError(
                    f"{label} references line {end}, but WUD file has "
                    f"{max_lines} line(s)"
                )
            selected.update(range(start, end + 1))
            continue

        if _NUMBER_RE.fullmatch(part) is not None:
            line_no = int(part, 10)
            if line_no < 1:
                raise LineSpecError(
                    f"{label} line numbers must be 1 or greater: {spec}"
                )
            if line_no > max_lines:
                raise LineSpecError(
                    f"{label} references line {line_no}, but WUD file has "
                    f"{max_lines} line(s)"
                )
            selected.add(line_no)
            continue

        raise LineSpecError(f"Invalid {label} value: {spec}")

    return sorted(selected)
