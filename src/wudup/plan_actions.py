"""Action rendering helpers for WebUI dry-run plans."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .compose import ComposeCli, ComposeStack
from .config import UpdaterConfig
from .plan_models import (
    DryRunPlanAction,
    DryRunPlanDigestPinUpdate,
    DryRunPlanDigestUnpinUpdate,
    DryRunPlanTagStreamUpdate,
    DryRunPlanTagUpdate,
)
from .updater_models import UpdateScope


def render_plan_actions(
    config: UpdaterConfig,
    compose: ComposeCli,
    stack: ComposeStack,
    scope: UpdateScope,
    tag_updates: Sequence[DryRunPlanTagUpdate],
    tag_stream_updates: Sequence[DryRunPlanTagStreamUpdate],
    digest_pin_updates: Sequence[DryRunPlanDigestPinUpdate],
    digest_unpin_updates: Sequence[DryRunPlanDigestUnpinUpdate],
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
    for update in tag_stream_updates:
        actions.append(
            DryRunPlanAction(
                kind="compose-tag-stream",
                description=(
                    f"Set {update.label_key} from "
                    f"{update.current_label_value or '<missing>'} to "
                    f"{update.proposed_label_regex} for {update.service}"
                ),
                cwd=str(stack.directory),
            )
        )
    for update in digest_unpin_updates:
        actions.append(
            DryRunPlanAction(
                kind="compose-digest-unpin",
                description=(
                    f"Unpin {update.source_image} to {update.tag_image}, "
                    f"remove {update.marker}, and preserve {update.label_key} "
                    f"for {', '.join(update.services)}"
                ),
                cwd=str(stack.directory),
            )
        )
    actions.append(
        _compose_action(
            stack,
            "pull",
            ("pull",),
            scope.pull_services,
            "Pull matched image updates",
        )
    )
    for update in digest_pin_updates:
        actions.append(
            DryRunPlanAction(
                kind="compose-digest-pin",
                description=(
                    f"Pin {update.source_image} to {update.final_image}, "
                    f"write {update.marker}, and set {update.label_key} "
                    f"for {', '.join(update.services)}"
                ),
                cwd=str(stack.directory),
            )
        )
    stop_services = scope.stop_services if scope.stop_services is not None else scope.services
    if config.update_mode == "pause":
        actions.append(
            _compose_action(
                stack,
                "pause",
                ("pause",),
                scope.services,
                "Pause affected services before recreate",
            )
        )
    elif config.update_mode == "stop":
        actions.append(
            _compose_action(
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
    if config.update_mode != "pause" and compose.up_wait_supported(
        stack.directory,
        stack.file,
        project_directory=stack.project_directory,
    ):
        up_args.extend(["--wait", "--wait-timeout", str(config.max_wait)])
        wait_handled = True
    actions.append(
        _compose_action(
            stack,
            "up",
            tuple(up_args),
            scope.services,
            "Recreate services with updated images",
        )
    )
    if config.update_mode == "pause":
        actions.append(
            _compose_action(
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
                description=f"Wait up to {config.max_wait}s for health",
                cwd=str(stack.directory),
            )
        )
    return tuple(actions)


def _compose_action(
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
