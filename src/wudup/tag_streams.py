"""Strict Docker tag-stream detection and WebUI decision planning."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .command import CommandError
from .compose_rewrite import plan_compose_tag_stream_update
from .docker_cli import DockerCli
from .images import image_repo_ref, image_tag, image_with_tag
from .lsio_updates import is_lsio_repo, parse_lsio_tag
from .plan_models import DryRunPlanIssue, PlanInputError
from .updater_models import (
    ComposeTagRewriteError,
    Match,
    TagOverride,
    TagStreamDecision,
    TagStreamLabelRewriteApproval,
    TagStreamUpdate,
)


_STRICT_VERSION_TAG_RE = re.compile(
    r"^(?P<version>v?\d+\.\d+\.\d+)(?P<suffix>[-_.].+)?$",
    re.ASCII,
)
_REGEX_SPECIAL_RE = re.compile(r"([\\^$.*+?()[\]{}|])")


@dataclass(frozen=True)
class TagStreamParts:
    version: str
    suffix: str

    @property
    def stream(self) -> str:
        return self.suffix[1:] if self.suffix else "default"


@dataclass(frozen=True)
class TagStreamHint:
    current_stream: str
    reported_stream: str


@dataclass(frozen=True)
class TagStreamPlanResult:
    matches: tuple[Match, ...]
    issues: tuple[DryRunPlanIssue, ...]
    updates_by_stack: Mapping[int, tuple[TagStreamUpdate, ...]]
    selected_tags_by_line: Mapping[int, str]


def parse_tag_stream(tag: str) -> TagStreamParts | None:
    match = _STRICT_VERSION_TAG_RE.fullmatch(tag)
    if match is None:
        return None
    return TagStreamParts(
        version=match.group("version"),
        suffix=match.group("suffix") or "",
    )


def pending_tag_stream_hint(
    *,
    image_repo: str,
    current_tag: str,
    reported_tag: str,
) -> TagStreamHint | None:
    current = parse_tag_stream(current_tag)
    reported = parse_tag_stream(reported_tag)
    if (
        current is None
        or reported is None
        or current.suffix == reported.suffix
        or _excluded_lsio_stream(image_repo, current_tag, reported_tag)
    ):
        return None
    return TagStreamHint(
        current_stream=current.stream,
        reported_stream=reported.stream,
    )


def tag_stream_include_regex(tag: str) -> str:
    parts = parse_tag_stream(tag)
    if parts is None:
        raise ValueError(f"tag is not a strict version stream: {tag}")
    prefix = "v" if parts.version.startswith("v") else ""
    suffix = _REGEX_SPECIAL_RE.sub(r"\\\1", parts.suffix)
    return rf"^{prefix}\d+\.\d+\.\d+{suffix}$"


def plan_tag_stream_changes(
    docker: DockerCli,
    matches: Sequence[Match],
    *,
    decisions: Sequence[TagStreamDecision] = (),
    label_rewrite_approvals: Sequence[TagStreamLabelRewriteApproval] = (),
    tag_overrides: Sequence[TagOverride] = (),
) -> TagStreamPlanResult:
    decision_by_line = _decision_map(decisions)
    override_lines = {item.line_no for item in tag_overrides}
    matches_by_line: dict[int, list[Match]] = {}
    for match in matches:
        matches_by_line.setdefault(match.target.line_no, []).append(match)

    issues: list[DryRunPlanIssue] = []
    selected_tags_by_line: dict[int, str] = {}
    updates_by_stack: dict[int, list[TagStreamUpdate]] = {}
    verified_lines: set[int] = set()
    used_approvals: set[TagStreamLabelRewriteApproval] = set()
    manifest_cache: dict[str, bool] = {}

    for line_no, line_matches in sorted(matches_by_line.items()):
        target = line_matches[0].target
        reported_tag = target.desired_tag
        if not reported_tag:
            continue
        candidates = _line_candidates(line_matches, reported_tag)
        if not candidates:
            continue
        if len({candidate[1] for candidate in candidates}) != 1:
            issues.append(
                DryRunPlanIssue(
                    severity="error",
                    code="tag-stream-change-ambiguous",
                    message=(
                        "Selected services use different current update streams; "
                        "review their Compose images separately."
                    ),
                    line_no=line_no,
                )
            )
            continue

        current, alternate_tag = candidates[0]
        alternate_images = {
            image_with_tag(match.compose_image, alternate_tag)
            for match in line_matches
        }
        verified = all(
            _manifest_exists(docker, image, manifest_cache)
            for image in sorted(alternate_images)
        )
        if not verified:
            issues.append(
                DryRunPlanIssue(
                    severity="warning",
                    code="possible-tag-stream-change",
                    message=(
                        f"Possible update stream change: {current.stream} to "
                        f"{parse_tag_stream(reported_tag).stream}. A same-stream "
                        "target could not be verified."
                    ),
                    line_no=line_no,
                    details={
                        "current_stream": current.stream,
                        "reported_stream": parse_tag_stream(reported_tag).stream,
                    },
                )
            )
            continue

        verified_lines.add(line_no)
        if line_no in override_lines:
            raise PlanInputError(
                f"tag_overrides line {line_no} has a verified stream change; "
                "submit an explicit tag_stream_decision"
            )
        decision = decision_by_line.get(line_no)
        preserve_regex = tag_stream_include_regex(alternate_tag)
        switch_regex = tag_stream_include_regex(reported_tag)
        if decision is None:
            issues.append(
                DryRunPlanIssue(
                    severity="error",
                    code="tag-stream-change",
                    message=(
                        f"WUD proposed changing the update stream from {current.stream} "
                        f"to {parse_tag_stream(reported_tag).stream}. Choose whether to "
                        "preserve or switch streams."
                    ),
                    line_no=line_no,
                    details={
                        "current_tag": image_tag(line_matches[0].compose_image),
                        "reported_tag": reported_tag,
                        "current_stream": current.stream,
                        "reported_stream": parse_tag_stream(reported_tag).stream,
                        "same_stream_tag": alternate_tag,
                        "preserve_label_regex": preserve_regex,
                        "switch_label_regex": switch_regex,
                    },
                )
            )
            continue

        selected_tag = alternate_tag if decision == "preserve" else reported_tag
        selected_regex = preserve_regex if decision == "preserve" else switch_regex
        selected_tags_by_line[line_no] = selected_tag
        for match in line_matches:
            try:
                stream_update = plan_compose_tag_stream_update(
                    match.stack.directory / match.stack.file,
                    line_no=line_no,
                    stack_name=match.stack.name,
                    service=match.service,
                    current_image=match.compose_image,
                    current_tag=image_tag(match.compose_image),
                    reported_tag=reported_tag,
                    selected_tag=selected_tag,
                    decision=decision,
                    proposed_label_regex=selected_regex,
                    approvals=label_rewrite_approvals,
                )
            except (ComposeTagRewriteError, OSError) as exc:
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="compose-tag-stream-rewrite-unsafe",
                        message=f"Tag stream configuration cannot be rewritten safely: {exc}",
                        line_no=line_no,
                        stack=match.stack.name,
                        service=match.service,
                    )
                )
                continue
            updates_by_stack.setdefault(match.stack.index, []).append(stream_update)
            matching_approval = (
                _matching_approval(label_rewrite_approvals, stream_update)
                if stream_update.reason == "approved"
                else None
            )
            if matching_approval is not None:
                used_approvals.add(matching_approval)
            if stream_update.reason == "approval-required":
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="compose-tag-stream-label-rewrite-unapproved",
                        message=(
                            f"Service {match.service} has a custom wud.tag.include "
                            "expression. Approve its exact replacement before apply."
                        ),
                        line_no=line_no,
                        stack=match.stack.name,
                        service=match.service,
                        details={
                            "label_key": stream_update.label_key,
                            "current_label_value": stream_update.current_label_value,
                            "selected_tag": stream_update.selected_tag,
                            "proposed_label_value": stream_update.proposed_label_value,
                            "proposed_label_regex": stream_update.proposed_label_regex,
                        },
                    )
                )

    unused_decisions = sorted(set(decision_by_line) - verified_lines)
    if unused_decisions:
        values = ", ".join(str(value) for value in unused_decisions)
        raise PlanInputError(
            "tag_stream_decisions must reference verified stream-change lines: "
            + values
        )
    unused_approvals = set(label_rewrite_approvals) - used_approvals
    if unused_approvals:
        raise PlanInputError(
            "tag_stream_label_rewrite_approvals contains a stale or forged approval"
        )

    adjusted_matches = tuple(
        replace(
            match,
            target=replace(
                match.target,
                desired_tag=selected_tags_by_line.get(
                    match.target.line_no,
                    match.target.desired_tag,
                ),
            ),
        )
        for match in matches
    )
    return TagStreamPlanResult(
        matches=adjusted_matches,
        issues=tuple(issues),
        updates_by_stack={
            stack_index: tuple(updates)
            for stack_index, updates in updates_by_stack.items()
        },
        selected_tags_by_line=selected_tags_by_line,
    )


def _line_candidates(
    matches: Sequence[Match],
    reported_tag: str,
) -> list[tuple[TagStreamParts, str]]:
    candidates: list[tuple[TagStreamParts, str]] = []
    for match in matches:
        current_tag = image_tag(match.compose_image)
        hint = pending_tag_stream_hint(
            image_repo=image_repo_ref(match.compose_image),
            current_tag=current_tag,
            reported_tag=reported_tag,
        )
        if hint is None:
            continue
        current = parse_tag_stream(current_tag)
        reported = parse_tag_stream(reported_tag)
        if current is None or reported is None:
            continue
        candidates.append((current, f"{reported.version}{current.suffix}"))
    return candidates


def _excluded_lsio_stream(
    image_repo: str,
    current_tag: str,
    reported_tag: str,
) -> bool:
    return (
        is_lsio_repo(image_repo)
        or parse_lsio_tag(current_tag).kind == "build"
        or parse_lsio_tag(reported_tag).kind == "build"
    )


def _manifest_exists(
    docker: DockerCli,
    image: str,
    cache: dict[str, bool],
) -> bool:
    if image in cache:
        return cache[image]
    try:
        docker.manifest_inspect(image)
    except CommandError:
        cache[image] = False
    else:
        cache[image] = True
    return cache[image]


def _decision_map(decisions: Sequence[TagStreamDecision]) -> dict[int, str]:
    values: dict[int, str] = {}
    for item in decisions:
        if item.line_no in values:
            raise PlanInputError(
                f"tag_stream_decisions line {item.line_no} was provided more than once"
            )
        if item.decision not in {"preserve", "switch"}:
            raise PlanInputError(
                f"tag_stream_decisions line {item.line_no} has invalid decision"
            )
        values[item.line_no] = item.decision
    return values


def _matching_approval(
    approvals: Sequence[TagStreamLabelRewriteApproval],
    update: TagStreamUpdate,
) -> TagStreamLabelRewriteApproval | None:
    for approval in approvals:
        if (
            approval.line_no == update.line_no
            and approval.stack == update.stack
            and approval.service == update.service
            and approval.label_key == update.label_key
            and approval.current_label_value == update.current_label_value
            and approval.selected_tag == update.selected_tag
            and approval.proposed_label_value == update.proposed_label_value
        ):
            return approval
    return None
