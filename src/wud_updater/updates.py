"""Python implementation of the host ``bin/updates`` wrapper."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_UPDATE_MODE = "stop"
DEFAULT_MAX_WAIT = "180"
DEFAULT_LOCK_TIMEOUT = "30"
DEFAULT_TRUENAS_STATUS_TIMEOUT = "5"
_SECONDS_RE = re.compile(r"^[0-9]+$")
_DISPLAY_RANGE_RE = re.compile(r"^([0-9]+)-([0-9]+)$")
_DISPLAY_NUMBER_RE = re.compile(r"^[0-9]+$")
_SHELL_SPACE_RE = re.compile(r"[ \t\n\r\v\f]")
_LEGACY_SHA_SUFFIX_RE = re.compile(r"^(.*\S)\s+sha256=\S+$")


class UpdatesError(RuntimeError):
    """Raised for a user-facing updates wrapper failure."""


@dataclass(frozen=True)
class TodoEntry:
    line_no: int
    raw: str

    @property
    def display_raw(self) -> str:
        match = _LEGACY_SHA_SUFFIX_RE.fullmatch(self.raw)
        if match is None:
            return self.raw
        return match.group(1)


@dataclass(frozen=True)
class UpdatesOptions:
    docker_base: str
    wud_file: str
    log_dir: str
    updater: str
    update_mode: str
    max_wait: str
    dry_run: bool = False
    auto_run: bool = False
    allow_tag_updates: bool = False
    out_uid: str = ""
    out_gid: str = ""
    lock_timeout: str = ""
    use_sudo: bool = True
    truenas_api_uri: str = ""
    truenas_api_key_file: str = ""
    truenas_api_username: str = ""
    truenas_api_insecure: bool = False
    truenas_status_timeout: str = DEFAULT_TRUENAS_STATUS_TIMEOUT


@dataclass(frozen=True)
class TrueNasCallResult:
    ok: bool
    data: object | None = None
    reason: str = ""


@dataclass
class UpdatesFileLock:
    path: str
    timeout_seconds: str
    environ: Mapping[str, str]
    use_sudo: bool = True
    sleep: Callable[[float], None] = time.sleep
    lock_dir: Path = field(init=False)
    held: bool = field(default=False, init=False)
    via_sudo: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.lock_dir = Path(f"{self.path}.lock")

    def acquire(self) -> None:
        timeout = _parse_lock_timeout(self.timeout_seconds or DEFAULT_LOCK_TIMEOUT)
        waited = 0
        lock_parent = self.lock_dir.parent
        self.via_sudo = self.use_sudo and not os.access(lock_parent, os.W_OK)
        if not self.use_sudo and not os.access(lock_parent, os.W_OK):
            raise UpdatesError(
                "Cannot create WUD file lock without sudo: "
                f"{self.lock_dir} (parent is not writable: {lock_parent})"
            )

        while True:
            if self.via_sudo:
                if not self.lock_dir.exists() and self._sudo_mkdir():
                    self.held = True
                    return
            else:
                try:
                    os.mkdir(self.lock_dir)
                    self.held = True
                    return
                except OSError as exc:
                    if self.lock_dir.exists():
                        pass
                    elif self.use_sudo and self._sudo_mkdir():
                        self.via_sudo = True
                        self.held = True
                        return
                    else:
                        raise UpdatesError(
                            "Cannot create WUD file lock without sudo: "
                            f"{self.lock_dir}: {_format_os_error(exc)}"
                        ) from exc

            if waited >= timeout:
                raise UpdatesError(
                    f"Timed out waiting for WUD file lock: {self.lock_dir}"
                )
            self.sleep(1)
            waited += 1

    def release(self) -> None:
        if not self.held:
            return
        if self.via_sudo:
            subprocess.run(
                ["sudo", "rmdir", str(self.lock_dir)],
                env=dict(self.environ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.rmdir(self.lock_dir)
            except OSError:
                pass
        self.held = False

    def _sudo_mkdir(self) -> bool:
        result = subprocess.run(
            ["sudo", "mkdir", str(self.lock_dir)],
            env=dict(self.environ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0


class UpdatesRunner:
    def __init__(
        self,
        options: UpdatesOptions,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.options = options
        self.environ = dict(os.environ if environ is None else environ)
        self.todo_entries: list[TodoEntry] = []
        self.selected_line_spec = ""
        self.remove_line_spec = ""
        self.lock = UpdatesFileLock(
            options.wud_file,
            options.lock_timeout or DEFAULT_LOCK_TIMEOUT,
            self.environ,
            use_sudo=options.use_sudo,
        )

    def run(self) -> int:
        try:
            return self._run()
        except UpdatesError as exc:
            print(exc, file=sys.stderr)
            return 1
        finally:
            self.lock.release()

    def _run(self) -> int:
        print("=== 📦 Docker Updates ===")
        self.todo_entries = self._snapshot_todo_entries()

        if self.todo_entries:
            _display_todo_entries(self.todo_entries, env=self.environ)
        else:
            print("✅ No pending Docker updates!")

        print()
        self._print_system_update_status()
        print()
        self._print_alert_status()

        if not self.todo_entries:
            return 0

        if not os.access(self.options.updater, os.X_OK):
            print()
            if Path(self.options.updater).is_file():
                print(
                    "ℹ️  Updater script found but not executable: "
                    f"{self.options.updater}"
                )
                print(
                    "    Make it executable with: "
                    f"chmod +x \"{self.options.updater}\""
                )
            else:
                print(f"ℹ️  Updater script not found: {self.options.updater}")
            return 0

        if self.options.dry_run:
            print()
            print("👀 Dry-run mode: not running updates.")
            return 0

        print()
        if self.options.auto_run:
            return self._run_updater()

        if not self._choose_update_lines():
            return 0

        self._lock_updater_handoff()
        status = self._run_updater()
        self.lock.release()
        return status

    def _snapshot_todo_entries(self) -> list[TodoEntry]:
        wud_file = Path(self.options.wud_file)
        try:
            file_stat = wud_file.stat()
        except FileNotFoundError:
            return []
        except OSError as exc:
            if not self.options.use_sudo:
                raise UpdatesError(
                    "Cannot stat WUD file without sudo: "
                    f"{wud_file}: {_format_os_error(exc)}"
                ) from exc
        else:
            if file_stat.st_size <= 0:
                return []

        if not self.options.use_sudo and not os.access(wud_file, os.R_OK):
            raise UpdatesError(
                "Cannot read WUD file without sudo: "
                f"{wud_file} (file is not readable)"
            )

        if not self.options.use_sudo and not os.access(wud_file.parent, os.W_OK):
            raise UpdatesError(
                "Cannot create WUD file lock without sudo: "
                f"{wud_file}.lock (parent is not writable: {wud_file.parent})"
            )

        self.lock.acquire()
        try:
            return self._read_todo_entries()
        finally:
            self.lock.release()

    def _read_todo_entries(self) -> list[TodoEntry]:
        wud_file = Path(self.options.wud_file)
        try:
            text = wud_file.read_text(encoding="utf-8")
        except OSError as exc:
            if not self.options.use_sudo:
                raise UpdatesError(
                    "Cannot read WUD file without sudo: "
                    f"{wud_file}: {_format_os_error(exc)}"
                ) from exc
            return _read_todo_entries_with_sudo(self.options.wud_file, self.environ)
        return _parse_todo_entries(text)

    def _print_system_update_status(self) -> None:
        print("=== 🖥️ TrueNAS System Update ===")
        result = _midclt_json("update.status", self.options, self.environ)
        if not result.ok:
            _print_truenas_unreachable("system update check", result.reason)
            return

        status = _truenas_update_status(result.data)
        if status == "UNAVAILABLE":
            print("✅ System up to date")
        elif status == "AVAILABLE":
            version = _truenas_update_version(result.data)
            suffix = f" ({version})" if version else ""
            print(f"⚠️  System update available!{suffix}")
        elif status == "ERROR":
            reason = _truenas_update_error_reason(result.data) or "<no response>"
            print(f"❓ TrueNAS update status error: {reason}")
        else:
            print(f"❓ Unknown status: {status or '<no response>'}")

    def _print_alert_status(self) -> None:
        print("=== 🚨 TrueNAS Alerts ===")
        result = _midclt_json("alert.list", self.options, self.environ)
        if not result.ok:
            _print_truenas_unreachable("alert check", result.reason)
            return

        alerts = _truenas_active_alerts(result.data)
        if alerts is None:
            _print_truenas_unreachable("alert check", "invalid alert response")
            return
        if alerts:
            _print_numbered_lines("\n".join(alerts), self.environ)
        else:
            print("✅ No active alerts")

    def _choose_update_lines(self) -> bool:
        todo_count = len(self.todo_entries)
        self.selected_line_spec = ""
        self.remove_line_spec = ""

        while True:
            choice = _prompt("Run Docker updates? [a=all, s=select, x=exclude, n=skip] ")
            if choice in ("", "n", "N", "no", "NO"):
                print("⏸️  Skipped running updates.")
                return False
            if choice in ("a", "A", "all", "ALL", "y", "Y", "yes", "YES"):
                return True

            if choice in ("s", "S", "select", "SELECT"):
                selected_display = self._read_display_selection(
                    "Enter update numbers/ranges to select: ",
                    todo_count,
                )
                if not selected_display:
                    return False
                unselected_display = _complement_display_numbers(
                    selected_display,
                    todo_count,
                )
                break

            if choice in ("x", "X", "exclude", "EXCLUDE"):
                unselected_display = self._read_display_selection(
                    "Enter update numbers/ranges to exclude: ",
                    todo_count,
                )
                if not unselected_display:
                    return False
                selected_display = _complement_display_numbers(
                    unselected_display,
                    todo_count,
                )
                break

            print("Invalid choice. Enter a, s, x, or n.")

        if not selected_display:
            print("⏸️  No updates selected; skipped running updates.")
            return False

        self.selected_line_spec = self._display_numbers_to_file_line_spec(
            selected_display
        )
        print(f"Selected {len(selected_display)} of {todo_count} pending update(s).")

        if unselected_display:
            remove_reply = _prompt(
                "Remove unselected entries from the WUD file before running? (y/N) "
            )
            if remove_reply in ("y", "Y", "yes", "YES", "Yes"):
                self.remove_line_spec = self._display_numbers_to_file_line_spec(
                    unselected_display
                )

        return True

    def _read_display_selection(self, prompt: str, todo_count: int) -> list[int]:
        while True:
            reply = _prompt(prompt)
            if _SHELL_SPACE_RE.sub("", reply) == "":
                print("⏸️  No selection; skipped running updates.")
                return []
            try:
                return _parse_display_spec(reply, todo_count)
            except ValueError:
                print("Invalid selection. Use numbers/ranges like 1,3-5.")

    def _display_numbers_to_file_line_spec(self, display_numbers: Iterable[int]) -> str:
        line_numbers: list[str] = []
        for display in display_numbers:
            line_numbers.append(str(self.todo_entries[display - 1].line_no))
        return ",".join(_unique_in_order(line_numbers))

    def _lock_updater_handoff(self) -> None:
        if self.selected_line_spec == "" and self.remove_line_spec == "":
            return
        self.lock.acquire()
        if not self._selected_lines_match_snapshot():
            self.lock.release()
            raise UpdatesError(
                "WUD file changed while selecting updates; please rerun updates."
            )

    def _selected_lines_match_snapshot(self) -> bool:
        selected_items = [
            *self.selected_line_spec.split(","),
            *self.remove_line_spec.split(","),
        ]
        wanted = {
            int(item)
            for item in selected_items
            if item
        }
        expected = [
            (entry.line_no, entry.raw)
            for entry in self.todo_entries
            if entry.line_no in wanted
        ]
        current_entries = self._read_todo_entries()
        current = [
            (entry.line_no, entry.raw)
            for entry in current_entries
            if entry.line_no in wanted
        ]
        return expected == current

    def _run_updater(self) -> int:
        updater_args = [
            "--base",
            self.options.docker_base,
            "--file",
            self.options.wud_file,
            "--log-dir",
            self.options.log_dir,
            "--mode",
            self.options.update_mode,
            "--max-wait",
            self.options.max_wait,
        ]
        if self.selected_line_spec:
            updater_args.extend(["--only-lines", self.selected_line_spec])
        if self.remove_line_spec:
            updater_args.extend(["--remove-lines-before-run", self.remove_line_spec])
        if self.options.allow_tag_updates:
            updater_args.append("--allow-tag-updates")
        updater_args.append("--yes")

        updater_env: list[str] = []
        if self.options.out_uid or self.options.out_gid:
            if self.options.out_uid:
                updater_env.append(f"OUT_UID={self.options.out_uid}")
            if self.options.out_gid:
                updater_env.append(f"OUT_GID={self.options.out_gid}")
        if self.options.lock_timeout:
            updater_env.append(f"WUD_LOCK_TIMEOUT={self.options.lock_timeout}")
        if self.lock.held:
            updater_env.append("WUD_LOCK_HELD_BY_PARENT=1")

        updater_environ = dict(self.environ)
        for assignment in updater_env:
            key, value = assignment.split("=", 1)
            updater_environ[key] = value

        if self.options.use_sudo and updater_env:
            print(
                "🚀 Running Docker updates via: sudo env "
                f"{' '.join(updater_env)} \"{self.options.updater}\" "
                f"{' '.join(updater_args)}"
            )
            command = ["sudo", "env", *updater_env, self.options.updater, *updater_args]
            command_env = self.environ
        elif self.options.use_sudo:
            print(
                "🚀 Running Docker updates via: sudo "
                f"\"{self.options.updater}\" {' '.join(updater_args)}"
            )
            command = ["sudo", self.options.updater, *updater_args]
            command_env = self.environ
        elif updater_env:
            print(
                "🚀 Running Docker updates via: env "
                f"{' '.join(updater_env)} \"{self.options.updater}\" "
                f"{' '.join(updater_args)}"
            )
            command = [self.options.updater, *updater_args]
            command_env = updater_environ
        else:
            print(
                "🚀 Running Docker updates via: "
                f"\"{self.options.updater}\" {' '.join(updater_args)}"
            )
            command = [self.options.updater, *updater_args]
            command_env = updater_environ

        try:
            result = subprocess.run(command, env=command_env, check=False)
            returncode = result.returncode
        except OSError as exc:
            print(exc, file=sys.stderr)
            returncode = _os_error_returncode(exc)

        print()
        if returncode == 0:
            print(f"✅ Update script completed (exit {returncode}).")
        else:
            print(f"❌ Update script failed (exit {returncode}).")
        return returncode


def run_updates_from_namespace(
    args: argparse.Namespace,
    *,
    repo_root: str | Path,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = load_configured_environ(environ)
    try:
        options = options_from_namespace(args, repo_root=repo_root, environ=env)
    except UpdatesError as exc:
        print(exc, file=sys.stderr)
        return 1
    return UpdatesRunner(options, environ=env).run()


def options_from_namespace(
    args: argparse.Namespace,
    *,
    repo_root: str | Path,
    environ: Mapping[str, str],
) -> UpdatesOptions:
    home = environ.get("HOME") or str(Path.home())
    docker_base = _arg_or_default(
        getattr(args, "base", None),
        environ.get("DOCKER_BASE") or f"{home}/docker",
    )

    env_wud_file = environ.get("WUD_OUT_FILE") or ""
    if getattr(args, "file", None) is not None:
        wud_file = str(getattr(args, "file"))
    elif env_wud_file:
        wud_file = env_wud_file
    else:
        wud_file = f"{docker_base}/wud/out/images.todo"

    log_dir = _arg_or_default(
        getattr(args, "log_dir", None),
        environ.get("WUD_LOG_DIR") or "./logs",
    )
    update_mode = _arg_or_default(
        getattr(args, "mode", None),
        environ.get("WUD_UPDATE_MODE") or DEFAULT_UPDATE_MODE,
    )
    max_wait = _arg_or_default(
        getattr(args, "max_wait", None),
        environ.get("WUD_MAX_WAIT") or DEFAULT_MAX_WAIT,
    )
    out_gid = environ.get("OUT_GID") or environ.get("OUT_GUID") or ""

    return UpdatesOptions(
        docker_base=docker_base,
        wud_file=wud_file,
        log_dir=log_dir,
        updater=environ.get("WUD_UPDATER")
        or str(Path(repo_root) / "bin" / "docker-update-from-wud"),
        update_mode=update_mode,
        max_wait=max_wait,
        dry_run=bool(getattr(args, "dry_run", False)),
        auto_run=bool(getattr(args, "yes", False)),
        allow_tag_updates=bool(getattr(args, "allow_tag_updates", False)),
        out_uid=environ.get("OUT_UID") or "",
        out_gid=out_gid,
        lock_timeout=environ.get("WUD_LOCK_TIMEOUT") or "",
        use_sudo=_resolve_use_sudo(
            environ.get("WUD_UPDATER_USE_SUDO"),
            no_updater_sudo=bool(getattr(args, "no_updater_sudo", False)),
        ),
        truenas_api_uri=environ.get("TRUENAS_API_URI") or "",
        truenas_api_key_file=environ.get("TRUENAS_API_KEY_FILE") or "",
        truenas_api_username=environ.get("TRUENAS_API_USERNAME") or "",
        truenas_api_insecure=_is_enabled(environ.get("TRUENAS_API_INSECURE")),
        truenas_status_timeout=(
            environ.get("TRUENAS_STATUS_TIMEOUT") or DEFAULT_TRUENAS_STATUS_TIMEOUT
        ),
    )


def load_configured_environ(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    home = env.get("HOME") or str(Path.home())
    config_file = Path(
        env.get("WUD_UPDATER_CONFIG")
        or str(Path(home) / ".config" / "wud-updater" / "env")
    )
    if not config_file.is_file() or not os.access(config_file, os.R_OK):
        return env

    try:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'set -a; . "$1"; env; exit 0',
                "wud-updater-config",
                str(config_file),
            ],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return env

    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def _parse_todo_entries(text: str) -> list[TodoEntry]:
    entries: list[TodoEntry] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        trimmed = raw.lstrip()
        if trimmed == "" or trimmed.startswith("#"):
            continue
        entries.append(TodoEntry(line_no=line_no, raw=raw))
    return entries


def _read_todo_entries_with_sudo(
    wud_file: str,
    environ: Mapping[str, str],
) -> list[TodoEntry]:
    awk_script = (
        "{ trimmed = $0; sub(/^[[:space:]]+/, \"\", trimmed); "
        'if (trimmed != "" && trimmed !~ /^#/) { print NR "\\t" $0 } }'
    )
    try:
        result = subprocess.run(
            ["sudo", "awk", awk_script, wud_file],
            env=dict(environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise UpdatesError(
            f"Unable to read WUD file with sudo: {wud_file}: {_format_os_error(exc)}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise UpdatesError(f"Unable to read WUD file with sudo: {wud_file}{suffix}")

    entries: list[TodoEntry] = []
    for line in result.stdout.splitlines():
        line_no, sep, raw = line.partition("\t")
        if not sep:
            continue
        try:
            entries.append(TodoEntry(line_no=int(line_no, 10), raw=raw))
        except ValueError:
            continue
    return entries


def _display_todo_entries(
    entries: Sequence[TodoEntry],
    *,
    env: Mapping[str, str],
) -> None:
    display = "".join(
        f"{display_no}\t{entry.display_raw}\n"
        for display_no, entry in enumerate(entries, start=1)
    )
    try:
        result = subprocess.run(
            ["column", "-t"],
            input=display,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        print(display, end="")
        return
    print(result.stdout, end="")


def _parse_display_spec(spec: str, max_value: int) -> list[int]:
    cleaned = _SHELL_SPACE_RE.sub("", spec)
    if cleaned == "":
        raise ValueError("empty selection")

    result: list[int] = []
    for part in cleaned.split(","):
        if part == "":
            raise ValueError("empty selection part")
        range_match = _DISPLAY_RANGE_RE.fullmatch(part)
        if range_match is not None:
            start = int(range_match.group(1), 10)
            end = int(range_match.group(2), 10)
            if start < 1 or end < start or end > max_value:
                raise ValueError("invalid range")
            for value in range(start, end + 1):
                if value not in result:
                    result.append(value)
            continue

        if _DISPLAY_NUMBER_RE.fullmatch(part) is not None:
            value = int(part, 10)
            if value < 1 or value > max_value:
                raise ValueError("invalid number")
            if value not in result:
                result.append(value)
            continue

        raise ValueError("invalid selection")

    if not result:
        raise ValueError("empty selection")
    return result


def _complement_display_numbers(selected: Sequence[int], max_value: int) -> list[int]:
    selected_set = set(selected)
    return [value for value in range(1, max_value + 1) if value not in selected_set]


def _unique_in_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _prompt(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _parse_lock_timeout(value: str) -> int:
    return _parse_seconds(value, "WUD_LOCK_TIMEOUT")


def _parse_seconds(value: str, label: str) -> int:
    if _SECONDS_RE.fullmatch(str(value)) is None:
        raise UpdatesError(f"{label} must be an integer number of seconds")
    return int(str(value), 10)


def _resolve_use_sudo(
    value: str | None,
    *,
    no_updater_sudo: bool,
) -> bool:
    if no_updater_sudo:
        return False
    if value is None or value == "":
        return True

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise UpdatesError(
        "WUD_UPDATER_USE_SUDO must be one of 1, 0, true, false, yes, no, on, or off"
    )


def _format_os_error(exc: OSError) -> str:
    return exc.strerror or str(exc)


def _has_command(command: str, environ: Mapping[str, str]) -> bool:
    return shutil.which(command, path=environ.get("PATH")) is not None


def _is_enabled(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _midclt_json(
    method: str,
    options: UpdatesOptions,
    environ: Mapping[str, str],
) -> TrueNasCallResult:
    if not _has_command("midclt", environ):
        return TrueNasCallResult(ok=False, reason="midclt not available")
    try:
        timeout = _parse_seconds(
            options.truenas_status_timeout or DEFAULT_TRUENAS_STATUS_TIMEOUT,
            "TRUENAS_STATUS_TIMEOUT",
        )
    except UpdatesError as exc:
        return TrueNasCallResult(ok=False, reason=str(exc))

    command = _midclt_command(method, options)
    try:
        result = subprocess.run(
            command,
            env=dict(environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TrueNasCallResult(ok=False, reason="midclt timed out")
    except OSError as exc:
        return TrueNasCallResult(
            ok=False,
            reason=f"midclt failed: {_format_os_error(exc)}",
        )

    if result.returncode != 0:
        return TrueNasCallResult(
            ok=False,
            reason=f"midclt exited {result.returncode}",
        )

    stdout = result.stdout.strip()
    if stdout == "":
        return TrueNasCallResult(ok=False, reason="empty midclt response")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return TrueNasCallResult(ok=False, reason="invalid JSON response")

    return TrueNasCallResult(ok=True, data=data)


def _midclt_command(method: str, options: UpdatesOptions) -> list[str]:
    command = ["midclt"]
    if options.truenas_api_uri:
        command.extend(["--uri", options.truenas_api_uri])
    if options.truenas_api_username:
        command.extend(["-U", options.truenas_api_username])
    if options.truenas_api_key_file:
        command.extend(["-K", options.truenas_api_key_file])
    if options.truenas_api_insecure:
        command.append("--insecure")
    command.extend(["call", method])
    return command


def _print_truenas_unreachable(check: str, reason: str = "") -> None:
    suffix = f" ({reason})" if reason else ""
    print(f"ℹ️  TrueNAS not reachable; skipping {check}.{suffix}")


def _truenas_update_status(data: object | None) -> str:
    if not isinstance(data, dict):
        return ""

    legacy_status = data.get("status")
    if isinstance(legacy_status, str):
        return legacy_status

    code = data.get("code")
    if code == "ERROR":
        return "ERROR"
    if code != "NORMAL":
        return str(code or "")

    status = data.get("status")
    if not isinstance(status, dict):
        return ""
    new_version = status.get("new_version")
    if isinstance(new_version, dict) and new_version:
        return "AVAILABLE"
    if new_version is None:
        return "UNAVAILABLE"
    return ""


def _truenas_update_version(data: object | None) -> str:
    if not isinstance(data, dict):
        return ""
    status = data.get("status")
    if not isinstance(status, dict):
        return ""
    new_version = status.get("new_version")
    if not isinstance(new_version, dict):
        return ""
    version = new_version.get("version")
    return version if isinstance(version, str) else ""


def _truenas_update_error_reason(data: object | None) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if not isinstance(error, dict):
        return ""
    reason = error.get("reason")
    return reason if isinstance(reason, str) else ""


def _truenas_active_alerts(data: object | None) -> list[str] | None:
    if not isinstance(data, list):
        return None

    alerts: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("dismissed") is True:
            continue
        formatted = item.get("formatted")
        if isinstance(formatted, str) and formatted:
            alerts.append(formatted)
    return alerts


def _print_numbered_lines(value: str, environ: Mapping[str, str]) -> None:
    text = "\n".join(value.splitlines()) + "\n"
    try:
        result = subprocess.run(
            ["nl", "-ba"],
            input=text,
            env=dict(environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        for index, line in enumerate(value.splitlines(), start=1):
            print(f"{index}\t{line}")
        return
    print(result.stdout, end="")


def _arg_or_default(value: object, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _os_error_returncode(exc: OSError) -> int:
    if isinstance(exc, FileNotFoundError):
        return 127
    if isinstance(exc, PermissionError):
        return 126
    return exc.errno or 1
