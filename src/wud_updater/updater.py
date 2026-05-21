"""Python implementation of ``bin/docker-update-from-wud``."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TextIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from .command import CommandError, CommandResult, CommandRunner
from .compose import (
    ComposeBindMount,
    ComposeCli,
    ComposeDiscoveryError,
    ComposeStack,
    ServiceImage,
)
from .config import DEFAULT_MAX_WAIT, DEFAULT_UPDATE_MODE
from .db import (
    DatabaseError,
    connect_db,
    init_db,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
    update_pending_update,
    upsert_known_image,
    utc_timestamp as db_utc_timestamp,
)
from .docker_cli import DockerCli
from .file_ops import OwnerConfig, OwnerConfigError, apply_configured_owner
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_with_tag,
    tag_value_valid,
)
from .line_specs import LineSpecError, parse_line_spec
from .locks import DirectoryLock, WudLockError
from .terminal import TerminalRenderer
from .wud_file import (
    ParsedWudFile,
    WudTarget,
    parse_wud_file,
    remove_lines_before_run,
    restore_failed_lines,
)


CONTAINER_SUMMARY_FORMAT = "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.ExitCode}}"
HEALTH_LOG_FORMAT = "{{if .State.Health}}{{range .State.Health.Log}}{{println .Output}}{{end}}{{end}}"
RECREATE_STACK_LABEL = "WUD-UPDATER-RECREATE-STACK"
RECREATE_STACK_LABEL_FORMAT = f'{{{{ index .Config.Labels "{RECREATE_STACK_LABEL}" }}}}'
VALID_MODES = frozenset({"pause", "stop", "live"})
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXCLUSIVE_CREATE_ATTEMPTS = 100
_SERVICES_UNSET = object()
_HELPER_ONLY_MOUNT_PREFIXES = (Path("/host"), Path("/docker-host"), Path("/container-host"))


class UpdaterError(RuntimeError):
    """Raised for a user-facing updater failure."""


class ComposeTagRewriteError(RuntimeError):
    """Raised when a Compose tag rewrite cannot be proven safe."""


@dataclass(frozen=True)
class UpdaterOptions:
    docker_base: Path
    wud_file: Path
    log_dir: Path
    mode: str = DEFAULT_UPDATE_MODE
    max_wait: int = DEFAULT_MAX_WAIT
    dry_run: bool = False
    assume_yes: bool = False
    allow_tag_updates: bool = False
    no_color: bool = False
    only_lines: str = ""
    remove_lines_before_run: str = ""
    tag_overrides: tuple["TagOverride", ...] = ()
    db_path: Path | None = None
    docker_base_label: str | None = None
    host_docker_base: Path | None = None
    host_docker_base_label: str | None = None
    wud_file_label: str | None = None
    log_dir_label: str | None = None


@dataclass(frozen=True)
class Match:
    stack: ComposeStack
    target: WudTarget
    resolved: str
    compose_image: str
    service: str


@dataclass(frozen=True)
class ImageState:
    image_id: str
    digest: str


@dataclass(frozen=True)
class TagUpdate:
    old_image: str
    desired_tag: str
    new_image: str
    services: tuple[str, ...]


@dataclass(frozen=True)
class TagOverride:
    line_no: int
    tag: str


@dataclass(frozen=True)
class AppliedTagUpdate(TagUpdate):
    replacements: int


@dataclass(frozen=True)
class StackStatus:
    status: str
    reason: str


@dataclass(frozen=True)
class UpResult:
    ok: bool
    wait_handled: bool
    command_error: CommandError | None = None
    health_details: str = ""


@dataclass(frozen=True)
class UpdateScope:
    services: tuple[str, ...] | None
    pull_services: tuple[str, ...] | None
    stack_reason: str = ""
    stop_services: tuple[str, ...] | None = None
    force_recreate: bool = False
    up_no_deps: bool = True


@dataclass
class FailureRecord:
    stack: ComposeStack
    services: tuple[str, ...] | None
    matches: tuple[Match, ...]
    phase: str
    reason: str
    command_result: CommandResult | None = None
    health_details: str = ""
    note: str = ""
    wud_restored: bool | None = None


class Logger:
    def __init__(
        self,
        log_file: Path,
        *,
        no_color: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.log_file = log_file
        self.no_color = no_color
        self.renderer = TerminalRenderer(no_color=no_color, environ=environ)

    def info(self, message: str) -> None:
        self._term("INFO", message)

    def warn(self, message: str) -> None:
        self._term("WARN", message)

    def error(self, message: str) -> None:
        self._term("ERROR", message, stream=sys.stderr)

    def plain(self, level: str, message: str) -> None:
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp()}] [{level}] {message}\n")

    def rich_enabled(self) -> bool:
        return self.renderer.rich_enabled()

    def _term(self, level: str, message: str, *, stream: TextIO | None = None) -> None:
        if stream is None:
            stream = sys.stdout
        stamped = timestamp()
        self.renderer.log_line(
            timestamp=stamped,
            level=level,
            message=message,
            stream=stream,
        )
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(f"[{stamped}] [{level}] {message}\n")


class UpdateFromWudRunner:
    def __init__(
        self,
        options: UpdaterOptions,
        *,
        environ: Mapping[str, str] | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.options = options
        self.environ = os.environ if environ is None else environ
        self.owner = OwnerConfig.from_env(self.environ)
        self.command_runner = command_runner or CommandRunner()
        self.docker = DockerCli(runner=self.command_runner)
        self.compose = ComposeCli(runner=self.command_runner)
        self.log_file = prepare_log_file(options.log_dir, self.owner)
        self.log = Logger(
            self.log_file,
            no_color=options.no_color,
            environ=self.environ,
        )
        self.failures: list[FailureRecord] = []
        self.audit_conn: sqlite3.Connection | None = None
        self.audit_run_id: int | None = None
        self.audit_db_path: Path | None = None

    def run(self) -> int:
        opts = self.options
        if opts.mode not in VALID_MODES:
            raise UpdaterError("--mode must be pause|stop|live")
        if opts.max_wait < 0:
            raise UpdaterError("--max-wait must be an integer number of seconds")
        if opts.tag_overrides and not opts.allow_tag_updates:
            raise UpdaterError("--tag-override requires --allow-tag-updates")

        lock = DirectoryLock(
            opts.wud_file,
            timeout_seconds=self.environ.get("WUD_LOCK_TIMEOUT", "30"),
            parent_held=self.environ.get("WUD_LOCK_HELD_BY_PARENT") == "1",
        )

        try:
            self._print_header()
            if not opts.wud_file.is_file():
                raise UpdaterError(f"List file not found: {opts.wud_file}")

            if lock.parent_held:
                lock.acquire()

            parsed = self._parse_wud_file()
            if opts.dry_run or not opts.remove_lines_before_run:
                lock.release_parent()

            if not parsed.targets:
                self.log.info("Nothing to do; list is empty.")
                return 0

            self._print_targets(parsed)
            stacks = self.compose.discover_stacks(
                opts.docker_base,
                project_base=opts.host_docker_base,
            )
            matches, skipped_tags = self._build_matches(parsed, stacks)
            self._print_skipped_tag_updates(skipped_tags)

            if not matches:
                if not opts.dry_run:
                    self._start_audit(parsed)
                    self._mark_unmatched_pending(parsed, matches, skipped_tags)
                    self._finish_audit_run("success")
                self.log.info("No stacks matched the list; nothing to do.")
                return 0

            self._print_plan(matches)

            if not self._validate_tag_update_plan(matches):
                return 1
            if not self._validate_compose_bind_mount_paths(matches):
                if opts.dry_run:
                    self.log.warn(
                        "Dry-run only; reported container bind-mount path issue without mutating."
                    )
                else:
                    return self._finish_preflight_failure(parsed, matches, skipped_tags)
            if not self._validate_tag_manifests(matches):
                return 1

            if opts.dry_run:
                self.log.info(
                    "Dry-run only; no pull, restart, health wait, or cleanup performed."
                )
                return 0

            self._confirm_before_mutation()
            remove_line_numbers = parse_line_spec(
                opts.remove_lines_before_run,
                len(parsed.lines),
                "--remove-lines-before-run",
            )
            in_flight_lines = sorted(
                {match.target.line_no for match in matches}
                | set(remove_line_numbers)
            )
            audit_parsed = self._audit_parsed_file(parsed, in_flight_lines)
            self._start_audit(audit_parsed)
            self._mark_unmatched_pending(audit_parsed, matches, skipped_tags)
            self._mark_removed_pending(audit_parsed, remove_line_numbers, matches)
            self._mark_matched_pending(matches, status="in_progress")
            remove_lines_before_run(
                opts.wud_file,
                parsed,
                in_flight_lines,
                lock=lock,
                owner=self.owner,
            )
            self.log.info("Removed in-flight WUD entries before update.")
            lock.release_parent()

            stack_statuses: dict[int, StackStatus] = {}
            for stack in _stacks_to_update(matches):
                stack_matches = [match for match in matches if match.stack.index == stack.index]
                stack_statuses[stack.index] = self._update_stack(stack, stack_matches)

            failed_lines = _failed_line_numbers(matches, stack_statuses)
            if failed_lines:
                restore_failed_lines(
                    opts.wud_file,
                    parsed,
                    failed_lines,
                    lock=lock,
                    owner=self.owner,
                )
                self._mark_failed_lines_restored(failed_lines)
                self._mark_failed_pending(matches, stack_statuses, failed_lines)
                self.log.warn(f"Restored failed WUD entries in {opts.wud_file}")
            else:
                self._mark_failed_lines_restored(())
                self.log.info("Successful WUD entries were removed before update.")
            self._mark_successful_pending(matches, stack_statuses)
            self._record_update_events(matches, stack_statuses)
            self._record_known_images(matches, stack_statuses)

            fail_count = sum(1 for status in stack_statuses.values() if status.status != "success")
            if fail_count:
                self._finish_audit_run("failure")
                error_report = self._write_error_report()
                if error_report is not None:
                    self.log.error(
                        f"Completed with {fail_count} failure(s). See log: {self.log_file}; "
                        f"error report: {error_report}"
                    )
                else:
                    self.log.error(f"Completed with {fail_count} failure(s). See log: {self.log_file}")
                return 1

            self._finish_audit_run("success")
            self.log.info(f"Done. See log: {self.log_file}")
            return 0
        except (CommandError, ComposeDiscoveryError, LineSpecError, OwnerConfigError, WudLockError) as exc:
            self._finish_audit_run("failure", best_effort=True)
            raise UpdaterError(str(exc)) from exc
        except OSError as exc:
            self._finish_audit_run("failure", best_effort=True)
            raise UpdaterError(f"Filesystem operation failed: {exc}") from exc
        except (sqlite3.Error, DatabaseError) as exc:
            self._finish_audit_run("failure", best_effort=True)
            raise UpdaterError(f"Could not update audit database: {exc}") from exc
        except UpdaterError:
            self._finish_audit_run("failure", best_effort=True)
            raise
        finally:
            if self.audit_conn is not None:
                self.audit_conn.close()
            lock.close()

    def _parse_wud_file(self) -> ParsedWudFile:
        opts = self.options
        full_parse = parse_wud_file(opts.wud_file)
        only_lines = parse_line_spec(opts.only_lines, len(full_parse.lines), "--only-lines")
        parse_line_spec(
            opts.remove_lines_before_run,
            len(full_parse.lines),
            "--remove-lines-before-run",
        )
        parsed = parse_wud_file(
            opts.wud_file,
            selected_lines=only_lines if only_lines else None,
        )
        for warning in parsed.warnings:
            self.log.warn(warning)
        return self._apply_tag_overrides(parsed)

    def _apply_tag_overrides(
        self,
        parsed: ParsedWudFile,
        *,
        log: bool = True,
    ) -> ParsedWudFile:
        overrides = {item.line_no: item.tag for item in self.options.tag_overrides}
        if not overrides:
            return parsed

        targets_by_line = {target.line_no: target for target in parsed.targets}
        missing = sorted(set(overrides) - set(targets_by_line))
        if missing:
            line_list = ", ".join(str(line_no) for line_no in missing)
            raise UpdaterError(
                f"--tag-override line(s) did not match selected WUD entries: {line_list}"
            )

        updated_targets: list[WudTarget] = []
        for target in parsed.targets:
            override = overrides.get(target.line_no)
            if override is None:
                updated_targets.append(target)
                continue
            if not target.desired_tag:
                raise UpdaterError(
                    f"--tag-override line {target.line_no} does not target a tag update"
                )
            if log:
                self.log.info(
                    "Tag override: "
                    f"line {target.line_no} uses tag {override} "
                    f"instead of {target.desired_tag}"
                )
            updated_targets.append(replace(target, desired_tag=override))

        return ParsedWudFile(
            lines=parsed.lines,
            targets=tuple(updated_targets),
            warnings=parsed.warnings,
        )

    def _audit_parsed_file(
        self,
        parsed: ParsedWudFile,
        audit_lines: Sequence[int],
    ) -> ParsedWudFile:
        target_lines = {target.line_no for target in parsed.targets}
        if set(audit_lines).issubset(target_lines):
            return parsed
        audit_parsed = parse_wud_file(
            self.options.wud_file,
            selected_lines=sorted(target_lines | set(audit_lines)),
        )
        return self._apply_tag_overrides(audit_parsed, log=False)

    def _build_matches(
        self,
        parsed: ParsedWudFile,
        stacks: Sequence[ComposeStack],
    ) -> tuple[list[Match], list[WudTarget]]:
        container_images = {item.name: item.image for item in self.docker.try_container_images()}
        matches: list[Match] = []
        skipped_tags: list[WudTarget] = []
        seen: set[tuple[int, int, str, str, str]] = set()

        for target in parsed.targets:
            if target.desired_tag and not self.options.allow_tag_updates:
                skipped_tags.append(target)
                continue

            resolved = container_images.get(target.first, target.first)
            allow_repo = target.allow_repo or resolved != target.first or not image_has_tag(resolved)

            for stack in stacks:
                for image in stack.images:
                    if not image_matches_resolved_target(image, resolved, allow_repo):
                        continue
                    services = _services_for_image(stack.service_images, image)
                    if services:
                        for service in services:
                            key = (stack.index, target.line_no, resolved, image, service)
                            if key not in seen:
                                matches.append(
                                    Match(stack, target, resolved, image, service)
                                )
                                seen.add(key)
                    else:
                        key = (stack.index, target.line_no, resolved, image, "")
                        if key not in seen:
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
        return matches, skipped_tags

    def _update_stack(self, stack: ComposeStack, matches: Sequence[Match]) -> StackStatus:
        opts = self.options
        scope = self._update_scope(stack, matches)
        services = scope.services
        pull_services = scope.pull_services
        stop_services = scope.stop_services if scope.stop_services is not None else services
        service_scoped = services is not None
        services_label = " ".join(services or ())
        pull_services_label = " ".join(pull_services or ())
        stop_services_label = " ".join(stop_services or ())

        if self.log.rich_enabled():
            self.log.plain("INFO", f"[{stack.name}] Checking for updates (mode={opts.mode})")
            panel_lines = [(f"Checking for updates (mode={opts.mode})", "info")]
            if service_scoped:
                message = f"Matched compose service(s): {services_label}"
                self.log.plain("INFO", f"[{stack.name}] {message}")
                panel_lines.append((message, "info"))
            else:
                message = _stack_level_scope_message(scope)
                self.log.plain("WARN", f"[{stack.name}] {message}")
                panel_lines.append((message, "warning"))
                if pull_services is not None:
                    pull_message = f"Pulling matched compose service(s): {pull_services_label}"
                    self.log.plain("INFO", f"[{stack.name}] {pull_message}")
                    panel_lines.append((pull_message, "info"))
            self.log.renderer.stack_summary(stack.name, panel_lines)
        else:
            self.log.info(f"[{stack.name}] Checking for updates (mode={opts.mode})")
            if service_scoped:
                self.log.info(f"[{stack.name}] Matched compose service(s): {services_label}")
            else:
                self.log.warn(f"[{stack.name}] {_stack_level_scope_message(scope)}")
                if pull_services is not None:
                    self.log.info(
                        f"[{stack.name}] Pulling matched compose service(s): {pull_services_label}"
                    )

        images = tuple(stack.images)
        before = self._image_state(images)
        tag_updates = self._tag_updates(matches)
        applied_tags: tuple[AppliedTagUpdate, ...] = ()
        compose_backup: Path | None = None
        current_stack = stack

        if tag_updates:
            self.log.info(f"[{stack.name}] Applying compose tag update(s)")
            compose_path = stack.directory / stack.file
            try:
                compose_backup = _backup_compose(compose_path)
            except OSError as exc:
                self.log.error(
                    f"[{stack.name}] Could not back up compose file before tag update: {exc}"
                )
                self._record_failure(
                    stack,
                    matches,
                    phase="compose-backup",
                    reason="compose-backup-failed",
                    services=pull_services,
                    note=str(exc),
                )
                return StackStatus("failure", "compose-backup-failed")
            try:
                applied_tags = apply_compose_tag_updates(compose_path, tag_updates)
            except ComposeTagRewriteError as exc:
                self.log.error(
                    f"[{stack.name}] Could not safely rewrite compose image tag(s): {exc}"
                )
                self._record_failure(
                    stack,
                    matches,
                    phase="compose-tag-rewrite",
                    reason="compose-tag-rewrite-failed",
                    services=pull_services,
                    note=str(exc),
                )
                return StackStatus("failure", "compose-tag-rewrite-failed")
            except OSError as exc:
                self.log.error(
                    f"[{stack.name}] Could not rewrite compose image tag(s): {exc}"
                )
                self._record_failure(
                    stack,
                    matches,
                    phase="compose-tag-rewrite",
                    reason="compose-tag-rewrite-failed",
                    services=pull_services,
                    note=str(exc),
                )
                return StackStatus("failure", "compose-tag-rewrite-failed")
            if not applied_tags:
                self.log.error(
                    f"[{stack.name}] Could not rewrite compose image tag(s); leaving WUD entry pending for manual review."
                )
                self._record_failure(
                    stack,
                    matches,
                    phase="compose-tag-rewrite",
                    reason="compose-tag-rewrite-failed",
                    services=pull_services,
                    note="No compose image lines were rewritten.",
                )
                return StackStatus("failure", "compose-tag-rewrite-failed")
            for applied in applied_tags:
                self.log.info(
                    f"[{stack.name}] Compose tag updated: {applied.old_image} -> {applied.new_image}"
                )
            refreshed = self._refresh_stack_images(current_stack)
            if refreshed is None:
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    "compose-refresh-failed",
                    phase="compose-refresh",
                    force_recreate=scope.force_recreate,
                    no_deps=scope.up_no_deps,
                )
            if not self._validate_applied_tag_updates(
                stack,
                applied_tags,
                refreshed.service_images,
            ):
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    "compose-tag-validation-failed",
                    phase="compose-tag-validation",
                    force_recreate=scope.force_recreate,
                    no_deps=scope.up_no_deps,
                )
            current_stack = refreshed
            images = tuple(current_stack.images)

        try:
            self.compose.pull(
                stack.directory,
                stack.file,
                pull_services,
                project_directory=stack.project_directory,
            )
        except CommandError as exc:
            if applied_tags and compose_backup is not None:
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    "pull-failed",
                    phase="pull",
                    command_error=exc,
                    force_recreate=scope.force_recreate,
                    no_deps=scope.up_no_deps,
                )
            self._record_failure(
                stack,
                matches,
                phase="pull",
                reason="pull-failed",
                services=pull_services,
                command_error=exc,
                health_details=self._capture_health_details(stack, pull_services),
            )
            return StackStatus("failure", "pull-failed")

        after = self._image_state(images)
        if not self._verify_expected_digests(stack, matches, images):
            if applied_tags and compose_backup is not None:
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    "expected-digest-not-reached",
                    phase="digest",
                    force_recreate=scope.force_recreate,
                    no_deps=scope.up_no_deps,
                )
            self._record_failure(
                stack,
                matches,
                phase="digest",
                reason="expected-digest-not-reached",
                services=pull_services,
                health_details=self._capture_health_details(stack, pull_services),
            )
            return StackStatus("failure", "expected-digest-not-reached")

        changes = _updated_images(before, after)
        update_needed = bool(applied_tags or changes)
        for image, state in changes:
            target = state.digest if state.digest else state.image_id
            self.log.info(f"[{stack.name}] Image updated: {image} -> {target}")

        if not update_needed:
            self.log.info(f"[{stack.name}] All images up to date, skipping restart")
            return StackStatus("success", "already-current")

        down_failed = False
        down_error: CommandError | None = None
        down_phase = "stop"
        if opts.mode == "pause":
            self.log.warn(
                f"[{stack.name}] Mode pause is deprecated; pausing before recreate and unpausing before health check"
            )
            try:
                self.compose.pause(
                    stack.directory,
                    stack.file,
                    services,
                    project_directory=stack.project_directory,
                )
            except CommandError:
                self.log.warn(f"[{stack.name}] Pause failed; continuing with live recreate")
        elif opts.mode == "stop":
            try:
                if service_scoped:
                    self.log.warn(f"[{stack.name}] Stopping affected service(s): {stop_services_label}")
                    self.compose.stop(
                        stack.directory,
                        stack.file,
                        stop_services,
                        project_directory=stack.project_directory,
                    )
                else:
                    if stop_services_label:
                        self.log.warn(
                            f"[{stack.name}] Stopping stack service(s): {stop_services_label}"
                        )
                    else:
                        self.log.warn(f"[{stack.name}] Stopping stack")
                    self.compose.stop(
                        stack.directory,
                        stack.file,
                        stop_services,
                        project_directory=stack.project_directory,
                    )
            except CommandError as exc:
                down_failed = True
                down_error = exc
                self.log.warn(
                    f"[{stack.name}] Stop failed; attempting up for recovery, but this stack will not be marked successful"
                )

        if service_scoped:
            self.log.info(f"[{stack.name}] Bringing affected service(s) up: {services_label}")
        else:
            self.log.info(f"[{stack.name}] Bringing stack up")

        up_result = self._run_compose_up(
            stack,
            services,
            force_recreate=scope.force_recreate,
            no_deps=scope.up_no_deps,
        )
        if not up_result.ok:
            if applied_tags and compose_backup is not None:
                failure_phase = "up"
                failure_reason = "up-or-health-failed"
                failure_error = up_result.command_error
                if down_failed and down_error is not None:
                    failure_phase = down_phase
                    failure_reason = "down-failed"
                    failure_error = down_error
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    failure_reason,
                    phase=failure_phase,
                    command_error=failure_error,
                    failure_health=up_result.health_details,
                    force_recreate=scope.force_recreate,
                    no_deps=scope.up_no_deps,
                )
            if down_failed and down_error is not None:
                self._record_failure(
                    stack,
                    matches,
                    phase=down_phase,
                    reason="down-failed",
                    services=services,
                    command_error=down_error,
                    health_details=self._capture_health_details(stack, services),
                    note="Update recovery also failed during compose up.",
                )
            self._record_failure(
                stack,
                matches,
                phase="up",
                reason="up-or-health-failed",
                services=services,
                command_error=up_result.command_error,
                health_details=up_result.health_details,
            )
            return StackStatus("failure", "up-or-health-failed")

        if opts.mode == "pause":
            self.log.warn(f"[{stack.name}] Unpausing before health check")
            try:
                    self.compose.unpause(
                        stack.directory,
                        stack.file,
                        services,
                        project_directory=stack.project_directory,
                    )
            except CommandError as exc:
                if applied_tags and compose_backup is not None:
                    return self._handle_tag_update_failure(
                        stack,
                        matches,
                        services,
                        applied_tags,
                        compose_backup,
                        "unpause-failed",
                        phase="unpause",
                        command_error=exc,
                        force_recreate=scope.force_recreate,
                        no_deps=scope.up_no_deps,
                    )
                self._record_failure(
                    stack,
                    matches,
                    phase="unpause",
                    reason="unpause-failed",
                    services=services,
                    command_error=exc,
                    health_details=self._capture_health_details(stack, services),
                )
                return StackStatus("failure", "unpause-failed")
            up_result = UpResult(up_result.ok, False, up_result.command_error, up_result.health_details)

        if up_result.wait_handled or self._wait_for_health(stack, services):
            self.log.info(f"[{stack.name}] Healthy")
            if down_failed:
                if applied_tags and compose_backup is not None:
                    return self._handle_tag_update_failure(
                        stack,
                        matches,
                        services,
                        applied_tags,
                        compose_backup,
                        "down-failed",
                        phase=down_phase,
                        command_error=down_error,
                        force_recreate=scope.force_recreate,
                        no_deps=scope.up_no_deps,
                    )
                self._record_failure(
                    stack,
                    matches,
                    phase=down_phase,
                    reason="down-failed",
                    services=services,
                    command_error=down_error,
                    health_details=self._capture_health_details(stack, services),
                    note="Compose up recovery succeeded, but the earlier stop command failed.",
                )
                return StackStatus("failure", "down-failed")
            return StackStatus("success", "updated")

        health_details = self._capture_health_details(stack, services)
        if applied_tags and compose_backup is not None:
            return self._handle_tag_update_failure(
                stack,
                matches,
                services,
                applied_tags,
                compose_backup,
                "health-failed",
                phase="health",
                failure_health=health_details,
                force_recreate=scope.force_recreate,
                no_deps=scope.up_no_deps,
            )
        self._record_failure(
            stack,
            matches,
            phase="health",
            reason="health-failed",
            services=services,
            health_details=health_details,
        )
        return StackStatus("failure", "health-failed")

    def _run_compose_up(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        *,
        force_recreate: bool = False,
        no_deps: bool = True,
    ) -> UpResult:
        if self.options.mode != "pause" and self.compose.up_wait_supported(
            stack.directory,
            stack.file,
            project_directory=stack.project_directory,
        ):
            self.log.info(
                f"[{stack.name}] docker compose up --wait is supported; using native wait"
            )
            try:
                self.compose.up(
                    stack.directory,
                    stack.file,
                    services,
                    wait=True,
                    wait_timeout=self.options.max_wait,
                    force_recreate=force_recreate,
                    no_deps=no_deps,
                    project_directory=stack.project_directory,
                )
                return UpResult(True, True)
            except CommandError as exc:
                self.log.error(f"[{stack.name}] docker compose up --wait failed")
                health_details = self._capture_health_details(stack, services)
                self._log_health_details(stack, services, health_details)
                return UpResult(False, True, exc, health_details)

        try:
            self.compose.up(
                stack.directory,
                stack.file,
                services,
                force_recreate=force_recreate,
                no_deps=no_deps,
                project_directory=stack.project_directory,
            )
            return UpResult(True, False)
        except CommandError as exc:
            self.log.error(f"[{stack.name}] docker compose up failed")
            health_details = self._capture_health_details(stack, services)
            self._log_health_details(stack, services, health_details)
            return UpResult(False, False, exc, health_details)

    def _wait_for_health(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
    ) -> bool:
        start = time.monotonic()
        if self.options.max_wait > 0:
            time.sleep(2)

        while True:
            cids = self.compose.ps_quiet(
                stack.directory,
                stack.file,
                services,
                project_directory=stack.project_directory,
            )
            ok = bool(cids)
            for cid in cids:
                summary = self._cid_summary(cid)
                if not summary or not _cid_is_ok(summary):
                    ok = False

            elapsed = int(time.monotonic() - start)
            if ok:
                self.log.plain("INFO", f"[{stack.name}] Health wait succeeded in {elapsed}s")
                return True
            if elapsed >= self.options.max_wait:
                self.log.error(f"[{stack.name}] Failed health gate after {elapsed}s")
                if not cids:
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] Health blocker: docker compose ps -q returned no containers",
                    )
                self._log_health_details(stack, services)
                return False
            time.sleep(2)

    def _handle_tag_update_failure(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        services: Sequence[str] | None,
        applied_tags: Sequence[AppliedTagUpdate],
        compose_backup: Path,
        reason: str,
        *,
        phase: str,
        command_error: CommandError | None = None,
        failure_health: str | None = None,
        force_recreate: bool = False,
        no_deps: bool = True,
    ) -> StackStatus:
        if failure_health is None:
            failure_health = self._capture_health_details(stack, services)
        self.log.warn(f"[{stack.name}] Restoring compose file after failed tag update.")
        rollback_result = "rollback-failed-manual-review-required"
        rollback_error: CommandError | None = None
        try:
            shutil.copy2(compose_backup, stack.directory / stack.file)
            rollback_up = self._run_compose_up(
                stack,
                services,
                force_recreate=force_recreate,
                no_deps=no_deps,
            )
            if rollback_up.ok and (rollback_up.wait_handled or self._wait_for_health(stack, services)):
                rollback_result = "restored-and-healthy"
                self.log.warn(
                    f"[{stack.name}] Rolled back to previous tag; leaving WUD entry pending for manual review."
                )
            else:
                rollback_error = rollback_up.command_error
                self.log.error(f"[{stack.name}] Rollback failed; manual review required.")
        except OSError:
            self.log.error(f"[{stack.name}] Rollback failed; manual review required.")

        report_error = rollback_error or command_error
        self._record_failure(
            stack,
            matches,
            phase=phase,
            reason=reason,
            services=services,
            command_error=report_error,
            health_details=failure_health,
            note=f"tag rollback={rollback_result}",
        )
        self._write_tag_incident_log(
            stack,
            services,
            applied_tags,
            reason,
            rollback_result,
            failure_health,
        )
        return StackStatus("failure", reason)

    def _write_tag_incident_log(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        applied_tags: Sequence[AppliedTagUpdate],
        reason: str,
        rollback_result: str,
        failure_health: str,
    ) -> None:
        first_tag = applied_tags[0].desired_tag if applied_tags else "tag"
        incident = stack.directory / f"error-{safe_component(first_tag)}-{file_timestamp()}.logs"
        services_label = " ".join(services or ()) or "stack-level"
        content = [
            "WUD-Updater tag update incident\n",
            f"timestamp={timestamp()}\n",
            f"stack={stack.name}\n",
            f"compose_file={stack.file}\n",
            f"services={services_label}\n",
            f"reason={reason}\n",
            f"rollback={rollback_result}\n",
            f"central_log={self.log_file}\n",
            "\ntag_updates:\n",
        ]
        for applied in applied_tags:
            content.append(
                f"  {applied.old_image} -> {applied.new_image} "
                f"(tag={applied.desired_tag} replacements={applied.replacements})\n"
            )
        content.append("\nfailure_health:\n")
        content.append(
            failure_health
            if failure_health
            else "health: no failure health details captured\n"
        )
        content.append(
            "\nmanual_review_required="
            + ("no\n" if rollback_result == "restored-and-healthy" else "yes\n")
        )
        try:
            incident = _create_unique_text_file_exclusive(
                incident,
                "".join(content),
            )
        except OSError as exc:
            raise UpdaterError(
                f"[{stack.name}] Could not create tag update incident log: {exc}"
            ) from exc
        self.log.warn(f"[{stack.name}] Wrote tag update incident log: {incident}")

    def _update_scope(self, stack: ComposeStack, matches: Sequence[Match]) -> UpdateScope:
        services = _update_services(matches)
        if services is None:
            return UpdateScope(
                services=None,
                pull_services=None,
                stop_services=self._stack_stop_services(stack),
                force_recreate=True,
            )
        lifecycle_services, uses_network_provider = _expand_network_mode_services(
            services,
            _network_mode_providers(stack.service_images),
        )
        stop_services = (
            tuple(reversed(lifecycle_services))
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

    def _capture_health_details(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
    ) -> str:
        cids = self.compose.ps_quiet(
            stack.directory,
            stack.file,
            services,
            project_directory=stack.project_directory,
        )
        if not cids:
            return "health: docker compose ps -q returned no containers\n"

        lines: list[str] = []
        for cid in cids:
            summary = self._cid_summary(cid)
            if not summary:
                lines.append(f"health: container={cid} inspect returned no state")
                continue
            name, status, health, restarts, exit_code = _split_summary(summary)
            lines.append(
                f"health: container={name.lstrip('/')} status={status} "
                f"health={health} restarts={restarts} exit_code={exit_code}"
            )
            for output in self.docker.try_inspect(cid, HEALTH_LOG_FORMAT):
                output = sanitize_stream(output)
                if output:
                    lines.append(f"health_output[{name.lstrip('/')}]: {output}")
        return "\n".join(lines) + "\n"

    def _log_health_details(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        health_details: str | None = None,
    ) -> None:
        details = health_details
        if details is None:
            details = self._capture_health_details(stack, services)
        for line in details.splitlines():
            self.log.plain("ERROR", f"[{stack.name}] {line}")

    def _log_command_result(self, result: CommandResult) -> None:
        for line in _render_command_result(result):
            self.log.plain("ERROR", line.rstrip("\n"))

    def _cid_summary(self, cid: str) -> str:
        lines = self.docker.try_inspect(cid, CONTAINER_SUMMARY_FORMAT)
        return lines[0] if lines else ""

    def _image_state(self, images: Iterable[str]) -> dict[str, ImageState]:
        return {
            image: ImageState(
                image_id=self.docker.image_id(image),
                digest=self.docker.image_digest(image),
            )
            for image in images
            if image
        }

    def _validate_tag_manifests(self, matches: Sequence[Match]) -> bool:
        ok = True
        for update in self._tag_updates(matches):
            try:
                self.docker.manifest_inspect(update.new_image)
            except CommandError as exc:
                ok = False
                self.log.error(
                    "Invalid or unavailable remote tag: "
                    f"{update.old_image} -> {update.new_image}"
                )
                for line in exc.result.stderr_lines:
                    self.log.error(f"manifest stderr: {sanitize_stream(line)}")
                self._log_command_result(exc.result)
            else:
                self.log.info(
                    "Validated remote tag: "
                    f"{update.old_image} -> {update.new_image}"
                )
        return ok

    def _validate_tag_update_plan(self, matches: Sequence[Match]) -> bool:
        ok = True
        desired_by_service: dict[tuple[int, str, str], set[str]] = {}
        for match in matches:
            if not match.target.desired_tag:
                continue
            if not match.service:
                ok = False
                self.log.error(
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
            self.log.error(
                f"[{stack_name}] Conflicting tag updates for service {service} "
                f"image {image}: {', '.join(sorted(desired))}"
            )
        return ok

    def _validate_compose_bind_mount_paths(self, matches: Sequence[Match]) -> bool:
        ok = True
        issue_messages: dict[int, list[str]] = {}
        issue_services: dict[int, set[str]] = {}
        for stack in _stacks_to_update(matches):
            stack_matches = [match for match in matches if match.stack.index == stack.index]
            mounts = self.compose.try_service_bind_mounts(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            )
            if not mounts:
                continue
            scope = self._update_scope(stack, stack_matches)
            scoped_services = set(scope.services or ())
            if scope.services is None:
                scoped_services = {mount.service for mount in mounts}
            for mount in mounts:
                if mount.service not in scoped_services:
                    continue
                issue = _container_bind_mount_path_issue(
                    mount,
                    docker_base=self.options.docker_base,
                )
                if not issue:
                    continue
                ok = False
                messages = self._bind_mount_path_issue_messages(stack, mount, issue)
                self._log_bind_mount_path_issue(messages)
                if not self.options.dry_run:
                    issue_messages.setdefault(stack.index, []).extend(messages)
                    issue_services.setdefault(stack.index, set()).add(mount.service)
        if not self.options.dry_run:
            for stack in _stacks_to_update(matches):
                messages = issue_messages.get(stack.index)
                if not messages:
                    continue
                stack_matches = [
                    match for match in matches if match.stack.index == stack.index
                ]
                services = tuple(sorted(issue_services.get(stack.index, ()))) or None
                self._record_failure(
                    stack,
                    stack_matches,
                    phase="preflight",
                    reason="bind-mount-path-invalid",
                    services=services,
                    health_details="\n".join(messages),
                )
        return ok

    def _bind_mount_path_issue_messages(
        self,
        stack: ComposeStack,
        mount: ComposeBindMount,
        issue: str,
    ) -> list[str]:
        target = f" -> {mount.target}" if mount.target else ""
        messages = [
            f"[{stack.name}] Compose bind mount for service {mount.service} "
            f"resolves to {mount.source}{target}; {issue}."
        ]
        if self.options.host_docker_base is not None:
            messages.append(
                f"[{stack.name}] HOST_DOCKER_BASE is set to "
                f"{self.options.host_docker_base}; verify it is the Docker "
                f"daemon-visible host root that corresponds to "
                f"DOCKER_BASE={self.options.docker_base}."
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

    def _log_bind_mount_path_issue(self, messages: Sequence[str]) -> None:
        log = self.log.warn if self.options.dry_run else self.log.error
        for message in messages:
            log(message)

    def _validate_applied_tag_updates(
        self,
        stack: ComposeStack,
        applied_tags: Sequence[AppliedTagUpdate],
        service_images: Sequence[ServiceImage],
    ) -> bool:
        ok = True
        image_by_service = {
            (item.service, item.image)
            for item in service_images
        }
        for applied in applied_tags:
            expected_replacements = len(applied.services)
            if applied.replacements != expected_replacements:
                ok = False
                self.log.error(
                    f"[{stack.name}] Compose tag rewrite touched "
                    f"{applied.replacements} image line(s) for {applied.old_image}, "
                    f"expected {expected_replacements}."
                )
            for service in applied.services:
                if (service, applied.new_image) in image_by_service:
                    continue
                ok = False
                self.log.error(
                    f"[{stack.name}] Compose service {service} did not resolve "
                    f"to rewritten image {applied.new_image} after tag rewrite."
                )
        return ok

    def _verify_expected_digests(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        images: Sequence[str],
    ) -> bool:
        ok = True
        requirements = {
            (
                match.target.line_no,
                match.target.first,
                _digest_check_image(match),
                _digest_check_allow_repo(match),
                match.target.digest,
            )
            for match in matches
            if match.target.digest
        }
        for line_no, target, expected_image, allow_repo, expected in sorted(requirements):
            matched = False
            digest_ok = False
            for image in images:
                if not image_matches_resolved_target(image, expected_image, allow_repo):
                    continue
                matched = True
                if self.docker.image_has_digest(image, expected):
                    digest_ok = True
                    break
            if not digest_ok:
                ok = False
                self.log.error(
                    f"[{stack.name}] Expected digest not reached for line {line_no} ({target}): wanted {expected}"
                )
                if not matched:
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] No compose image matched line {line_no} while checking expected digest",
                    )
        return ok

    def _tag_updates(self, matches: Sequence[Match]) -> tuple[TagUpdate, ...]:
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

    def _refresh_stack_images(self, stack: ComposeStack) -> ComposeStack | None:
        try:
            images = tuple(
                self.compose.config_images(
                    stack.directory,
                    stack.file,
                    project_directory=stack.project_directory,
                )
            )
        except CommandError:
            self.log.error(f"[{stack.name}] Could not refresh compose images after tag rewrite.")
            return None
        return ComposeStack(
            index=stack.index,
            directory=stack.directory,
            file=stack.file,
            name=stack.name,
            images=images,
            service_images=self.compose.try_service_image_pairs(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            ),
            project_directory=stack.project_directory,
        )

    def _record_failure(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        *,
        phase: str,
        reason: str,
        services: Sequence[str] | None | object = _SERVICES_UNSET,
        command_error: CommandError | None = None,
        health_details: str = "",
        note: str = "",
    ) -> None:
        if services is _SERVICES_UNSET:
            failure_services = _update_services(matches)
        elif services is None:
            failure_services = None
        else:
            failure_services = tuple(services)
        self.failures.append(
            FailureRecord(
                stack=stack,
                services=failure_services,
                matches=tuple(matches),
                phase=phase,
                reason=reason,
                command_result=command_error.result if command_error else None,
                health_details=health_details,
                note=note,
            )
        )

    def _finish_preflight_failure(
        self,
        parsed: ParsedWudFile,
        matches: Sequence[Match],
        skipped_tags: Sequence[WudTarget],
    ) -> int:
        preflight_failures = [
            failure
            for failure in self.failures
            if failure.phase == "preflight"
            and failure.reason == "bind-mount-path-invalid"
        ]
        failed_stack_indices = {failure.stack.index for failure in preflight_failures}
        failed_matches = [
            match for match in matches if match.stack.index in failed_stack_indices
        ]
        failed_lines = sorted({match.target.line_no for match in failed_matches})
        stack_statuses = {
            stack_index: StackStatus("failure", "bind-mount-path-invalid")
            for stack_index in failed_stack_indices
        }

        self._start_audit(parsed)
        self._mark_unmatched_pending(parsed, matches, skipped_tags)
        self._mark_failed_pending(failed_matches, stack_statuses, failed_lines)
        self._mark_failed_lines_restored(())
        self._finish_audit_run("failure")

        error_report = self._write_error_report()
        if error_report is not None:
            self.log.error(
                "Completed with preflight failure(s). "
                f"See log: {self.log_file}; error report: {error_report}"
            )
        else:
            self.log.error(f"Completed with preflight failure(s). See log: {self.log_file}")
        return 1

    def _start_audit(self, parsed: ParsedWudFile) -> None:
        if self.audit_run_id is not None:
            return
        conn: sqlite3.Connection | None = None
        try:
            db_path = _db_path(self.options, self.environ)
            chown_parent = _sqlite_parent_missing(db_path)
            conn = connect_db(db_path)
            self.audit_db_path = db_path
            init_db(conn)
            self.audit_conn = conn
            self.audit_run_id = insert_update_run(
                conn,
                status="started",
                dry_run=False,
                mode=self.options.mode,
                wud_file=self.options.wud_file_label or str(self.options.wud_file),
                log_file=str(self.log_file),
            )
            for target in parsed.targets:
                insert_pending_update(
                    conn,
                    run_id=self.audit_run_id,
                    line_no=target.line_no,
                    raw=target.raw,
                    image=target.first,
                    target_digest=target.digest,
                    desired_tag=target.desired_tag,
                )
            self._apply_audit_db_owner(chown_parent=chown_parent)
        except (OSError, sqlite3.Error, DatabaseError, OwnerConfigError) as exc:
            if self.audit_conn is not None and self.audit_run_id is not None:
                self._finish_audit_run("failure", best_effort=True)
            if conn is not None:
                conn.close()
            self.audit_conn = None
            self.audit_run_id = None
            self.audit_db_path = None
            raise UpdaterError(f"Could not initialize audit database: {exc}") from exc

    def _apply_audit_db_owner(self, *, chown_parent: bool = False) -> None:
        if self.audit_db_path is None:
            return
        _apply_sqlite_owner(
            self.audit_db_path,
            self.owner,
            chown_parent=chown_parent,
        )

    def _finish_audit_run(self, status: str, *, best_effort: bool = False) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        try:
            with self.audit_conn:
                self.audit_conn.execute(
                    """
                    UPDATE update_runs
                    SET status = ?,
                        finished_at = ?
                    WHERE id = ?
                    """,
                    (status, db_utc_timestamp(), self.audit_run_id),
                )
        except sqlite3.Error:
            if best_effort:
                return
            raise

    def _mark_unmatched_pending(
        self,
        parsed: ParsedWudFile,
        matches: Sequence[Match],
        skipped_tags: Sequence[WudTarget],
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        matched_lines = {match.target.line_no for match in matches}
        skipped_lines = {target.line_no for target in skipped_tags}
        for target in parsed.targets:
            if target.line_no in matched_lines:
                continue
            reason = "tag-update-disabled" if target.line_no in skipped_lines else "unmatched"
            update_pending_update(
                self.audit_conn,
                run_id=self.audit_run_id,
                line_no=target.line_no,
                status="pending",
                status_reason=reason,
            )

    def _mark_matched_pending(
        self,
        matches: Sequence[Match],
        *,
        status: str,
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        for line_no, match in _first_match_by_line(matches).items():
            update_pending_update(
                self.audit_conn,
                run_id=self.audit_run_id,
                line_no=line_no,
                status=status,
                status_reason="matched",
                service_key=_service_key(match),
                stack_name=match.stack.name,
                service_name=match.service,
            )

    def _mark_removed_pending(
        self,
        parsed: ParsedWudFile,
        remove_lines: Iterable[int],
        matches: Sequence[Match],
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        matched_lines = {match.target.line_no for match in matches}
        removed_lines = set(remove_lines) - matched_lines
        for target in parsed.targets:
            if target.line_no not in removed_lines:
                continue
            update_pending_update(
                self.audit_conn,
                run_id=self.audit_run_id,
                line_no=target.line_no,
                status="resolved",
                status_reason="removed-before-run",
            )

    def _mark_failed_pending(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
        failed_lines: Iterable[int],
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        for line_no in failed_lines:
            match = _failed_match_for_line(line_no, matches, stack_statuses)
            if match is None:
                continue
            reason = _line_status_reason(line_no, matches, stack_statuses)
            update_pending_update(
                self.audit_conn,
                run_id=self.audit_run_id,
                line_no=line_no,
                status="failed",
                status_reason=reason,
                service_key=_service_key(match),
                stack_name=match.stack.name,
                service_name=match.service,
            )

    def _mark_successful_pending(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        failed = set(_failed_line_numbers(matches, stack_statuses))
        for line_no, match in _first_match_by_line(matches).items():
            if line_no in failed:
                continue
            reason = _line_status_reason(line_no, matches, stack_statuses)
            update_pending_update(
                self.audit_conn,
                run_id=self.audit_run_id,
                line_no=line_no,
                status="resolved",
                status_reason=reason,
                service_key=_service_key(match),
                stack_name=match.stack.name,
                service_name=match.service,
            )

    def _record_update_events(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        if self.audit_conn is None or self.audit_run_id is None:
            return
        for match in matches:
            status = stack_statuses.get(match.stack.index, StackStatus("failure", "missing"))
            insert_update_event(
                self.audit_conn,
                run_id=self.audit_run_id,
                service_name=match.service,
                stack_name=match.stack.name,
                image=match.compose_image,
                target_image=_target_image_for_match(match),
                status=status.status,
                metadata_json=json.dumps({"reason": status.reason}, sort_keys=True),
            )

    def _record_known_images(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        if self.audit_conn is None:
            return
        for match in matches:
            status = stack_statuses.get(match.stack.index)
            if status is None or status.status != "success":
                continue
            image = _target_image_for_match(match)
            upsert_known_image(
                self.audit_conn,
                service_key=_service_key(match),
                image=image,
                image_id=self.docker.image_id(image),
                digest=self.docker.image_digest(image),
            )

    def _mark_failed_lines_restored(self, failed_lines: Iterable[int]) -> None:
        restored = set(failed_lines)
        for failure in self.failures:
            failure_lines = {match.target.line_no for match in failure.matches}
            failure.wud_restored = bool(failure_lines & restored)

    def _write_error_report(self) -> Path | None:
        if not self.failures:
            return None
        report_path = self._error_report_path()
        content = self._render_error_report(report_path)
        try:
            return _create_unique_text_file_exclusive(
                report_path,
                content,
                owner=self.owner,
            )
        except OSError as exc:
            self.log.error(f"Could not write error report: {exc}")
            return None

    def _error_report_path(self) -> Path:
        name = self.log_file.name
        if name.endswith(".log"):
            name = f"{name[:-4]}.errors.log"
        else:
            name = f"{name}.errors.log"
        return self.log_file.with_name(name)

    def _render_error_report(self, report_path: Path) -> str:
        content = [
            "WUD-Updater error report\n",
            f"timestamp={timestamp()}\n",
            f"central_log={self.log_file}\n",
            f"error_report={report_path}\n",
            f"failures={len(self.failures)}\n",
        ]
        for index, failure in enumerate(self.failures, start=1):
            content.extend(self._render_failure(index, failure))
        return "".join(content)

    def _render_failure(self, index: int, failure: FailureRecord) -> list[str]:
        services = " ".join(failure.services or ()) or "stack-level"
        restored = _restored_text(failure.wud_restored)
        content = [
            f"\n[Failure {index}]\n",
            f"stack={failure.stack.name}\n",
            f"stack_dir={failure.stack.directory}\n",
            f"compose_file={failure.stack.file}\n",
            f"services={services}\n",
            f"phase={failure.phase}\n",
            f"reason={failure.reason}\n",
            f"wud_entries_restored={restored}\n",
            "targets:\n",
        ]
        for line in _failure_target_lines(failure.matches):
            content.append(f"  {line}\n")
        if failure.note:
            content.append(f"note={sanitize_stream(failure.note)}\n")
        result = failure.command_result
        if result is not None:
            content.extend(_render_command_result(result))
        details_label = "details" if failure.phase == "preflight" else "health"
        content.append(f"{details_label}:\n")
        content.extend(_indented_block(failure.health_details, "  "))
        return content

    def _print_header(self) -> None:
        opts = self.options
        self.log.info("docker-update-from-wud-v2")
        self.log.info(f"Base    : {opts.docker_base_label or str(opts.docker_base)}")
        if opts.host_docker_base is not None:
            self.log.info(
                f"HostBase: {opts.host_docker_base_label or str(opts.host_docker_base)}"
            )
        self.log.info(f"WUD file: {opts.wud_file_label or str(opts.wud_file)}")
        self.log.info(f"Log file: {self.log_file}")
        self.log.info(f"Mode    : {opts.mode}")
        self.log.info(f"Dry-run : {_bool_text(opts.dry_run)}")
        self.log.info(f"Confirm : {_bool_text(opts.assume_yes)}")
        self.log.info(f"TagEdit : {_bool_text(opts.allow_tag_updates)}")
        self.log.info(f"MaxWait : {opts.max_wait}s")
        if opts.only_lines:
            self.log.info(f"Only    : {opts.only_lines}")
        if opts.remove_lines_before_run:
            self.log.info(f"Remove  : {opts.remove_lines_before_run}")
        for override in opts.tag_overrides:
            self.log.info(f"Override: line {override.line_no} tag={override.tag}")
        if self.owner.configured:
            self.log.info(f"Owner   : {self.owner.uid}:{self.owner.gid}")
        self.log.info("PTY     : python subprocess")

    def _print_targets(self, parsed: ParsedWudFile) -> None:
        if self.log.rich_enabled():
            self.log.plain("INFO", "Targets:")
            rows: list[tuple[int, str, str, str]] = []
            for target in parsed.targets:
                suffix = f" sha256={target.digest}" if target.digest else ""
                suffix += f" tag={target.desired_tag}" if target.desired_tag else ""
                self.log.plain(
                    "INFO",
                    f"  line {target.line_no}: {target.first}{suffix}",
                )
                rows.append(
                    (
                        target.line_no,
                        target.first,
                        target.digest,
                        target.desired_tag,
                    )
                )
            self.log.renderer.updater_targets(rows)
            return

        self.log.info("Targets:")
        for target in parsed.targets:
            suffix = f" sha256={target.digest}" if target.digest else ""
            suffix += f" tag={target.desired_tag}" if target.desired_tag else ""
            self.log.info(f"  line {target.line_no}: {target.first}{suffix}")

    def _print_skipped_tag_updates(self, skipped_tags: Sequence[WudTarget]) -> None:
        if not skipped_tags:
            return
        self.log.warn("Tag update entries require --allow-tag-updates and were left pending:")
        for target in skipped_tags:
            desired_image = image_with_tag(target.first, target.desired_tag)
            self.log.info(f"  line {target.line_no}: {target.first} -> {desired_image}")

    def _print_plan(self, matches: Sequence[Match]) -> None:
        if self.log.rich_enabled():
            self.log.plain("INFO", "Stacks to update:")
            rows: list[tuple[str, str, list[str]]] = []
            for stack in _stacks_to_update(matches):
                self.log.plain("INFO", f"  - {stack.name} ({stack.directory})")
                stack_matches = [
                    match for match in matches if match.stack.index == stack.index
                ]
                scope = self._update_scope(stack, stack_matches)
                services_label = _scope_plan_label(scope)
                self.log.plain("INFO", f"      services: {services_label}")

                plan_lines: list[str] = []
                lines = {
                    (
                        match.target.line_no,
                        match.target.first,
                        match.resolved,
                        match.target.desired_tag,
                    )
                    for match in stack_matches
                }
                for line_no, target, resolved, desired_tag in sorted(lines):
                    line = _plan_line(line_no, target, resolved, desired_tag)
                    self.log.plain("INFO", f"      {line}")
                    plan_lines.append(line)
                rows.append((stack.name, services_label, plan_lines))
            self.log.renderer.updater_stack_plan(rows)
            return

        self.log.info("Stacks to update:")
        for stack in _stacks_to_update(matches):
            self.log.info(f"  - {stack.name} ({stack.directory})")
            stack_matches = [match for match in matches if match.stack.index == stack.index]
            scope = self._update_scope(stack, stack_matches)
            self.log.info(f"      services: {_scope_plan_label(scope)}")
            lines = {
                (match.target.line_no, match.target.first, match.resolved, match.target.desired_tag)
                for match in stack_matches
            }
            for line_no, target, resolved, desired_tag in sorted(lines):
                self.log.info(f"      {_plan_line(line_no, target, resolved, desired_tag)}")

    def _confirm_before_mutation(self) -> None:
        if self.options.assume_yes:
            return
        if not sys.stdin.isatty():
            raise UpdaterError("Refusing to mutate without --yes because stdin is not a TTY.")
        print("Proceed with docker compose pull/restart and WUD cleanup? [y/N] ", end="")
        answer = sys.stdin.readline().strip()
        if answer not in {"y", "Y", "yes", "YES"}:
            raise UpdaterError("Aborted before mutation.")


def run_update_from_wud(
    options: UpdaterOptions,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    try:
        return UpdateFromWudRunner(options, environ=environ).run()
    except (UpdaterError, OwnerConfigError, WudLockError) as exc:
        log_dir = options.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        print(f"[{timestamp()}] {exc}", file=sys.stderr)
        return 1


def options_from_namespace(args: object, *, environ: Mapping[str, str] | None = None) -> UpdaterOptions:
    env = os.environ if environ is None else environ
    home = env.get("HOME") or str(Path.home())
    docker_base_label = str(getattr(args, "base", None) or f"{home}/docker")
    wud_file_label = str(
        getattr(args, "file", None) or f"{docker_base_label}/wud/out/images.todo"
    )
    log_dir_label = str(
        getattr(args, "log_dir", None) or env.get("WUD_LOG_DIR") or "./logs"
    )
    docker_base = Path(docker_base_label)
    wud_file = Path(wud_file_label)
    log_dir = Path(log_dir_label)
    db_path = Path(env.get("WUD_DB_PATH") or str(log_dir / "wud-updater.sqlite"))
    host_docker_base_label = env.get("HOST_DOCKER_BASE") or ""
    host_docker_base = Path(host_docker_base_label) if host_docker_base_label else None
    if host_docker_base is not None:
        if not host_docker_base.is_absolute():
            raise UpdaterError("HOST_DOCKER_BASE must be an absolute path")
        if not docker_base.is_absolute():
            raise UpdaterError(
                "DOCKER_BASE must be an absolute path when HOST_DOCKER_BASE is set"
            )
    max_wait = parse_seconds(getattr(args, "max_wait", None), "--max-wait")
    tag_overrides = parse_tag_overrides(getattr(args, "tag_override", None) or ())
    allow_tag_updates = bool(getattr(args, "allow_tag_updates", False))
    if tag_overrides and not allow_tag_updates:
        raise UpdaterError("--tag-override requires --allow-tag-updates")
    return UpdaterOptions(
        docker_base=docker_base,
        wud_file=wud_file,
        log_dir=log_dir,
        mode=getattr(args, "mode", None) or DEFAULT_UPDATE_MODE,
        max_wait=max_wait,
        dry_run=bool(getattr(args, "dry_run", False)),
        assume_yes=bool(getattr(args, "yes", False)),
        allow_tag_updates=allow_tag_updates,
        no_color=bool(getattr(args, "no_color", False)),
        only_lines=getattr(args, "only_lines", None) or "",
        remove_lines_before_run=getattr(args, "remove_lines_before_run", None) or "",
        tag_overrides=tag_overrides,
        db_path=db_path,
        docker_base_label=docker_base_label,
        host_docker_base=host_docker_base,
        host_docker_base_label=host_docker_base_label or None,
        wud_file_label=wud_file_label,
        log_dir_label=log_dir_label,
    )


def prepare_log_file(log_dir: Path, owner: OwnerConfig) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    apply_configured_owner(log_dir, owner)
    log_file = log_dir / f"update-from-wud-v2-{file_timestamp()}.log"
    try:
        return _create_unique_text_file_exclusive(log_file, "", owner=owner)
    except OSError as exc:
        raise UpdaterError(f"Could not create updater log file: {exc}") from exc


def _create_unique_text_file_exclusive(
    path: Path,
    content: str,
    *,
    owner: OwnerConfig | None = None,
    encoding: str = "utf-8",
) -> Path:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    owner = owner or OwnerConfig()

    for attempt in range(_EXCLUSIVE_CREATE_ATTEMPTS):
        candidate = _collision_path(path, attempt)
        fd = -1
        try:
            fd = os.open(candidate, flags, 0o666)
            if owner.configured:
                if owner.uid is None or owner.gid is None:
                    raise OwnerConfigError(
                        "OUT_UID and OUT_GID/OUT_GUID must be set together"
                    )
                os.fchown(fd, owner.uid, owner.gid)
            with os.fdopen(fd, "w", encoding=encoding, newline="") as file:
                fd = -1
                file.write(content)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                continue
            raise
        finally:
            if fd != -1:
                os.close(fd)

    raise FileExistsError(
        errno.EEXIST,
        f"could not create a unique file after {_EXCLUSIVE_CREATE_ATTEMPTS} attempts",
        str(path),
    )


def _collision_path(path: Path, attempt: int) -> Path:
    if attempt == 0:
        return path
    return path.with_name(f"{path.stem}-{attempt}{path.suffix}")


def parse_seconds(value: str | None, label: str) -> int:
    if value is None or value == "":
        return DEFAULT_MAX_WAIT
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise UpdaterError(f"{label} must be an integer number of seconds")
    return int(str(value), 10)


def parse_tag_overrides(values: Sequence[str]) -> tuple[TagOverride, ...]:
    overrides: list[TagOverride] = []
    seen: set[int] = set()
    for value in values:
        line_raw, sep, tag = value.partition("=")
        if not sep or not line_raw or not tag:
            raise UpdaterError("--tag-override must use LINE=TAG")
        if not re.fullmatch(r"[0-9]+", line_raw):
            raise UpdaterError("--tag-override line must be a positive integer")
        line_no = int(line_raw, 10)
        if line_no < 1:
            raise UpdaterError("--tag-override line must be a positive integer")
        if line_no in seen:
            raise UpdaterError(f"--tag-override line {line_no} was provided more than once")
        if not tag_value_valid(tag):
            raise UpdaterError(f"--tag-override line {line_no} has invalid tag: {tag}")
        overrides.append(TagOverride(line_no=line_no, tag=tag))
        seen.add(line_no)
    return tuple(overrides)


def apply_compose_tag_updates(
    compose_path: Path,
    updates: Sequence[TagUpdate],
) -> tuple[AppliedTagUpdate, ...]:
    if not updates:
        return ()

    source = compose_path.read_text(encoding="utf-8")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        parsed = yaml.load(source)
    except YAMLError as exc:
        raise ComposeTagRewriteError(
            f"Compose file YAML could not be parsed: {exc}"
        ) from exc
    if not isinstance(parsed, CommentedMap):
        raise ComposeTagRewriteError("Compose file is not a YAML mapping.")
    services = parsed.get("services")
    if not isinstance(services, CommentedMap):
        raise ComposeTagRewriteError("Compose file has no services mapping.")

    line_offsets = _line_start_offsets(source)
    spans: list[tuple[int, int, str, TagUpdate]] = []
    counts = {id(update): 0 for update in updates}
    seen_spans: set[tuple[int, int]] = set()

    for update in updates:
        if not update.services:
            raise ComposeTagRewriteError(
                f"No compose service was mapped for {update.old_image}."
            )
        for service in update.services:
            span = _service_image_scalar_span(
                services,
                service,
                update.old_image,
                source,
                line_offsets,
            )
            if span in seen_spans:
                raise ComposeTagRewriteError(
                    f"Service {service} image for {update.old_image} was "
                    "selected more than once."
                )
            seen_spans.add(span)
            spans.append((*span, update.new_image, update))
            counts[id(update)] += 1

    rendered = source
    for start, end, replacement, _update in sorted(
        spans,
        key=lambda item: item[0],
        reverse=True,
    ):
        rendered = f"{rendered[:start]}{replacement}{rendered[end:]}"

    applied = tuple(
        AppliedTagUpdate(
            old_image=update.old_image,
            desired_tag=update.desired_tag,
            new_image=update.new_image,
            services=update.services,
            replacements=counts[id(update)],
        )
        for update in updates
    )
    if any(item.replacements < 1 for item in applied):
        return ()

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{compose_path.name}.tag.",
        dir=str(compose_path.parent),
    )
    tmp_path: Path | None = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            tmp.write(rendered)
        st = compose_path.stat()
        os.chown(tmp_path, st.st_uid, st.st_gid)
        os.chmod(tmp_path, st.st_mode & 0o7777)
        os.replace(tmp_path, compose_path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    return applied


def _line_start_offsets(source: str) -> list[int]:
    offsets = [0]
    for match in re.finditer("\n", source):
        offsets.append(match.end())
    return offsets


def _service_image_scalar_span(
    services: CommentedMap,
    service: str,
    old_image: str,
    source: str,
    line_offsets: Sequence[int],
) -> tuple[int, int]:
    service_config = services.get(service)
    if not isinstance(service_config, CommentedMap):
        raise ComposeTagRewriteError(
            f"Service {service} is not a mapping with a direct image field."
        )
    image_value = service_config.get("image")
    if not isinstance(image_value, str):
        raise ComposeTagRewriteError(
            f"Service {service} image is not a direct string scalar."
        )
    if "$" in image_value:
        raise ComposeTagRewriteError(
            f"Service {service} image uses interpolation and needs manual review."
        )
    if image_value != old_image:
        raise ComposeTagRewriteError(
            f"Service {service} image is {image_value}, expected {old_image}."
        )

    try:
        line_no, _col = service_config.lc.value("image")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ComposeTagRewriteError(
            f"Service {service} image source location is unavailable."
        ) from exc

    if line_no < 0 or line_no >= len(line_offsets):
        raise ComposeTagRewriteError(
            f"Service {service} image source location is invalid."
        )

    line_start = line_offsets[line_no]
    line_end = source.find("\n", line_start)
    if line_end == -1:
        line_end = len(source)
    line = source[line_start:line_end]
    body = line[:-1] if line.endswith("\r") else line
    pattern = re.compile(
        r"^([ \t]*(?:[\"']image[\"']|image)[ \t]*:[ \t]*)"
        r"([\"']?)"
        + re.escape(old_image)
        + r"\2"
        r"([ \t]*(?:#.*)?)$"
    )
    match = pattern.fullmatch(body)
    if match is None:
        raise ComposeTagRewriteError(
            f"Service {service} image uses unsupported YAML syntax for automatic "
            "rewrite."
        )

    start = line_start + len(match.group(1)) + len(match.group(2))
    end = start + len(old_image)
    return start, end


def _backup_compose(compose_path: Path) -> Path:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{compose_path.name}.backup.",
        dir=str(compose_path.parent),
    )
    os.close(fd)
    backup = Path(tmp_name)
    shutil.copy2(compose_path, backup)
    return backup


def _services_for_image(service_images: Sequence[ServiceImage], image: str) -> tuple[str, ...]:
    return tuple(sorted({item.service for item in service_images if item.image == image}))


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


def _update_services(matches: Sequence[Match]) -> tuple[str, ...] | None:
    services = sorted({match.service for match in matches if match.service})
    if not services:
        return None
    if any(not match.service for match in matches):
        return None
    return tuple(services)


def _label_value_is_true(value: str) -> bool:
    return value.strip().lower() == "true"


def _stack_level_scope_message(scope: UpdateScope) -> str:
    if scope.stack_reason:
        if scope.pull_services is not None:
            return f"{scope.stack_reason}; using service pull with stack-level recreate"
        return f"{scope.stack_reason}; using stack-level pull/recreate"
    return (
        "Could not map every matched image to a compose service; "
        "using stack-level pull/recreate"
    )


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
) -> str:
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
        if any(stack_statuses.get(idx, StackStatus("failure", "missing")).status != "success" for idx in idxs):
            failed.append(line_no)
    return failed


def _first_match_by_line(matches: Sequence[Match]) -> dict[int, Match]:
    first: dict[int, Match] = {}
    for match in matches:
        first.setdefault(match.target.line_no, match)
    return first


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
        return sorted(failure_reasons)[0]
    reasons = {
        status.reason
        for status in statuses
    }
    if "updated" in reasons:
        return "updated"
    if "already-current" in reasons:
        return "already-current"
    return sorted(reasons)[0] if reasons else "missing"


def _service_key(match: Match) -> str:
    if match.service:
        return f"{match.stack.name}/{match.service}"
    return f"{match.stack.name}/{match.compose_image}"


def _target_image_for_match(match: Match) -> str:
    if match.target.desired_tag:
        return image_with_tag(match.compose_image, match.target.desired_tag)
    return match.resolved


def _db_path(options: UpdaterOptions, environ: Mapping[str, str]) -> Path:
    configured = environ.get("WUD_DB_PATH")
    if configured:
        return Path(configured)
    if options.db_path is not None:
        return options.db_path
    return options.log_dir / "wud-updater.sqlite"


def _sqlite_parent_missing(db_path: Path) -> bool:
    return str(db_path) != ":memory:" and not db_path.parent.exists()


def _apply_sqlite_owner(
    db_path: Path,
    owner: OwnerConfig,
    *,
    chown_parent: bool = False,
) -> None:
    if not owner.configured or str(db_path) == ":memory:":
        return
    if chown_parent and db_path.parent.exists():
        apply_configured_owner(db_path.parent, owner)
    for path in _sqlite_state_paths(db_path):
        if path.exists():
            apply_configured_owner(path, owner)


def _sqlite_state_paths(db_path: Path) -> tuple[Path, ...]:
    return (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    )


def _updated_images(
    before: Mapping[str, ImageState],
    after: Mapping[str, ImageState],
) -> list[tuple[str, ImageState]]:
    changes: list[tuple[str, ImageState]] = []
    for image, old in before.items():
        new = after.get(image)
        if new is not None and new.image_id and old.image_id != new.image_id:
            changes.append((image, new))
    return changes


def _cid_is_ok(summary: str) -> bool:
    _name, status, health, _restarts, _exit_code = _split_summary(summary)
    if health != "none":
        return health == "healthy"
    return status == "running"


def _split_summary(summary: str) -> tuple[str, str, str, str, str]:
    parts = summary.split("|", 4)
    while len(parts) < 5:
        parts.append("")
    return tuple(parts[:5])  # type: ignore[return-value]


def safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT_RE.sub("_", value)
    return cleaned or "tag"


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


def _render_command_result(result: CommandResult) -> list[str]:
    content = [
        "command:\n",
        f"  cwd={result.cwd if result.cwd is not None else ''}\n",
        f"  argv={result.display}\n",
        f"  exit_code={result.returncode}\n",
        f"  stdout_tail_truncated={_bool_text(result.stdout_truncated)}\n",
        "  stdout_tail:\n",
    ]
    content.extend(_indented_block(result.stdout, "    "))
    content.append(f"  stderr_tail_truncated={_bool_text(result.stderr_truncated)}\n")
    content.append("  stderr_tail:\n")
    content.extend(_indented_block(result.stderr, "    "))
    return content


def _indented_block(value: str, prefix: str) -> list[str]:
    if not value.strip():
        return [f"{prefix}(empty)\n"]
    lines: list[str] = []
    for line in value.splitlines():
        lines.append(f"{prefix}{sanitize_stream(line)}\n")
    return lines


def _restored_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def sanitize_stream(value: str) -> str:
    return _CONTROL_RE.sub("", value.replace("\r", "\n")).strip()


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def file_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
