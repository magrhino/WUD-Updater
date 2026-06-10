"""Recreate and health-finish helpers for updater lifecycle execution."""

from __future__ import annotations

from .command import CommandError
from .updater_lifecycle_state import _StackUpdateState, _StopResult
from .updater_models import StackStatus, UpResult


class _LifecycleRecreateMixin:
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
        unpaused = self._unpause_after_recreate(state, up_result)
        if isinstance(unpaused, StackStatus):
            return unpaused
        up_result = unpaused

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
