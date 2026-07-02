"""Retag choice identity lookup and validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from fastapi import HTTPException

from .web_models import RetagChoiceRequest

__all__ = ["validated_retag_choice_map"]


def validated_retag_choice_map(
    choices: Sequence[RetagChoiceRequest],
    *,
    service_key_by_target_id: Mapping[str, str],
) -> dict[str, RetagChoiceRequest]:
    service_counts = Counter(service_key_by_target_id.values())
    unique_target_id_by_service = {
        service_key: target_id
        for target_id, service_key in service_key_by_target_id.items()
        if service_counts[service_key] == 1
    }
    duplicate_service_keys = {
        service_key for service_key, count in service_counts.items() if count > 1
    }
    target_id_required: list[str] = []
    unknown_services: list[str] = []
    unknown_targets: list[str] = []
    mismatches: list[str] = []
    duplicates: list[str] = []
    values: dict[str, RetagChoiceRequest] = {}

    for item in choices:
        target_id = item.target_id or ""
        if target_id:
            service_key = service_key_by_target_id.get(target_id)
            if service_key is None:
                unknown_targets.append(target_id)
                continue
            if service_key != item.service_key:
                mismatches.append(f"{item.service_key} ({target_id})")
                continue
            choice_key = target_id
            duplicate_label = f"{service_key} ({target_id})"
        elif item.service_key in duplicate_service_keys:
            target_id_required.append(item.service_key)
            continue
        else:
            choice_key = unique_target_id_by_service.get(item.service_key)
            if choice_key is None:
                unknown_services.append(item.service_key)
                continue
            duplicate_label = item.service_key

        if choice_key in values:
            duplicates.append(duplicate_label)
            continue
        values[choice_key] = item

    _raise_retag_choice_validation_error(
        (
            (
                "retag choices for duplicate service(s) must include target_id",
                target_id_required,
            ),
            (
                "retag choices reference unknown service(s)",
                unknown_services,
            ),
            (
                "retag choices reference unknown target(s)",
                unknown_targets,
            ),
            (
                "retag choice target_id does not match service_key",
                mismatches,
            ),
            (
                "retag choices contain duplicate target(s)",
                duplicates,
            ),
        ),
    )
    return values


def _raise_retag_choice_validation_error(
    cases: Sequence[tuple[str, Sequence[str]]],
) -> None:
    for detail_prefix, values in cases:
        if values:
            names = sorted(set(values))
            raise HTTPException(
                status_code=422,
                detail=f"{detail_prefix}: {', '.join(names)}",
            )
