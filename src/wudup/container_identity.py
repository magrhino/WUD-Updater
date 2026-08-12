"""Helpers for finding the current Docker container identity."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

_CONTAINER_ID_RE = re.compile(r"\b[0-9a-f]{64}\b")


def container_identity_candidates(
    environ: Mapping[str, str],
    *,
    cgroup_path: Path = Path("/proc/self/cgroup"),
) -> list[str]:
    """Return likely Docker container names or IDs for self-inspection."""

    candidates: list[str] = []
    for name in ("WUD_WEB_RESTART_CONTAINER", "HOSTNAME"):
        value = environ.get(name, "").strip()
        if value:
            candidates.append(value)

    try:
        cgroup_text = cgroup_path.read_text(encoding="utf-8")
    except OSError:
        cgroup_text = ""
    candidates.extend(_container_ids_from_cgroup(cgroup_text))
    return _unique(candidates)


def _container_ids_from_cgroup(cgroup_text: str) -> list[str]:
    return _unique(match.group(0) for match in _CONTAINER_ID_RE.finditer(cgroup_text))


def _unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
