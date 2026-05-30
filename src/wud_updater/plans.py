"""Structured dry-run planning for WebUI update previews."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .command import CommandError, CommandRunner
from .compose import ComposeCli, ComposeDiscoveryError, ComposeStack
from .config import UpdaterConfig
from .docker_cli import DockerCli
from .images import image_has_tag, image_matches_resolved_target, image_with_tag
from .updater import (
    RECREATE_STACK_LABEL,
    RECREATE_STACK_LABEL_FORMAT,
    Match,
    TagOverride,
    TagUpdate,
    UpdateScope,
    _container_bind_mount_path_issue,
    _expand_network_mode_services,
    _label_value_is_true,
    _network_mode_providers,
    _ordered_unique,
    _scope_plan_label,
    _services_for_image,
    _stacks_to_update,
    _update_services,
)
from .wud_file import ParsedWudFile, WudTarget, parse_wud_file


class PlanInputError(ValueError):
    """Raised when a requested plan cannot be built from the submitted lines."""


class PlanFileMissing(FileNotFoundError):
    """Raised when the WUD file is missing for a selected-line plan."""


@dataclass(frozen=True)
class DryRunPlanIssue:
    severity: str
    code: str
    message: str
    line_no: int | None = None
    stack: str = ""
    service: str = ""


@dataclass(frozen=True)
class DryRunPlanTarget:
    line_no: int
    raw: str
    image: str
    resolved_image: str
    digest: str
    desired_tag: str
    matched: bool
    action: str


@dataclass(frozen=True)
class DryRunPlanLine:
    line_no: int
    raw: str
    image: str
    resolved_image: str
    compose_image: str
    target_image: str
    service: str
    digest: str
    desired_tag: str
    action: str


@dataclass(frozen=True)
class DryRunPlanTagUpdate:
    old_image: str
    desired_tag: str
    new_image: str
    services: tuple[str, ...]


@dataclass(frozen=True)
class DryRunPlanAction:
    kind: str
    description: str
    cwd: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class DryRunPlanStack:
    name: str
    directory: str
    compose_file: str
    project_directory: str
    services_label: str
    services: tuple[str, ...]
    pull_services: tuple[str, ...]
    stop_services: tuple[str, ...]
    force_recreate: bool
    up_no_deps: bool
    tag_updates: tuple[DryRunPlanTagUpdate, ...] = ()
    actions: tuple[DryRunPlanAction, ...] = ()
    lines: tuple[DryRunPlanLine, ...] = ()


@dataclass(frozen=True)
class DryRunPlanSkipped:
    line_no: int
    raw: str
    image: str
    desired_tag: str
    reason: str


@dataclass(frozen=True)
class DryRunPlanSummary:
    target_count: int
    matched_target_count: int
    stack_count: int
    service_count: int
    skipped_count: int
    issue_count: int


@dataclass(frozen=True)
class DryRunPlan:
    plan_id: str
    dry_run: bool
    can_apply: bool
    status: str
    source_file: str
    mode: str
    max_wait: int
    selected_line_numbers: tuple[int, ...]
    summary: DryRunPlanSummary
    targets: tuple[DryRunPlanTarget, ...] = ()
    stacks: tuple[DryRunPlanStack, ...] = ()
    skipped: tuple[DryRunPlanSkipped, ...] = ()
    issues: tuple[DryRunPlanIssue, ...] = ()


@dataclass(frozen=True)
class PendingGroupingItem:
    line_no: int
    raw: str
    image: str
    key: str
    repo: str
    has_tag: bool
    allow_repo: bool
    digest: str
    desired_tag: str
    resolved_image: str
    target_image: str
    compose_images: tuple[str, ...]
    services: tuple[str, ...]
    action: str


@dataclass(frozen=True)
class PendingStackGroup:
    name: str
    directory: str
    compose_file: str
    project_directory: str
    services_label: str
    services: tuple[str, ...]
    line_numbers: tuple[int, ...]
    items: tuple[PendingGroupingItem, ...]


@dataclass(frozen=True)
class PendingGroupingResult:
    status: str
    groups: tuple[PendingStackGroup, ...] = ()
    unmatched: tuple[PendingGroupingItem, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class _PlanBuilder:
    config: UpdaterConfig
    line_numbers: Sequence[int]
    allow_tag_updates: bool = False
    tag_overrides: Sequence[TagOverride] = ()
    host_docker_base: Path | None = None
    command_runner: CommandRunner | None = None
    docker: DockerCli = field(init=False)
    compose: ComposeCli = field(init=False)

    def __post_init__(self) -> None:
        runner = self.command_runner or CommandRunner()
        self.docker = DockerCli(runner=runner)
        self.compose = ComposeCli(runner=runner)

    def build(self) -> DryRunPlan:
        selected = _selected_line_numbers(self.line_numbers)
        full_parse = _read_wud_file(self.config.wud_out_file)
        _validate_selected_targets(full_parse, selected)
        parsed = parse_wud_file(self.config.wud_out_file, selected_lines=selected)
        parsed = self._apply_tag_overrides(parsed)

        issues = [
            DryRunPlanIssue(
                severity="warning",
                code="wud-parse-warning",
                message=warning,
            )
            for warning in parsed.warnings
        ]
        targets_by_line = {target.line_no: target for target in parsed.targets}
        skipped: list[DryRunPlanSkipped] = []
        matches: list[Match] = []
        stacks: tuple[ComposeStack, ...] = ()

        try:
            stacks = self.compose.discover_stacks(
                self.config.docker_base,
                project_base=self.host_docker_base,
            )
        except ComposeDiscoveryError as exc:
            issues.append(
                DryRunPlanIssue(
                    severity="error",
                    code="compose-discovery-failed",
                    message=str(exc),
                )
            )
        else:
            matches, skipped = self._build_matches(parsed, stacks)
            issues.extend(self._unmatched_issues(parsed.targets, matches, skipped))
            issues.extend(self._tag_update_plan_issues(matches))
            issues.extend(self._manifest_issues(matches))
            issues.extend(self._preflight_issues(matches))

        plan_stacks = self._plan_stacks(matches)
        targets = self._plan_targets(targets_by_line, matches, skipped)
        status = _plan_status(matches, skipped, issues)
        summary = DryRunPlanSummary(
            target_count=len(parsed.targets),
            matched_target_count=len({match.target.line_no for match in matches}),
            stack_count=len(plan_stacks),
            service_count=_service_count(plan_stacks),
            skipped_count=len(skipped),
            issue_count=len(issues),
        )
        plan = DryRunPlan(
            plan_id="",
            dry_run=True,
            can_apply=False,
            status=status,
            source_file=str(self.config.wud_out_file),
            mode=self.config.update_mode,
            max_wait=self.config.max_wait,
            selected_line_numbers=selected,
            summary=summary,
            targets=targets,
            stacks=plan_stacks,
            skipped=tuple(skipped),
            issues=tuple(issues),
        )
        return replace(
            plan,
            plan_id=_plan_id(
                plan,
                config=self.config,
                allow_tag_updates=self.allow_tag_updates,
                tag_overrides=self.tag_overrides,
                host_docker_base=self.host_docker_base,
                wud_file_hash=_file_sha256(self.config.wud_out_file),
            ),
        )

    def _apply_tag_overrides(self, parsed: ParsedWudFile) -> ParsedWudFile:
        overrides = {item.line_no: item.tag for item in self.tag_overrides}
        if not overrides:
            return parsed
        if not self.allow_tag_updates:
            raise PlanInputError("tag_overrides require allow_tag_updates=true")

        targets_by_line = {target.line_no: target for target in parsed.targets}
        missing = sorted(set(overrides) - set(targets_by_line))
        if missing:
            values = ", ".join(str(line_no) for line_no in missing)
            raise PlanInputError(
                "tag_overrides must reference selected WUD tag update lines: "
                + values
            )

        updated_targets: list[WudTarget] = []
        for target in parsed.targets:
            override = overrides.get(target.line_no)
            if override is None:
                updated_targets.append(target)
                continue
            if not target.desired_tag:
                raise PlanInputError(
                    f"tag_overrides line {target.line_no} does not target a tag update"
                )
            updated_targets.append(replace(target, desired_tag=override))

        return ParsedWudFile(
            lines=parsed.lines,
            targets=tuple(updated_targets),
            warnings=parsed.warnings,
        )

    def _build_matches(
        self,
        parsed: ParsedWudFile,
        stacks: Sequence[ComposeStack],
    ) -> tuple[list[Match], list[DryRunPlanSkipped]]:
        return _match_targets(
            parsed,
            stacks,
            self.docker,
            allow_tag_updates=self.allow_tag_updates,
        )

    def _unmatched_issues(
        self,
        targets: Sequence[WudTarget],
        matches: Sequence[Match],
        skipped: Sequence[DryRunPlanSkipped],
    ) -> list[DryRunPlanIssue]:
        matched_lines = {match.target.line_no for match in matches}
        skipped_reasons = {item.line_no: item.reason for item in skipped}
        issues: list[DryRunPlanIssue] = []
        for target in targets:
            if target.line_no in matched_lines:
                continue
            reason = skipped_reasons.get(target.line_no, "unmatched")
            severity = "warning" if reason == "tag-updates-disabled" else "error"
            message = (
                "Tag update entries require allow_tag_updates=true."
                if reason == "tag-updates-disabled"
                else "No Compose stack matched this WUD entry."
            )
            issues.append(
                DryRunPlanIssue(
                    severity=severity,
                    code=reason,
                    message=message,
                    line_no=target.line_no,
                )
            )
        return issues

    def _tag_update_plan_issues(
        self,
        matches: Sequence[Match],
    ) -> list[DryRunPlanIssue]:
        desired_by_service: dict[tuple[int, str, str], set[str]] = {}
        issues: list[DryRunPlanIssue] = []
        for match in matches:
            if not match.target.desired_tag:
                continue
            if not match.service:
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="tag-update-service-unmapped",
                        message=(
                            "Tag update cannot be safely rewritten because the "
                            "Compose service image could not be mapped."
                        ),
                        line_no=match.target.line_no,
                        stack=match.stack.name,
                    )
                )
                continue
            key = (match.stack.index, match.service, match.compose_image)
            desired_by_service.setdefault(key, set()).add(match.target.desired_tag)

        for stack_index, service, image in sorted(desired_by_service):
            desired = desired_by_service[(stack_index, service, image)]
            if len(desired) <= 1:
                continue
            stack_name = next(
                (
                    match.stack.name
                    for match in matches
                    if match.stack.index == stack_index
                ),
                str(stack_index),
            )
            issues.append(
                DryRunPlanIssue(
                    severity="error",
                    code="conflicting-tag-updates",
                    message=(
                        f"Conflicting tag updates for service {service} image "
                        f"{image}: {', '.join(sorted(desired))}."
                    ),
                    stack=stack_name,
                    service=service,
                )
            )
        return issues

    def _manifest_issues(self, matches: Sequence[Match]) -> list[DryRunPlanIssue]:
        issues: list[DryRunPlanIssue] = []
        for update in _tag_updates(matches):
            try:
                self.docker.manifest_inspect(update.new_image)
            except CommandError as exc:
                detail = _first_error_line(exc)
                suffix = f": {detail}" if detail else ""
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="tag-manifest-unavailable",
                        message=(
                            f"Invalid or unavailable remote tag "
                            f"{update.old_image} -> {update.new_image}{suffix}"
                        ),
                    )
                )
        return issues

    def _preflight_issues(self, matches: Sequence[Match]) -> list[DryRunPlanIssue]:
        issues: list[DryRunPlanIssue] = []
        for stack in _stacks_to_update(matches):
            stack_matches = [
                match for match in matches if match.stack.index == stack.index
            ]
            scope = self._update_scope(stack, stack_matches)
            scoped_services = set(scope.services or ())

            runtime_issues = self.compose.try_service_runtime_port_issues(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            )
            runtime_scope = scoped_services or {issue.service for issue in runtime_issues}
            for issue in runtime_issues:
                if issue.service not in runtime_scope:
                    continue
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="compose-port-invalid",
                        message=(
                            f"Compose service {issue.service} has invalid "
                            f"{issue.field} value {issue.value!r}: {issue.reason}."
                        ),
                        stack=stack.name,
                        service=issue.service,
                    )
                )

            mounts = self.compose.try_service_bind_mounts(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            )
            mount_scope = scoped_services or {mount.service for mount in mounts}
            for mount in mounts:
                if mount.service not in mount_scope:
                    continue
                issue = _container_bind_mount_path_issue(
                    mount,
                    docker_base=self.config.docker_base,
                )
                if not issue:
                    continue
                target = f" -> {mount.target}" if mount.target else ""
                issues.append(
                    DryRunPlanIssue(
                        severity="error",
                        code="bind-mount-path-invalid",
                        message=(
                            f"Compose bind mount resolves to {mount.source}"
                            f"{target}; {issue}."
                        ),
                        stack=stack.name,
                        service=mount.service,
                    )
                )
        return issues

    def _plan_stacks(self, matches: Sequence[Match]) -> tuple[DryRunPlanStack, ...]:
        stacks: list[DryRunPlanStack] = []
        for stack in _stacks_to_update(matches):
            stack_matches = [
                match for match in matches if match.stack.index == stack.index
            ]
            scope = self._update_scope(stack, stack_matches)
            tag_updates = _tag_updates(stack_matches)
            plan_tag_updates = tuple(
                DryRunPlanTagUpdate(
                    old_image=update.old_image,
                    desired_tag=update.desired_tag,
                    new_image=update.new_image,
                    services=update.services,
                )
                for update in tag_updates
            )
            stacks.append(
                DryRunPlanStack(
                    name=stack.name,
                    directory=str(stack.directory),
                    compose_file=stack.file,
                    project_directory=(
                        "" if stack.project_directory is None else str(stack.project_directory)
                    ),
                    services_label=_scope_plan_label(scope),
                    services=tuple(scope.services or ()),
                    pull_services=tuple(scope.pull_services or ()),
                    stop_services=tuple(scope.stop_services or ()),
                    force_recreate=scope.force_recreate,
                    up_no_deps=scope.up_no_deps,
                    tag_updates=plan_tag_updates,
                    actions=self._actions(stack, scope, plan_tag_updates),
                    lines=self._plan_lines(stack_matches),
                )
            )
        return tuple(stacks)

    def _plan_targets(
        self,
        targets_by_line: Mapping[int, WudTarget],
        matches: Sequence[Match],
        skipped: Sequence[DryRunPlanSkipped],
    ) -> tuple[DryRunPlanTarget, ...]:
        matches_by_line: dict[int, list[Match]] = {}
        for match in matches:
            matches_by_line.setdefault(match.target.line_no, []).append(match)
        skipped_by_line = {item.line_no: item for item in skipped}
        targets: list[DryRunPlanTarget] = []
        for line_no in sorted(targets_by_line):
            target = targets_by_line[line_no]
            line_matches = matches_by_line.get(line_no, [])
            resolved = line_matches[0].resolved if line_matches else target.first
            action = _target_action(target, bool(line_matches), skipped_by_line.get(line_no))
            targets.append(
                DryRunPlanTarget(
                    line_no=target.line_no,
                    raw=target.raw,
                    image=target.first,
                    resolved_image=resolved,
                    digest=target.digest,
                    desired_tag=target.desired_tag,
                    matched=bool(line_matches),
                    action=action,
                )
            )
        return tuple(targets)

    def _plan_lines(self, matches: Sequence[Match]) -> tuple[DryRunPlanLine, ...]:
        seen: set[tuple[int, str, str, str]] = set()
        lines: list[DryRunPlanLine] = []
        for match in matches:
            key = (
                match.target.line_no,
                match.resolved,
                match.compose_image,
                match.service,
            )
            if key in seen:
                continue
            seen.add(key)
            target_image = (
                image_with_tag(match.compose_image, match.target.desired_tag)
                if match.target.desired_tag
                else match.resolved
            )
            lines.append(
                DryRunPlanLine(
                    line_no=match.target.line_no,
                    raw=match.target.raw,
                    image=match.target.first,
                    resolved_image=match.resolved,
                    compose_image=match.compose_image,
                    target_image=target_image,
                    service=match.service,
                    digest=match.target.digest,
                    desired_tag=match.target.desired_tag,
                    action="tag-update" if match.target.desired_tag else "update",
                )
            )
        return tuple(lines)

    def _actions(
        self,
        stack: ComposeStack,
        scope: UpdateScope,
        tag_updates: Sequence[DryRunPlanTagUpdate],
    ) -> tuple[DryRunPlanAction, ...]:
        actions: list[DryRunPlanAction] = []
        for update in tag_updates:
            actions.append(
                DryRunPlanAction(
                    kind="compose-tag-update",
                    description=(
                        f"Rewrite {update.old_image} to {update.new_image} "
                        f"for {', '.join(update.services)}"
                    ),
                    cwd=str(stack.directory),
                )
            )
        actions.append(
            self._compose_action(
                stack,
                "pull",
                ("pull",),
                scope.pull_services,
                "Pull matched image updates",
            )
        )
        stop_services = (
            scope.stop_services if scope.stop_services is not None else scope.services
        )
        if self.config.update_mode == "pause":
            actions.append(
                self._compose_action(
                    stack,
                    "pause",
                    ("pause",),
                    scope.services,
                    "Pause affected services before recreate",
                )
            )
        elif self.config.update_mode == "stop":
            actions.append(
                self._compose_action(
                    stack,
                    "stop",
                    ("stop",),
                    stop_services,
                    "Stop affected services before recreate",
                )
            )

        up_args = ["up", "-d", "--remove-orphans"]
        if scope.force_recreate:
            up_args.append("--force-recreate")
        if scope.services and scope.up_no_deps:
            up_args.append("--no-deps")
        wait_handled = False
        if self.config.update_mode != "pause" and self.compose.up_wait_supported(
            stack.directory,
            stack.file,
            project_directory=stack.project_directory,
        ):
            up_args.extend(["--wait", "--wait-timeout", str(self.config.max_wait)])
            wait_handled = True
        actions.append(
            self._compose_action(
                stack,
                "up",
                tuple(up_args),
                scope.services,
                "Recreate services with updated images",
            )
        )
        if self.config.update_mode == "pause":
            actions.append(
                self._compose_action(
                    stack,
                    "unpause",
                    ("unpause",),
                    scope.services,
                    "Unpause services before health check",
                )
            )
        if not wait_handled:
            actions.append(
                DryRunPlanAction(
                    kind="health-wait",
                    description=f"Wait up to {self.config.max_wait}s for health",
                    cwd=str(stack.directory),
                )
            )
        return tuple(actions)

    def _compose_action(
        self,
        stack: ComposeStack,
        kind: str,
        compose_args: Sequence[str],
        services: Sequence[str] | None,
        description: str,
    ) -> DryRunPlanAction:
        return DryRunPlanAction(
            kind=kind,
            description=description,
            cwd=str(stack.directory),
            args=tuple(
                _compose_args(
                    stack.file,
                    *compose_args,
                    *_service_args(services),
                    project_directory=stack.project_directory,
                )
            ),
        )

    def _update_scope(self, stack: ComposeStack, matches: Sequence[Match]) -> UpdateScope:
        services = _update_services(matches)
        if services is None:
            return UpdateScope(
                services=None,
                pull_services=None,
                stop_services=self._stack_stop_services(stack),
                force_recreate=True,
            )
        network_providers = _network_mode_providers(stack.service_images)
        lifecycle_services, uses_network_provider = _expand_network_mode_services(
            services,
            network_providers,
        )
        missing_providers = self._missing_network_mode_providers(
            stack,
            services,
            network_providers,
        )
        if missing_providers:
            lifecycle_services = _ordered_unique(
                (*missing_providers, *lifecycle_services)
            )
            uses_network_provider = True
        stop_services = (
            services
            if missing_providers
            else tuple(reversed(lifecycle_services))
            if uses_network_provider
            else lifecycle_services
        )

        label_cid = self._stack_recreate_label_cid(stack, lifecycle_services)
        if label_cid:
            return UpdateScope(
                services=None,
                pull_services=services,
                stack_reason=(
                    f"selected service scope container {label_cid} has "
                    f"{RECREATE_STACK_LABEL}=true"
                ),
                stop_services=self._stack_stop_services(stack),
                force_recreate=False,
            )
        return UpdateScope(
            services=lifecycle_services,
            pull_services=services,
            stop_services=stop_services,
            up_no_deps=not uses_network_provider,
        )

    def _missing_network_mode_providers(
        self,
        stack: ComposeStack,
        services: Sequence[str],
        providers: Mapping[str, str],
    ) -> tuple[str, ...]:
        missing: list[str] = []
        for service in services:
            provider = providers.get(service)
            if not provider or provider in services or provider in missing:
                continue
            cids = self.compose.ps_quiet(
                stack.directory,
                stack.file,
                (provider,),
                project_directory=stack.project_directory,
            )
            if not cids:
                missing.append(provider)
        return tuple(missing)

    def _stack_stop_services(self, stack: ComposeStack) -> tuple[str, ...] | None:
        try:
            services = self.compose.config_services(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            )
        except CommandError:
            return None
        if not services:
            return None
        return tuple(reversed(services))

    def _stack_recreate_label_cid(
        self,
        stack: ComposeStack,
        services: Sequence[str],
    ) -> str:
        for cid in self.compose.ps_quiet(
            stack.directory,
            stack.file,
            services,
            project_directory=stack.project_directory,
        ):
            for value in self.docker.try_inspect(cid, RECREATE_STACK_LABEL_FORMAT):
                if _label_value_is_true(value):
                    return cid
        return ""


def build_dry_run_plan(
    config: UpdaterConfig,
    *,
    line_numbers: Sequence[int],
    allow_tag_updates: bool = False,
    tag_overrides: Sequence[TagOverride] = (),
    host_docker_base: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DryRunPlan:
    runner = CommandRunner(env=environ) if environ is not None else CommandRunner()
    return _PlanBuilder(
        config=config,
        line_numbers=line_numbers,
        allow_tag_updates=allow_tag_updates,
        tag_overrides=tag_overrides,
        host_docker_base=host_docker_base,
        command_runner=runner,
    ).build()


def resolve_pending_groups(
    config: UpdaterConfig,
    parsed: ParsedWudFile,
    *,
    host_docker_base: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> PendingGroupingResult:
    runner = CommandRunner(env=environ) if environ is not None else CommandRunner()
    docker = DockerCli(runner=runner)
    compose = ComposeCli(runner=runner)

    try:
        stacks = compose.discover_stacks(
            config.docker_base,
            project_base=host_docker_base,
        )
    except ComposeDiscoveryError as exc:
        return PendingGroupingResult(
            status="unavailable",
            unmatched=tuple(
                _pending_grouping_item(target, action=_target_action_name(target))
                for target in parsed.targets
            ),
            warnings=(str(exc),),
        )

    matches, skipped = _match_targets(
        parsed,
        stacks,
        docker,
        allow_tag_updates=True,
    )
    targets_by_line = {target.line_no: target for target in parsed.targets}
    return PendingGroupingResult(
        status="ready",
        groups=_pending_stack_groups(matches),
        unmatched=tuple(
            _pending_grouping_item(targets_by_line[item.line_no], action=item.reason)
            for item in skipped
            if item.line_no in targets_by_line
        ),
    )


def _match_targets(
    parsed: ParsedWudFile,
    stacks: Sequence[ComposeStack],
    docker: DockerCli,
    *,
    allow_tag_updates: bool,
) -> tuple[list[Match], list[DryRunPlanSkipped]]:
    container_images = {item.name: item.image for item in docker.try_container_images()}
    matches: list[Match] = []
    skipped: list[DryRunPlanSkipped] = []
    seen: set[tuple[int, int, str, str, str]] = set()

    for target in parsed.targets:
        if target.desired_tag and not allow_tag_updates:
            skipped.append(_skipped(target, "tag-updates-disabled"))
            continue

        resolved = container_images.get(target.first, target.first)
        allow_repo = (
            target.allow_repo or resolved != target.first or not image_has_tag(resolved)
        )

        for stack in stacks:
            for image in stack.images:
                if not image_matches_resolved_target(image, resolved, allow_repo):
                    continue
                services = _services_for_image(stack.service_images, image)
                if services:
                    for service in services:
                        key = (stack.index, target.line_no, resolved, image, service)
                        if key in seen:
                            continue
                        matches.append(Match(stack, target, resolved, image, service))
                        seen.add(key)
                else:
                    key = (stack.index, target.line_no, resolved, image, "")
                    if key in seen:
                        continue
                    matches.append(Match(stack, target, resolved, image, ""))
                    seen.add(key)

    matches.sort(
        key=lambda item: (
            item.stack.index,
            item.target.line_no,
            item.target.first,
            item.resolved,
            item.compose_image,
            item.service,
        )
    )
    matched_lines = {match.target.line_no for match in matches}
    skipped_lines = {item.line_no for item in skipped}
    for target in parsed.targets:
        if target.line_no not in matched_lines and target.line_no not in skipped_lines:
            skipped.append(_skipped(target, "unmatched"))
    return matches, skipped


def _pending_stack_groups(matches: Sequence[Match]) -> tuple[PendingStackGroup, ...]:
    groups: list[PendingStackGroup] = []
    for stack in _stacks_to_update(matches):
        stack_matches = [match for match in matches if match.stack.index == stack.index]
        services = _ordered_unique(
            match.service for match in stack_matches if match.service
        )
        items = _pending_grouping_items(stack_matches)
        groups.append(
            PendingStackGroup(
                name=stack.name,
                directory=str(stack.directory),
                compose_file=stack.file,
                project_directory=(
                    ""
                    if stack.project_directory is None
                    else str(stack.project_directory)
                ),
                services_label=_pending_services_label(services),
                services=services,
                line_numbers=tuple(item.line_no for item in items),
                items=items,
            )
        )
    return tuple(groups)


def _pending_grouping_items(
    matches: Sequence[Match],
) -> tuple[PendingGroupingItem, ...]:
    items: list[PendingGroupingItem] = []
    for line_no in sorted({match.target.line_no for match in matches}):
        line_matches = [match for match in matches if match.target.line_no == line_no]
        target = line_matches[0].target
        resolved = line_matches[0].resolved
        compose_images = _ordered_unique(match.compose_image for match in line_matches)
        services = _ordered_unique(
            match.service for match in line_matches if match.service
        )
        items.append(
            _pending_grouping_item(
                target,
                resolved_image=resolved,
                compose_images=compose_images,
                services=services,
                action=_target_action_name(target),
            )
        )
    return tuple(items)


def _pending_grouping_item(
    target: WudTarget,
    *,
    action: str,
    resolved_image: str = "",
    compose_images: Sequence[str] = (),
    services: Sequence[str] = (),
) -> PendingGroupingItem:
    resolved = resolved_image or target.first
    return PendingGroupingItem(
        line_no=target.line_no,
        raw=target.raw,
        image=target.first,
        key=target.key,
        repo=target.repo,
        has_tag=target.has_tag,
        allow_repo=target.allow_repo,
        digest=target.digest,
        desired_tag=target.desired_tag,
        resolved_image=resolved,
        target_image=_pending_target_image(target, resolved, compose_images),
        compose_images=tuple(compose_images),
        services=tuple(services),
        action=action,
    )


def _pending_target_image(
    target: WudTarget,
    resolved_image: str,
    compose_images: Sequence[str],
) -> str:
    if not target.desired_tag:
        return resolved_image
    base_image = compose_images[0] if compose_images else resolved_image
    return image_with_tag(base_image, target.desired_tag)


def _target_action_name(target: WudTarget) -> str:
    return "tag-update" if target.desired_tag else "update"


def _pending_services_label(services: Sequence[str]) -> str:
    return ", ".join(services) if services else "stack-level"


def _read_wud_file(path: Path) -> ParsedWudFile:
    try:
        return parse_wud_file(path)
    except FileNotFoundError as exc:
        raise PlanFileMissing(f"WUD file not found: {path}") from exc


def _file_sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise PlanFileMissing(f"WUD file not found: {path}") from exc
    return hashlib.sha256(data).hexdigest()


def _plan_id(
    plan: DryRunPlan,
    *,
    config: UpdaterConfig,
    allow_tag_updates: bool,
    tag_overrides: Sequence[TagOverride],
    host_docker_base: Path | None,
    wud_file_hash: str,
) -> str:
    plan_payload = asdict(plan)
    plan_payload.pop("plan_id", None)
    plan_payload.pop("can_apply", None)
    payload = {
        "version": 1,
        "allow_tag_updates": allow_tag_updates,
        "tag_overrides": [
            {"line_no": item.line_no, "tag": item.tag}
            for item in sorted(tag_overrides, key=lambda item: item.line_no)
        ],
        "docker_base": str(config.docker_base),
        "host_docker_base": "" if host_docker_base is None else str(host_docker_base),
        "max_wait": config.max_wait,
        "mode": config.update_mode,
        "plan": plan_payload,
        "source_file": str(config.wud_out_file),
        "wud_file_sha256": wud_file_hash,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selected_line_numbers(line_numbers: Sequence[int]) -> tuple[int, ...]:
    selected = tuple(sorted(set(line_numbers)))
    if not selected:
        raise PlanInputError("line_numbers must not be empty")
    invalid = [line_no for line_no in selected if line_no < 1]
    if invalid:
        values = ", ".join(str(line_no) for line_no in invalid)
        raise PlanInputError(f"line_numbers must be positive integers: {values}")
    return selected


def _validate_selected_targets(
    parsed: ParsedWudFile,
    selected: Sequence[int],
) -> None:
    target_lines = {target.line_no for target in parsed.targets}
    missing = [line_no for line_no in selected if line_no not in target_lines]
    if missing:
        values = ", ".join(str(line_no) for line_no in missing)
        raise PlanInputError(
            "line_numbers must reference actionable WUD target lines: " + values
        )


def _skipped(target: WudTarget, reason: str) -> DryRunPlanSkipped:
    return DryRunPlanSkipped(
        line_no=target.line_no,
        raw=target.raw,
        image=target.first,
        desired_tag=target.desired_tag,
        reason=reason,
    )


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


def _target_action(
    target: WudTarget,
    matched: bool,
    skipped: DryRunPlanSkipped | None,
) -> str:
    if skipped is not None:
        return skipped.reason
    if target.desired_tag and matched:
        return "tag-update"
    if matched:
        return "update"
    return "unmatched"


def _plan_status(
    matches: Sequence[Match],
    skipped: Sequence[DryRunPlanSkipped],
    issues: Sequence[DryRunPlanIssue],
) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "blocked"
    if not matches:
        return "empty"
    if skipped:
        return "blocked"
    return "ready"


def _service_count(stacks: Sequence[DryRunPlanStack]) -> int:
    services: set[tuple[str, str]] = set()
    for stack in stacks:
        for service in stack.services or stack.pull_services:
            services.add((stack.name, service))
    return len(services)


def _first_error_line(exc: CommandError) -> str:
    for line in (*exc.result.stderr_lines, *exc.result.stdout_lines):
        if line.strip():
            return line.strip()
    return ""


def _compose_args(
    file: str,
    *args: str,
    project_directory: str | Path | None = None,
) -> list[str]:
    command = ["docker", "compose"]
    if project_directory is not None:
        command.extend(["--project-directory", str(project_directory)])
    command.extend(["-f", file, *args])
    return command


def _service_args(services: Sequence[str] | None) -> tuple[str, ...]:
    if services is None:
        return ()
    return tuple(service for service in services if service)
