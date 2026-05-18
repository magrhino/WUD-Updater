"""Subprocess helpers for the Python updater."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


CommandArg = str | os.PathLike[str]


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: Path | None
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def stdout_lines(self) -> list[str]:
        return self.stdout.splitlines()

    @property
    def stderr_lines(self) -> list[str]:
        return self.stderr.splitlines()

    @property
    def display(self) -> str:
        return display_command(self.args)


class CommandError(RuntimeError):
    """Raised when a checked subprocess exits unsuccessfully."""

    def __init__(self, result: CommandResult) -> None:
        super().__init__(
            f"Command failed with exit code {result.returncode}: {result.display}"
        )
        self.result = result


class CommandRunner:
    """Small subprocess wrapper with explicit argv lists and optional base env."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = dict(env) if env is not None else None

    def capture(
        self,
        args: Sequence[CommandArg],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run a command and capture stdout/stderr as text."""

        argv = normalize_args(args)
        cwd_path = Path(cwd) if cwd is not None else None
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd_path) if cwd_path is not None else None,
                env=self._merged_env(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            result = CommandResult(
                args=argv,
                cwd=cwd_path,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except OSError as exc:
            result = _result_from_os_error(argv, cwd_path, exc)
        if check and not result.ok:
            raise CommandError(result)
        return result

    def capture_lines(
        self,
        args: Sequence[CommandArg],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> list[str]:
        """Run a command and return stdout split into lines."""

        return self.capture(args, cwd=cwd, env=env, check=check).stdout_lines

    def run(
        self,
        args: Sequence[CommandArg],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run a command without capturing output."""

        argv = normalize_args(args)
        cwd_path = Path(cwd) if cwd is not None else None
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd_path) if cwd_path is not None else None,
                env=self._merged_env(env),
                stdin=subprocess.DEVNULL,
                check=False,
            )
            result = CommandResult(
                args=argv,
                cwd=cwd_path,
                returncode=completed.returncode,
            )
        except OSError as exc:
            result = _result_from_os_error(argv, cwd_path, exc)
        if check and not result.ok:
            raise CommandError(result)
        return result

    def run_in_pty(
        self,
        args: Sequence[CommandArg],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run a mutating command.

        Keep this method boundary so real PTY handling can be added without
        changing the Docker/Compose call sites.
        """

        return self.run(args, cwd=cwd, env=env, check=check)

    def _merged_env(self, env: Mapping[str, str] | None) -> dict[str, str] | None:
        if self._env is None and env is None:
            return None
        merged = os.environ.copy()
        if self._env is not None:
            merged.update(self._env)
        if env is not None:
            merged.update(env)
        return merged


def normalize_args(args: Sequence[CommandArg]) -> tuple[str, ...]:
    return tuple(os.fspath(arg) for arg in args)


def display_command(args: Sequence[CommandArg]) -> str:
    return shlex.join(normalize_args(args))


def _result_from_os_error(
    args: tuple[str, ...],
    cwd: Path | None,
    exc: OSError,
) -> CommandResult:
    return CommandResult(
        args=args,
        cwd=cwd,
        returncode=_os_error_returncode(exc),
        stderr=str(exc),
    )


def _os_error_returncode(exc: OSError) -> int:
    if isinstance(exc, FileNotFoundError):
        return 127
    if isinstance(exc, PermissionError):
        return 126
    return exc.errno or 1
