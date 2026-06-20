"""Shared matching, scope, and status helpers for updater planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .compose import ComposeStack, ServiceImage
from .compose_rewrite import WUD_TAG_INCLUDE_LABEL, _exact_tag_include_matches
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_tag,
    image_with_tag,
    repo_key,
    tag_value_valid,
)
from .updater_models import (
    DigestPinUpdate,
    FailureRecord,
    Match,
    StackStatus,
    TagExclusionUpdate,
    UpdateScope,
)
from .wud_file import WudTarget


RECREATE_STACK_LABEL = "WUD-UPDATER-RECREATE-STACK"
RECREATE_STACK_LABEL_FORMAT = f'{{{{ index .Config.Labels "{RECREATE_STACK_LABEL}" }}}}'


def _services_for_image(
    service_images: Sequence[ServiceImage],
    image: str,
) -> tuple[str, ...]:
    return tuple(sorted({item.service for item in service_images if item.image == image}))


def _services_for_target_match(
    service_images: Sequence[ServiceImage],
    image: str,
    target: WudTarget,
    resolved: str,
    allow_repo: bool,
    *,
    allow_digest_pin_rematch: bool = False,
) -> tuple[str, ...] | None:
    if image_matches_resolved_target(image, resolved, allow_repo):
        return _services_for_image(service_images, image)
    if not allow_digest_pin_rematch:
        return None
    services = _digest_pin_rematch_services(service_images, image, target)
    if services:
        return services
    return None


def _digest_pin_rematch_services(
    service_images: Sequence[ServiceImage],
    image: str,
    target: WudTarget,
) -> tuple[str, ...]:
    if not target.digest or not image_has_tag(target.first):
        return ()
    if image_has_tag(image) or repo_key(image) != target.repo:
        return ()
    tag = image_tag(target.first)
    if not tag_value_valid(tag):
        return ()
    return tuple(
        sorted(
            item.service
            for item in service_images
            if item.image == image
            and _exact_tag_include_matches(
                _service_image_label_value(item, WUD_TAG_INCLUDE_LABEL),
                tag,
            )
        )
    )


def _service_image_label_value(service_image: ServiceImage, key: str) -> str:
    for label_key, label_value in service_image.labels:
        if label_key == key:
            return label_value
    return ""


def _network_mode_providers(service_images: Sequence[ServiceImage]) -> dict[str, str]:
    providers: dict[str, str] = {}
    for item in service_images:
        mode = item.network_mode.strip()
        if not mode.startswith("service:"):
            continue
        provider = mode.removeprefix("service:").strip()
        if provider:
            providers[item.service] = provider
    return providers


def _expand_network_mode_services(
    services: Sequence[str],
    providers: Mapping[str, str],
) -> tuple[tuple[str, ...], bool]:
    consumers_by_provider = _network_mode_consumers(providers)
    expanded: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()
    uses_network_provider = False

    def visit(service: str) -> None:
        nonlocal uses_network_provider
        if service in seen:
            return
        if service in visiting:
            return

        visiting.add(service)
        consumers = consumers_by_provider.get(service, ())
        if consumers:
            uses_network_provider = True

        if service not in seen:
            expanded.append(service)
            seen.add(service)

        for consumer in consumers:
            visit(consumer)
        visiting.remove(service)

    for service in services:
        visit(service)
    return tuple(expanded), uses_network_provider


def _network_mode_consumers(providers: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    consumers: dict[str, list[str]] = {}
    for service, provider in providers.items():
        if provider and provider != service:
            consumers.setdefault(provider, []).append(service)
    return {
        provider: tuple(sorted(service_names))
        for provider, service_names in consumers.items()
    }


def _ordered_unique(services: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for service in services:
        if service in seen:
            continue
        seen.add(service)
        ordered.append(service)
    return tuple(ordered)


def _update_services(matches: Sequence[Match]) -> tuple[str, ...] | None:
    services = sorted({match.service for match in matches if match.service})
    if not services:
        return None
    if any(not match.service for match in matches):
        return None
    return tuple(services)


def _label_value_is_true(value: str) -> bool:
    return value.strip().lower() == "true"


def _scope_plan_label(scope: UpdateScope) -> str:
    if scope.services is not None:
        return " ".join(scope.services)
    if scope.stack_reason:
        if scope.pull_services is not None:
            return (
                f"{' '.join(scope.pull_services)} "
                f"(stack-level recreate: {RECREATE_STACK_LABEL}=true)"
            )
        return f"stack-level recreate ({RECREATE_STACK_LABEL}=true)"
    return "stack-level fallback"


def _stacks_to_update(matches: Sequence[Match]) -> tuple[ComposeStack, ...]:
    stacks: dict[int, ComposeStack] = {}
    for match in matches:
        stacks[match.stack.index] = match.stack
    return tuple(stacks[idx] for idx in sorted(stacks))


def _plan_line(
    line_no: int,
    target: str,
    resolved: str,
    desired_tag: str,
    digest_pin: DigestPinUpdate | None = None,
) -> str:
    if digest_pin is not None:
        return (
            f"line {line_no}: {resolved} -> {digest_pin.final_image} "
            f"(digest pin tag={digest_pin.resolved_tag} digest={digest_pin.planned_digest})"
        )
    if desired_tag:
        desired_image = image_with_tag(resolved, desired_tag)
        return f"line {line_no}: {resolved} -> {desired_image} (tag update)"
    if target == resolved:
        return f"line {line_no}: {target}"
    return f"line {line_no}: {target} -> {resolved}"


def _failed_line_numbers(
    matches: Sequence[Match],
    stack_statuses: Mapping[int, StackStatus],
) -> list[int]:
    failed: list[int] = []
    for line_no in sorted({match.target.line_no for match in matches}):
        idxs = {match.stack.index for match in matches if match.target.line_no == line_no}
        if any(
            stack_statuses.get(idx, StackStatus("failure", "missing")).status
            != "success"
            for idx in idxs
        ):
            failed.append(line_no)
    return failed


def _first_match_by_line(matches: Sequence[Match]) -> dict[int, Match]:
    first: dict[int, Match] = {}
    for match in matches:
        first.setdefault(match.target.line_no, match)
    return first


def _tag_exclusion_preflight_matches(
    matches: Sequence[Match],
    updates: Sequence[TagExclusionUpdate],
) -> tuple[Match, ...]:
    keys = {
        (update.stack.index, update.service, update.source_line)
        for update in updates
    }
    return tuple(
        match
        for match in matches
        if (match.stack.index, match.service, match.target.line_no) in keys
    )


def _unique_matches(matches: Iterable[Match]) -> tuple[Match, ...]:
    unique: list[Match] = []
    seen: set[tuple[int, int, str, str, str]] = set()
    for match in matches:
        key = (
            match.stack.index,
            match.target.line_no,
            match.resolved,
            match.compose_image,
            match.service,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return tuple(unique)


def _failed_match_for_line(
    line_no: int,
    matches: Sequence[Match],
    stack_statuses: Mapping[int, StackStatus],
) -> Match | None:
    first: Match | None = None
    for match in matches:
        if match.target.line_no != line_no:
            continue
        if first is None:
            first = match
        status = stack_statuses.get(match.stack.index, StackStatus("failure", "missing"))
        if status.status != "success":
            return match
    return first


def _line_status_reason(
    line_no: int,
    matches: Sequence[Match],
    stack_statuses: Mapping[int, StackStatus],
) -> str:
    statuses = [
        stack_statuses.get(match.stack.index, StackStatus("failure", "missing"))
        for match in matches
        if match.target.line_no == line_no
    ]
    failure_reasons = {
        status.reason for status in statuses if status.status != "success"
    }
    if failure_reasons:
        return min(failure_reasons)
    reasons = {status.reason for status in statuses}
    if "updated" in reasons:
        return "updated"
    if "already-current" in reasons:
        return "already-current"
    return min(reasons) if reasons else "missing"


def _preflight_status_reason(
    stack_index: int,
    failures: Sequence[FailureRecord],
) -> str:
    reasons = sorted(
        {
            failure.reason
            for failure in failures
            if failure.stack.index == stack_index
        }
    )
    if len(reasons) == 1:
        return reasons[0]
    if reasons:
        return "preflight-failed"
    return "missing"


def _service_key(match: Match) -> str:
    if match.service:
        return f"{match.stack.name}/{match.service}"
    return f"{match.stack.name}/{match.compose_image}"


def _target_image_for_match(match: Match) -> str:
    if match.target.desired_tag:
        return image_with_tag(match.compose_image, match.target.desired_tag)
    return match.resolved


def _failure_target_lines(matches: Sequence[Match]) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[int, str, str, str, str, str]] = set()
    for match in sorted(
        matches,
        key=lambda item: (
            item.target.line_no,
            item.target.first,
            item.resolved,
            item.compose_image,
            item.service,
        ),
    ):
        suffix = f" sha256={match.target.digest}" if match.target.digest else ""
        suffix += f" tag={match.target.desired_tag}" if match.target.desired_tag else ""
        key = (
            match.target.line_no,
            match.target.first,
            suffix,
            match.resolved,
            match.compose_image,
            match.service,
        )
        if key in seen:
            continue
        seen.add(key)
        service = match.service or "stack-level"
        lines.append(
            f"line {match.target.line_no}: {match.target.first}{suffix}; "
            f"resolved={match.resolved}; compose_image={match.compose_image}; "
            f"service={service}"
        )
    return lines
