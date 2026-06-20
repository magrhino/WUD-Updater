"""Shared WebUI metadata JSON helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def json_object(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def json_list(value: Sequence[Any]) -> str:
    return json.dumps(list(value), separators=(",", ":"))


def json_object_or_empty(raw: object) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
