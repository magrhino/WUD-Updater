"""WebUI retag review route handlers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Protocol

from fastapi import HTTPException, Request

from . import web_database
from .command import CommandRunner
from .compose import ComposeCli, ComposeDiscoveryError, ServiceImage
from .compose_rewrite import (
    WUD_TAG_INCLUDE_LABEL,
    compose_unescape_dollars,
)
from .config import ConfigError, UpdaterConfig
from .digest_provenance import DigestTagProvenance
from .images import image_tag, repo_key, tag_value_valid
from .web_auth import _safe_exception_detail, _settings
from .web_models import (
    RetagTargetItem,
    RetagTargetsResponse,
    WebSettings,
)


KEEP_CURRENT_CHOICE = "keep-current"
SWITCH_TO_CONCRETE_CHOICE = "switch-to-concrete"
_REGEX_SPECIAL_CHARS = "\\^$.*+?()[]{}|"


class EffectiveConfigLoader(Protocol):
    def __call__(self, settings: WebSettings) -> UpdaterConfig: ...


_effective_config_loader: EffectiveConfigLoader | None = None


def configure(*, effective_config_loader: EffectiveConfigLoader) -> None:
    global _effective_config_loader
    _effective_config_loader = effective_config_loader


def api_retag_targets(request: Request) -> RetagTargetsResponse:
    return retag_targets_response(_settings(request))


def retag_targets_response(settings: WebSettings) -> RetagTargetsResponse:
    config = _effective_config(settings)
    runner = (
        CommandRunner(env=settings.command_env)
        if settings.command_env is not None
        else CommandRunner()
    )
    compose = ComposeCli(runner=runner)
    try:
        stacks = compose.discover_stacks(
            config.docker_base,
            project_base=settings.host_docker_base,
            ignore_paths=config.compose_ignore_paths,
        )
    except ComposeDiscoveryError as exc:
        return RetagTargetsResponse(
            status="unavailable",
            count=0,
            warnings=[str(exc)],
        )

    known_by_service = web_database.known_digest_state_by_service(settings)
    items: list[RetagTargetItem] = []
    for stack in stacks:
        project_directory = (
            "" if stack.project_directory is None else str(stack.project_directory)
        )
        for service_image in stack.service_images:
            service_key = f"{stack.name}/{service_image.service}"
            known = known_by_service.get(service_key)
            provenance = None if known is None else known.digest_provenance
            items.append(
                _retag_target_item(
                    service_key=service_key,
                    stack=stack.name,
                    service_image=service_image,
                    directory=str(stack.directory),
                    compose_file=stack.file,
                    project_directory=project_directory,
                    known_image="" if known is None else known.image,
                    provenance=provenance,
                )
            )

    return RetagTargetsResponse(
        status="ready",
        count=len(items),
        items=items,
        warnings=[],
    )


def _effective_config(settings: WebSettings) -> UpdaterConfig:
    if _effective_config_loader is None:
        return settings.config
    try:
        return _effective_config_loader(settings)
    except ConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail=_safe_exception_detail(
                settings,
                "could not read effective config",
                exc,
            ),
        ) from exc


def _retag_target_item(
    *,
    service_key: str,
    stack: str,
    service_image: ServiceImage,
    directory: str,
    compose_file: str,
    project_directory: str,
    known_image: str,
    provenance: DigestTagProvenance | None,
) -> RetagTargetItem:
    label_value = _label_value(service_image.labels, WUD_TAG_INCLUDE_LABEL)
    tracking_tag, tracking_tag_source = _tracking_tag(
        service_image.image,
        label_value=label_value,
        provenance=provenance,
    )
    retag_available, retag_reason = _retag_eligibility(
        service_image.image,
        known_image=known_image,
        tracking_tag=tracking_tag,
        tracking_tag_source=tracking_tag_source,
        label_value=label_value,
        provenance=provenance,
    )
    choices = [KEEP_CURRENT_CHOICE]
    if retag_available:
        choices.append(SWITCH_TO_CONCRETE_CHOICE)
    return RetagTargetItem(
        service_key=service_key,
        stack=stack,
        service=service_image.service,
        image=service_image.image,
        image_repo=repo_key(service_image.image),
        current_tag=image_tag(service_image.image),
        tracking_tag=tracking_tag,
        tracking_tag_source=tracking_tag_source,
        proposed_tag="" if provenance is None else provenance.resolved_tag,
        final_image="" if provenance is None else provenance.final_image,
        retag_available=retag_available,
        retag_reason=retag_reason,
        choices=choices,
        label_key=WUD_TAG_INCLUDE_LABEL,
        label_value=label_value,
        directory=directory,
        compose_file=compose_file,
        project_directory=project_directory,
        digest_provenance=(
            None if provenance is None else asdict(provenance)
        ),
    )


def _tracking_tag(
    image: str,
    *,
    label_value: str,
    provenance: DigestTagProvenance | None,
) -> tuple[str, str]:
    if label_value:
        label_tag = _single_exact_tag(label_value)
        if label_tag:
            return label_tag, "label"
        return "", "unsupported-label"
    if provenance is not None and provenance.watch_tag:
        return provenance.watch_tag, "provenance"
    tag = image_tag(image)
    if tag:
        return tag, "image"
    return "", ""


def _retag_eligibility(
    image: str,
    *,
    known_image: str,
    tracking_tag: str,
    tracking_tag_source: str,
    label_value: str,
    provenance: DigestTagProvenance | None,
) -> tuple[bool, str]:
    if tracking_tag_source == "unsupported-label":
        return False, "unsupported-tracking-label"
    if tracking_tag != "latest":
        return False, "not-latest-tracking"
    if provenance is None:
        return False, "missing-provenance"
    if not _provenance_matches_image(
        image,
        known_image=known_image,
        provenance=provenance,
    ):
        return False, "stale-provenance"
    if not provenance.resolved_tag or provenance.resolved_tag == "latest":
        return False, "missing-concrete-tag"
    if not tag_value_valid(provenance.resolved_tag):
        return False, "invalid-candidate-tag"
    if not provenance.target_digest or not provenance.final_image:
        return False, "missing-final-image"
    if label_value and not _single_exact_tag(label_value):
        return False, "unsupported-tracking-label"
    return True, "eligible"


def _provenance_matches_image(
    image: str,
    *,
    known_image: str,
    provenance: DigestTagProvenance,
) -> bool:
    return image in {known_image, provenance.final_image}


def _label_value(labels: tuple[tuple[str, str], ...], key: str) -> str:
    values: Mapping[str, str] = dict(labels)
    return values.get(key, "")


def _single_exact_tag(value: str) -> str:
    normalized = compose_unescape_dollars(value)
    if tag_value_valid(normalized):
        return normalized
    if not normalized.startswith("^") or not normalized.endswith("$"):
        return ""
    tag_chars: list[str] = []
    index = 1
    end = len(normalized) - 1
    while index < end:
        char = normalized[index]
        if char == "\\":
            index += 1
            if index >= end:
                return ""
            escaped = normalized[index]
            if escaped not in _REGEX_SPECIAL_CHARS:
                return ""
            tag_chars.append(escaped)
            index += 1
            continue
        if char in _REGEX_SPECIAL_CHARS:
            return ""
        tag_chars.append(char)
        index += 1
    tag = "".join(tag_chars)
    return tag if tag_value_valid(tag) else ""
