"""Docker Compose subprocess layer for the Python updater."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .command import CommandError, CommandResult, CommandRunner


COMPOSE_FILENAMES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)
_WAIT_FLAG_RE = re.compile(r"(^|\s)--wait([=,\s]|$)")


@dataclass(frozen=True)
class ServiceImage:
    service: str
    image: str
    network_mode: str = ""


@dataclass(frozen=True)
class ComposeStack:
    index: int
    directory: Path
    file: str
    name: str
    images: tuple[str, ...]
    service_images: tuple[ServiceImage, ...]


class ComposeCli:
    """Thin Compose command wrapper matching the shell updater's call shapes."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        docker_executable: str = "docker",
    ) -> None:
        self.runner = runner or CommandRunner()
        self.docker_executable = docker_executable

    def config_images(
        self,
        directory: str | Path,
        file: str,
        service: str | None = None,
    ) -> list[str]:
        args = self._compose_args(file, "config", "--images")
        if service:
            args.append(service)
        return _sorted_unique_nonblank(
            self.runner.capture_lines(args, cwd=directory, check=True)
        )

    def config_services(self, directory: str | Path, file: str) -> list[str]:
        return _nonblank_lines(
            self.runner.capture_lines(
                self._compose_args(file, "config", "--services"),
                cwd=directory,
                check=True,
            )
        )

    def service_image_pairs(
        self,
        directory: str | Path,
        file: str,
    ) -> tuple[ServiceImage, ...]:
        result = self.runner.capture(
            self._compose_args(file, "config", "--format", "json"),
            cwd=directory,
            check=True,
        )
        return _service_image_pairs_from_config_json(result.stdout)

    def try_service_image_pairs(
        self,
        directory: str | Path,
        file: str,
    ) -> tuple[ServiceImage, ...]:
        try:
            return self.service_image_pairs(directory, file)
        except (CommandError, ValueError):
            return ()

    def discover_stacks(self, docker_base: str | Path) -> tuple[ComposeStack, ...]:
        stacks: list[ComposeStack] = []
        for compose_file in _compose_files_under(docker_base):
            directory = compose_file.parent
            file_name = compose_file.name
            try:
                images = tuple(self.config_images(directory, file_name))
            except CommandError:
                continue
            stacks.append(
                ComposeStack(
                    index=len(stacks) + 1,
                    directory=directory,
                    file=file_name,
                    name=directory.name,
                    images=images,
                    service_images=self.try_service_image_pairs(directory, file_name),
                )
            )
        if not stacks:
            raise ComposeDiscoveryError(
                f"No compose stacks found under {Path(docker_base)} outside ./old."
            )
        return tuple(stacks)

    def pull(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
    ) -> CommandResult:
        return self.run_with_services(directory, file, services, "pull")

    def stop(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
    ) -> CommandResult:
        return self.run_with_services(directory, file, services, "stop")

    def down(self, directory: str | Path, file: str) -> CommandResult:
        return self.run_with_services(directory, file, (), "down")

    def pause(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
    ) -> CommandResult:
        return self.run_with_services(directory, file, services, "pause")

    def unpause(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
    ) -> CommandResult:
        return self.run_with_services(directory, file, services, "unpause")

    def up(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        wait: bool = False,
        wait_timeout: int | None = None,
        force_recreate: bool = False,
        no_deps: bool = True,
    ) -> CommandResult:
        args = ["up", "-d", "--remove-orphans"]
        if force_recreate:
            args.append("--force-recreate")
        if services and no_deps:
            args.append("--no-deps")
        if wait:
            args.append("--wait")
            if wait_timeout is not None:
                args.extend(["--wait-timeout", str(wait_timeout)])
        return self.run_with_services(directory, file, services, *args)

    def ps_quiet(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
    ) -> list[str]:
        try:
            return _nonblank_lines(
                self.runner.capture_lines(
                    self._compose_args(file, "ps", "-q", *_service_args(services)),
                    cwd=directory,
                    check=True,
                )
            )
        except CommandError:
            return []

    def up_wait_supported(self, directory: str | Path, file: str) -> bool:
        result = self.runner.capture(
            self._compose_args(file, "up", "--help"),
            cwd=directory,
            check=False,
        )
        if not result.ok:
            return False
        return (
            bool(_WAIT_FLAG_RE.search(result.stdout))
            and "--wait-timeout" in result.stdout
        )

    def pull_and_recreate(
        self,
        directory: str | Path,
        file: str,
        *,
        mode: str = "stop",
        services: Sequence[str] | None = None,
        max_wait: int = 180,
        use_native_wait: bool | None = None,
    ) -> None:
        """Run the shell updater's pull/stop/up command sequence."""

        if mode not in {"pause", "stop", "live"}:
            raise ValueError("mode must be pause, stop, or live")

        service_args = tuple(_service_args(services))
        force_recreate = not service_args
        self.pull(directory, file, service_args)

        pre_up_error: CommandError | None = None
        if mode == "pause":
            try:
                self.pause(directory, file, service_args)
            except CommandError:
                pass
        elif mode == "stop":
            try:
                stop_services = service_args or tuple(
                    reversed(self.config_services(directory, file))
                )
                self.stop(directory, file, stop_services)
            except CommandError as exc:
                pre_up_error = exc

        if mode == "pause":
            wait = False
        elif use_native_wait is None:
            wait = self.up_wait_supported(directory, file)
        else:
            wait = use_native_wait
        self.up(
            directory,
            file,
            service_args,
            wait=wait,
            wait_timeout=max_wait if wait else None,
            force_recreate=force_recreate,
        )

        if mode == "pause":
            self.unpause(directory, file, service_args)
        if pre_up_error is not None:
            raise pre_up_error

    def run_with_services(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None,
        *compose_args: str,
    ) -> CommandResult:
        return self.runner.run_in_pty(
            self._compose_args(file, *compose_args, *_service_args(services)),
            cwd=directory,
            check=True,
        )

    def _compose_args(self, file: str, *args: str) -> list[str]:
        return [self.docker_executable, "compose", "-f", file, *args]


class ComposeDiscoveryError(RuntimeError):
    """Raised when no usable compose stacks are found."""


def _compose_files_under(docker_base: str | Path) -> list[Path]:
    base = Path(docker_base)
    files: list[Path] = []
    pending = [base]
    while pending:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            relative = path.relative_to(base)
            if path.is_symlink():
                continue
            if path.is_file() and path.name in COMPOSE_FILENAMES:
                files.append(path)
            if len(relative.parts) >= 3 or path.name == "old":
                continue
            if path.is_dir():
                pending.append(path)
    return sorted(files)


def _service_args(services: Sequence[str] | None) -> tuple[str, ...]:
    if services is None:
        return ()
    return tuple(service for service in services if service)


def _nonblank_lines(lines: Iterable[str]) -> list[str]:
    return [line for line in lines if line]


def _sorted_unique_nonblank(lines: Iterable[str]) -> list[str]:
    return sorted(set(_nonblank_lines(lines)))


def _service_image_pairs_from_config_json(config_json: str) -> tuple[ServiceImage, ...]:
    parsed = json.loads(config_json)
    if not isinstance(parsed, dict):
        raise ValueError("Compose config JSON is not an object.")
    services = parsed.get("services")
    if not isinstance(services, dict):
        raise ValueError("Compose config JSON has no services object.")

    pairs: set[ServiceImage] = set()
    for service, config in services.items():
        if not isinstance(service, str) or not isinstance(config, dict):
            continue
        image = config.get("image")
        network_mode = config.get("network_mode")
        network_mode_text = network_mode if isinstance(network_mode, str) else ""
        if isinstance(image, str) and image:
            pairs.add(
                ServiceImage(
                    service=service,
                    image=image,
                    network_mode=network_mode_text,
                )
            )
    return tuple(sorted(pairs, key=lambda pair: (pair.service, pair.image)))
