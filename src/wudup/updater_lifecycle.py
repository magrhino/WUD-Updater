"""Stack lifecycle execution for ``update-from-wud``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .command import CommandError
from .compose import ComposeStack
from .updater_digest_pin import _digest_pin_tag_materialization_updates
from .updater_lifecycle_digest import _LifecycleDigestMixin
from .updater_lifecycle_health import (
    CONTAINER_SUMMARY_FORMAT as CONTAINER_SUMMARY_FORMAT,
)
from .updater_lifecycle_health import (
    HEALTH_LOG_FORMAT as HEALTH_LOG_FORMAT,
)
from .updater_lifecycle_health import (
    _cid_is_ok as _cid_is_ok,
)
from .updater_lifecycle_health import (
    _LifecycleHealthMixin,
)
from .updater_lifecycle_health import (
    _split_summary as _split_summary,
)
from .updater_lifecycle_health import (
    _updated_images as _updated_images,
)
from .updater_lifecycle_recreate import _LifecycleRecreateMixin
from .updater_lifecycle_rewrite import (
    _LifecycleRewriteMixin,
)
from .updater_lifecycle_rewrite import (
    _tag_update_failure_progress_message as _tag_update_failure_progress_message,
)
from .updater_lifecycle_rewrite import (
    _tag_update_failure_progress_phase as _tag_update_failure_progress_phase,
)
from .updater_lifecycle_scope import (
    _stack_level_scope_message as _stack_level_scope_message,
)
from .updater_lifecycle_scope import (
    _UpdateScopeMixin,
)
from .updater_lifecycle_state import _StackUpdateState
from .updater_models import (
    STALE_PENDING_DIGEST_REASON,
    Match,
    StackStatus,
    UpdaterError,
    UpdateScope,
)


class StackLifecycleExecutor(
    _LifecycleRewriteMixin,
    _LifecycleRecreateMixin,
    _LifecycleHealthMixin,
    _UpdateScopeMixin,
    _LifecycleDigestMixin,
):
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
            self._apply_compose_digest_unpin_updates,
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
        stack_directory = str(stack.directory.resolve(strict=False))
        tag_stream_updates = tuple(
            update
            for update in self.options.tag_stream_updates
            if update.stack_directory == stack_directory
            and update.compose_file == stack.file
        )
        selected_lines = {match.target.line_no for match in matches}
        unexpected_stream_lines = sorted(
            {
                update.line_no
                for update in tag_stream_updates
                if update.line_no not in selected_lines
            }
        )
        if unexpected_stream_lines:
            line_list = ", ".join(str(line_no) for line_no in unexpected_stream_lines)
            self.log.error(
                f"[{stack.name}] Tag stream update line(s) are not selected: {line_list}"
            )
            self._record_failure(
                stack,
                matches,
                phase="compose-tag-rewrite",
                reason="compose-tag-stream-plan-stale",
                services=scope.pull_services,
                note=f"Unselected tag stream line(s): {line_list}",
            )
            return StackStatus("failure", "compose-tag-stream-plan-stale")
        try:
            digest_pin_updates = self._digest_pin_updates(matches)
            digest_unpin_updates = self._digest_unpin_updates(matches)
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
            digest_unpin_updates=digest_unpin_updates,
            compose_tag_updates=compose_tag_updates,
            tag_stream_updates=tag_stream_updates,
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
            if state.compose_rewrite_applied and state.compose_backup is not None:
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
        self.runner.stack_image_states[state.stack.index] = (
            dict(state.before),
            dict(state.after),
        )
        if not self._verify_expected_digests(stack, matches, state.images):
            reason = self._expected_digest_failure_reason(stack, matches)
            note = (
                "Stale pending digest entry was removed; refresh or replace it "
                "before retrying."
                if reason == STALE_PENDING_DIGEST_REASON
                else ""
            )
            if state.compose_rewrite_applied and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    reason,
                    phase="digest",
                )
            self._record_failure(
                stack,
                state.matches,
                phase="digest",
                reason=reason,
                services=state.pull_services,
                health_details=self._capture_health_details(stack, state.pull_services),
                note=note,
            )
            self._progress(
                "pull",
                "failure",
                f"[{stack.name}] Pulled images did not reach the expected digest.",
                stack=stack.name,
                services=state.pull_services,
                matches=state.matches,
            )
            return StackStatus("failure", reason)

        if state.digest_pin_updates and not self._verify_digest_pin_updates(
            stack,
            state.digest_pin_updates,
            state.images,
        ):
            if state.compose_rewrite_applied and state.compose_backup is not None:
                return self._handle_compose_rewrite_failure(
                    state,
                    "digest-pin-verification-failed",
                    phase="digest",
                )
            self._progress(
                "pull",
                "failure",
                f"[{stack.name}] Pulled images failed digest pin verification.",
                stack=stack.name,
                services=state.pull_services,
                matches=state.matches,
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

    def _finish_pull_phase(self, state: _StackUpdateState) -> StackStatus | None:
        stack = state.stack
        self.runner.stack_image_states[state.stack.index] = (
            dict(state.before),
            dict(state.after),
        )
        self._progress(
            "pull",
            "success",
            f"[{stack.name}] Images pulled and verified.",
            stack=stack.name,
            services=state.pull_services,
            matches=state.matches,
        )

        changes = _updated_images(state.before, state.after)
        update_needed = bool(
            state.applied_tags
            or state.applied_digest_pins
            or state.applied_digest_unpins
            or changes
        )
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
