"""Stack update state records for updater lifecycle execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .command import CommandError
from .compose import ComposeStack
from .updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagUpdate,
    DigestPinUpdate,
    ImageState,
    Match,
    TagUpdate,
    UpdateScope,
)


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
