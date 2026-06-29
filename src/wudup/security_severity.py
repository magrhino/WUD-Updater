"""Shared security scan severity helpers."""

from __future__ import annotations

from typing import Literal

SecuritySeverity = Literal["critical", "high", "medium", "low", "unknown"]

SECURITY_SEVERITIES: tuple[SecuritySeverity, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "unknown",
)


def normalize_security_severity(value: object) -> SecuritySeverity:
    severity = str(value or "").strip().lower()
    for allowed in SECURITY_SEVERITIES:
        if severity == allowed:
            return allowed
    return "unknown"
