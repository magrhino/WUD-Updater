"""Shared retag target identity helpers."""

from __future__ import annotations

import hashlib


def retag_target_id(
    directory: object,
    compose_file: object,
    project_directory: object,
    stack: object,
    service: object,
) -> str:
    raw = "\0".join(
        str(field)
        for field in (
            directory,
            compose_file,
            project_directory,
            stack,
            service,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
