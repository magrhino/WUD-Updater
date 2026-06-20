"""Shared planning helpers that are not tied to updater orchestration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from .compose import ComposeBindMount, ComposeStack
from .images import image_has_tag, image_with_tag
from .updater_digest_pin import (
    _digest_pin_candidates as _digest_pin_candidates,
    _digest_pin_match_tag as _digest_pin_match_tag,
    _digest_pin_resolve_error as _digest_pin_resolve_error,
    _digest_pin_tag_materialization_updates as _digest_pin_tag_materialization_updates,
    _resolve_digest_pin_candidate as _resolve_digest_pin_candidate,
    digest_pin_update_from_values as digest_pin_update_from_values,
)
from .updater_matching import (
    RECREATE_STACK_LABEL as RECREATE_STACK_LABEL,
    RECREATE_STACK_LABEL_FORMAT as RECREATE_STACK_LABEL_FORMAT,
    _expand_network_mode_services as _expand_network_mode_services,
    _failed_line_numbers as _failed_line_numbers,
    _failed_match_for_line as _failed_match_for_line,
    _failure_target_lines as _failure_target_lines,
    _first_match_by_line as _first_match_by_line,
    _label_value_is_true as _label_value_is_true,
    _line_status_reason as _line_status_reason,
    _network_mode_providers as _network_mode_providers,
    _ordered_unique as _ordered_unique,
    _plan_line as _plan_line,
    _preflight_status_reason as _preflight_status_reason,
    _scope_plan_label as _scope_plan_label,
    _service_key as _service_key,
    _services_for_image as _services_for_image,
    _services_for_target_match as _services_for_target_match,
    _stacks_to_update as _stacks_to_update,
    _tag_exclusion_preflight_matches as _tag_exclusion_preflight_matches,
    _target_image_for_match as _target_image_for_match,
    _unique_matches as _unique_matches,
    _update_services as _update_services,
)
from .updater_models import Match, TagExclusionUpdate, TagUpdate


_HELPER_ONLY_MOUNT_PREFIXES = (Path("/host"), Path("/docker-host"), Path("/container-host"))


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


def _digest_check_image(match: Match) -> str:
    if match.target.desired_tag:
        return image_with_tag(match.compose_image, match.target.desired_tag)
    return match.resolved


def _digest_check_allow_repo(match: Match) -> bool:
    if match.target.desired_tag:
        return False
    return match.resolved != match.target.first or not image_has_tag(match.resolved)


def _tag_updates(matches: Sequence[Match]) -> tuple[TagUpdate, ...]:
    services_by_update: dict[tuple[str, str, str], set[str]] = {}
    for match in matches:
        if match.target.desired_tag:
            new_image = image_with_tag(match.compose_image, match.target.desired_tag)
            key = (match.compose_image, match.target.desired_tag, new_image)
            services_by_update.setdefault(key, set())
            if match.service:
                services_by_update[key].add(match.service)
    return tuple(
        TagUpdate(
            old_image=old_image,
            desired_tag=desired_tag,
            new_image=new_image,
            services=tuple(sorted(services)),
        )
        for (old_image, desired_tag, new_image), services in sorted(
            services_by_update.items()
        )
    )


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
