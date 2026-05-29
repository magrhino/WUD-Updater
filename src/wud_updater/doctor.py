"""Read-only diagnostics for containerized WUD-Updater deployments."""

from __future__ import annotations

import argparse
import errno
import os
import shutil
import socket
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .command import CommandResult, CommandRunner
from .compose import ComposeCli, compose_files_under
from .updates import (
    DEFAULT_TRUENAS_STATUS_TIMEOUT,
    TRUENAS_MIDDLEWARE_MOUNT,
    load_configured_environ,
)


DEFAULT_CONTAINER_APP_DIR = Path("/app")
DEFAULT_CONTAINER_DOCKER_BASE = "/host/docker"
DEFAULT_CONTAINER_OUT_FILE = "/out/images.todo"
DEFAULT_CONTAINER_LOG_DIR = "/logs"
DEFAULT_CONTAINER_SCRIPTS_DIR = "/managed-wud"
HELPER_ONLY_MOUNT_PREFIXES = (Path("/host"), Path("/docker-host"), Path("/container-host"))
MANAGED_SCRIPTS_MARKER = ".wud-updater-managed"
DOCTOR_PROBE_NAME = ".wud-updater-doctor-probe"


@dataclass(frozen=True)
class DoctorOptions:
    docker_base: Path
    wud_file: Path
    log_dir: Path
    scripts_dir: Path
    packaged_scripts_dir: Path
    app_dir: Path
    updater: str
    host_docker_base: Path | None = None
    docker_host: str = ""
    sync_scripts: bool = False
    updater_use_sudo: bool = True
    truenas_status_check: bool = False
    truenas_status_timeout: str = DEFAULT_TRUENAS_STATUS_TIMEOUT
    no_color: bool = False


@dataclass(frozen=True)
class DoctorCheck:
    status: str
    name: str
    detail: str = ""


class DoctorConfigError(RuntimeError):
    """Raised for invalid doctor configuration."""


class Doctor:
    def __init__(
        self,
        options: DoctorOptions,
        *,
        environ: Mapping[str, str] | None = None,
        runner: CommandRunner | None = None,
        compose: ComposeCli | None = None,
    ) -> None:
        self.options = options
        self.environ = dict(os.environ if environ is None else environ)
        self.runner = runner or CommandRunner(env=self.environ)
        self.compose = compose or ComposeCli(runner=self.runner)
        self.checks: list[DoctorCheck] = []

    def run(self) -> int:
        self._check_runtime()
        self._check_docker_access()
        self._check_paths()
        self._check_compose()
        self._check_truenas()
        self._print_results()
        return 1 if any(check.status == "FAIL" for check in self.checks) else 0

    def _check_runtime(self) -> None:
        version = (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        )
        self._record("PASS", "python runtime", version)
        self._check_python_import("rich")
        self._check_python_import("ruamel.yaml")
        self._check_command("docker cli", ["docker", "--version"])
        self._check_command("docker compose plugin", ["docker", "compose", "version"])
        self._check_updater()
        self._check_sudo()

    def _check_docker_access(self) -> None:
        socket_path = _docker_unix_socket_path(self.options.docker_host)
        if socket_path is None:
            self._record(
                "PASS",
                "docker endpoint",
                f"using DOCKER_HOST={self.options.docker_host}",
            )
        else:
            self._check_unix_socket(socket_path)

        self._check_command("docker daemon version", ["docker", "version"])
        self._check_command("docker daemon info", ["docker", "info"])
        self._check_command("docker container listing", ["docker", "ps"])

    def _check_paths(self) -> None:
        self._check_readable_dir(
            "DOCKER_BASE",
            self.options.docker_base,
            critical=True,
        )
        if self.options.host_docker_base is None:
            self._record("PASS", "HOST_DOCKER_BASE", "not configured")
        else:
            if not self.options.host_docker_base.is_absolute():
                self._record(
                    "FAIL",
                    "HOST_DOCKER_BASE",
                    f"{self.options.host_docker_base} is not absolute",
                )
            else:
                self._check_readable_dir(
                    "HOST_DOCKER_BASE",
                    self.options.host_docker_base,
                    critical=True,
                )

        self._check_wud_file()
        self._check_log_dir()
        self._check_packaged_scripts()
        self._check_script_sync()

    def _check_compose(self) -> None:
        compose_files = compose_files_under(self.options.docker_base)
        if not compose_files:
            self._record(
                "FAIL",
                "compose discovery",
                f"no compose stacks found under {self.options.docker_base} outside ./old",
            )
            return

        valid_count = 0
        for compose_file in compose_files:
            project_directory = None
            if self.options.host_docker_base is not None:
                project_directory = self._mapped_project_directory(compose_file)
                if project_directory is None:
                    continue
            result = self.runner.capture(
                self.compose._compose_args(
                    compose_file.name,
                    "config",
                    project_directory=project_directory,
                ),
                cwd=compose_file.parent,
                check=False,
            )
            label = f"compose config {compose_file}"
            if result.ok:
                valid_count += 1
                self._record("PASS", label)
                self._check_bind_mount_safety(compose_file, project_directory)
            else:
                self._record("FAIL", label, _failure_detail(result))

        if valid_count > 0:
            self._record(
                "PASS",
                "compose discovery",
                f"{valid_count} stack(s) rendered",
            )
        else:
            self._record(
                "FAIL",
                "compose discovery",
                "no discovered compose stacks rendered successfully",
            )

    def _check_truenas(self) -> None:
        if not self.options.truenas_status_check:
            self._record(
                "WARN",
                "TrueNAS status helper",
                "TRUENAS_STATUS_CHECK is disabled",
            )
            return

        if not _seconds_valid(self.options.truenas_status_timeout):
            self._record(
                "FAIL",
                "TrueNAS status timeout",
                "TRUENAS_STATUS_TIMEOUT must be an integer number of seconds",
            )
        else:
            self._record(
                "PASS",
                "TrueNAS status timeout",
                f"{self.options.truenas_status_timeout}s",
            )

        hostname = self.environ.get("HOSTNAME") or ""
        if not hostname:
            self._record(
                "FAIL",
                "TrueNAS helper container inspect",
                "HOSTNAME is not set",
            )
            return

        result = self.runner.capture(
            ["docker", "container", "inspect", hostname],
            check=False,
        )
        if result.ok:
            self._record(
                "PASS",
                "TrueNAS helper container inspect",
                "current container is inspectable",
            )
            self._record(
                "WARN",
                "TrueNAS middleware socket",
                f"{TRUENAS_MIDDLEWARE_MOUNT} is validated by docker run at status-check time",
            )
        else:
            self._record(
                "FAIL",
                "TrueNAS helper container inspect",
                _failure_detail(result),
            )

    def _check_command(self, name: str, command: Sequence[str]) -> CommandResult:
        result = self.runner.capture(command, check=False)
        if result.ok:
            detail = _first_line(result.stdout) or _first_line(result.stderr)
            self._record("PASS", name, detail)
        else:
            self._record("FAIL", name, _failure_detail(result))
        return result

    def _check_python_import(self, module: str) -> None:
        try:
            __import__(module)
        except ImportError as exc:
            self._record("FAIL", f"python import {module}", str(exc))
        else:
            self._record("PASS", f"python import {module}")

    def _check_updater(self) -> None:
        updater = self.options.updater
        if not updater:
            self._record("FAIL", "updater executable", "WUD_UPDATER is empty")
            return

        path = Path(updater)
        if path.is_absolute() or "/" in updater:
            if path.is_file() and os.access(path, os.X_OK):
                self._record("PASS", "updater executable", str(path))
            elif path.exists():
                self._record(
                    "FAIL",
                    "updater executable",
                    f"{path} is not executable",
                )
            else:
                self._record("FAIL", "updater executable", f"{path} does not exist")
            return

        resolved = shutil.which(updater, path=self.environ.get("PATH"))
        if resolved:
            self._record("PASS", "updater executable", resolved)
        else:
            self._record(
                "FAIL",
                "updater executable",
                f"{updater} not found on PATH",
            )

    def _check_sudo(self) -> None:
        if not self.options.updater_use_sudo:
            self._record("PASS", "sudo", "disabled by WUD_UPDATER_USE_SUDO=false")
            return

        if shutil.which("sudo", path=self.environ.get("PATH")) is None:
            self._record("FAIL", "sudo", "required but not found on PATH")
            return

        result = self.runner.capture(["sudo", "-n", "true"], check=False)
        if result.ok:
            self._record("PASS", "sudo", "non-interactive sudo works")
        else:
            self._record("FAIL", "sudo", _failure_detail(result))

    def _check_unix_socket(self, socket_path: Path) -> None:
        try:
            mode = socket_path.stat().st_mode
        except OSError as exc:
            self._record(
                "FAIL",
                "docker socket",
                f"{socket_path}: {_format_os_error(exc)}",
            )
            return

        if not stat.S_ISSOCK(mode):
            self._record(
                "FAIL",
                "docker socket",
                f"{socket_path} is not a Unix socket",
            )
            return

        if not os.access(socket_path, os.R_OK | os.W_OK):
            self._record(
                "FAIL",
                "docker socket",
                f"{socket_path} is not readable and writable",
            )
            return

        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(2)
                probe.connect(str(socket_path))
            finally:
                probe.close()
        except OSError as exc:
            self._record(
                "FAIL",
                "docker socket",
                f"{socket_path}: {_format_os_error(exc)}",
            )
            return

        self._record("PASS", "docker socket", str(socket_path))

    def _check_readable_dir(self, name: str, path: Path, *, critical: bool) -> None:
        if not path.exists():
            self._record(
                "FAIL" if critical else "WARN",
                name,
                f"{path} does not exist",
            )
        elif not path.is_dir():
            self._record("FAIL", name, f"{path} is not a directory")
        elif not os.access(path, os.R_OK | os.X_OK):
            self._record("FAIL", name, f"{path} is not readable/searchable")
        else:
            self._record("PASS", name, str(path))

    def _check_wud_file(self) -> None:
        wud_file = self.options.wud_file
        parent = wud_file.parent
        if not parent.exists():
            self._record(
                "FAIL",
                "WUD_OUT_FILE directory",
                f"{parent} does not exist",
            )
            return
        if not parent.is_dir():
            self._record("FAIL", "WUD_OUT_FILE directory", f"{parent} is not a directory")
            return
        if not os.access(parent, os.W_OK | os.X_OK):
            self._record(
                "FAIL",
                "WUD_OUT_FILE directory",
                f"{parent} is not writable/searchable",
            )
            return
        probe = _write_probe(parent)
        if probe:
            self._record("FAIL", "WUD_OUT_FILE directory", probe)
            return
        self._record("PASS", "WUD_OUT_FILE directory", str(parent))

        if not wud_file.exists():
            self._record("PASS", "WUD_OUT_FILE", f"{wud_file} may be created by WUD")
        elif not wud_file.is_file():
            self._record("FAIL", "WUD_OUT_FILE", f"{wud_file} is not a file")
        elif not os.access(wud_file, os.R_OK | os.W_OK):
            self._record(
                "FAIL",
                "WUD_OUT_FILE",
                f"{wud_file} is not readable and writable",
            )
        else:
            self._record("PASS", "WUD_OUT_FILE", str(wud_file))

    def _check_log_dir(self) -> None:
        log_dir = self.options.log_dir
        if log_dir.exists():
            if not log_dir.is_dir():
                self._record("FAIL", "WUD_LOG_DIR", f"{log_dir} is not a directory")
                return
            if not os.access(log_dir, os.W_OK | os.X_OK):
                self._record("FAIL", "WUD_LOG_DIR", f"{log_dir} is not writable/searchable")
                return
            probe = _write_probe(log_dir)
            if probe:
                self._record("FAIL", "WUD_LOG_DIR", probe)
            else:
                self._record("PASS", "WUD_LOG_DIR", str(log_dir))
            return

        parent = _nearest_existing_parent(log_dir)
        if parent is None:
            self._record("FAIL", "WUD_LOG_DIR", f"{log_dir} has no existing parent")
        elif not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            self._record(
                "FAIL",
                "WUD_LOG_DIR",
                f"{parent} cannot create {log_dir.name}",
            )
        else:
            self._record("PASS", "WUD_LOG_DIR", f"{log_dir} can be created")

    def _check_packaged_scripts(self) -> None:
        scripts = self.options.packaged_scripts_dir
        if not scripts.is_dir():
            self._record("FAIL", "packaged WUD scripts", f"{scripts} does not exist")
            return

        required = (
            "on-update.sh",
            "append-updates.sh",
            "release-notes-to-discord.sh",
            "github-release-embed.sh",
            "tag-manager.sh",
        )
        failures: list[str] = []
        for name in required:
            path = scripts / name
            if not path.is_file():
                failures.append(f"{name} missing")
            elif not os.access(path, os.X_OK):
                failures.append(f"{name} not executable")
        if failures:
            self._record("FAIL", "packaged WUD scripts", "; ".join(failures))
        else:
            self._record("PASS", "packaged WUD scripts", str(scripts))

    def _check_script_sync(self) -> None:
        if not self.options.sync_scripts:
            self._record("WARN", "WUD script sync", "WUD_SYNC_SCRIPTS is disabled")
            return

        issue = self._script_sync_issue()
        if issue:
            self._record("FAIL", "WUD script sync", issue)
        else:
            self._record("PASS", "WUD script sync", str(self.options.scripts_dir))

    def _script_sync_issue(self) -> str:
        dst = self.options.scripts_dir
        if str(dst) == "":
            return "WUD_SCRIPTS_DIR is empty"

        resolved_dst = _canonical_dir_target(dst)
        if resolved_dst is None:
            return f"unable to resolve WUD_SCRIPTS_DIR {dst}"
        resolved_app = _canonical_dir_target(self.options.app_dir)
        resolved_base = _canonical_dir_target(self.options.docker_base)
        resolved_out = _canonical_dir_target(self.options.wud_file.parent)
        if resolved_app is None:
            return f"unable to resolve WUD_APP_DIR {self.options.app_dir}"
        if resolved_base is None:
            return f"unable to resolve DOCKER_BASE {self.options.docker_base}"
        if resolved_out is None:
            return f"unable to resolve WUD_OUT_FILE directory {self.options.wud_file.parent}"

        if (
            resolved_dst == Path("/")
            or _path_is_or_under(resolved_dst, resolved_app)
            or _path_is_or_under(resolved_dst, resolved_base)
            or _path_is_or_under(resolved_dst, resolved_out)
        ):
            return f"unsafe WUD_SCRIPTS_DIR {dst}"

        if dst.exists():
            if not dst.is_dir():
                return f"{dst} is not a directory"
            if not os.access(dst, os.W_OK | os.X_OK):
                return f"{dst} is not writable/searchable"
            marker = dst / MANAGED_SCRIPTS_MARKER
            if not marker.exists() and any(dst.iterdir()):
                return f"{dst} is non-empty and not marked as managed"
            probe = _write_probe(dst)
            return probe

        parent = _nearest_existing_parent(dst)
        if parent is None:
            return f"{dst} has no existing parent"
        if not os.access(parent, os.W_OK | os.X_OK):
            return f"{parent} cannot create {dst.name}"
        return ""

    def _mapped_project_directory(self, compose_file: Path) -> Path | None:
        host_base = self.options.host_docker_base
        if host_base is None:
            return None
        stack_dir = compose_file.parent
        try:
            relative = stack_dir.relative_to(self.options.docker_base)
        except ValueError:
            self._record(
                "FAIL",
                f"HOST_DOCKER_BASE mapping {stack_dir}",
                f"not under DOCKER_BASE {self.options.docker_base}",
            )
            return None
        project_directory = host_base / relative
        compose_path = project_directory / compose_file.name
        if not project_directory.is_dir():
            self._record(
                "FAIL",
                f"HOST_DOCKER_BASE mapping {stack_dir}",
                f"{project_directory} does not exist",
            )
            return None
        if not os.access(project_directory, os.R_OK | os.X_OK):
            self._record(
                "FAIL",
                f"HOST_DOCKER_BASE mapping {stack_dir}",
                f"{project_directory} is not readable/searchable",
            )
            return None
        if not compose_path.exists():
            self._record(
                "FAIL",
                f"HOST_DOCKER_BASE mapping {stack_dir}",
                f"{compose_path} does not exist",
            )
            return None
        return project_directory

    def _check_bind_mount_safety(
        self,
        compose_file: Path,
        project_directory: Path | None,
    ) -> None:
        mounts = self.compose.try_service_bind_mounts(
            compose_file.parent,
            compose_file.name,
            project_directory=project_directory,
        )
        unsafe: list[str] = []
        for mount in mounts:
            source = Path(mount.source)
            if not source.is_absolute():
                continue
            for prefix in HELPER_ONLY_MOUNT_PREFIXES:
                if _path_is_or_under(source, prefix):
                    unsafe.append(f"{mount.service}: {source}")
                    break
        if unsafe:
            self._record(
                "WARN",
                f"bind mount path safety {compose_file}",
                "helper-only path(s): " + ", ".join(unsafe),
            )

    def _record(self, status: str, name: str, detail: str = "") -> None:
        self.checks.append(DoctorCheck(status=status, name=name, detail=detail))

    def _print_results(self) -> None:
        print("WUD-Updater doctor")
        for check in self.checks:
            if check.detail:
                print(f"[{check.status}] {check.name}: {check.detail}")
            else:
                print(f"[{check.status}] {check.name}")
        failures = sum(1 for check in self.checks if check.status == "FAIL")
        warnings = sum(1 for check in self.checks if check.status == "WARN")
        print(f"Result: {failures} failure(s), {warnings} warning(s)")


def run_doctor_from_namespace(
    args: argparse.Namespace,
    *,
    repo_root: str | Path,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = load_configured_environ(environ)
    try:
        options = options_from_namespace(args, repo_root=repo_root, environ=env)
    except DoctorConfigError as exc:
        print("WUD-Updater doctor")
        print(f"[FAIL] configuration: {exc}")
        print("Result: 1 failure(s), 0 warning(s)")
        return 1
    return Doctor(options, environ=env).run()


def options_from_namespace(
    args: argparse.Namespace,
    *,
    repo_root: str | Path,
    environ: Mapping[str, str],
) -> DoctorOptions:
    repo_path = Path(repo_root)
    app_dir = Path(environ.get("WUD_APP_DIR") or _default_app_dir(repo_path))
    docker_base_label = (
        str(getattr(args, "base", "") or "")
        or environ.get("DOCKER_BASE")
        or _default_docker_base(repo_path)
    )
    docker_base = Path(docker_base_label)
    wud_file = Path(
        str(getattr(args, "file", "") or "")
        or environ.get("WUD_OUT_FILE")
        or f"{docker_base_label}/wud/out/images.todo"
    )
    log_dir = Path(
        str(getattr(args, "log_dir", "") or "")
        or environ.get("WUD_LOG_DIR")
        or _default_log_dir()
    )
    scripts_dir = Path(
        str(getattr(args, "scripts_dir", "") or "")
        or environ.get("WUD_SCRIPTS_DIR")
        or DEFAULT_CONTAINER_SCRIPTS_DIR
    )
    packaged_scripts_dir = _default_packaged_scripts_dir(app_dir, repo_path)
    host_docker_base = environ.get("HOST_DOCKER_BASE") or ""
    updater = environ.get("WUD_UPDATER") or _default_updater(repo_path)

    return DoctorOptions(
        docker_base=docker_base,
        wud_file=wud_file,
        log_dir=log_dir,
        scripts_dir=scripts_dir,
        packaged_scripts_dir=packaged_scripts_dir,
        app_dir=app_dir,
        updater=updater,
        host_docker_base=Path(host_docker_base) if host_docker_base else None,
        docker_host=environ.get("DOCKER_HOST") or "",
        sync_scripts=_resolve_bool_env(
            environ.get("WUD_SYNC_SCRIPTS"),
            "WUD_SYNC_SCRIPTS",
            default=False,
        ),
        updater_use_sudo=_resolve_bool_env(
            environ.get("WUD_UPDATER_USE_SUDO"),
            "WUD_UPDATER_USE_SUDO",
            default=True,
        ),
        truenas_status_check=_resolve_bool_env(
            environ.get("TRUENAS_STATUS_CHECK"),
            "TRUENAS_STATUS_CHECK",
            default=False,
        ),
        truenas_status_timeout=(
            environ.get("TRUENAS_STATUS_TIMEOUT") or DEFAULT_TRUENAS_STATUS_TIMEOUT
        ),
        no_color=bool(getattr(args, "no_color", False)),
    )


def _default_app_dir(repo_root: Path) -> str:
    if (DEFAULT_CONTAINER_APP_DIR / "wud").is_dir():
        return str(DEFAULT_CONTAINER_APP_DIR)
    return str(repo_root)


def _default_docker_base(repo_root: Path) -> str:
    if DEFAULT_CONTAINER_APP_DIR.is_dir():
        return DEFAULT_CONTAINER_DOCKER_BASE
    home = os.environ.get("HOME") or str(Path.home())
    if (repo_root / "wud").is_dir():
        return f"{home}/docker"
    return DEFAULT_CONTAINER_DOCKER_BASE


def _default_log_dir() -> str:
    if DEFAULT_CONTAINER_APP_DIR.is_dir():
        return DEFAULT_CONTAINER_LOG_DIR
    return "./logs"


def _default_packaged_scripts_dir(app_dir: Path, repo_root: Path) -> Path:
    app_scripts = app_dir / "wud"
    if app_scripts.is_dir():
        return app_scripts
    return repo_root / "wud"


def _default_updater(repo_root: Path) -> str:
    repo_updater = repo_root / "bin" / "docker-update-from-wud"
    if repo_updater.exists():
        return str(repo_updater)
    return "/app/bin/docker-update-from-wud"


def _docker_unix_socket_path(docker_host: str) -> Path | None:
    if docker_host == "":
        return Path("/var/run/docker.sock")
    if docker_host.startswith("unix://"):
        return Path(docker_host.removeprefix("unix://"))
    return None


def _resolve_bool_env(value: str | None, label: str, *, default: bool) -> bool:
    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DoctorConfigError(
        f"{label} must be one of true, false, 1, 0, yes, no, on, or off"
    )


def _write_probe(directory: Path) -> str:
    probe = directory / f"{DOCTOR_PROBE_NAME}.{os.getpid()}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(probe, flags, 0o600)
        try:
            os.write(fd, b"ok\n")
        finally:
            os.close(fd)
        probe.unlink()
    except OSError as exc:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        return f"{directory}: {_format_os_error(exc)}"
    return ""


def _nearest_existing_parent(path: Path) -> Path | None:
    parent = path
    while not parent.exists():
        next_parent = parent.parent
        if next_parent == parent:
            return None
        parent = next_parent
    return parent


def _canonical_dir_target(path: Path) -> Path | None:
    if str(path) == "":
        return None
    if not path.is_absolute():
        path = Path.cwd() / path

    suffix: list[str] = []
    probe = path
    while not probe.exists():
        if probe == probe.parent:
            return None
        suffix.insert(0, probe.name)
        probe = probe.parent
    if not probe.is_dir():
        return None
    try:
        resolved = probe.resolve(strict=True)
    except OSError:
        return None
    for part in suffix:
        resolved = resolved / part
    return resolved


def _path_is_or_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _failure_detail(result: CommandResult) -> str:
    detail = _first_line(result.stderr) or _first_line(result.stdout)
    if detail:
        return f"exit {result.returncode}: {detail}"
    return f"exit {result.returncode}: {result.display}"


def _first_line(value: str) -> str:
    for line in value.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _format_os_error(exc: OSError) -> str:
    if exc.errno:
        return f"{exc.strerror or errno.errorcode.get(exc.errno, 'OS error')} (errno {exc.errno})"
    return str(exc)


def _seconds_valid(value: str) -> bool:
    return value.isdigit()
