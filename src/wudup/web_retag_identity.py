"""Shared retag target identity helpers."""

from __future__ import annotations

import hashlib


def _identity_field(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def retag_target_id(
    directory: object,
    compose_file: object,
    project_directory: object,
    stack: object,
    service: object,
) -> str:
    raw = "\0".join(
        _identity_field(field)
        for field in (
            directory,
            compose_file,
            project_directory,
            stack,
            service,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
