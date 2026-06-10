"""Stack lifecycle execution for ``update-from-wud``."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import compose_rewrite, updater_logging
from .command import CommandError, CommandResult
from .compose import ComposeStack, ServiceImage
from .digest_verifier import (
    DigestCheckResult,
    DigestResolveResult,
    DigestVerifier,
    DockerManifestResolver,
)
from .images import (
    image_matches_resolved_target,
    image_with_tag,
    normalize_digest,
)
from .updater_digest_pin import (
    _digest_pin_candidates,
    _digest_pin_resolve_error,
    _digest_pin_tag_materialization_updates,
    _resolve_digest_pin_candidate,
    digest_pin_update_from_values,
)
from .updater_matching import (
    RECREATE_STACK_LABEL,
    RECREATE_STACK_LABEL_FORMAT,
    _expand_network_mode_services,
    _label_value_is_true,
    _network_mode_providers,
    _ordered_unique,
    _update_services,
)
from .updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagUpdate,
    ComposeTagRewriteError,
    DigestPinCandidate,
    DigestPinUpdate,
    ImageState,
    Match,
    StackStatus,
    TagUpdate,
    UpResult,
    UpdateScope,
    UpdaterError,
)
from .updater_planning import _digest_check_allow_repo, _digest_check_image


CONTAINER_SUMMARY_FORMAT = "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.ExitCode}}"
HEALTH_LOG_FORMAT = "{{if .State.Health}}{{range .State.Health.Log}}{{println .Output}}{{end}}{{end}}"


@dataclass
class _StackUpdateState:
    stack: ComposeStack
    matches: Sequence[Match]
    scope: UpdateScope
    current_stack: ComposeStack
    images: tuple[str, ...]
    before: dict[str, ImageState]
    after: dict[str, ImageState]
    digest_pin_updates: tuple[DigestPinUpdate, ...]
    compose_tag_updates: tuple[TagUpdate, ...]
    applied_tags: tuple[AppliedTagUpdate, ...] = ()
    applied_digest_pins: tuple[AppliedDigestPinUpdate, ...] = ()
    compose_backup: Path | None = None

    @property
    def services(self) -> tuple[str, ...] | None:
        return self.scope.services

    @property
    def pull_services(self) -> tuple[str, ...] | None:
        return self.scope.pull_services

    @property
    def stop_services(self) -> tuple[str, ...] | None:
        return (
            self.scope.stop_services
            if self.scope.stop_services is not None
            else self.scope.services
        )

    @property
    def service_scoped(self) -> bool:
        return self.services is not None

    @property
    def services_label(self) -> str:
        return " ".join(self.services or ())

    @property
    def stop_services_label(self) -> str:
        return " ".join(self.stop_services or ())

    @property
    def compose_rewrite_applied(self) -> bool:
        return bool(self.applied_tags or self.applied_digest_pins)


@dataclass(frozen=True)
class _StopResult:
    failed: bool = False
    error: CommandError | None = None
    phase: str = "stop"


class StackLifecycleExecutor:
    def __init__(self, runner: Any) -> None:
        self.runner = runner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.runner, name)

    def _update_stack(self, stack: ComposeStack, matches: Sequence[Match]) -> StackStatus:
        state_or_status = self._build_stack_update_state(stack, matches)
        if isinstance(state_or_status, StackStatus):
            return state_or_status

        state = state_or_status
        for step in (
            self._apply_compose_tag_updates,
            self._pull_and_verify_images,
            self._apply_compose_digest_pin_updates,
            self._finish_pull_phase,
        ):
            status = step(state)
            if status is not None:
                return status

        return self._recreate_and_verify_stack(state)

    def _build_stack_update_state(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
    ) -> _StackUpdateState | StackStatus:
        scope = self._update_scope(stack, matches)
        self._log_stack_scope(stack, scope)

        images = tuple(stack.images)
        before = self._image_state(images)
        tag_updates = self._tag_updates(matches)
        try:
            digest_pin_updates = self._digest_pin_updates(matches)
        except UpdaterError as exc:
            self.log.error(f"[{stack.name}] {exc}")
            self._record_failure(
                stack,
                matches,
                phase="compose-digest-pin",
                reason="compose-digest-pin-plan-failed",
                services=scope.pull_services,
                note=str(exc),
            )
            return StackStatus("failure", "compose-digest-pin-plan-failed")

        digest_pin_tag_updates = _digest_pin_tag_materialization_updates(
            digest_pin_updates
        )
        compose_tag_updates = (*tag_updates, *digest_pin_tag_updates)
        return _StackUpdateState(
            stack=stack,
            matches=matches,
            scope=scope,
            current_stack=stack,
            images=images,
            before=before,
            after=dict(before),
            digest_pin_updates=digest_pin_updates,
            compose_tag_updates=compose_tag_updates,
        )

    def _log_stack_scope(self, stack: ComposeStack, scope: UpdateScope) -> None:
        opts = self.options
        services = scope.services
        pull_services = scope.pull_services
        service_scoped = services is not None
        services_label = " ".join(services or ())
        pull_services_label = " ".join(pull_services or ())

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

    def _apply_compose_tag_updates(
        self,
        state: _StackUpdateState,
    ) -> StackStatus | None:
        if not state.compose_tag_updates:
            return None

        stack = state.stack
        self.log.info(f"[{stack.name}] Applying compose tag update(s)")
        status = self._ensure_compose_backup(state, "tag update")
        if status is not None:
            return status

        compose_path = stack.directory / stack.file
        try:
            state.applied_tags = compose_rewrite.apply_compose_tag_updates(
                compose_path,
                state.compose_tag_updates,
            )
        except ComposeTagRewriteError as exc:
            self.log.error(
                f"[{stack.name}] Could not safely rewrite compose image tag(s): {exc}"
            )
            self._record_failure(
                stack,
                state.matches,
                phase="compose-tag-rewrite",
                reason="compose-tag-rewrite-failed",
                services=state.pull_services,
                note=str(exc),
            )
            return StackStatus("failure", "compose-tag-rewrite-failed")
        except OSError as exc:
            self.log.error(f"[{stack.name}] Could not rewrite compose image tag(s): {exc}")
            self._record_failure(
                stack,
                state.matches,
                phase="compose-tag-rewrite",
                reason="compose-tag-rewrite-failed",
                services=state.pull_services,
                note=str(exc),
            )
            return StackStatus("failure", "compose-tag-rewrite-failed")

        if not state.applied_tags:
            self.log.error(
                f"[{stack.name}] Could not rewrite compose image tag(s); leaving WUD entry pending for manual review."
            )
            self._record_failure(
                stack,
                state.matches,
                phase="compose-tag-rewrite",
                reason="compose-tag-rewrite-failed",
                services=state.pull_services,
                note="No compose image lines were rewritten.",
            )
            return StackStatus("failure", "compose-tag-rewrite-failed")

        for applied in state.applied_tags:
            self.log.info(
                f"[{stack.name}] Compose tag updated: {applied.old_image} -> {applied.new_image}"
            )

        refreshed = self.runner._refresh_stack_images(state.current_stack)
        if refreshed is None:
            return self._handle_compose_rewrite_failure(
                state,
                "compose-refresh-failed",
                phase="compose-refresh",
            )
        if not self._validate_applied_tag_updates(
            stack,
            state.applied_tags,
            refreshed.service_images,
        ):
            return self._handle_compose_rewrite_failure(
                state,
                "compose-tag-validation-failed",
                phase="compose-tag-validation",
            )

        self._set_current_stack(state, refreshed)
        return None

    def _pull_and_verify_images(
        self,
        state: _StackUpdateState,
    ) -> StackStatus | None:
        stack = state.stack
        matches = state.matches

        self._progress(
            "pull",
            "running",
            f"[{stack.name}] Pulling selected image updates.",
            stack=stack.name,
            services=state.pull_services,
            matches=state.matches,
        )
        try:
            self.compose.pull(
                stack.directory,
                stack.file,
                state.pull_services,
                project_directory=stack.project_directory,
            )
        except CommandError as exc:
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "pull-failed",
                    phase="pull",
                    command_error=exc,
                )
            self._record_failure(
                stack,
                state.matches,
                phase="pull",
                reason="pull-failed",
                services=state.pull_services,
                command_error=exc,
                health_details=self._capture_health_details(stack, state.pull_services),
            )
            self._progress(
                "pull",
                "failure",
                f"[{stack.name}] Pull failed.",
                stack=stack.name,
                services=state.pull_services,
                matches=state.matches,
            )
            return StackStatus("failure", "pull-failed")

        state.after = self._image_state(state.images)
        if not self._verify_expected_digests(stack, matches, state.images):
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "expected-digest-not-reached",
                    phase="digest",
                )
            self._record_failure(
                stack,
                state.matches,
                phase="digest",
                reason="expected-digest-not-reached",
                services=state.pull_services,
                health_details=self._capture_health_details(stack, state.pull_services),
            )
            self._progress(
                "pull",
                "failure",
                f"[{stack.name}] Pulled images did not reach the expected digest.",
                stack=stack.name,
                services=state.pull_services,
                matches=state.matches,
            )
            return StackStatus("failure", "expected-digest-not-reached")

        if state.digest_pin_updates and not self._verify_digest_pin_updates(
            stack,
            state.digest_pin_updates,
            state.images,
        ):
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "digest-pin-verification-failed",
                    phase="digest",
                )
            self._record_failure(
                stack,
                state.matches,
                phase="digest",
                reason="digest-pin-verification-failed",
                services=state.pull_services,
                health_details=self._capture_health_details(stack, state.pull_services),
            )
            return StackStatus("failure", "digest-pin-verification-failed")

        return None

    def _apply_compose_digest_pin_updates(
        self,
        state: _StackUpdateState,
    ) -> StackStatus | None:
        if not state.digest_pin_updates:
            return None

        stack = state.stack
        status = self._ensure_compose_backup(state, "digest-pin rewrite")
        if status is not None:
            return status

        compose_path = stack.directory / stack.file
        try:
            state.applied_digest_pins = compose_rewrite.apply_compose_digest_pins(
                compose_path,
                state.digest_pin_updates,
                label_rewrite_approvals=(
                    self.options.digest_pin_label_rewrite_approvals
                ),
                stack_name=stack.name,
            )
        except ComposeTagRewriteError as exc:
            self.log.error(
                f"[{stack.name}] Could not safely write digest-pinned compose image(s): {exc}"
            )
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "compose-digest-pin-failed",
                    phase="compose-digest-pin",
                )
            return StackStatus("failure", "compose-digest-pin-failed")
        except OSError as exc:
            self.log.error(
                f"[{stack.name}] Could not write digest-pinned compose image(s): {exc}"
            )
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "compose-digest-pin-failed",
                    phase="compose-digest-pin",
                )
            return StackStatus("failure", "compose-digest-pin-failed")

        if not state.applied_digest_pins:
            self.log.error(
                f"[{stack.name}] Could not write digest-pinned compose image(s); leaving WUD entry pending for manual review."
            )
            if state.applied_tags and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "compose-digest-pin-failed",
                    phase="compose-digest-pin",
                )
            return StackStatus("failure", "compose-digest-pin-failed")

        for applied in state.applied_digest_pins:
            self.log.info(
                f"[{stack.name}] Compose digest pinned: "
                f"{applied.old_image} -> {applied.final_image} "
                f"(resolved-tag={applied.resolved_tag})"
            )

        refreshed = self.runner._refresh_stack_images(state.current_stack)
        if refreshed is None:
            return self._handle_compose_rewrite_failure(
                state,
                "compose-digest-pin-refresh-failed",
                phase="compose-digest-pin",
            )
        if not self._validate_applied_digest_pins(
            stack,
            state.applied_digest_pins,
            refreshed.service_images,
        ):
            return self._handle_compose_rewrite_failure(
                state,
                "compose-digest-pin-validation-failed",
                phase="compose-digest-pin",
            )

        self._set_current_stack(state, refreshed)
        state.after = self._image_state(state.images)
        return None

    def _finish_pull_phase(self, state: _StackUpdateState) -> StackStatus | None:
        stack = state.stack
        self._progress(
            "pull",
            "success",
            f"[{stack.name}] Images pulled and verified.",
            stack=stack.name,
            services=state.pull_services,
            matches=state.matches,
        )

        changes = _updated_images(state.before, state.after)
        update_needed = bool(state.applied_tags or state.applied_digest_pins or changes)
        for image, image_state in changes:
            target = image_state.digest if image_state.digest else image_state.image_id
            self.log.info(f"[{stack.name}] Image updated: {image} -> {target}")

        if not update_needed:
            self.log.info(f"[{stack.name}] All images up to date, skipping restart")
            self._progress(
                "recreate",
                "skipped",
                f"[{stack.name}] Images are already current; recreate was skipped.",
                stack=stack.name,
                services=state.services,
                matches=state.matches,
            )
            self._progress(
                "health",
                "skipped",
                f"[{stack.name}] Health wait was skipped because no containers changed.",
                stack=stack.name,
                services=state.services,
                matches=state.matches,
            )
            return StackStatus("success", "already-current")

        return None

    def _recreate_and_verify_stack(self, state: _StackUpdateState) -> StackStatus:
        stack = state.stack
        self._progress(
            "recreate",
            "running",
            f"[{stack.name}] Recreating selected containers.",
            stack=stack.name,
            services=state.services,
            matches=state.matches,
        )

        stop_result = self._prepare_for_recreate(state)
        self._log_compose_up_scope(state)
        up_result = self._run_compose_up(
            stack,
            state.services,
            force_recreate=state.scope.force_recreate,
            no_deps=state.scope.up_no_deps,
        )
        if not up_result.ok:
            return self._handle_compose_up_failure(state, stop_result, up_result)

        self._progress(
            "recreate",
            "success",
            f"[{stack.name}] Containers were recreated.",
            stack=stack.name,
            services=state.services,
            matches=state.matches,
        )

        unpaused = self._unpause_after_recreate(state, up_result)
        if isinstance(unpaused, StackStatus):
            return unpaused
        return self._finish_health_after_recreate(state, stop_result, unpaused)

    def _prepare_for_recreate(self, state: _StackUpdateState) -> _StopResult:
        stack = state.stack
        if self.options.mode == "pause":
            self.log.warn(
                f"[{stack.name}] Mode pause is deprecated; pausing before recreate and unpausing before health check"
            )
            try:
                self.compose.pause(
                    stack.directory,
                    stack.file,
                    state.services,
                    project_directory=stack.project_directory,
                )
            except CommandError:
                self.log.warn(f"[{stack.name}] Pause failed; continuing with live recreate")
        elif self.options.mode == "stop":
            try:
                if state.service_scoped:
                    self.log.warn(
                        f"[{stack.name}] Stopping affected service(s): {state.stop_services_label}"
                    )
                    self.compose.stop(
                        stack.directory,
                        stack.file,
                        state.stop_services,
                        project_directory=stack.project_directory,
                    )
                else:
                    if state.stop_services_label:
                        self.log.warn(
                            f"[{stack.name}] Stopping stack service(s): {state.stop_services_label}"
                        )
                    else:
                        self.log.warn(f"[{stack.name}] Stopping stack")
                    self.compose.stop(
                        stack.directory,
                        stack.file,
                        state.stop_services,
                        project_directory=stack.project_directory,
                    )
            except CommandError as exc:
                self.log.warn(
                    f"[{stack.name}] Stop failed; attempting up for recovery, but this stack will not be marked successful"
                )
                return _StopResult(True, exc)
        return _StopResult()

    def _log_compose_up_scope(self, state: _StackUpdateState) -> None:
        if state.service_scoped:
            self.log.info(
                f"[{state.stack.name}] Bringing affected service(s) up: {state.services_label}"
            )
        else:
            self.log.info(f"[{state.stack.name}] Bringing stack up")

    def _handle_compose_up_failure(
        self,
        state: _StackUpdateState,
        stop_result: _StopResult,
        up_result: UpResult,
    ) -> StackStatus:
        stack = state.stack
        if state.compose_rewrite_applied and state.compose_backup is not None:
            failure_phase = "up"
            failure_reason = "up-or-health-failed"
            failure_error = up_result.command_error
            if stop_result.failed and stop_result.error is not None:
                failure_phase = stop_result.phase
                failure_reason = "down-failed"
                failure_error = stop_result.error
            return self._handle_compose_rewrite_failure(
                state,
                failure_reason,
                phase=failure_phase,
                command_error=failure_error,
                failure_health=up_result.health_details,
            )

        if stop_result.failed and stop_result.error is not None:
            self._record_failure(
                stack,
                state.matches,
                phase=stop_result.phase,
                reason="down-failed",
                services=state.services,
                command_error=stop_result.error,
                health_details=self._capture_health_details(stack, state.services),
                note="Update recovery also failed during compose up.",
            )

        self._record_failure(
            stack,
            state.matches,
            phase="up",
            reason="up-or-health-failed",
            services=state.services,
            command_error=up_result.command_error,
            health_details=up_result.health_details,
        )
        self._progress(
            "recreate",
            "failure",
            f"[{stack.name}] Compose up failed.",
            stack=stack.name,
            services=state.services,
            matches=state.matches,
        )
        return StackStatus("failure", "up-or-health-failed")

    def _unpause_after_recreate(
        self,
        state: _StackUpdateState,
        up_result: UpResult,
    ) -> UpResult | StackStatus:
        stack = state.stack
        if self.options.mode != "pause":
            return up_result

        self.log.warn(f"[{stack.name}] Unpausing before health check")
        try:
            self.compose.unpause(
                stack.directory,
                stack.file,
                state.services,
                project_directory=stack.project_directory,
            )
        except CommandError as exc:
            if state.compose_rewrite_applied and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "unpause-failed",
                    phase="unpause",
                    command_error=exc,
                )
            self._record_failure(
                stack,
                state.matches,
                phase="unpause",
                reason="unpause-failed",
                services=state.services,
                command_error=exc,
                health_details=self._capture_health_details(stack, state.services),
            )
            return StackStatus("failure", "unpause-failed")
        return UpResult(
            up_result.ok,
            False,
            up_result.command_error,
            up_result.health_details,
        )

    def _finish_health_after_recreate(
        self,
        state: _StackUpdateState,
        stop_result: _StopResult,
        up_result: UpResult,
    ) -> StackStatus:
        stack = state.stack
        if up_result.wait_handled:
            self._progress(
                "health",
                "success",
                f"[{stack.name}] Compose reported healthy containers.",
                stack=stack.name,
                services=state.services,
                matches=state.matches,
            )

        if up_result.wait_handled or self._wait_for_health(
            stack,
            state.services,
            state.matches,
        ):
            self.log.info(f"[{stack.name}] Healthy")
            if stop_result.failed:
                if state.compose_rewrite_applied and state.compose_backup is not None:
                    return self._handle_compose_rewrite_failure(
                        state,
                        "down-failed",
                        phase=stop_result.phase,
                        command_error=stop_result.error,
                    )
                self._record_failure(
                    stack,
                    state.matches,
                    phase=stop_result.phase,
                    reason="down-failed",
                    services=state.services,
                    command_error=stop_result.error,
                    health_details=self._capture_health_details(stack, state.services),
                    note="Compose up recovery succeeded, but the earlier stop command failed.",
                )
                self._progress(
                    "recreate",
                    "failure",
                    f"[{stack.name}] Stop failed before recreate.",
                    stack=stack.name,
                    services=state.services,
                    matches=state.matches,
                )
                return StackStatus("failure", "down-failed")

            if state.digest_pin_updates:
                self._remember_applied_digest_pins(
                    stack,
                    state.matches,
                    state.digest_pin_updates,
                )
            return StackStatus("success", "updated")

        health_details = self._capture_health_details(stack, state.services)
        if state.compose_rewrite_applied and state.compose_backup is not None:
            return self._handle_compose_rewrite_failure(
                state,
                "health-failed",
                phase="health",
                failure_health=health_details,
            )
        self._record_failure(
            stack,
            state.matches,
            phase="health",
            reason="health-failed",
            services=state.services,
            health_details=health_details,
        )
        self._progress(
            "health",
            "failure",
            f"[{stack.name}] Health wait failed.",
            stack=stack.name,
            services=state.services,
            matches=state.matches,
        )
        return StackStatus("failure", "health-failed")

    def _ensure_compose_backup(
        self,
        state: _StackUpdateState,
        action: str,
    ) -> StackStatus | None:
        if state.compose_backup is not None:
            return None

        stack = state.stack
        compose_path = stack.directory / stack.file
        try:
            state.compose_backup = compose_rewrite._backup_compose(compose_path)
        except OSError as exc:
            self.log.error(
                f"[{stack.name}] Could not back up compose file before {action}: {exc}"
            )
            self._record_failure(
                stack,
                state.matches,
                phase="compose-backup",
                reason="compose-backup-failed",
                services=state.pull_services,
                note=str(exc),
            )
            return StackStatus("failure", "compose-backup-failed")
        return None

    def _handle_compose_rewrite_failure(
        self,
        state: _StackUpdateState,
        reason: str,
        *,
        phase: str,
        command_error: CommandError | None = None,
        failure_health: str | None = None,
    ) -> StackStatus:
        if state.compose_backup is None:
            return StackStatus("failure", reason)
        return self._handle_tag_update_failure(
            state.stack,
            state.matches,
            state.services,
            state.applied_tags,
            state.compose_backup,
            reason,
            phase=phase,
            command_error=command_error,
            failure_health=failure_health,
            force_recreate=state.scope.force_recreate,
            no_deps=state.scope.up_no_deps,
        )

    @staticmethod
    def _set_current_stack(
        state: _StackUpdateState,
        stack: ComposeStack,
    ) -> None:
        state.current_stack = stack
        state.images = tuple(stack.images)

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
        matches: Sequence[Match] = (),
    ) -> bool:
        start = time.monotonic()
        self._progress(
            "health",
            "running",
            f"[{stack.name}] Waiting up to {self.options.max_wait}s for health.",
            stack=stack.name,
            services=services,
            matches=matches,
        )
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
                self._progress(
                    "health",
                    "success",
                    f"[{stack.name}] Health wait succeeded in {elapsed}s.",
                    stack=stack.name,
                    services=services,
                    matches=matches,
                )
                return True
            if elapsed >= self.options.max_wait:
                self.log.error(f"[{stack.name}] Failed health gate after {elapsed}s")
                if not cids:
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] Health blocker: docker compose ps -q returned no containers",
                    )
                self._log_health_details(stack, services)
                self._progress(
                    "health",
                    "failure",
                    f"[{stack.name}] Failed health gate after {elapsed}s.",
                    stack=stack.name,
                    services=services,
                    matches=matches,
                )
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
        self._progress(
            _tag_update_failure_progress_phase(phase),
            "failure",
            _tag_update_failure_progress_message(stack.name, phase, reason),
            stack=stack.name,
            services=services,
            matches=matches,
        )
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
        incident = (
            stack.directory
            / f"error-{updater_logging.safe_component(first_tag)}-{updater_logging.file_timestamp()}.logs"
        )
        services_label = " ".join(services or ()) or "stack-level"
        content = [
            "WUD-Updater tag update incident\n",
            f"timestamp={updater_logging.timestamp()}\n",
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
            incident = updater_logging._create_unique_text_file_exclusive(
                incident,
                "".join(content),
                owner=self.owner,
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
            lifecycle_services = _ordered_unique((*missing_providers, *lifecycle_services))
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
                output = updater_logging.sanitize_stream(output)
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
        for line in updater_logging._render_command_result(result):
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

    def _validate_applied_digest_pins(
        self,
        stack: ComposeStack,
        applied_pins: Sequence[AppliedDigestPinUpdate],
        service_images: Sequence[ServiceImage],
    ) -> bool:
        ok = True
        image_by_service = {(item.service, item.image) for item in service_images}
        for applied in applied_pins:
            expected_replacements = len(applied.services)
            if applied.replacements != expected_replacements:
                ok = False
                self.log.error(
                    f"[{stack.name}] Compose digest-pin rewrite touched "
                    f"{applied.replacements} image line(s) for {applied.old_image}, "
                    f"expected {expected_replacements}."
                )
            for service in applied.services:
                if (service, applied.final_image) in image_by_service:
                    continue
                ok = False
                self.log.error(
                    f"[{stack.name}] Compose service {service} did not resolve "
                    f"to digest-pinned image {applied.final_image}."
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
            digest_result: DigestCheckResult | None = None
            for image in images:
                if not image_matches_resolved_target(image, expected_image, allow_repo):
                    continue
                matched = True
                digest_result = self.digest_verifier.verify(image, expected)
                if digest_result.ok:
                    break
            if digest_result is not None and digest_result.status == "untrusted":
                self.log.warn(
                    f"[{stack.name}] Digest verification was inconclusive for line {line_no} ({target}): wanted {expected}"
                )
                self._log_digest_untrusted(stack.name, digest_result)
                continue
            if digest_result is None or not digest_result.ok:
                ok = False
                self.log.error(
                    f"[{stack.name}] Expected digest not reached for line {line_no} ({target}): wanted {expected}"
                )
                if digest_result is not None:
                    self._log_digest_mismatch(stack.name, digest_result)
                if not matched:
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] No compose image matched line {line_no} while checking expected digest",
                    )
        return ok

    def _verify_digest_pin_updates(
        self,
        stack: ComposeStack,
        updates: Sequence[DigestPinUpdate],
        images: Sequence[str],
    ) -> bool:
        ok = True
        for update in updates:
            current = self._verify_digest_pin_update_target(update)
            if not current.ok:
                ok = False
                if current.reason == "stale-digest":
                    current_digest = normalize_digest(current.digest)
                    suffix = f", current {current_digest}" if current_digest else ""
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] Digest-pin target moved for "
                        f"{update.resolved_image}: planned {update.planned_digest}"
                        f"{suffix}",
                    )
                else:
                    self.log.error(
                        f"[{stack.name}] Could not re-resolve digest-pin target "
                        f"{update.resolved_image}: {current.reason}"
                    )
                    if current.error:
                        self.log.plain(
                            "ERROR",
                            f"[{stack.name}] Digest resolution error: {updater_logging.sanitize_stream(current.error)}",
                        )
                continue
            matched = False
            digest_result: DigestCheckResult | None = None
            for image in images:
                if not image_matches_resolved_target(
                    image,
                    update.resolved_image,
                    False,
                ):
                    continue
                matched = True
                digest_result = self.digest_verifier.verify(
                    image,
                    update.planned_digest,
                )
                if digest_result.ok:
                    break
            if digest_result is not None and digest_result.ok:
                self.log.info(
                    f"[{stack.name}] Verified digest-pin target: "
                    f"{update.resolved_image} -> {update.planned_digest}"
                )
                continue
            ok = False
            self.log.error(
                f"[{stack.name}] Digest-pin target did not verify for "
                f"{update.resolved_image}: wanted {update.planned_digest}"
            )
            if digest_result is not None:
                self._log_digest_mismatch(stack.name, digest_result)
            if not matched:
                self.log.plain(
                    "ERROR",
                    f"[{stack.name}] No compose image matched digest-pin target "
                    f"{update.resolved_image}",
                )
        return ok

    def _log_digest_untrusted(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.log.plain(
            "WARN",
            f"[{stack_name}] Digest verification reason: {result.reason}",
        )
        self._log_digest_details("WARN", stack_name, result)

    def _log_digest_mismatch(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.log.plain(
            "ERROR",
            f"[{stack_name}] Digest verification reason: {result.reason}",
        )
        self._log_digest_details("ERROR", stack_name, result)

    def _log_digest_details(
        self,
        level: str,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        if result.local_image_id:
            self.log.plain(
                level,
                f"[{stack_name}] Local image id: {result.local_image_id}",
            )
        if result.seen_repo_digests:
            for digest in result.seen_repo_digests:
                self.log.plain(
                    level,
                    f"[{stack_name}] RepoDigest seen: {digest}",
                )
        if result.tag_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Current tag digest: {result.tag_digest}",
            )
        if result.matched_child_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Matched platform digest: {result.matched_child_digest}",
            )
        if result.expected_config_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Expected config digest: {result.expected_config_digest}",
            )
        if result.source:
            self.log.plain(
                level,
                f"[{stack_name}] Digest verification source: {result.source}",
            )
        if result.error:
            self.log.plain(
                level,
                f"[{stack_name}] Digest verification error: {updater_logging.sanitize_stream(result.error)}",
            )

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

    def _digest_pin_updates(
        self,
        matches: Sequence[Match],
    ) -> tuple[DigestPinUpdate, ...]:
        if not self.options.digest_pin_updates:
            return ()
        candidates = _digest_pin_candidates(matches)
        cached = self.digest_pin_update_cache.get(candidates)
        if cached is not None:
            return cached
        planned = {
            (update.old_image, update.resolved_tag): update
            for update in self.options.digest_pin_plan
        }
        updates: list[DigestPinUpdate] = []
        for candidate in candidates:
            planned_update = planned.get(
                (candidate.old_image, candidate.resolved_tag)
            )
            if planned_update is not None:
                updates.append(replace(planned_update, services=candidate.services))
                continue
            resolved = self._resolve_digest_pin_candidate(candidate)
            if not resolved.ok:
                raise UpdaterError(
                    _digest_pin_resolve_error(candidate.resolved_image, resolved)
                    + (f" ({resolved.error})" if resolved.error else "")
                )
            updates.append(
                digest_pin_update_from_values(
                    old_image=candidate.old_image,
                    resolved_tag=candidate.resolved_tag,
                    planned_digest=resolved.digest,
                    services=candidate.services,
                )
            )
        result = tuple(updates)
        self.digest_pin_update_cache[candidates] = result
        return result

    def _resolve_digest_pin(self, image: str) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return verifier.resolve_tag_digest(image)

    def _resolve_digest_pin_candidate(
        self,
        candidate: DigestPinCandidate,
    ) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return _resolve_digest_pin_candidate(verifier, candidate)

    def _verify_digest_pin_update_target(
        self,
        update: DigestPinUpdate,
    ) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return verifier.verify_tag_digest(
            update.resolved_image,
            update.planned_digest,
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

def _stack_level_scope_message(scope: UpdateScope) -> str:
    if scope.stack_reason:
        if scope.pull_services is not None:
            return f"{scope.stack_reason}; using service pull with stack-level recreate"
        return f"{scope.stack_reason}; using stack-level pull/recreate"
    return (
        "Could not map every matched image to a compose service; "
        "using stack-level pull/recreate"
    )


def _tag_update_failure_progress_phase(phase: str) -> str:
    if phase in {"pull", "digest", "compose-digest-pin"}:
        return "pull"
    if phase in {"up", "stop", "down", "unpause"}:
        return "recreate"
    if phase == "health":
        return "health"
    return "preflight"


def _tag_update_failure_progress_message(stack_name: str, phase: str, reason: str) -> str:
    if phase == "pull":
        return f"[{stack_name}] Pull failed after tag rewrite."
    if phase == "digest":
        return (
            f"[{stack_name}] Pulled image did not reach the expected digest after tag rewrite."
        )
    if phase == "compose-digest-pin":
        return f"[{stack_name}] Compose digest-pin rewrite failed after pull."
    if phase in {"up", "stop", "down", "unpause"}:
        return f"[{stack_name}] Compose {phase} failed after tag rewrite."
    if phase == "health":
        return f"[{stack_name}] Health wait failed after tag rewrite."
    return f"[{stack_name}] Tag update failed before pull: {reason}."


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
