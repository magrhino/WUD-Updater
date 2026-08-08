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
    failures: dict[str, list[str]] = {
        "target_id_required": [],
        "unknown_services": [],
        "unknown_targets": [],
        "mismatches": [],
        "duplicates": [],
    }
    values: dict[str, RetagChoiceRequest] = {}

    # Resolve all choices first; the ordered cases below preserve 422 precedence.
    for item in choices:
        identity = _resolve_choice_key(
            item,
            service_key_by_target_id=service_key_by_target_id,
            unique_target_id_by_service=unique_target_id_by_service,
            duplicate_service_keys=duplicate_service_keys,
            failures=failures,
        )
        if identity is None:
            continue
        choice_key, duplicate_label = identity
        if choice_key in values:
            failures["duplicates"].append(duplicate_label)
            continue
        values[choice_key] = item

    _raise_retag_choice_validation_error(
        (
            (
                "retag choices for duplicate service(s) must include target_id",
                failures["target_id_required"],
            ),
            (
                "retag choices reference unknown service(s)",
                failures["unknown_services"],
            ),
            (
                (
                    "retag targets changed; reload retag targets before retrying. "
                    "Affected service(s)"
                ),
                failures["unknown_targets"],
            ),
            (
                "retag choice target_id does not match service_key",
                failures["mismatches"],
            ),
            (
                "retag choices contain duplicate target(s)",
                failures["duplicates"],
            ),
        ),
    )
    return values


def _resolve_choice_key(
    item: RetagChoiceRequest,
    *,
    service_key_by_target_id: Mapping[str, str],
    unique_target_id_by_service: Mapping[str, str],
    duplicate_service_keys: set[str],
    failures: Mapping[str, list[str]],
) -> tuple[str, str] | None:
    target_id = item.target_id or ""
    if target_id:
        service_key = service_key_by_target_id.get(target_id)
        if service_key is None:
            failures["unknown_targets"].append(item.service_key)
            return None
        if service_key != item.service_key:
            failures["mismatches"].append(f"{item.service_key} ({target_id})")
            return None
        return target_id, f"{service_key} ({target_id})"

    if item.service_key in duplicate_service_keys:
        failures["target_id_required"].append(item.service_key)
        return None

    choice_key = unique_target_id_by_service.get(item.service_key)
    if choice_key is None:
        failures["unknown_services"].append(item.service_key)
        return None
    return choice_key, item.service_key


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
