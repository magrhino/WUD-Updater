"""Digest-unpin recovery helpers for WebUI dry-run plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .compose import ComposeStack
from .compose_rewrite import (
    WUD_TAG_INCLUDE_LABEL,
    compose_unescape_dollars,
    exact_tags_regex,
    service_resolved_tag_marker,
)
from .digest_provenance import DigestTagProvenance, digest_from_image
from .images import image_tag, repo_key, tag_value_valid
from .plan_models import DryRunPlanIssue, DryRunPlanSkipped
from .updater_digest_unpin import digest_unpin_update_from_values
from .updater_models import ComposeTagRewriteError, DigestUnpinUpdate, Match
from .wud_file import ParsedWudFile, WudTarget, is_digest_target_line


@dataclass(frozen=True)
class DigestUnpinMatchResult:
    matches: tuple[Match, ...]
    skipped: tuple[DryRunPlanSkipped, ...]
    updates_by_stack: Mapping[int, tuple[DigestUnpinUpdate, ...]]
    issues: tuple[DryRunPlanIssue, ...]


def recover_digest_unpin_matches(
    parsed: ParsedWudFile,
    stacks: Sequence[ComposeStack],
    matches: Sequence[Match],
    skipped: Sequence[DryRunPlanSkipped],
    known_digest_provenance_by_service: Mapping[str, DigestTagProvenance],
) -> DigestUnpinMatchResult:
    issues: list[DryRunPlanIssue] = []
    updates_by_stack: dict[int, tuple[DigestUnpinUpdate, ...]] = {}
    skipped_by_line = {item.line_no: item for item in skipped}
    targets_by_line = {target.line_no: target for target in parsed.targets}
    updated_matches = list(matches)
    matched_lines = {match.target.line_no for match in matches}
    seen = {
        (
            match.stack.index,
            match.target.line_no,
            match.resolved,
            match.compose_image,
            match.service,
        )
        for match in matches
    }

    for line_no, item in list(skipped_by_line.items()):
        if item.reason != "unmatched" or line_no in matched_lines:
            continue
        target = targets_by_line.get(line_no)
        if target is None or not _digest_unpin_candidate_target(target):
            continue
        updates = _digest_unpin_updates_for_target(
            target,
            stacks,
            known_digest_provenance_by_service,
            updates_by_stack,
            issues,
        )
        if not updates:
            continue
        skipped_by_line.pop(line_no, None)
        for stack_index, stack_updates in updates.items():
            stack = next(
                (candidate for candidate in stacks if candidate.index == stack_index),
                None,
            )
            if stack is None:
                continue
            for update in stack_updates:
                _append_digest_unpin_update_matches(
                    update,
                    stack,
                    target,
                    updated_matches,
                    seen,
                )

    updated_matches.sort(
        key=lambda match: (
            match.stack.index,
            match.target.line_no,
            match.target.first,
            match.resolved,
            match.compose_image,
            match.service,
        )
    )
    return DigestUnpinMatchResult(
        matches=tuple(updated_matches),
        skipped=tuple(skipped_by_line[line_no] for line_no in sorted(skipped_by_line)),
        updates_by_stack=updates_by_stack,
        issues=tuple(issues),
    )


def _append_digest_unpin_update_matches(
    update: DigestUnpinUpdate,
    stack: ComposeStack,
    target: WudTarget,
    updated_matches: list[Match],
    seen: set[tuple[int, int, str, str, str]],
) -> None:
    for service in update.services:
        key = (
            stack.index,
            target.line_no,
            update.tag_image,
            update.old_image,
            service,
        )
        if key in seen:
            continue
        updated_matches.append(
            Match(
                stack,
                target,
                update.tag_image,
                update.old_image,
                service,
            )
        )
        seen.add(key)


def _digest_unpin_updates_for_target(
    target: WudTarget,
    stacks: Sequence[ComposeStack],
    known_digest_provenance_by_service: Mapping[str, DigestTagProvenance],
    updates_by_stack: dict[int, tuple[DigestUnpinUpdate, ...]],
    issues: list[DryRunPlanIssue],
) -> dict[int, tuple[DigestUnpinUpdate, ...]]:
    tag = image_tag(target.first)
    grouped: dict[tuple[int, str, str], set[str]] = {}
    stack_by_index = {stack.index: stack for stack in stacks}
    for stack in stacks:
        for service_image in stack.service_images:
            if not service_image.service:
                continue
            if not _digest_unpin_service_matches_target(service_image.image, target):
                continue
            recovered = _recover_digest_unpin_tag(
                target,
                stack,
                service_image.service,
                service_image.image,
                service_image.labels,
                tag,
                known_digest_provenance_by_service,
                issues,
            )
            if recovered is None:
                continue
            grouped.setdefault(
                (stack.index, service_image.image, recovered),
                set(),
            ).add(service_image.service)

    by_stack: dict[int, list[DigestUnpinUpdate]] = {}
    for (stack_index, old_image, resolved_tag), services in sorted(grouped.items()):
        update = digest_unpin_update_from_values(
            old_image=old_image,
            resolved_tag=resolved_tag,
            target_digest=target.digest,
            services=tuple(sorted(services)),
        )
        stack = stack_by_index.get(stack_index)
        if stack is not None:
            by_stack.setdefault(stack_index, []).append(update)
            updates_by_stack.setdefault(stack_index, ())

    for stack_index, updates in by_stack.items():
        existing = list(updates_by_stack.get(stack_index, ()))
        existing.extend(updates)
        updates_by_stack[stack_index] = tuple(_unique_digest_unpin_updates(existing))
    return {stack_index: tuple(updates) for stack_index, updates in by_stack.items()}


def _recover_digest_unpin_tag(
    target: WudTarget,
    stack: ComposeStack,
    service: str,
    image: str,
    labels: Sequence[tuple[str, str]],
    target_tag: str,
    known_digest_provenance_by_service: Mapping[str, DigestTagProvenance],
    issues: list[DryRunPlanIssue],
) -> str | None:
    service_key = f"{stack.name}/{service}"
    provenance = known_digest_provenance_by_service.get(service_key)
    if provenance is not None:
        tag = provenance.watch_tag or provenance.resolved_tag
        if provenance.final_image and provenance.final_image != image:
            issues.append(
                _digest_unpin_issue(
                    "digest-unpin-db-provenance-conflict",
                    (
                        f"Known digest provenance for {service_key} points to "
                        f"{provenance.final_image}, but Compose currently uses "
                        f"{image}."
                    ),
                    target,
                    stack,
                    service,
                )
            )
            return None
        if not tag or not tag_value_valid(tag):
            issues.append(
                _digest_unpin_issue(
                    "digest-unpin-tag-missing",
                    (
                        f"Known digest provenance for {service_key} does not "
                        "include a valid tag."
                    ),
                    target,
                    stack,
                    service,
                )
            )
            return None
        if tag != target_tag:
            issues.append(
                _digest_unpin_issue(
                    "digest-unpin-db-provenance-conflict",
                    (
                        f"Known digest provenance for {service_key} recovered "
                        f"tag {tag}, but the pending line targets {target_tag}."
                    ),
                    target,
                    stack,
                    service,
                )
            )
            return None
        return tag

    marker_tag = ""
    try:
        marker_tag = service_resolved_tag_marker(
            stack.directory / stack.file,
            service,
            expected_image=image,
        )
    except ComposeTagRewriteError as exc:
        issues.append(
            _digest_unpin_issue(
                "digest-unpin-marker-unsupported",
                f"Could not read resolved-tag marker for {service_key}: {exc}",
                target,
                stack,
                service,
            )
        )
        return None

    label_tag = _digest_unpin_label_tag(
        target,
        stack,
        service,
        labels,
        target_tag,
        issues,
    )
    if label_tag is None:
        return None
    if marker_tag and label_tag and marker_tag != label_tag:
        issues.append(
            _digest_unpin_issue(
                "digest-unpin-provenance-conflict",
                (
                    f"Resolved-tag marker for {service_key} is {marker_tag}, "
                    f"but {WUD_TAG_INCLUDE_LABEL} targets {label_tag}."
                ),
                target,
                stack,
                service,
            )
        )
        return None
    tag = marker_tag or label_tag
    if not tag:
        issues.append(
            _digest_unpin_issue(
                "digest-unpin-tag-missing",
                (
                    f"Digest-pinned service {service_key} has no known tag "
                    "provenance for a safe unpin."
                ),
                target,
                stack,
                service,
            )
        )
        return None
    if tag != target_tag:
        issues.append(
            _digest_unpin_issue(
                "digest-unpin-provenance-conflict",
                (
                    f"Recovered tag for {service_key} is {tag}, but the "
                    f"pending line targets {target_tag}."
                ),
                target,
                stack,
                service,
            )
        )
        return None
    return tag


def _digest_unpin_label_tag(
    target: WudTarget,
    stack: ComposeStack,
    service: str,
    labels: Sequence[tuple[str, str]],
    target_tag: str,
    issues: list[DryRunPlanIssue],
) -> str | None:
    raw = _label_value(labels, WUD_TAG_INCLUDE_LABEL)
    if not raw:
        return ""
    value = compose_unescape_dollars(raw)
    if value == exact_tags_regex((target_tag,)):
        return target_tag
    if tag_value_valid(value) and value == target_tag:
        return target_tag
    issues.append(
        _digest_unpin_issue(
            "digest-unpin-label-conflict",
            (
                f'{stack.name}/{service} {WUD_TAG_INCLUDE_LABEL} is "{value}", '
                f'expected "{exact_tags_regex((target_tag,))}".'
            ),
            target,
            stack,
            service,
        )
    )
    return None


def _digest_unpin_candidate_target(target: WudTarget) -> bool:
    return is_digest_target_line(target)


def _digest_unpin_service_matches_target(image: str, target: WudTarget) -> bool:
    if not digest_from_image(image):
        return False
    return repo_key(image) == target.repo


def _digest_unpin_issue(
    code: str,
    message: str,
    target: WudTarget,
    stack: ComposeStack,
    service: str,
) -> DryRunPlanIssue:
    return DryRunPlanIssue(
        severity="error",
        code=code,
        message=message,
        line_no=target.line_no,
        stack=stack.name,
        service=service,
        hint=(
            "Review the Compose image, WUD tag include label, and digest tag "
            "provenance before applying this pending update."
        ),
    )


def _label_value(labels: Sequence[tuple[str, str]], key: str) -> str:
    for label_key, label_value in labels:
        if label_key == key:
            return label_value
    return ""


def _unique_digest_unpin_updates(
    updates: Sequence[DigestUnpinUpdate],
) -> tuple[DigestUnpinUpdate, ...]:
    unique: dict[tuple[str, str, str], DigestUnpinUpdate] = {}
    for update in updates:
        key = (update.old_image, update.resolved_tag, update.target_digest)
        existing = unique.get(key)
        if existing is None:
            unique[key] = update
            continue
        services = tuple(sorted({*existing.services, *update.services}))
        unique[key] = digest_unpin_update_from_values(
            old_image=update.old_image,
            resolved_tag=update.resolved_tag,
            target_digest=update.target_digest,
            services=services,
        )
    return tuple(unique[key] for key in sorted(unique))
