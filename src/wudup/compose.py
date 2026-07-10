"""Docker Compose subprocess layer for the Python updater."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .command import CommandError, CommandResult, CommandRunner
from .config import DEFAULT_COMPOSE_IGNORE_PATHS, format_compose_ignore_paths
from .platforms import ImagePlatform, parse_platform


COMPOSE_FILENAMES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)
_WAIT_FLAG_RE = re.compile(r"(^|\s)--wait([=,\s]|$)")
_COMPOSE_CONFIG_JSON_OBJECT_ERROR = "Compose config JSON is not an object."
_COMPOSE_CONFIG_SERVICES_OBJECT_ERROR = "Compose config JSON has no services object."


@dataclass(frozen=True)
class ServiceImage:
    service: str
    image: str
    network_mode: str = ""
    labels: tuple[tuple[str, str], ...] = ()
    platform: ImagePlatform | None = None


@dataclass(frozen=True)
class ComposeBindMount:
    service: str
    source: str
    target: str = ""


@dataclass(frozen=True)
class ComposeRuntimePortIssue:
    service: str
    field: str
    value: str
    reason: str


@dataclass(frozen=True)
class ComposeStack:
    index: int
    directory: Path
    file: str
    name: str
    images: tuple[str, ...]
    service_images: tuple[ServiceImage, ...]
    project_directory: Path | None = None


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
        *,
        project_directory: str | Path | None = None,
    ) -> list[str]:
        args = self._compose_args(
            file,
            "config",
            "--images",
            project_directory=project_directory,
        )
        if service:
            args.append(service)
        return _sorted_unique_nonblank(
            self.runner.capture_lines(args, cwd=directory, check=True)
        )

    def config_services(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> list[str]:
        return _nonblank_lines(
            self.runner.capture_lines(
                self._compose_args(
                    file,
                    "config",
                    "--services",
                    project_directory=project_directory,
                ),
                cwd=directory,
                check=True,
            )
        )

    def service_image_pairs(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ServiceImage, ...]:
        result = self.config_json(
            directory,
            file,
            project_directory=project_directory,
        )
        return _service_image_pairs_from_config_json(result.stdout)

    def try_service_image_pairs(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ServiceImage, ...]:
        try:
            return self.service_image_pairs(
                directory,
                file,
                project_directory=project_directory,
            )
        except (CommandError, ValueError):
            return ()

    def service_bind_mounts(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ComposeBindMount, ...]:
        result = self.config_json(
            directory,
            file,
            project_directory=project_directory,
        )
        return _service_bind_mounts_from_config_json(result.stdout)

    def try_service_bind_mounts(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ComposeBindMount, ...]:
        try:
            return self.service_bind_mounts(
                directory,
                file,
                project_directory=project_directory,
            )
        except (CommandError, ValueError):
            return ()

    def service_runtime_port_issues(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ComposeRuntimePortIssue, ...]:
        result = self.config_json(
            directory,
            file,
            project_directory=project_directory,
        )
        return _service_runtime_port_issues_from_config_json(result.stdout)

    def try_service_runtime_port_issues(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> tuple[ComposeRuntimePortIssue, ...]:
        try:
            return self.service_runtime_port_issues(
                directory,
                file,
                project_directory=project_directory,
            )
        except (CommandError, ValueError):
            return ()

    def config_json(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.runner.capture(
            self._compose_args(
                file,
                "config",
                "--format",
                "json",
                project_directory=project_directory,
            ),
            cwd=directory,
            check=True,
        )

    def discover_stacks(
        self,
        docker_base: str | Path,
        *,
        project_base: str | Path | None = None,
        ignore_paths: Sequence[str | Path] | None = None,
        required_stack_names: Collection[str] = (),
    ) -> tuple[ComposeStack, ...]:
        docker_base_path = Path(docker_base)
        project_base_path = Path(project_base) if project_base is not None else None
        normalized_ignore_paths = normalize_compose_ignore_paths(ignore_paths)
        required_names = set(required_stack_names)
        stacks: list[ComposeStack] = []
        for compose_file in _compose_files_under(
            docker_base_path,
            ignore_paths=normalized_ignore_paths,
        ):
            directory = compose_file.parent
            file_name = compose_file.name
            project_directory = _validated_project_directory_for_stack(
                directory,
                file_name,
                docker_base_path,
                project_base_path,
            )
            required = directory.name in required_names
            try:
                images = tuple(
                    self.config_images(
                        directory,
                        file_name,
                        project_directory=project_directory,
                    )
                )
                service_images = (
                    self.service_image_pairs(
                        directory,
                        file_name,
                        project_directory=project_directory,
                    )
                    if required
                    else self.try_service_image_pairs(
                        directory,
                        file_name,
                        project_directory=project_directory,
                    )
                )
            except (CommandError, ValueError) as exc:
                if required:
                    raise ComposeDiscoveryError(
                        "Could not inspect a required Compose stack."
                    ) from exc
                continue
            stacks.append(
                ComposeStack(
                    index=len(stacks) + 1,
                    directory=directory,
                    file=file_name,
                    name=directory.name,
                    images=images,
                    service_images=service_images,
                    project_directory=project_directory,
                )
            )
        if not stacks:
            raise ComposeDiscoveryError(
                compose_discovery_message(
                    docker_base_path,
                    ignore_paths=normalized_ignore_paths,
                )
            )
        return tuple(stacks)

    def pull(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.run_with_services(
            directory,
            file,
            services,
            "pull",
            project_directory=project_directory,
        )

    def stop(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.run_with_services(
            directory,
            file,
            services,
            "stop",
            project_directory=project_directory,
        )

    def down(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.run_with_services(
            directory,
            file,
            (),
            "down",
            project_directory=project_directory,
        )

    def pause(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.run_with_services(
            directory,
            file,
            services,
            "pause",
            project_directory=project_directory,
        )

    def unpause(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.run_with_services(
            directory,
            file,
            services,
            "unpause",
            project_directory=project_directory,
        )

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
        project_directory: str | Path | None = None,
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
        return self.run_with_services(
            directory,
            file,
            services,
            *args,
            project_directory=project_directory,
        )

    def ps_quiet(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None = None,
        *,
        project_directory: str | Path | None = None,
    ) -> list[str]:
        try:
            return _nonblank_lines(
                self.runner.capture_lines(
                    self._compose_args(
                        file,
                        "ps",
                        "-q",
                        *_service_args(services),
                        project_directory=project_directory,
                    ),
                    cwd=directory,
                    check=True,
                )
            )
        except CommandError:
            return []

    def up_wait_supported(
        self,
        directory: str | Path,
        file: str,
        *,
        project_directory: str | Path | None = None,
    ) -> bool:
        result = self.runner.capture(
            self._compose_args(
                file,
                "up",
                "--help",
                project_directory=project_directory,
            ),
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
        project_directory: str | Path | None = None,
    ) -> None:
        """Run the shell updater's pull/stop/up command sequence."""

        if mode not in {"pause", "stop", "live"}:
            raise ValueError("mode must be pause, stop, or live")

        service_args = tuple(_service_args(services))
        force_recreate = not service_args
        self.pull(
            directory,
            file,
            service_args,
            project_directory=project_directory,
        )

        pre_up_error: CommandError | None = None
        if mode == "pause":
            try:
                self.pause(
                    directory,
                    file,
                    service_args,
                    project_directory=project_directory,
                )
            except CommandError:
                pass
        elif mode == "stop":
            try:
                stop_services = service_args or tuple(
                    reversed(
                        self.config_services(
                            directory,
                            file,
                            project_directory=project_directory,
                        )
                    )
                )
                self.stop(
                    directory,
                    file,
                    stop_services,
                    project_directory=project_directory,
                )
            except CommandError as exc:
                pre_up_error = exc

        if mode == "pause":
            wait = False
        elif use_native_wait is None:
            wait = self.up_wait_supported(
                directory,
                file,
                project_directory=project_directory,
            )
        else:
            wait = use_native_wait
        self.up(
            directory,
            file,
            service_args,
            wait=wait,
            wait_timeout=max_wait if wait else None,
            force_recreate=force_recreate,
            project_directory=project_directory,
        )

        if mode == "pause":
            self.unpause(
                directory,
                file,
                service_args,
                project_directory=project_directory,
            )
        if pre_up_error is not None:
            raise pre_up_error

    def run_with_services(
        self,
        directory: str | Path,
        file: str,
        services: Sequence[str] | None,
        *compose_args: str,
        project_directory: str | Path | None = None,
    ) -> CommandResult:
        return self.runner.run_in_pty(
            self._compose_args(
                file,
                *compose_args,
                *_service_args(services),
                project_directory=project_directory,
            ),
            cwd=directory,
            check=True,
        )

    def _compose_args(
        self,
        file: str,
        *args: str,
        project_directory: str | Path | None = None,
    ) -> list[str]:
        command = [self.docker_executable, "compose"]
        if project_directory is not None:
            command.extend(["--project-directory", str(project_directory)])
        command.extend(["-f", file, *args])
        return command


class ComposeDiscoveryError(RuntimeError):
    """Raised when no usable compose stacks are found."""


def normalize_compose_ignore_paths(
    ignore_paths: Sequence[str | Path] | None = None,
) -> tuple[Path, ...]:
    if ignore_paths is None:
        return DEFAULT_COMPOSE_IGNORE_PATHS

    normalized: list[Path] = []
    seen: set[tuple[str, ...]] = set()
    for ignore_path in ignore_paths:
        path = Path(ignore_path)
        parts = path.parts
        if (
            path.is_absolute()
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("compose ignore paths must be relative paths")
        if parts not in seen:
            seen.add(parts)
            normalized.append(path)
    return tuple(normalized)


def compose_discovery_message(
    docker_base: str | Path,
    *,
    ignore_paths: Sequence[str | Path] | None = None,
) -> str:
    normalized_ignore_paths = normalize_compose_ignore_paths(ignore_paths)
    message = f"No compose stacks found under {Path(docker_base)}."
    if normalized_ignore_paths:
        message = (
            f"{message} Ignored paths: "
            f"{format_compose_ignore_paths(normalized_ignore_paths)}."
        )
    return message


def _compose_files_under(
    docker_base: str | Path,
    *,
    ignore_paths: Sequence[str | Path] | None = None,
) -> list[Path]:
    base = Path(docker_base)
    normalized_ignore_paths = normalize_compose_ignore_paths(ignore_paths)
    ignore_path_parts = tuple(path.parts for path in normalized_ignore_paths)
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
            if len(relative.parts) >= 3 or _ignored_compose_path(
                path,
                relative,
                ignore_path_parts,
            ):
                continue
            if path.is_dir():
                pending.append(path)
    return sorted(files)


def compose_files_under(
    docker_base: str | Path,
    *,
    ignore_paths: Sequence[str | Path] | None = None,
) -> tuple[Path, ...]:
    """Return compose files discovered with the updater's stack search rules."""

    return tuple(_compose_files_under(docker_base, ignore_paths=ignore_paths))


def _ignored_compose_path(
    path: Path,
    relative: Path,
    ignore_path_parts: tuple[tuple[str, ...], ...],
) -> bool:
    relative_parts = relative.parts
    for ignored_parts in ignore_path_parts:
        if len(ignored_parts) == 1 and path.name == ignored_parts[0]:
            return True
        if len(ignored_parts) > 1 and relative_parts[: len(ignored_parts)] == ignored_parts:
            return True
    return False


def _service_args(services: Sequence[str] | None) -> tuple[str, ...]:
    if services is None:
        return ()
    return tuple(service for service in services if service)


def _project_directory_for_stack(
    directory: Path,
    docker_base: Path,
    project_base: Path | None,
) -> Path | None:
    if project_base is None:
        return None
    try:
        relative = directory.relative_to(docker_base)
    except ValueError as exc:
        raise ComposeDiscoveryError(
            f"Compose stack {directory} is not under DOCKER_BASE {docker_base}; "
            f"cannot map HOST_DOCKER_BASE {project_base}."
        ) from exc
    return project_base / relative


def _validated_project_directory_for_stack(
    directory: Path,
    file: str,
    docker_base: Path,
    project_base: Path | None,
) -> Path | None:
    project_directory = _project_directory_for_stack(
        directory,
        docker_base,
        project_base,
    )
    if project_directory is None:
        return None

    compose_path = project_directory / file
    if compose_path.is_file() and os.access(compose_path, os.R_OK):
        return project_directory

    raise ComposeDiscoveryError(
        f"HOST_DOCKER_BASE maps Compose stack {directory} to "
        f"{project_directory}, but {compose_path} is not a readable compose "
        "file. Mount the host Compose root into the helper at HOST_DOCKER_BASE "
        "(for example /srv/docker:/srv/docker), or set DOCKER_BASE to a "
        "same-absolute-path mount."
    )


def _nonblank_lines(lines: Iterable[str]) -> list[str]:
    return [line for line in lines if line]


def _sorted_unique_nonblank(lines: Iterable[str]) -> list[str]:
    return sorted(set(_nonblank_lines(lines)))


def _service_image_pairs_from_config_json(config_json: str) -> tuple[ServiceImage, ...]:
    services = _services_from_config_json(config_json)
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
                    labels=_service_labels(config.get("labels")),
                    platform=_service_platform(config.get("platform")),
                )
            )
    return tuple(sorted(pairs, key=lambda pair: (pair.service, pair.image)))


def _service_platform(value: object) -> ImagePlatform | None:
    if not isinstance(value, str):
        return None
    return parse_platform(value)


def _service_labels(labels: object) -> tuple[tuple[str, str], ...]:
    values: dict[str, str] = {}
    if isinstance(labels, dict):
        for key, value in labels.items():
            if isinstance(key, str) and isinstance(value, str):
                values[key] = value
    elif isinstance(labels, list):
        for item in labels:
            if not isinstance(item, str):
                continue
            key, sep, value = item.partition("=")
            if key:
                values[key] = value if sep else ""
    return tuple(sorted(values.items()))


def _service_bind_mounts_from_config_json(config_json: str) -> tuple[ComposeBindMount, ...]:
    services = _services_from_config_json(config_json)
    mounts: set[ComposeBindMount] = set()
    for service, config in services.items():
        if not isinstance(service, str) or not isinstance(config, dict):
            continue
        volumes = config.get("volumes")
        if not isinstance(volumes, list):
            continue
        for volume in volumes:
            if not isinstance(volume, dict) or volume.get("type") != "bind":
                continue
            source = volume.get("source")
            target = volume.get("target")
            if isinstance(source, str) and source:
                mounts.add(
                    ComposeBindMount(
                        service=service,
                        source=source,
                        target=target if isinstance(target, str) else "",
                    )
                )
    return tuple(sorted(mounts, key=lambda item: (item.service, item.source, item.target)))


def _service_runtime_port_issues_from_config_json(
    config_json: str,
) -> tuple[ComposeRuntimePortIssue, ...]:
    services = _services_from_config_json(config_json)
    issues: list[ComposeRuntimePortIssue] = []
    for service, config in services.items():
        if not isinstance(service, str) or not isinstance(config, dict):
            continue
        expose = config.get("expose")
        if isinstance(expose, list):
            for item in expose:
                value = _display_runtime_port_value(item)
                reason = _runtime_expose_issue(item)
                if reason:
                    issues.append(
                        ComposeRuntimePortIssue(
                            service=service,
                            field="expose",
                            value=value,
                            reason=reason,
                        )
                    )
        ports = config.get("ports")
        if isinstance(ports, list):
            for item in ports:
                issues.extend(_runtime_port_issues(service, item))
    return tuple(issues)


def _services_from_config_json(config_json: str) -> dict[object, object]:
    parsed = json.loads(config_json)
    if not isinstance(parsed, dict):
        raise ValueError(_COMPOSE_CONFIG_JSON_OBJECT_ERROR)
    services = parsed.get("services")
    if not isinstance(services, dict):
        raise ValueError(_COMPOSE_CONFIG_SERVICES_OBJECT_ERROR)
    return services


def _runtime_expose_issue(value: object) -> str:
    if not isinstance(value, (str, int)):
        return "expected numeric port or port range with optional protocol"
    text = str(value).strip()
    if not text:
        return "expected numeric port or port range with optional protocol"
    return _port_range_issue(text)


def _runtime_port_issues(
    service: str,
    value: object,
) -> tuple[ComposeRuntimePortIssue, ...]:
    if not isinstance(value, dict):
        reason = "expected normalized Compose port mapping object"
        return (
            ComposeRuntimePortIssue(
                service=service,
                field="ports",
                value=_display_runtime_port_value(value),
                reason=reason,
            ),
        )

    issues: list[ComposeRuntimePortIssue] = []
    target = value.get("target")
    target_issue = _port_number_issue(target)
    if target_issue:
        issues.append(
            ComposeRuntimePortIssue(
                service=service,
                field="ports.target",
                value=_display_runtime_port_value(target),
                reason=target_issue,
            )
        )

    published = value.get("published")
    if published not in (None, ""):
        published_issue = _port_range_issue(str(published).strip())
        if published_issue:
            issues.append(
                ComposeRuntimePortIssue(
                    service=service,
                    field="ports.published",
                    value=_display_runtime_port_value(published),
                    reason=published_issue,
                )
            )
    return tuple(issues)


def _port_range_issue(value: str) -> str:
    port_text, sep, protocol = value.partition("/")
    if sep and protocol not in {"tcp", "udp", "sctp"}:
        return "expected protocol tcp, udp, or sctp"
    parts = port_text.split("-")
    if len(parts) > 2 or any(_port_number_issue(part) for part in parts):
        return "expected numeric port or port range from 1 to 65535"
    if len(parts) == 2 and int(parts[0]) > int(parts[1]):
        return "expected port range start to be less than or equal to end"
    return ""


def _port_number_issue(value: object) -> str:
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        return "expected numeric port from 1 to 65535"
    port = int(text)
    if port < 1 or port > 65535:
        return "expected numeric port from 1 to 65535"
    return ""


def _display_runtime_port_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)
