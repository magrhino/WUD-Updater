"""Python implementation of ``bin/docker-update-from-wud``."""

from __future__ import annotations

import errno
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .command import CommandError, CommandResult, CommandRunner
from .compose import ComposeCli, ComposeDiscoveryError, ComposeStack, ServiceImage
from .config import DEFAULT_MAX_WAIT, DEFAULT_UPDATE_MODE
from .docker_cli import DockerCli
from .file_ops import OwnerConfig, OwnerConfigError, apply_configured_owner
from .images import (
    image_has_tag,
    image_matches_resolved_target,
    image_with_tag,
)
from .line_specs import LineSpecError, parse_line_spec
from .locks import DirectoryLock, WudLockError
from .wud_file import (
    ParsedWudFile,
    WudTarget,
    parse_wud_file,
    remove_lines_before_run,
    restore_failed_lines,
)


CONTAINER_SUMMARY_FORMAT = "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.ExitCode}}"
HEALTH_LOG_FORMAT = "{{if .State.Health}}{{range .State.Health.Log}}{{println .Output}}{{end}}{{end}}"
VALID_MODES = frozenset({"pause", "stop", "live"})
_IMAGE_LINE_RE = re.compile(
    r"^([ \t]*image:[ \t]*)([\"']?)([^\"'\s#]+)\2([ \t]*(?:#.*)?)$"
)
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXCLUSIVE_CREATE_ATTEMPTS = 100


class UpdaterError(RuntimeError):
    """Raised for a user-facing updater failure."""


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
    docker_base_label: str | None = None
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
    def __init__(self, log_file: Path, *, no_color: bool = False) -> None:
        self.log_file = log_file
        self.no_color = no_color

    def info(self, message: str) -> None:
        self._term("INFO", message)

    def warn(self, message: str) -> None:
        self._term("WARN", message)

    def error(self, message: str) -> None:
        self._term("ERROR", message, stream=sys.stderr)

    def plain(self, level: str, message: str) -> None:
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp()}] [{level}] {message}\n")

    def _term(self, level: str, message: str, *, stream: object | None = None) -> None:
        if stream is None:
            stream = sys.stdout
        print(f"[{timestamp()}] {message}", file=stream)
        self.plain(level, message)


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
        self.log = Logger(self.log_file, no_color=options.no_color)
        self.failures: list[FailureRecord] = []

    def run(self) -> int:
        opts = self.options
        if opts.mode not in VALID_MODES:
            raise UpdaterError("--mode must be pause|stop|live")
        if opts.max_wait < 0:
            raise UpdaterError("--max-wait must be an integer number of seconds")

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
            stacks = self.compose.discover_stacks(opts.docker_base)
            matches, skipped_tags = self._build_matches(parsed, stacks)
            self._print_skipped_tag_updates(skipped_tags)

            if not matches:
                self.log.info("No stacks matched the list; nothing to do.")
                return 0

            self._print_plan(matches)

            if opts.dry_run:
                self.log.info(
                    "Dry-run only; no pull, restart, health wait, or cleanup performed."
                )
                return 0

            self._confirm_before_mutation()
            in_flight_lines = sorted(
                {match.target.line_no for match in matches}
                | set(parse_line_spec(opts.remove_lines_before_run, len(parsed.lines), "--remove-lines-before-run"))
            )
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
                self.log.warn(f"Restored failed WUD entries in {opts.wud_file}")
            else:
                self._mark_failed_lines_restored(())
                self.log.info("Successful WUD entries were removed before update.")

            fail_count = sum(1 for status in stack_statuses.values() if status.status != "success")
            if fail_count:
                error_report = self._write_error_report()
                if error_report is not None:
                    self.log.error(
                        f"Completed with {fail_count} failure(s). See log: {self.log_file}; "
                        f"error report: {error_report}"
                    )
                else:
                    self.log.error(f"Completed with {fail_count} failure(s). See log: {self.log_file}")
                return 1

            self.log.info(f"Done. See log: {self.log_file}")
            return 0
        except (CommandError, ComposeDiscoveryError, LineSpecError, OwnerConfigError, WudLockError) as exc:
            raise UpdaterError(str(exc)) from exc
        finally:
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
        return parsed

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
        self.log.info(f"[{stack.name}] Checking for updates (mode={opts.mode})")
        services = _update_services(matches)
        service_scoped = services is not None
        services_label = " ".join(services or ())
        if service_scoped:
            self.log.info(f"[{stack.name}] Matched compose service(s): {services_label}")
        else:
            self.log.warn(
                f"[{stack.name}] Could not map every matched image to a compose service; using stack-level pull/recreate"
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
                    note=str(exc),
                )
                return StackStatus("failure", "compose-backup-failed")
            try:
                applied_tags = apply_compose_tag_updates(compose_path, tag_updates)
            except OSError as exc:
                self.log.error(
                    f"[{stack.name}] Could not rewrite compose image tag(s): {exc}"
                )
                self._record_failure(
                    stack,
                    matches,
                    phase="compose-tag-rewrite",
                    reason="compose-tag-rewrite-failed",
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
                )
            current_stack = refreshed
            images = tuple(current_stack.images)

        try:
            self.compose.pull(stack.directory, stack.file, services)
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
                )
            self._record_failure(
                stack,
                matches,
                phase="pull",
                reason="pull-failed",
                command_error=exc,
                health_details=self._capture_health_details(stack, services),
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
                )
            self._record_failure(
                stack,
                matches,
                phase="digest",
                reason="expected-digest-not-reached",
                health_details=self._capture_health_details(stack, services),
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
        down_phase = "stop" if service_scoped else "down"
        if opts.mode == "pause":
            self.log.warn(
                f"[{stack.name}] Mode pause is deprecated; pausing before recreate and unpausing before health check"
            )
            try:
                self.compose.pause(stack.directory, stack.file, services)
            except CommandError:
                self.log.warn(f"[{stack.name}] Pause failed; continuing with live recreate")
        elif opts.mode == "stop":
            try:
                if service_scoped:
                    self.log.warn(f"[{stack.name}] Stopping affected service(s): {services_label}")
                    self.compose.stop(stack.directory, stack.file, services)
                else:
                    self.log.warn(f"[{stack.name}] Bringing down stack")
                    self.compose.down(stack.directory, stack.file)
            except CommandError as exc:
                down_failed = True
                down_error = exc
                self.log.warn(
                    f"[{stack.name}] Stop/down failed; attempting up for recovery, but this stack will not be marked successful"
                )

        if service_scoped:
            self.log.info(f"[{stack.name}] Bringing affected service(s) up: {services_label}")
        else:
            self.log.info(f"[{stack.name}] Bringing stack up")

        up_result = self._run_compose_up(stack, services)
        if not up_result.ok:
            if applied_tags and compose_backup is not None:
                return self._handle_tag_update_failure(
                    stack,
                    matches,
                    services,
                    applied_tags,
                    compose_backup,
                    "up-or-health-failed",
                    phase="up",
                    command_error=up_result.command_error,
                    failure_health=up_result.health_details,
                )
            if down_failed and down_error is not None:
                self._record_failure(
                    stack,
                    matches,
                    phase=down_phase,
                    reason="down-failed",
                    command_error=down_error,
                    health_details=self._capture_health_details(stack, services),
                    note="Update recovery also failed during compose up.",
                )
            self._record_failure(
                stack,
                matches,
                phase="up",
                reason="up-or-health-failed",
                command_error=up_result.command_error,
                health_details=up_result.health_details,
            )
            return StackStatus("failure", "up-or-health-failed")

        if opts.mode == "pause":
            self.log.warn(f"[{stack.name}] Unpausing before health check")
            try:
                self.compose.unpause(stack.directory, stack.file, services)
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
                    )
                self._record_failure(
                    stack,
                    matches,
                    phase="unpause",
                    reason="unpause-failed",
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
                    )
                self._record_failure(
                    stack,
                    matches,
                    phase=down_phase,
                    reason="down-failed",
                    command_error=down_error,
                    health_details=self._capture_health_details(stack, services),
                    note="Compose up recovery succeeded, but the earlier stop/down command failed.",
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
            )
        self._record_failure(
            stack,
            matches,
            phase="health",
            reason="health-failed",
            health_details=health_details,
        )
        return StackStatus("failure", "health-failed")

    def _run_compose_up(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
    ) -> UpResult:
        if self.options.mode != "pause" and self.compose.up_wait_supported(stack.directory, stack.file):
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
                )
                return UpResult(True, True)
            except CommandError as exc:
                self.log.error(f"[{stack.name}] docker compose up --wait failed")
                health_details = self._capture_health_details(stack, services)
                self._log_health_details(stack, services, health_details)
                return UpResult(False, True, exc, health_details)

        try:
            self.compose.up(stack.directory, stack.file, services)
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
            cids = self.compose.ps_quiet(stack.directory, stack.file, services)
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
    ) -> StackStatus:
        if failure_health is None:
            failure_health = self._capture_health_details(stack, services)
        self.log.warn(f"[{stack.name}] Restoring compose file after failed tag update.")
        rollback_result = "rollback-failed-manual-review-required"
        rollback_error: CommandError | None = None
        try:
            shutil.copy2(compose_backup, stack.directory / stack.file)
            rollback_up = self._run_compose_up(stack, services)
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

        report_error = command_error or rollback_error
        self._record_failure(
            stack,
            matches,
            phase=phase,
            reason=reason,
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

    def _capture_health_details(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
    ) -> str:
        cids = self.compose.ps_quiet(stack.directory, stack.file, services)
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

    def _verify_expected_digests(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        images: Sequence[str],
    ) -> bool:
        ok = True
        requirements = {
            (match.target.line_no, match.target.first, match.resolved, match.target.digest)
            for match in matches
            if match.target.digest
        }
        for line_no, target, resolved, expected in sorted(requirements):
            allow_repo = resolved != target or not image_has_tag(resolved)
            matched = False
            digest_ok = False
            for image in images:
                if not image_matches_resolved_target(image, resolved, allow_repo):
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
        updates: set[tuple[str, str, str]] = set()
        for match in matches:
            if match.target.desired_tag:
                new_image = image_with_tag(match.compose_image, match.target.desired_tag)
                updates.add((match.compose_image, match.target.desired_tag, new_image))
        return tuple(TagUpdate(*item) for item in sorted(updates))

    def _refresh_stack_images(self, stack: ComposeStack) -> ComposeStack | None:
        try:
            images = tuple(self.compose.config_images(stack.directory, stack.file))
        except CommandError:
            self.log.error(f"[{stack.name}] Could not refresh compose images after tag rewrite.")
            return None
        return ComposeStack(
            index=stack.index,
            directory=stack.directory,
            file=stack.file,
            name=stack.name,
            images=images,
            service_images=self.compose.try_service_image_pairs(stack.directory, stack.file),
        )

    def _record_failure(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        *,
        phase: str,
        reason: str,
        command_error: CommandError | None = None,
        health_details: str = "",
        note: str = "",
    ) -> None:
        services = _update_services(matches)
        self.failures.append(
            FailureRecord(
                stack=stack,
                services=services,
                matches=tuple(matches),
                phase=phase,
                reason=reason,
                command_result=command_error.result if command_error else None,
                health_details=health_details,
                note=note,
            )
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
        content.append("health:\n")
        content.extend(_indented_block(failure.health_details, "  "))
        return content

    def _print_header(self) -> None:
        opts = self.options
        self.log.info("docker-update-from-wud-v2")
        self.log.info(f"Base    : {opts.docker_base_label or str(opts.docker_base)}")
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
        if self.owner.configured:
            self.log.info(f"Owner   : {self.owner.uid}:{self.owner.gid}")
        self.log.info("PTY     : python subprocess")

    def _print_targets(self, parsed: ParsedWudFile) -> None:
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
        self.log.info("Stacks to update:")
        for stack in _stacks_to_update(matches):
            self.log.info(f"  - {stack.name} ({stack.directory})")
            stack_matches = [match for match in matches if match.stack.index == stack.index]
            services = _update_services(stack_matches)
            if services is None:
                self.log.info("      services: stack-level fallback")
            else:
                self.log.info(f"      services: {' '.join(services)}")
            lines = {
                (match.target.line_no, match.target.first, match.resolved, match.target.desired_tag)
                for match in stack_matches
            }
            for line_no, target, resolved, desired_tag in sorted(lines):
                if desired_tag:
                    desired_image = image_with_tag(resolved, desired_tag)
                    self.log.info(
                        f"      line {line_no}: {resolved} -> {desired_image} (tag update)"
                    )
                elif target == resolved:
                    self.log.info(f"      line {line_no}: {target}")
                else:
                    self.log.info(f"      line {line_no}: {target} -> {resolved}")

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
    max_wait = parse_seconds(getattr(args, "max_wait", None), "--max-wait")
    return UpdaterOptions(
        docker_base=docker_base,
        wud_file=wud_file,
        log_dir=log_dir,
        mode=getattr(args, "mode", None) or DEFAULT_UPDATE_MODE,
        max_wait=max_wait,
        dry_run=bool(getattr(args, "dry_run", False)),
        assume_yes=bool(getattr(args, "yes", False)),
        allow_tag_updates=bool(getattr(args, "allow_tag_updates", False)),
        no_color=bool(getattr(args, "no_color", False)),
        only_lines=getattr(args, "only_lines", None) or "",
        remove_lines_before_run=getattr(args, "remove_lines_before_run", None) or "",
        docker_base_label=docker_base_label,
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


def apply_compose_tag_updates(
    compose_path: Path,
    updates: Sequence[TagUpdate],
) -> tuple[AppliedTagUpdate, ...]:
    new_for = {update.old_image: update for update in updates}
    counts = {update.old_image: 0 for update in updates}
    original = compose_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rendered: list[str] = []
    for line in original:
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        match = _IMAGE_LINE_RE.fullmatch(body)
        if match is not None and match.group(3) in new_for:
            update = new_for[match.group(3)]
            rendered.append(
                f"{match.group(1)}{match.group(2)}{update.new_image}"
                f"{match.group(2)}{match.group(4)}{newline}"
            )
            counts[update.old_image] += 1
        else:
            rendered.append(line)

    applied = tuple(
        AppliedTagUpdate(
            old_image=update.old_image,
            desired_tag=update.desired_tag,
            new_image=update.new_image,
            replacements=counts[update.old_image],
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
            tmp.write("".join(rendered))
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


def _update_services(matches: Sequence[Match]) -> tuple[str, ...] | None:
    services = sorted({match.service for match in matches if match.service})
    if not services:
        return None
    if any(not match.service for match in matches):
        return None
    return tuple(services)


def _stacks_to_update(matches: Sequence[Match]) -> tuple[ComposeStack, ...]:
    stacks: dict[int, ComposeStack] = {}
    for match in matches:
        stacks[match.stack.index] = match.stack
    return tuple(stacks[idx] for idx in sorted(stacks))


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
