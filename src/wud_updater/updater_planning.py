"""Shared side-effect-light planning helpers for updater and WebUI plans."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from .compose import ComposeBindMount, ComposeStack, ServiceImage
from .compose_rewrite import (
    DIGEST_PIN_MARKER_PREFIX,
    WUD_TAG_INCLUDE_LABEL,
    _exact_tag_include_matches,
    compose_escape_dollars,
    exact_tags_regex,
)
from .digest_verifier import DigestResolveResult, DigestVerifier
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_tag,
    image_with_digest,
    image_with_tag,
    normalize_digest,
    repo_key,
    tag_value_valid,
)
from .updater_models import (
    DigestPinCandidate,
    DigestPinUpdate,
    FailureRecord,
    Match,
    StackStatus,
    TagExclusionUpdate,
    TagUpdate,
    UpdateScope,
    UpdaterError,
)
from .wud_file import WudTarget


RECREATE_STACK_LABEL = "WUD-UPDATER-RECREATE-STACK"
RECREATE_STACK_LABEL_FORMAT = f'{{{{ index .Config.Labels "{RECREATE_STACK_LABEL}" }}}}'
_HELPER_ONLY_MOUNT_PREFIXES = (Path("/host"), Path("/docker-host"), Path("/container-host"))


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


def _container_bind_mount_path_issue(
    mount: ComposeBindMount,
    *,
    docker_base: Path,
) -> str:
    source = Path(mount.source)
    if not source.is_absolute():
        return ""
    for prefix in _HELPER_ONLY_MOUNT_PREFIXES:
        if _path_is_or_under(source, prefix):
            base_hint = ""
            if _path_is_or_under(source, docker_base):
                base_hint = f" from DOCKER_BASE={docker_base}"
            return (
                f"the source path is under helper-only prefix {prefix}{base_hint}; "
                "the Docker daemon must be able to see bind sources at the same path"
            )
    return ""


def _path_is_or_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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


def _digest_check_image(match: Match) -> str:
    if match.target.desired_tag:
        return image_with_tag(match.compose_image, match.target.desired_tag)
    return match.resolved


def _digest_check_allow_repo(match: Match) -> bool:
    if match.target.desired_tag:
        return False
    return match.resolved != match.target.first or not image_has_tag(match.resolved)


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


def _unique_tag_exclusion_updates(
    updates: Iterable[TagExclusionUpdate],
) -> list[TagExclusionUpdate]:
    unique: dict[tuple[int, str, str, str, str], TagExclusionUpdate] = {}
    for update in updates:
        key = (
            update.stack.index,
            update.service,
            update.image_repo,
            update.tag,
            update.scope,
        )
        unique.setdefault(key, update)
    return [unique[key] for key in sorted(unique)]


def digest_pin_update_from_values(
    *,
    old_image: str,
    resolved_tag: str,
    planned_digest: str,
    services: Sequence[str],
) -> DigestPinUpdate:
    tag_update = TagUpdate(
        old_image=old_image,
        desired_tag=resolved_tag,
        new_image=image_with_tag(old_image, resolved_tag),
        services=tuple(sorted(services)),
    )
    return _digest_pin_update_from_tag_update(tag_update, planned_digest)


def _digest_pin_match_tag(match: Match) -> str:
    if match.target.desired_tag:
        return match.target.desired_tag
    if not match.target.digest or not image_has_tag(match.target.first):
        return ""
    tag = image_tag(match.target.first)
    return tag if tag_value_valid(tag) else ""


def _digest_pin_candidates(
    matches: Sequence[Match],
) -> tuple[DigestPinCandidate, ...]:
    services_by_key: dict[tuple[str, str, str], set[str]] = {}
    digests_by_key: dict[tuple[str, str, str], set[str]] = {}
    for match in matches:
        resolved_tag = _digest_pin_match_tag(match)
        if not resolved_tag:
            continue
        resolved_image = image_with_tag(match.compose_image, resolved_tag)
        key = (match.compose_image, resolved_tag, resolved_image)
        services_by_key.setdefault(key, set())
        if match.service:
            services_by_key[key].add(match.service)
        if not match.target.desired_tag:
            digests_by_key.setdefault(key, set()).add(
                normalize_digest(match.target.digest)
            )

    candidates: list[DigestPinCandidate] = []
    for key, services in sorted(services_by_key.items()):
        old_image, resolved_tag, resolved_image = key
        digests = sorted(digests_by_key.get(key, set()))
        if len(digests) > 1:
            raise UpdaterError(
                "Conflicting digest-pin digests for "
                f"{resolved_image}: {', '.join(digests)}"
            )
        candidates.append(
            DigestPinCandidate(
                old_image=old_image,
                resolved_tag=resolved_tag,
                resolved_image=resolved_image,
                planned_digest=digests[0] if digests else "",
                services=tuple(sorted(services)),
            )
        )
    return tuple(candidates)


def _digest_pin_tag_materialization_updates(
    updates: Sequence[DigestPinUpdate],
) -> tuple[TagUpdate, ...]:
    tag_updates: list[TagUpdate] = []
    for update in updates:
        if (
            update.old_image == update.resolved_image
            or "@sha256:" not in update.old_image
        ):
            continue
        tag_updates.append(
            TagUpdate(
                old_image=update.old_image,
                desired_tag=update.resolved_tag,
                new_image=update.resolved_image,
                services=update.services,
            )
        )
    return tuple(tag_updates)


def _resolve_digest_pin_candidate(
    verifier: DigestVerifier,
    candidate: DigestPinCandidate,
) -> DigestResolveResult:
    if candidate.planned_digest:
        return verifier.verify_tag_digest(
            candidate.resolved_image,
            candidate.planned_digest,
        )
    return verifier.resolve_tag_digest(candidate.resolved_image)


def _digest_pin_resolve_error(
    resolved_image: str,
    result: DigestResolveResult,
) -> str:
    if result.reason == "stale-digest":
        current = f", current {normalize_digest(result.digest)}" if result.digest else ""
        return (
            f"Digest-pin target moved for {resolved_image}: "
            f"planned digest is no longer current{current}"
        )
    return f"Could not resolve digest-pin target for {resolved_image}: {result.reason}"


def _digest_pin_update_from_tag_update(
    update: TagUpdate,
    planned_digest: str,
) -> DigestPinUpdate:
    digest = normalize_digest(planned_digest)
    watch_tag = update.desired_tag
    return DigestPinUpdate(
        old_image=update.old_image,
        resolved_tag=update.desired_tag,
        resolved_image=update.new_image,
        planned_digest=digest,
        final_image=image_with_digest(update.old_image, digest),
        watch_tag=watch_tag,
        marker=f"{DIGEST_PIN_MARKER_PREFIX}{watch_tag}",
        label_key=WUD_TAG_INCLUDE_LABEL,
        label_value=compose_escape_dollars(exact_tags_regex((watch_tag,))),
        services=update.services,
    )


def _tag_exclusion_updates_by_stack(
    updates: Sequence[TagExclusionUpdate],
) -> dict[ComposeStack, list[TagExclusionUpdate]]:
    grouped: dict[ComposeStack, list[TagExclusionUpdate]] = {}
    for update in updates:
        grouped.setdefault(update.stack, []).append(update)
    return grouped


def _first_tag_exclusion_by_line(
    updates: Sequence[TagExclusionUpdate],
) -> dict[int, TagExclusionUpdate]:
    first: dict[int, TagExclusionUpdate] = {}
    for update in updates:
        first.setdefault(update.source_line, update)
    return first


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
