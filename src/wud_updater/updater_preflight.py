"""Preflight validation helpers for ``update-from-wud``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import compose_rewrite, updater_logging
from .command import CommandError
from .compose import ComposeBindMount, ComposeRuntimePortIssue, ComposeStack
from .updater_digest_pin import _digest_pin_match_tag
from .updater_matching import _preflight_status_reason, _stacks_to_update
from .updater_models import (
    ComposeTagRewriteError,
    Match,
    StackStatus,
    UpdaterError,
)
from .updater_planning import _container_bind_mount_path_issue
from .wud_file import ParsedWudFile, WudTarget


@dataclass
class _PreflightIssueRecords:
    messages_by_stack: dict[int, list[str]] = field(default_factory=dict)
    services_by_stack: dict[int, set[str]] = field(default_factory=dict)

    def add(
        self,
        stack: ComposeStack,
        service: str,
        messages: Sequence[str],
    ) -> None:
        self.messages_by_stack.setdefault(stack.index, []).extend(messages)
        self.services_by_stack.setdefault(stack.index, set()).add(service)

    def messages_for(self, stack: ComposeStack) -> list[str] | None:
        return self.messages_by_stack.get(stack.index)

    def services_for(self, stack: ComposeStack) -> tuple[str, ...] | None:
        return tuple(sorted(self.services_by_stack.get(stack.index, ()))) or None


_ComposePreflightValidator = Callable[
    [Any, ComposeStack, Sequence[Match], _PreflightIssueRecords],
    bool,
]


def validate_tag_manifests(runner: Any, matches: Sequence[Match]) -> bool:
    ok = True
    for update in runner._tag_updates(matches):
        try:
            runner.docker.manifest_inspect(update.new_image)
        except CommandError as exc:
            ok = False
            runner.log.error(
                "Invalid or unavailable remote tag: "
                f"{update.old_image} -> {update.new_image}"
            )
            for line in exc.result.stderr_lines:
                runner.log.error(
                    f"manifest stderr: {updater_logging.sanitize_stream(line)}"
                )
            runner._log_command_result(exc.result)
        else:
            runner.log.info(
                "Validated remote tag: "
                f"{update.old_image} -> {update.new_image}"
            )
    return ok


def validate_tag_update_plan(runner: Any, matches: Sequence[Match]) -> bool:
    ok = True
    desired_by_service: dict[tuple[int, str, str], set[str]] = {}
    for match in matches:
        if not match.target.desired_tag:
            continue
        if not match.service:
            ok = False
            runner.log.error(
                f"[{match.stack.name}] Tag update for {match.compose_image} "
                "cannot be safely rewritten because the compose service image "
                "could not be mapped."
            )
            continue
        key = (match.stack.index, match.service, match.compose_image)
        desired_by_service.setdefault(key, set()).add(match.target.desired_tag)

    for stack_index, service, image in sorted(desired_by_service):
        desired = desired_by_service[(stack_index, service, image)]
        if len(desired) <= 1:
            continue
        ok = False
        stack_name = next(
            (
                match.stack.name
                for match in matches
                if match.stack.index == stack_index
            ),
            str(stack_index),
        )
        runner.log.error(
            f"[{stack_name}] Conflicting tag updates for service {service} "
            f"image {image}: {', '.join(sorted(desired))}"
        )
    return ok


def validate_compose_bind_mount_paths(
    runner: Any,
    matches: Sequence[Match],
) -> bool:
    return _validate_compose_preflight(
        runner,
        matches,
        reason="bind-mount-path-invalid",
        validate_stack=_validate_stack_bind_mount_paths,
    )


def _validate_compose_preflight(
    runner: Any,
    matches: Sequence[Match],
    *,
    reason: str,
    validate_stack: _ComposePreflightValidator,
) -> bool:
    ok = True
    stacks = _stacks_to_update(matches)
    records = _PreflightIssueRecords()
    for stack in stacks:
        stack_matches = _matches_for_stack(matches, stack)
        if validate_stack(runner, stack, stack_matches, records):
            continue
        ok = False
    _record_compose_preflight_failures(
        runner,
        matches,
        stacks,
        records,
        reason=reason,
    )
    return ok


def _validate_stack_bind_mount_paths(
    runner: Any,
    stack: ComposeStack,
    stack_matches: Sequence[Match],
    records: _PreflightIssueRecords,
) -> bool:
    stack_ok = True
    mounts = runner.compose.try_service_bind_mounts(
        stack.directory,
        stack.file,
        project_directory=stack.project_directory,
    )
    if not mounts:
        return stack_ok

    scoped_services = _scoped_preflight_services(
        runner,
        stack,
        stack_matches,
        (mount.service for mount in mounts),
    )
    for mount in mounts:
        if mount.service not in scoped_services:
            continue
        issue = _container_bind_mount_path_issue(
            mount,
            docker_base=runner.options.docker_base,
        )
        if not issue:
            continue
        stack_ok = False
        messages = runner._bind_mount_path_issue_messages(stack, mount, issue)
        runner._log_bind_mount_path_issue(messages)
        if runner.options.dry_run:
            continue
        records.add(stack, mount.service, messages)
    return stack_ok


def _record_compose_preflight_failures(
    runner: Any,
    matches: Sequence[Match],
    stacks: Sequence[ComposeStack],
    records: _PreflightIssueRecords,
    *,
    reason: str,
) -> None:
    if runner.options.dry_run:
        return
    for stack in stacks:
        messages = records.messages_for(stack)
        if not messages:
            continue
        runner._record_failure(
            stack,
            _matches_for_stack(matches, stack),
            phase="preflight",
            reason=reason,
            services=records.services_for(stack),
            health_details="\n".join(messages),
        )


def _matches_for_stack(
    matches: Sequence[Match],
    stack: ComposeStack,
) -> list[Match]:
    return [match for match in matches if match.stack.index == stack.index]


def _scoped_preflight_services(
    runner: Any,
    stack: ComposeStack,
    stack_matches: Sequence[Match],
    service_names: Iterable[str],
) -> set[str]:
    scope = runner._update_scope(stack, stack_matches)
    if scope.services is None:
        return set(service_names)
    return set(scope.services)


def validate_compose_runtime_ports(
    runner: Any,
    matches: Sequence[Match],
) -> bool:
    return _validate_compose_preflight(
        runner,
        matches,
        reason="compose-port-invalid",
        validate_stack=_validate_stack_runtime_ports,
    )


def _validate_stack_runtime_ports(
    runner: Any,
    stack: ComposeStack,
    stack_matches: Sequence[Match],
    records: _PreflightIssueRecords,
) -> bool:
    stack_ok = True
    issues = runner.compose.try_service_runtime_port_issues(
        stack.directory,
        stack.file,
        project_directory=stack.project_directory,
    )
    if not issues:
        return stack_ok

    scoped_services = _scoped_preflight_services(
        runner,
        stack,
        stack_matches,
        (issue.service for issue in issues),
    )
    for issue in issues:
        if issue.service not in scoped_services:
            continue
        stack_ok = False
        message = runner._compose_runtime_port_issue_message(stack, issue)
        runner._log_preflight_issue(message)
        if runner.options.dry_run:
            continue
        records.add(stack, issue.service, (message,))
    return stack_ok


def compose_runtime_port_issue_message(
    stack: ComposeStack,
    issue: ComposeRuntimePortIssue,
) -> str:
    return (
        f"[{stack.name}] Compose service {issue.service} has invalid "
        f"{issue.field} value {issue.value!r}: {issue.reason}."
    )


def bind_mount_path_issue_messages(
    runner: Any,
    stack: ComposeStack,
    mount: ComposeBindMount,
    issue: str,
) -> list[str]:
    target = f" -> {mount.target}" if mount.target else ""
    messages = [
        f"[{stack.name}] Compose bind mount for service {mount.service} "
        f"resolves to {mount.source}{target}; {issue}."
    ]
    if runner.options.host_docker_base is not None:
        messages.append(
            f"[{stack.name}] HOST_DOCKER_BASE is set to "
            f"{runner.options.host_docker_base}; verify it is the Docker "
            f"daemon-visible host root that corresponds to "
            f"DOCKER_BASE={runner.options.docker_base}."
        )
        return messages
    messages.append(
        f"[{stack.name}] Mount the Compose root at the same absolute path "
        "the Docker daemon uses, then set DOCKER_BASE to that path "
        "(for example DOCKER_BASE=/srv/docker with /srv/docker:/srv/docker), "
        "or keep the helper path and set HOST_DOCKER_BASE=/srv/docker "
        "to the matching daemon-visible host root."
    )
    return messages


def log_bind_mount_path_issue(runner: Any, messages: Sequence[str]) -> None:
    for message in messages:
        log_preflight_issue(runner, message)


def log_preflight_issue(runner: Any, message: str) -> None:
    log = runner.log.warn if runner.options.dry_run else runner.log.error
    log(message)


def validate_digest_pin_plan(runner: Any, matches: Sequence[Match]) -> bool:
    if not runner.options.digest_pin_updates:
        return True
    ok = True
    for match in matches:
        if _digest_pin_match_tag(match):
            continue
        ok = False
        runner.log.error(
            f"[{match.stack.name}] Digest-pin updates require a safe resolved "
            f"tag for line {match.target.line_no} ({match.target.first})."
        )
    try:
        for stack in _stacks_to_update(matches):
            stack_updates = runner._digest_pin_updates(
                [match for match in matches if match.stack.index == stack.index]
            )
            compose_rewrite.render_compose_digest_pins(
                stack.directory / stack.file,
                stack_updates,
                label_rewrite_approvals=(
                    runner.options.digest_pin_label_rewrite_approvals
                ),
                stack_name=stack.name,
            )
    except (ComposeTagRewriteError, UpdaterError) as exc:
        ok = False
        runner.log.error(f"Digest-pin plan is not safe to apply: {exc}")
    return ok


def finish_preflight_failure(
    runner: Any,
    parsed: ParsedWudFile,
    matches: Sequence[Match],
    skipped_tags: Sequence[WudTarget],
) -> int:
    preflight_failures = [
        failure
        for failure in runner.failures
        if failure.phase == "preflight"
    ]
    failed_stack_indices = {failure.stack.index for failure in preflight_failures}
    failed_matches = [
        match for match in matches if match.stack.index in failed_stack_indices
    ]
    skipped_matches = [
        match for match in matches if match.stack.index not in failed_stack_indices
    ]
    failed_lines = sorted({match.target.line_no for match in failed_matches})
    stack_statuses = {
        stack_index: StackStatus(
            "failure",
            _preflight_status_reason(stack_index, preflight_failures),
        )
        for stack_index in failed_stack_indices
    }

    runner._start_audit(parsed)
    runner._mark_unmatched_pending(parsed, matches, skipped_tags)
    runner._mark_matched_pending(
        skipped_matches,
        status="pending",
        status_reason="preflight-skipped",
    )
    runner._mark_failed_pending(failed_matches, stack_statuses, failed_lines)
    runner._mark_failed_lines_restored(())
    runner._finish_audit_run("failure")

    error_report = runner._write_error_report()
    if error_report is not None:
        runner.log.error(
            "Completed with preflight failure(s). "
            f"See log: {runner.log_file}; error report: {error_report}"
        )
    else:
        runner.log.error(
            f"Completed with preflight failure(s). See log: {runner.log_file}"
        )
    return 1
