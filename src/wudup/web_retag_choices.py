"""Retag choice identity lookup and validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException

from .web_models import RetagChoiceRequest

__all__ = ["validated_retag_choice_map"]


@dataclass(frozen=True)
class _RetagChoiceLookup:
    service_key_by_target_id: Mapping[str, str]
    unique_target_id_by_service: Mapping[str, str]
    duplicate_service_keys: frozenset[str]


@dataclass
class _RetagChoiceValidationFailures:
    duplicates: list[str] = field(default_factory=list)
    unknown_services: list[str] = field(default_factory=list)
    unknown_targets: list[str] = field(default_factory=list)
    target_id_required: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _RetagChoiceValidationCase:
    code: str
    detail_prefix: str
    values: Sequence[str]


@dataclass(frozen=True)
class _RetagChoiceValidationError:
    code: str
    detail: str
    values: tuple[str, ...]


def validated_retag_choice_map(
    choices: Sequence[RetagChoiceRequest],
    *,
    service_key_by_target_id: Mapping[str, str],
) -> dict[str, RetagChoiceRequest]:
    lookup = _retag_choice_lookup(service_key_by_target_id)
    failures = _RetagChoiceValidationFailures()
    values: dict[str, RetagChoiceRequest] = {}
    for item in choices:
        identity = _retag_choice_identity(item, lookup, failures)
        if identity is None:
            continue
        choice_key, duplicate_label = identity
        if choice_key in values:
            failures.duplicates.append(duplicate_label)
            continue
        values[choice_key] = item
    _raise_retag_choice_validation_errors(failures)
    return values


def _retag_choice_lookup(
    service_key_by_target_id: Mapping[str, str],
) -> _RetagChoiceLookup:
    service_counts = Counter(service_key_by_target_id.values())
    return _RetagChoiceLookup(
        service_key_by_target_id=service_key_by_target_id,
        unique_target_id_by_service={
            service_key: target_id
            for target_id, service_key in service_key_by_target_id.items()
            if service_counts[service_key] == 1
        },
        duplicate_service_keys=frozenset(
            service_key for service_key, count in service_counts.items() if count > 1
        ),
    )


def _retag_choice_identity(
    item: RetagChoiceRequest,
    lookup: _RetagChoiceLookup,
    failures: _RetagChoiceValidationFailures,
) -> tuple[str, str] | None:
    target_id = item.target_id or ""
    if target_id:
        return _retag_choice_identity_from_target_id(item, target_id, lookup, failures)
    return _retag_choice_identity_from_service_key(item, lookup, failures)


def _retag_choice_identity_from_target_id(
    item: RetagChoiceRequest,
    target_id: str,
    lookup: _RetagChoiceLookup,
    failures: _RetagChoiceValidationFailures,
) -> tuple[str, str] | None:
    service_key = lookup.service_key_by_target_id.get(target_id)
    if service_key is None:
        failures.unknown_targets.append(target_id)
        return None
    if service_key != item.service_key:
        failures.mismatches.append(f"{item.service_key} ({target_id})")
        return None
    return target_id, f"{service_key} ({target_id})"


def _retag_choice_identity_from_service_key(
    item: RetagChoiceRequest,
    lookup: _RetagChoiceLookup,
    failures: _RetagChoiceValidationFailures,
) -> tuple[str, str] | None:
    if item.service_key in lookup.duplicate_service_keys:
        failures.target_id_required.append(item.service_key)
        return None
    choice_key = lookup.unique_target_id_by_service.get(item.service_key)
    if choice_key is None:
        failures.unknown_services.append(item.service_key)
        return None
    return choice_key, item.service_key


def _raise_retag_choice_validation_errors(
    failures: _RetagChoiceValidationFailures,
) -> None:
    error = _retag_choice_validation_error(failures)
    if error is not None:
        raise HTTPException(status_code=422, detail=error.detail)


def _retag_choice_validation_error(
    failures: _RetagChoiceValidationFailures,
) -> _RetagChoiceValidationError | None:
    for case in _retag_choice_validation_cases(failures):
        if not case.values:
            continue
        values = tuple(sorted(set(case.values)))
        return _RetagChoiceValidationError(
            code=case.code,
            detail=f"{case.detail_prefix}: {', '.join(values)}",
            values=values,
        )
    return None


def _retag_choice_validation_cases(
    failures: _RetagChoiceValidationFailures,
) -> tuple[_RetagChoiceValidationCase, ...]:
    return (
        _RetagChoiceValidationCase(
            code="duplicate-service-target-id-required",
            detail_prefix=(
                "retag choices for duplicate service(s) must include target_id"
            ),
            values=failures.target_id_required,
        ),
        _RetagChoiceValidationCase(
            code="unknown-service",
            detail_prefix="retag choices reference unknown service(s)",
            values=failures.unknown_services,
        ),
        _RetagChoiceValidationCase(
            code="unknown-target",
            detail_prefix="retag choices reference unknown target(s)",
            values=failures.unknown_targets,
        ),
        _RetagChoiceValidationCase(
            code="target-service-mismatch",
            detail_prefix="retag choice target_id does not match service_key",
            values=failures.mismatches,
        ),
        _RetagChoiceValidationCase(
            code="duplicate-target",
            detail_prefix="retag choices contain duplicate target(s)",
            values=failures.duplicates,
        ),
    )
