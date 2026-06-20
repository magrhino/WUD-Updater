"""Retag plan rendering and identity helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from .compose import ComposeStack
from .digest_provenance import DigestTagProvenance
from .updater_models import DigestPinUpdate
from .web_models import (
    RetagPlanDigestPinUpdate,
    RetagPlanIssue,
    RetagPlanLabelRewrite,
    RetagPlanResponse,
    RetagPlanStack,
)


RETAG_PLAN_VERSION = 1


@dataclass(frozen=True)
class RetagPlanUpdate:
    service_key: str
    stack: ComposeStack
    update: DigestPinUpdate
    provenance: DigestTagProvenance
    label_rewrites: tuple[RetagPlanLabelRewrite, ...] = ()


@dataclass(frozen=True)
class RetagPlanBuild:
    response: RetagPlanResponse
    updates: tuple[RetagPlanUpdate, ...]


def retag_update_service(item: RetagPlanUpdate) -> str:
    return item.update.services[0] if item.update.services else ""


def retag_plan_status(
    selected: Sequence[RetagPlanUpdate],
    choices: Mapping[str, str],
    issues: Sequence[RetagPlanIssue],
) -> str:
    if issues:
        return "blocked"
    if not selected:
        return "empty"
    if not choices:
        return "empty"
    return "ready"


def retag_plan_stacks(
    selected: Sequence[RetagPlanUpdate],
) -> list[RetagPlanStack]:
    stacks: list[RetagPlanStack] = []
    for stack in ordered_retag_stacks(selected):
        stack_updates = [item for item in selected if item.stack.index == stack.index]
        stacks.append(
            RetagPlanStack(
                stack=stack.name,
                directory=str(stack.directory),
                compose_file=stack.file,
                project_directory=(
                    "" if stack.project_directory is None else str(stack.project_directory)
                ),
                services=sorted(
                    {
                        service
                        for item in stack_updates
                        for service in item.update.services
                    }
                ),
                digest_pin_updates=[
                    retag_plan_digest_update(item)
                    for item in sorted(stack_updates, key=lambda value: value.service_key)
                ],
            )
        )
    return stacks


def retag_plan_digest_update(
    item: RetagPlanUpdate,
) -> RetagPlanDigestPinUpdate:
    update = item.update
    service = retag_update_service(item)
    return RetagPlanDigestPinUpdate(
        service_key=item.service_key,
        stack=item.stack.name,
        service=service,
        source_image=update.old_image,
        resolved_tag=update.resolved_tag,
        planned_digest=update.planned_digest,
        final_image=update.final_image,
        watch_tag=update.watch_tag,
        marker=update.marker,
        label_key=update.label_key,
        label_value=update.label_value,
        label_rewrites=list(item.label_rewrites),
        digest_provenance=asdict(item.provenance),
    )


def retag_compose_hashes(
    selected: Sequence[RetagPlanUpdate],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for stack in ordered_retag_stacks(selected):
        path = stack.directory / stack.file
        try:
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            hashes[str(path)] = ""
    return hashes


def retag_plan_id(
    plan: RetagPlanResponse,
    *,
    updates: Sequence[RetagPlanUpdate],
    compose_hashes: Mapping[str, str],
) -> str:
    payload = {
        "version": RETAG_PLAN_VERSION,
        "status": plan.status,
        "selected": [
            {
                "service_key": item.service_key,
                "stack": item.stack.name,
                "service": retag_update_service(item),
                "source_image": item.update.old_image,
                "resolved_tag": item.update.resolved_tag,
                "planned_digest": item.update.planned_digest,
                "final_image": item.update.final_image,
                "label_value": item.update.label_value,
                "provenance": asdict(item.provenance),
            }
            for item in sorted(updates, key=lambda value: value.service_key)
        ],
        "compose_hashes": dict(sorted(compose_hashes.items())),
        "issues": [issue.model_dump() for issue in plan.issues],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ordered_retag_stacks(
    updates: Sequence[RetagPlanUpdate],
) -> tuple[ComposeStack, ...]:
    stacks: dict[int, ComposeStack] = {}
    for item in updates:
        stacks[item.stack.index] = item.stack
    return tuple(stacks[index] for index in sorted(stacks))
