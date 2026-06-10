"""Python implementation of ``bin/docker-update-from-wud``."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from . import (
    compose_rewrite as compose_rewrite,
    updater_audit,
    updater_logging,
    updater_preflight,
    updater_tag_exclusions,
)
from .command import CommandError, CommandResult, CommandRunner
from .compose import (
    ComposeBindMount,
    ComposeCli,
    ComposeDiscoveryError,
    ComposeRuntimePortIssue,
    ComposeStack,
    ServiceImage,
)
from .compose_rewrite import (
    DIGEST_PIN_MARKER_PREFIX as DIGEST_PIN_MARKER_PREFIX,
    WUD_TAG_INCLUDE_LABEL as WUD_TAG_INCLUDE_LABEL,
    _backup_compose as _backup_compose,
    _exact_tag_include_matches as _exact_tag_include_matches,
    _is_simple_exact_tag_include as _is_simple_exact_tag_include,
    apply_compose_digest_pins as apply_compose_digest_pins,
    apply_compose_tag_exclusions as apply_compose_tag_exclusions,
    apply_compose_tag_updates as apply_compose_tag_updates,
    compose_escape_dollars as compose_escape_dollars,
    compose_unescape_dollars as compose_unescape_dollars,
    exact_tags_regex as exact_tags_regex,
    js_regex_escape as js_regex_escape,
    merge_wud_exclude_regex as merge_wud_exclude_regex,
    render_compose_digest_pins as render_compose_digest_pins,
    render_compose_tag_exclusions as render_compose_tag_exclusions,
)
from .db import (
    DatabaseError,
    insert_update_event,
)
from .digest_verifier import (
    DigestCheckResult,
    DigestResolveResult,
    DigestVerifier,
    DockerManifestResolver as DockerManifestResolver,
)
from .docker_cli import DockerCli
from .file_ops import OwnerConfig, OwnerConfigError, apply_configured_owner
from .images import (
    image_has_tag,
    image_matches_resolved_target as image_matches_resolved_target,
    image_with_tag,
    normalize_digest as normalize_digest,
    repo_key as repo_key,
)
from .line_specs import LineSpecError, parse_line_spec
from .locks import DirectoryLock, WudLockError
from .updater_cli import (
    options_from_namespace as options_from_namespace,
    parse_seconds as parse_seconds,
    parse_tag_overrides as parse_tag_overrides,
)
from .updater_logging import (
    Logger as Logger,
    file_timestamp as file_timestamp,
    prepare_log_file as prepare_log_file,
    safe_component as safe_component,
    sanitize_stream as sanitize_stream,
    timestamp as timestamp,
)
from .updater_lifecycle import (
    CONTAINER_SUMMARY_FORMAT as CONTAINER_SUMMARY_FORMAT,
    HEALTH_LOG_FORMAT as HEALTH_LOG_FORMAT,
    StackLifecycleExecutor,
    _cid_is_ok as _cid_is_ok,
    _split_summary as _split_summary,
    _stack_level_scope_message as _stack_level_scope_message,
    _tag_update_failure_progress_message as _tag_update_failure_progress_message,
    _tag_update_failure_progress_phase as _tag_update_failure_progress_phase,
    _updated_images as _updated_images,
)
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
    _failed_line_numbers,
    _failure_target_lines,
    _first_match_by_line as _first_match_by_line,
    _label_value_is_true as _label_value_is_true,
    _network_mode_providers as _network_mode_providers,
    _ordered_unique as _ordered_unique,
    _plan_line,
    _scope_plan_label,
    _services_for_image as _services_for_image,
    _services_for_target_match,
    _stacks_to_update,
    _tag_exclusion_preflight_matches,
    _target_image_for_match,
    _unique_matches,
    _update_services,
)
from .updater_planning import (
    _digest_check_allow_repo as _digest_check_allow_repo,
    _digest_check_image as _digest_check_image,
    _tag_exclusion_updates_by_stack as _tag_exclusion_updates_by_stack,
    _unique_tag_exclusion_updates as _unique_tag_exclusion_updates,
)
from .wud_file import (
    ParsedWudFile,
    WudTarget,
    parse_wud_file,
    remove_lines_before_run,
    restore_failed_lines,
)
from .updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagUpdate,
    ComposeTagRewriteError as ComposeTagRewriteError,
    DigestPinCandidate,
    DigestPinUpdate,
    FailureRecord,
    ImageState,
    Match,
    StackStatus,
    TagExclusionUpdate,
    TagUpdate,
    UpResult,
    UpdateScope,
    UpdaterError,
    UpdaterOptions,
    UpdaterProgressEvent,
)

VALID_MODES = frozenset({"pause", "stop", "live"})
_SERVICES_UNSET = object()




class UpdateFromWudRunner:
    def __init__(
        self,
        options: UpdaterOptions,
        *,
        environ: Mapping[str, str] | None = None,
        command_runner: CommandRunner | None = None,
        digest_verifier: DigestVerifier | None = None,
        progress_callback: Callable[[UpdaterProgressEvent], None] | None = None,
    ) -> None:
        self.options = options
        self.environ = os.environ if environ is None else environ
        self.owner = OwnerConfig.from_env(self.environ)
        self.command_runner = command_runner or CommandRunner()
        self.docker = DockerCli(runner=self.command_runner)
        self.digest_verifier = digest_verifier or DigestVerifier(self.docker)
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
        self.applied_digest_pins: dict[tuple[int, int, str], DigestPinUpdate] = {}
        self.digest_pin_update_cache: dict[
            tuple[DigestPinCandidate, ...],
            tuple[DigestPinUpdate, ...],
        ] = {}
        self.progress_callback = progress_callback
        self.lifecycle = StackLifecycleExecutor(self)

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
            self._progress(
                "preflight",
                "running",
                "Checking pending entries, Compose stacks, and update safety.",
            )
            if not opts.wud_file.is_file():
                raise UpdaterError(f"List file not found: {opts.wud_file}")

            if lock.parent_held:
                lock.acquire()

            parsed, excluded_tags = self._parse_wud_files()
            if opts.dry_run or not opts.remove_lines_before_run:
                lock.release_parent()

            if not parsed.targets and not excluded_tags.targets:
                self.log.info("Nothing to do; list is empty.")
                self._progress("preflight", "success", "Pending list is empty.")
                self._progress("completion", "success", "No updates were pending.")
                return 0

            if parsed.targets:
                self._print_targets(parsed)
            self._print_tag_exclusions(excluded_tags)
            stacks = self.compose.discover_stacks(
                opts.docker_base,
                project_base=opts.host_docker_base,
                ignore_paths=opts.compose_ignore_paths,
            )
            exclusion_matches, invalid_exclusions = self._build_tag_exclusion_matches(
                excluded_tags,
                stacks,
            )
            exclusion_updates, exclusion_failures = self._plan_tag_exclusions(
                exclusion_matches,
                stacks,
            )
            exclusion_failures.extend(invalid_exclusions)
            self._print_tag_exclusion_plan(exclusion_updates, exclusion_failures)
            matches, skipped_tags = self._build_matches(parsed, stacks)
            self._print_skipped_tag_updates(skipped_tags)

            if not matches and not exclusion_updates:
                if not opts.dry_run:
                    audit_parsed = self._audit_parsed_file(
                        parsed,
                        [target.line_no for target in excluded_tags.targets],
                    )
                    self._start_audit(audit_parsed)
                    self._mark_unmatched_pending(audit_parsed, matches, skipped_tags)
                    self._mark_tag_exclusion_failures(exclusion_failures)
                    self._finish_audit_run(
                        "failure" if exclusion_failures else "success"
                    )
                self.log.info("No stacks matched the list; nothing to do.")
                self._progress(
                    "preflight",
                    "failure" if exclusion_failures else "success",
                    "No Compose stacks matched the selected pending entries.",
                )
                self._progress(
                    "completion",
                    "failure" if exclusion_failures else "success",
                    "Updater finished without matching a stack.",
                )
                return 1 if exclusion_failures else 0

            if matches:
                self._print_plan(matches)

            if not self._validate_tag_update_plan(matches):
                self._progress(
                    "preflight",
                    "failure",
                    "Tag update plan validation failed.",
                    matches=matches,
                )
                return 1
            if not self._validate_digest_pin_plan(matches):
                self._progress(
                    "preflight",
                    "failure",
                    "Digest-pin plan validation failed.",
                    matches=matches,
                )
                return 1
            preflight_matches = _unique_matches(
                (
                    *matches,
                    *_tag_exclusion_preflight_matches(
                        exclusion_matches,
                        exclusion_updates,
                    ),
                )
            )
            if not self._validate_compose_runtime_ports(preflight_matches):
                if opts.dry_run:
                    self.log.warn(
                        "Dry-run only; reported Compose runtime port issue without mutating."
                    )
                else:
                    audit_parsed = self._audit_parsed_file(
                        parsed,
                        [match.target.line_no for match in preflight_matches],
                    )
                    self._progress(
                        "preflight",
                        "failure",
                        "Compose runtime port preflight failed.",
                        matches=preflight_matches,
                    )
                    return self._finish_preflight_failure(
                        audit_parsed,
                        preflight_matches,
                        skipped_tags,
                    )
            if not self._validate_compose_bind_mount_paths(matches):
                if opts.dry_run:
                    self.log.warn(
                        "Dry-run only; reported container bind-mount path issue without mutating."
                    )
                else:
                    self._progress(
                        "preflight",
                        "failure",
                        "Compose bind-mount preflight failed.",
                        matches=matches,
                    )
                    return self._finish_preflight_failure(parsed, matches, skipped_tags)
            if not self._validate_tag_manifests(matches):
                self._progress(
                    "preflight",
                    "failure",
                    "Target image manifest validation failed.",
                    matches=matches,
                )
                return 1

            self._progress(
                "preflight",
                "success",
                "Preflight checks passed.",
                matches=matches,
            )
            if opts.dry_run:
                self.log.info(
                    "Dry-run only; no pull, restart, health wait, or cleanup performed."
                )
                self._progress("completion", "success", "Dry run completed.")
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
                | {update.source_line for update in exclusion_updates}
            )
            audit_lines = sorted(
                set(in_flight_lines)
                | {target.line_no for target, _reason in exclusion_failures}
            )
            audit_parsed = self._audit_parsed_file(parsed, audit_lines)
            self._start_audit(audit_parsed)
            self._mark_unmatched_pending(audit_parsed, matches, skipped_tags)
            self._mark_removed_pending(audit_parsed, remove_line_numbers, matches)
            self._mark_matched_pending(matches, status="in_progress")
            self._mark_tag_exclusions_pending(exclusion_updates)
            self._mark_tag_exclusion_failures(exclusion_failures)
            remove_lines_before_run(
                opts.wud_file,
                audit_parsed,
                in_flight_lines,
                lock=lock,
                owner=self.owner,
            )
            self.log.info("Removed in-flight WUD entries before update.")
            lock.release_parent()

            exclusion_statuses = self._apply_tag_exclusions(exclusion_updates)
            stack_statuses: dict[int, StackStatus] = {}
            for stack in _stacks_to_update(matches):
                stack_matches = [match for match in matches if match.stack.index == stack.index]
                stack_statuses[stack.index] = self._update_stack(stack, stack_matches)

            self._progress(
                "cleanup",
                "running",
                "Reconciling pending entries after the update attempt.",
                matches=matches,
            )
            failed_lines = _failed_line_numbers(matches, stack_statuses)
            failed_lines.extend(
                sorted(
                    {
                        update.source_line
                        for update in exclusion_updates
                        if exclusion_statuses.get(update.source_line, StackStatus("failure", "missing")).status
                        != "success"
                    }
                )
            )
            if failed_lines:
                restore_failed_lines(
                    opts.wud_file,
                    audit_parsed,
                    failed_lines,
                    lock=lock,
                    owner=self.owner,
                )
                self._mark_failed_lines_restored(failed_lines)
                self._mark_failed_pending(matches, stack_statuses, failed_lines)
                self.log.warn(f"Restored failed WUD entries in {opts.wud_file}")
                self._progress(
                    "cleanup",
                    "failure",
                    "Restored failed entries to the pending file.",
                    matches=matches,
                )
            else:
                self._mark_failed_lines_restored(())
                self.log.info("Successful WUD entries were removed before update.")
                self._progress(
                    "cleanup",
                    "success",
                    "Pending entries were reconciled.",
                    matches=matches,
                )
            self._mark_successful_pending(matches, stack_statuses)
            self._mark_successful_tag_exclusions(exclusion_updates, exclusion_statuses)
            self._record_update_events(matches, stack_statuses)
            self._record_known_images(matches, stack_statuses)

            fail_count = sum(
                1 for status in stack_statuses.values() if status.status != "success"
            ) + sum(
                1
                for status in exclusion_statuses.values()
                if status.status != "success"
            ) + len(exclusion_failures)
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
                self._progress(
                    "completion",
                    "failure",
                    f"Updater completed with {fail_count} failure(s).",
                    matches=matches,
                )
                return 1

            self._finish_audit_run("success")
            self.log.info(f"Done. See log: {self.log_file}")
            self._progress(
                "completion",
                "success",
                "Updater completed successfully.",
                matches=matches,
            )
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

    def _parse_wud_files(self) -> tuple[ParsedWudFile, ParsedWudFile]:
        opts = self.options
        full_parse = parse_wud_file(opts.wud_file)
        only_lines = parse_line_spec(opts.only_lines, len(full_parse.lines), "--only-lines")
        exclude_lines = parse_line_spec(
            opts.exclude_tag_lines,
            len(full_parse.lines),
            "--exclude-tag-lines",
        )
        parse_line_spec(
            opts.remove_lines_before_run,
            len(full_parse.lines),
            "--remove-lines-before-run",
        )
        update_lines: set[int] | None = set(only_lines) if only_lines else None
        if exclude_lines:
            if update_lines is None:
                update_lines = {
                    line.line_no for line in full_parse.lines if line.actionable
                }
            update_lines -= set(exclude_lines)
        parsed = parse_wud_file(
            opts.wud_file,
            selected_lines=sorted(update_lines) if update_lines is not None else None,
        )
        excluded = parse_wud_file(opts.wud_file, selected_lines=exclude_lines)
        for warning in parsed.warnings:
            self.log.warn(warning)
        for warning in excluded.warnings:
            self.log.warn(warning)
        return self._apply_tag_overrides(parsed), excluded

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
        return updater_audit.audit_parsed_file(self, parsed, audit_lines)

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
                    services = _services_for_target_match(
                        stack.service_images,
                        image,
                        target,
                        resolved,
                        allow_repo,
                        allow_digest_pin_rematch=self.options.digest_pin_updates,
                    )
                    if services is None:
                        continue
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

    def _build_tag_exclusion_matches(
        self,
        parsed: ParsedWudFile,
        stacks: Sequence[ComposeStack],
    ) -> tuple[list[Match], list[tuple[WudTarget, str]]]:
        return updater_tag_exclusions.build_tag_exclusion_matches(
            self,
            parsed,
            stacks,
        )

    def _plan_tag_exclusions(
        self,
        matches: Sequence[Match],
        stacks: Sequence[ComposeStack],
    ) -> tuple[list[TagExclusionUpdate], list[tuple[WudTarget, str]]]:
        return updater_tag_exclusions.plan_tag_exclusions(self, matches, stacks)

    def _progress(
        self,
        phase: str,
        status: str,
        message: str,
        *,
        stack: str = "",
        services: Sequence[str] | None = (),
        matches: Sequence[Match] = (),
    ) -> None:
        if self.progress_callback is None:
            return
        line_numbers = tuple(sorted({match.target.line_no for match in matches}))
        self.progress_callback(
            UpdaterProgressEvent(
                phase=phase,
                status=status,
                message=message,
                stack=stack,
                services=tuple(services or ()),
                line_numbers=line_numbers,
            )
        )

    def _tag_exclusion_repo_updates(
        self,
        stacks: Sequence[ComposeStack],
        *,
        image_repo: str,
        tag: str,
        source_line: int,
    ) -> list[TagExclusionUpdate]:
        return updater_tag_exclusions.tag_exclusion_repo_updates(
            stacks,
            image_repo=image_repo,
            tag=tag,
            source_line=source_line,
        )

    def _can_apply_tag_exclusions(
        self,
        updates: Sequence[TagExclusionUpdate],
    ) -> bool:
        return updater_tag_exclusions.can_apply_tag_exclusions(self, updates)

    def _apply_tag_exclusions(
        self,
        updates: Sequence[TagExclusionUpdate],
    ) -> dict[int, StackStatus]:
        return updater_tag_exclusions.apply_tag_exclusions(self, updates)

    def _existing_exact_tag_exclusions(
        self,
        updates: Sequence[TagExclusionUpdate],
    ) -> dict[str, set[str]]:
        return updater_tag_exclusions.existing_exact_tag_exclusions(self, updates)

    def _record_tag_exclusion_rules(
        self,
        updates: Sequence[TagExclusionUpdate],
    ) -> None:
        updater_tag_exclusions.record_tag_exclusion_rules(self, updates)

    def _recreate_tag_exclusion_services(
        self,
        updates: Sequence[TagExclusionUpdate],
        statuses: dict[int, StackStatus],
    ) -> None:
        updater_tag_exclusions.recreate_tag_exclusion_services(
            self,
            updates,
            statuses,
        )

    def _mark_tag_exclusions_pending(
        self,
        updates: Sequence[TagExclusionUpdate],
    ) -> None:
        updater_tag_exclusions.mark_tag_exclusions_pending(self, updates)

    def _mark_successful_tag_exclusions(
        self,
        updates: Sequence[TagExclusionUpdate],
        statuses: Mapping[int, StackStatus],
    ) -> None:
        updater_tag_exclusions.mark_successful_tag_exclusions(self, updates, statuses)

    def _mark_tag_exclusion_failures(
        self,
        failures: Sequence[tuple[WudTarget, str]],
    ) -> None:
        updater_tag_exclusions.mark_tag_exclusion_failures(self, failures)

    def _update_stack(self, stack: ComposeStack, matches: Sequence[Match]) -> StackStatus:
        return self.lifecycle._update_stack(stack, matches)

    def _run_compose_up(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        *,
        force_recreate: bool = False,
        no_deps: bool = True,
    ) -> UpResult:
        return self.lifecycle._run_compose_up(
            stack,
            services,
            force_recreate=force_recreate,
            no_deps=no_deps,
        )

    def _wait_for_health(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        matches: Sequence[Match] = (),
    ) -> bool:
        return self.lifecycle._wait_for_health(stack, services, matches)

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
        return self.lifecycle._handle_tag_update_failure(
            stack,
            matches,
            services,
            applied_tags,
            compose_backup,
            reason,
            phase=phase,
            command_error=command_error,
            failure_health=failure_health,
            force_recreate=force_recreate,
            no_deps=no_deps,
        )

    def _write_tag_incident_log(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        applied_tags: Sequence[AppliedTagUpdate],
        reason: str,
        rollback_result: str,
        failure_health: str,
    ) -> None:
        self.lifecycle._write_tag_incident_log(
            stack,
            services,
            applied_tags,
            reason,
            rollback_result,
            failure_health,
        )

    def _update_scope(self, stack: ComposeStack, matches: Sequence[Match]) -> UpdateScope:
        return self.lifecycle._update_scope(stack, matches)

    def _missing_network_mode_providers(
        self,
        stack: ComposeStack,
        services: Sequence[str],
        providers: Mapping[str, str],
    ) -> tuple[str, ...]:
        return self.lifecycle._missing_network_mode_providers(stack, services, providers)

    def _stack_stop_services(self, stack: ComposeStack) -> tuple[str, ...] | None:
        return self.lifecycle._stack_stop_services(stack)

    def _stack_recreate_label_cid(
        self,
        stack: ComposeStack,
        services: Sequence[str],
    ) -> str:
        return self.lifecycle._stack_recreate_label_cid(stack, services)

    def _capture_health_details(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
    ) -> str:
        return self.lifecycle._capture_health_details(stack, services)

    def _log_health_details(
        self,
        stack: ComposeStack,
        services: Sequence[str] | None,
        health_details: str | None = None,
    ) -> None:
        self.lifecycle._log_health_details(stack, services, health_details)

    def _log_command_result(self, result: CommandResult) -> None:
        self.lifecycle._log_command_result(result)

    def _cid_summary(self, cid: str) -> str:
        return self.lifecycle._cid_summary(cid)

    def _image_state(self, images: Iterable[str]) -> dict[str, ImageState]:
        return self.lifecycle._image_state(images)

    def _validate_tag_manifests(self, matches: Sequence[Match]) -> bool:
        return updater_preflight.validate_tag_manifests(self, matches)

    def _validate_tag_update_plan(self, matches: Sequence[Match]) -> bool:
        return updater_preflight.validate_tag_update_plan(self, matches)

    def _validate_compose_bind_mount_paths(self, matches: Sequence[Match]) -> bool:
        return updater_preflight.validate_compose_bind_mount_paths(self, matches)

    def _validate_compose_runtime_ports(self, matches: Sequence[Match]) -> bool:
        return updater_preflight.validate_compose_runtime_ports(self, matches)

    def _compose_runtime_port_issue_message(
        self,
        stack: ComposeStack,
        issue: ComposeRuntimePortIssue,
    ) -> str:
        return updater_preflight.compose_runtime_port_issue_message(stack, issue)

    def _bind_mount_path_issue_messages(
        self,
        stack: ComposeStack,
        mount: ComposeBindMount,
        issue: str,
    ) -> list[str]:
        return updater_preflight.bind_mount_path_issue_messages(
            self,
            stack,
            mount,
            issue,
        )

    def _log_bind_mount_path_issue(self, messages: Sequence[str]) -> None:
        updater_preflight.log_bind_mount_path_issue(self, messages)

    def _log_preflight_issue(self, message: str) -> None:
        updater_preflight.log_preflight_issue(self, message)

    def _validate_applied_tag_updates(
        self,
        stack: ComposeStack,
        applied_tags: Sequence[AppliedTagUpdate],
        service_images: Sequence[ServiceImage],
    ) -> bool:
        return self.lifecycle._validate_applied_tag_updates(
            stack,
            applied_tags,
            service_images,
        )

    def _validate_applied_digest_pins(
        self,
        stack: ComposeStack,
        applied_pins: Sequence[AppliedDigestPinUpdate],
        service_images: Sequence[ServiceImage],
    ) -> bool:
        return self.lifecycle._validate_applied_digest_pins(
            stack,
            applied_pins,
            service_images,
        )

    def _verify_expected_digests(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        images: Sequence[str],
    ) -> bool:
        return self.lifecycle._verify_expected_digests(stack, matches, images)

    def _verify_digest_pin_updates(
        self,
        stack: ComposeStack,
        updates: Sequence[DigestPinUpdate],
        images: Sequence[str],
    ) -> bool:
        return self.lifecycle._verify_digest_pin_updates(stack, updates, images)

    def _log_digest_untrusted(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.lifecycle._log_digest_untrusted(stack_name, result)

    def _log_digest_mismatch(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.lifecycle._log_digest_mismatch(stack_name, result)

    def _log_digest_details(
        self,
        level: str,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.lifecycle._log_digest_details(level, stack_name, result)

    def _tag_updates(self, matches: Sequence[Match]) -> tuple[TagUpdate, ...]:
        return self.lifecycle._tag_updates(matches)

    def _digest_pin_updates(
        self,
        matches: Sequence[Match],
    ) -> tuple[DigestPinUpdate, ...]:
        return self.lifecycle._digest_pin_updates(matches)

    def _resolve_digest_pin(self, image: str) -> DigestResolveResult:
        return self.lifecycle._resolve_digest_pin(image)

    def _resolve_digest_pin_candidate(
        self,
        candidate: DigestPinCandidate,
    ) -> DigestResolveResult:
        return self.lifecycle._resolve_digest_pin_candidate(candidate)

    def _verify_digest_pin_update_target(
        self,
        update: DigestPinUpdate,
    ) -> DigestResolveResult:
        return self.lifecycle._verify_digest_pin_update_target(update)

    def _validate_digest_pin_plan(self, matches: Sequence[Match]) -> bool:
        return updater_preflight.validate_digest_pin_plan(self, matches)

    def _refresh_stack_images(self, stack: ComposeStack) -> ComposeStack | None:
        return self.lifecycle._refresh_stack_images(stack)

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
        return updater_preflight.finish_preflight_failure(
            self,
            parsed,
            matches,
            skipped_tags,
        )

    def _start_audit(self, parsed: ParsedWudFile) -> None:
        updater_audit.start_audit(self, parsed, db_path_fn=_db_path)

    def _apply_audit_db_owner(self, *, chown_parent: bool = False) -> None:
        updater_audit.apply_audit_db_owner(self, chown_parent=chown_parent)

    def _apply_sqlite_owner(
        self,
        db_path: Path,
        owner: OwnerConfig,
        *,
        chown_parent: bool = False,
    ) -> None:
        _apply_sqlite_owner(db_path, owner, chown_parent=chown_parent)

    def _finish_audit_run(self, status: str, *, best_effort: bool = False) -> None:
        updater_audit.finish_audit_run(self, status, best_effort=best_effort)

    def _mark_unmatched_pending(
        self,
        parsed: ParsedWudFile,
        matches: Sequence[Match],
        skipped_tags: Sequence[WudTarget],
    ) -> None:
        updater_audit.mark_unmatched_pending(self, parsed, matches, skipped_tags)

    def _mark_matched_pending(
        self,
        matches: Sequence[Match],
        *,
        status: str,
        status_reason: str = "matched",
    ) -> None:
        updater_audit.mark_matched_pending(
            self,
            matches,
            status=status,
            status_reason=status_reason,
        )

    def _mark_removed_pending(
        self,
        parsed: ParsedWudFile,
        remove_lines: Iterable[int],
        matches: Sequence[Match],
    ) -> None:
        updater_audit.mark_removed_pending(self, parsed, remove_lines, matches)

    def _mark_failed_pending(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
        failed_lines: Iterable[int],
    ) -> None:
        updater_audit.mark_failed_pending(self, matches, stack_statuses, failed_lines)

    def _mark_successful_pending(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        updater_audit.mark_successful_pending(self, matches, stack_statuses)

    def _record_update_events(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        updater_audit.record_update_events(
            self,
            matches,
            stack_statuses,
            insert_event=insert_update_event,
        )

    def _record_known_images(
        self,
        matches: Sequence[Match],
        stack_statuses: Mapping[int, StackStatus],
    ) -> None:
        updater_audit.record_known_images(self, matches, stack_statuses)

    def _remember_applied_digest_pins(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        updates: Sequence[DigestPinUpdate],
    ) -> None:
        by_key = {
            (update.old_image, update.resolved_tag): update
            for update in updates
        }
        for match in matches:
            resolved_tag = _digest_pin_match_tag(match)
            if not resolved_tag:
                continue
            update = by_key.get((match.compose_image, resolved_tag))
            if update is None:
                continue
            self.applied_digest_pins[
                (stack.index, match.target.line_no, match.service)
            ] = update

    def _target_image_for_match(self, match: Match) -> str:
        update = self.applied_digest_pins.get(
            (match.stack.index, match.target.line_no, match.service)
        )
        if update is not None:
            return update.final_image
        return _target_image_for_match(match)

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
            return updater_logging._create_unique_text_file_exclusive(
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
            f"timestamp={updater_logging.timestamp()}\n",
            f"central_log={self.log_file}\n",
            f"error_report={report_path}\n",
            f"failures={len(self.failures)}\n",
        ]
        for index, failure in enumerate(self.failures, start=1):
            content.extend(self._render_failure(index, failure))
        return "".join(content)

    def _render_failure(self, index: int, failure: FailureRecord) -> list[str]:
        services = " ".join(failure.services or ()) or "stack-level"
        restored = updater_logging._restored_text(failure.wud_restored)
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
            content.append(f"note={updater_logging.sanitize_stream(failure.note)}\n")
        result = failure.command_result
        if result is not None:
            content.extend(updater_logging._render_command_result(result))
        details_label = "details" if failure.phase == "preflight" else "health"
        content.append(f"{details_label}:\n")
        content.extend(updater_logging._indented_block(failure.health_details, "  "))
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
        self.log.info(f"Dry-run : {updater_logging._bool_text(opts.dry_run)}")
        self.log.info(f"Confirm : {updater_logging._bool_text(opts.assume_yes)}")
        self.log.info(
            f"TagEdit : {updater_logging._bool_text(opts.allow_tag_updates)}"
        )
        self.log.info(
            f"DigestP : {updater_logging._bool_text(opts.digest_pin_updates)}"
        )
        self.log.info(f"MaxWait : {opts.max_wait}s")
        if opts.only_lines:
            self.log.info(f"Only    : {opts.only_lines}")
        if opts.remove_lines_before_run:
            self.log.info(f"Remove  : {opts.remove_lines_before_run}")
        if opts.exclude_tag_lines:
            self.log.info(f"Exclude : {opts.exclude_tag_lines}")
            self.log.info(
                f"Recreate: {updater_logging._bool_text(opts.recreate_excluded_services)}"
            )
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

    def _print_tag_exclusions(self, parsed: ParsedWudFile) -> None:
        updater_tag_exclusions.print_tag_exclusions(self, parsed)

    def _print_skipped_tag_updates(self, skipped_tags: Sequence[WudTarget]) -> None:
        if not skipped_tags:
            return
        self.log.warn("Tag update entries require --allow-tag-updates and were left pending:")
        for target in skipped_tags:
            desired_image = image_with_tag(target.first, target.desired_tag)
            self.log.info(f"  line {target.line_no}: {target.first} -> {desired_image}")

    def _print_tag_exclusion_plan(
        self,
        updates: Sequence[TagExclusionUpdate],
        failures: Sequence[tuple[WudTarget, str]],
    ) -> None:
        updater_tag_exclusions.print_tag_exclusion_plan(self, updates, failures)

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
                digest_pins = self._digest_pin_plan_by_line(stack_matches)

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
                    line = _plan_line(
                        line_no,
                        target,
                        resolved,
                        desired_tag,
                        digest_pins.get(line_no),
                    )
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
            digest_pins = self._digest_pin_plan_by_line(stack_matches)
            lines = {
                (match.target.line_no, match.target.first, match.resolved, match.target.desired_tag)
                for match in stack_matches
            }
            for line_no, target, resolved, desired_tag in sorted(lines):
                self.log.info(
                    f"      {_plan_line(line_no, target, resolved, desired_tag, digest_pins.get(line_no))}"
                )

    def _digest_pin_plan_by_line(
        self,
        matches: Sequence[Match],
    ) -> dict[int, DigestPinUpdate]:
        if not self.options.digest_pin_updates:
            return {}
        try:
            updates = self._digest_pin_updates(matches)
        except UpdaterError:
            return {}
        by_key = {
            (update.old_image, update.resolved_tag): update
            for update in updates
        }
        by_line: dict[int, DigestPinUpdate] = {}
        for match in matches:
            resolved_tag = _digest_pin_match_tag(match)
            if not resolved_tag:
                continue
            update = by_key.get((match.compose_image, resolved_tag))
            if update is not None:
                by_line.setdefault(match.target.line_no, update)
        return by_line

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
        print(f"[{updater_logging.timestamp()}] {exc}", file=sys.stderr)
        return 1


def _db_path(options: UpdaterOptions, environ: Mapping[str, str]) -> Path:
    return updater_audit.db_path(options, environ)


def _sqlite_parent_missing(db_path: Path) -> bool:
    return updater_audit.sqlite_parent_missing(db_path)


def _apply_sqlite_owner(
    db_path: Path,
    owner: OwnerConfig,
    *,
    chown_parent: bool = False,
) -> None:
    updater_audit.apply_sqlite_owner(
        db_path,
        owner,
        chown_parent=chown_parent,
        apply_owner=apply_configured_owner,
    )


def _sqlite_state_paths(db_path: Path) -> tuple[Path, ...]:
    return updater_audit.sqlite_state_paths(db_path)
