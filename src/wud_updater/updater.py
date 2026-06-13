"""Python implementation of ``bin/docker-update-from-wud``."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from . import (
    compose_rewrite as compose_rewrite,
    updater_audit,
    updater_logging,
    updater_preflight as updater_preflight,
    updater_tag_exclusions as updater_tag_exclusions,
)
from .command import CommandError, CommandResult as CommandResult, CommandRunner
from .compose import (
    ComposeBindMount as ComposeBindMount,
    ComposeCli,
    ComposeDiscoveryError,
    ComposeRuntimePortIssue as ComposeRuntimePortIssue,
    ComposeStack as ComposeStack,
    ServiceImage as ServiceImage,
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
    DigestCheckResult as DigestCheckResult,
    DigestResolveResult as DigestResolveResult,
    DigestVerifier,
    DockerManifestResolver as DockerManifestResolver,
)
from .docker_cli import DockerCli
from .file_ops import OwnerConfig, OwnerConfigError, apply_configured_owner
from .images import (
    image_has_tag as image_has_tag,
    image_matches_resolved_target as image_matches_resolved_target,
    image_with_tag as image_with_tag,
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
    _failure_target_lines as _failure_target_lines,
    _first_match_by_line as _first_match_by_line,
    _label_value_is_true as _label_value_is_true,
    _network_mode_providers as _network_mode_providers,
    _ordered_unique as _ordered_unique,
    _plan_line as _plan_line,
    _scope_plan_label as _scope_plan_label,
    _services_for_image as _services_for_image,
    _services_for_target_match as _services_for_target_match,
    _stacks_to_update,
    _tag_exclusion_preflight_matches,
    _target_image_for_match as _target_image_for_match,
    _unique_matches,
    _update_services as _update_services,
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
    parse_wud_file as parse_wud_file,
    remove_lines_before_run,
    restore_failed_lines,
)
from .updater_models import (
    AppliedDigestPinUpdate as AppliedDigestPinUpdate,
    AppliedTagUpdate as AppliedTagUpdate,
    ComposeTagRewriteError as ComposeTagRewriteError,
    DigestPinCandidate,
    DigestPinUpdate,
    DigestUnpinUpdate,
    FailureRecord,
    ImageState as ImageState,
    Match,
    StackStatus,
    TagExclusionUpdate as TagExclusionUpdate,
    TagUpdate as TagUpdate,
    UpResult as UpResult,
    UpdateScope as UpdateScope,
    UpdaterError,
    UpdaterOptions,
    UpdaterProgressEvent,
)
from .updater_runner_matching import _RunnerMatchingMixin
from .updater_runner_operations import (
    _RunnerOperationsMixin,
    _SERVICES_UNSET as _SERVICES_UNSET,
)
from .updater_runner_output import _RunnerOutputMixin

VALID_MODES = frozenset({"pause", "stop", "live"})




class UpdateFromWudRunner(
    _RunnerMatchingMixin,
    _RunnerOperationsMixin,
    _RunnerOutputMixin,
):
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
        self.stale_pending_digest_lines: set[tuple[int, int]] = set()
        self.audit_conn: sqlite3.Connection | None = None
        self.audit_run_id: int | None = None
        self.audit_db_path: Path | None = None
        self.applied_digest_pins: dict[tuple[int, int, str], DigestPinUpdate] = {}
        self.applied_digest_unpins: dict[
            tuple[int, int, str],
            DigestUnpinUpdate,
        ] = {}
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
            if not self._validate_digest_unpin_plan(matches):
                self._progress(
                    "preflight",
                    "failure",
                    "Digest-unpin plan validation failed.",
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
                stale_failed_lines = self._stale_pending_digest_line_numbers(
                    matches,
                    failed_lines,
                )
                restorable_failed_lines = [
                    line_no
                    for line_no in failed_lines
                    if line_no not in stale_failed_lines
                ]
                if restorable_failed_lines:
                    restore_failed_lines(
                        opts.wud_file,
                        audit_parsed,
                        restorable_failed_lines,
                        lock=lock,
                        owner=self.owner,
                    )
                    self.log.warn(f"Restored failed WUD entries in {opts.wud_file}")
                if stale_failed_lines:
                    stale_lines = ", ".join(
                        str(line) for line in sorted(stale_failed_lines)
                    )
                    self.log.warn(
                        "Removed stale digest WUD entries from "
                        f"{opts.wud_file}: lines {stale_lines}. "
                        "Refresh or replace them before retrying."
                    )
                self._mark_failed_lines_restored(restorable_failed_lines)
                self._mark_failed_pending(matches, stack_statuses, failed_lines)
                cleanup_message = (
                    "Failed entries were reconciled; stale digest entries were removed."
                    if stale_failed_lines
                    else "Restored failed entries to the pending file."
                )
                self._progress(
                    "cleanup",
                    "failure",
                    cleanup_message,
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
