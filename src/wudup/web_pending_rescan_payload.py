"""Payload validation helpers for WebUI WUD rescans."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException

from .plans import PlanInputError
from .web_models import PendingRescanLine, PendingRescanRequest


def rescan_payload_lines(
    payload: PendingRescanRequest,
) -> tuple[PendingRescanLine, ...]:
    if not payload.lines:
        raise HTTPException(
            status_code=422,
            detail="selected rescan lines are required",
        )

    seen: set[int] = set()
    selected: list[PendingRescanLine] = []
    for line in payload.lines:
        if line.line_no in seen:
            raise HTTPException(
                status_code=422,
                detail=f"rescan line {line.line_no} was provided more than once",
            )
        if not line.raw:
            raise HTTPException(
                status_code=422,
                detail=f"rescan line {line.line_no} raw value is required",
            )
        if not line.source_id:
            raise HTTPException(
                status_code=422,
                detail=f"rescan line {line.line_no} source_id is required",
            )
        if not line.source_hash:
            raise HTTPException(
                status_code=422,
                detail=f"rescan line {line.line_no} source_hash is required",
            )
        seen.add(line.line_no)
        selected.append(line)

    sorted_selected = tuple(sorted(selected, key=lambda line: line.line_no))
    if payload.line_numbers:
        _validate_payload_line_numbers_match(
            payload.line_numbers,
            selected_line_numbers=tuple(line.line_no for line in sorted_selected),
            operation="rescan",
        )
    return sorted_selected


def _validate_payload_line_numbers_match(
    line_numbers: Sequence[int],
    *,
    selected_line_numbers: Sequence[int],
    operation: str,
) -> None:
    try:
        validated_line_numbers = _selected_line_numbers(line_numbers)
    except PlanInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if validated_line_numbers != tuple(selected_line_numbers):
        raise HTTPException(
            status_code=422,
            detail=f"line_numbers must match selected {operation} lines",
        )


def _selected_line_numbers(line_numbers: Sequence[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    selected: list[int] = []
    for line_no in line_numbers:
        if line_no in seen:
            raise PlanInputError(
                f"line_numbers line {line_no} was provided more than once"
            )
        seen.add(line_no)
        selected.append(line_no)
    return tuple(sorted(selected))
