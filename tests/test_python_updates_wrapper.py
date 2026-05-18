from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PythonUpdatesWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-python-updates.")
        self.root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.wud_file = self.root / "images.todo"
        self.updater = self.root / "updater"
        self.sudo_log = self.root / "sudo.log"
        self.updater_log = self.root / "updater.log"
        self._write_fakes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_updates(
        self,
        *args: str,
        input_text: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command: list[str] | None = None,
        include_file: bool = True,
        include_pythonpath: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env_defaults = {
            "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
            "WUD_UPDATER": str(self.updater),
            "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
            "FAKE_SUDO_LOG": str(self.sudo_log),
            "FAKE_UPDATER_LOG": str(self.updater_log),
            "FAKE_WUD_FILE": str(self.wud_file),
        }
        if include_pythonpath:
            env_defaults["PYTHONPATH"] = str(self.repo_root / "src")
        else:
            env.pop("PYTHONPATH", None)
        env.update(env_defaults)
        if env_overrides is not None:
            env.update(env_overrides)

        if command is None:
            command = [sys.executable, "-m", "wud_updater.cli", "updates"]
        if include_file:
            command = [*command, "--file", str(self.wud_file)]
        command = [*command, *args]

        return subprocess.run(
            command,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_dry_run_does_not_invoke_updater(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())
        self.assertIn("Dry-run mode: not running updates", result.stdout)

    def test_yes_invokes_configured_updater_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--allow-tag-updates",
            "--base",
            str(self.root / "docker"),
            env_overrides={
                "OUT_UID": "1000",
                "OUT_GUID": "1001",
                "WUD_LOCK_TIMEOUT": "0",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "env OUT_UID=1000 OUT_GID=1001 WUD_LOCK_TIMEOUT=0 "
            f"{self.updater} --base {self.root / 'docker'} --file {self.wud_file} "
            "--mode stop --max-wait 180 --allow-tag-updates --yes",
            sudo_log,
        )
        self.assertIn("OUT_UID=1000 OUT_GID=1001", updater_log)
        self.assertIn("--allow-tag-updates --yes", updater_log)

    def test_yes_passes_legacy_bash_flag_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--base",
            str(self.root / "docker"),
            env_overrides={"WUD_UPDATER_LEGACY_BASH": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "env WUD_UPDATER_LEGACY_BASH=1 "
            f"{self.updater} --base {self.root / 'docker'} --file {self.wud_file} "
            "--mode stop --max-wait 180 --yes",
            sudo_log,
        )
        self.assertIn("WUD_UPDATER_LEGACY_BASH=1", updater_log)

    def test_no_updater_sudo_flag_invokes_updater_directly(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--no-updater-sudo",
            "--base",
            str(self.root / "docker"),
            env_overrides={
                "OUT_UID": "1000",
                "OUT_GID": "1001",
                "WUD_LOCK_TIMEOUT": "0",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("OUT_UID=1000 OUT_GID=1001 WUD_LOCK_TIMEOUT=0", updater_log)
        self.assertIn(f"--base {self.root / 'docker'} --file {self.wud_file}", updater_log)
        self.assertIn("Running Docker updates via: env OUT_UID=1000", result.stdout)

    def test_no_updater_sudo_env_invokes_updater_directly(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            env_overrides={"WUD_UPDATER_USE_SUDO": "0"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertIn("--yes", self.updater_log.read_text(encoding="utf-8"))

    def test_no_updater_sudo_fails_when_wud_file_is_unreadable(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.wud_file.chmod(0)

        try:
            result = self.run_updates("--dry-run", "--no-updater-sudo")
        finally:
            self.wud_file.chmod(0o600)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot read WUD file without sudo", result.stderr)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())

    def test_interactive_select_remove_passes_original_line_numbers(self) -> None:
        self.wud_file.write_text(
            "# comment\nrepo/app:one\n\nrepo/app:two\nrepo/app:three\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1,3\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 2,5 --remove-lines-before-run 4 --yes", sudo_log)

    def test_interactive_holds_wud_lock_for_updater_handoff(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_UPDATER_ASSERT_LOCK": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "WUD_LOCK_HELD_BY_PARENT=1",
            self.updater_log.read_text(encoding="utf-8"),
        )
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())

    def test_interactive_select_aborts_when_snapshot_lines_change(self) -> None:
        self.wud_file.write_text("repo/app:one\nrepo/app:two\n", encoding="utf-8")
        hook = self.root / "change-wud-file"
        hook.write_text(
            f"#!/usr/bin/env bash\nprintf 'repo/app:changed\\nrepo/app:two\\n' > {self.wud_file}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_COLUMN_HOOK": str(hook)},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "WUD file changed while selecting updates; please rerun updates.",
            result.stderr,
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())

    def test_config_file_supplies_defaults(self) -> None:
        home = self.root / "home"
        docker_base = home / "from-config"
        docker_base.mkdir(parents=True)
        config_wud_file = docker_base / "images.todo"
        config_wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        config_file = home / ".config" / "wud-updater" / "env"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "\n".join(
                [
                    'DOCKER_BASE="$HOME/from-config"',
                    'WUD_OUT_FILE="$DOCKER_BASE/images.todo"',
                    'WUD_UPDATE_MODE="live"',
                    'WUD_MAX_WAIT="7"',
                    f'WUD_UPDATER="{self.updater}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--yes",
            include_file=False,
            env_overrides={
                "HOME": str(home),
                "WUD_UPDATER_CONFIG": str(config_file),
                "FAKE_WUD_FILE": str(config_wud_file),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            f"{self.updater} --base {docker_base} --file {config_wud_file} "
            "--mode live --max-wait 7 --yes",
            self.sudo_log.read_text(encoding="utf-8"),
        )

    def test_truenas_checks_use_midclt_and_jq_when_available(self) -> None:
        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("⚠️  System update available!", result.stdout)
        self.assertIn("Pool needs attention", result.stdout)

    def test_bin_updates_opt_in_dispatches_python_wrapper(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--dry-run",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={
                "WUD_UPDATER_PYTHON": "1",
                "PYTHON_BIN": sys.executable,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_opt_in_resolves_installed_symlink(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        installed_bin = self.root / "installed-bin"
        installed_bin.mkdir()
        installed_updates = installed_bin / "updates"
        installed_updates.symlink_to(self.repo_root / "bin" / "updates")

        result = self.run_updates(
            "--dry-run",
            command=[str(installed_updates)],
            env_overrides={
                "WUD_UPDATER_PYTHON": "1",
                "PYTHON_BIN": sys.executable,
            },
            include_pythonpath=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_config_file_can_enable_python_wrapper(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        config_file = self.root / "host-env"
        config_file.write_text(
            "\n".join(
                [
                    "WUD_UPDATER_PYTHON=1",
                    f'PYTHON_BIN="{sys.executable}"',
                    "WUD_UPDATER_USE_SUDO=0",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--dry-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"WUD_UPDATER_CONFIG": str(config_file)},
            include_pythonpath=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_no_updater_sudo_stays_python_only(self) -> None:
        result = self.run_updates(
            "--dry-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown argument: --no-updater-sudo", result.stderr)

    def _write_fakes(self) -> None:
        self._write_executable(
            self.fake_bin / "column",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_COLUMN_LOCK_LOG:-}" ]]; then
  if [[ -d "${FAKE_WUD_FILE:?FAKE_WUD_FILE is required}.lock" ]]; then
    printf 'present\\n' >> "$FAKE_COLUMN_LOCK_LOG"
  else
    printf 'missing\\n' >> "$FAKE_COLUMN_LOCK_LOG"
  fi
fi
cat
if [[ -n "${FAKE_COLUMN_HOOK:-}" ]]; then
  "$FAKE_COLUMN_HOOK"
fi
""",
        )
        self._write_executable(
            self.fake_bin / "sudo",
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${FAKE_SUDO_LOG:?FAKE_SUDO_LOG is required}"
"$@"
""",
        )
        self._write_executable(
            self.fake_bin / "midclt",
            """#!/usr/bin/env bash
case "$*" in
  "call update.check_available")
    printf '{"status":"AVAILABLE"}\\n'
    ;;
  "call alert.list")
    printf '[{"dismissed":false,"formatted":"Pool needs attention"}]\\n'
    ;;
esac
""",
        )
        self._write_executable(
            self.fake_bin / "jq",
            """#!/usr/bin/env bash
filter="${*: -1}"
if [[ "$filter" == ".status" ]]; then
  printf 'AVAILABLE\\n'
else
  printf 'Pool needs attention\\n'
fi
""",
        )
        self._write_executable(
            self.updater,
            """#!/usr/bin/env bash
args=("$@")
wud_file=""
while (($#)); do
  case "$1" in
    --file)
      wud_file="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'OUT_UID=%s OUT_GID=%s WUD_LOCK_TIMEOUT=%s WUD_LOCK_HELD_BY_PARENT=%s WUD_UPDATER_LEGACY_BASH=%s\\n' "${OUT_UID:-}" "${OUT_GID:-}" "${WUD_LOCK_TIMEOUT:-}" "${WUD_LOCK_HELD_BY_PARENT:-}" "${WUD_UPDATER_LEGACY_BASH:-}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
if [[ "${FAKE_UPDATER_ASSERT_LOCK:-}" = "1" ]]; then
  if [[ "${WUD_LOCK_HELD_BY_PARENT:-}" != "1" ]]; then
    printf 'missing WUD_LOCK_HELD_BY_PARENT\\n' >> "$FAKE_UPDATER_LOG"
    exit 21
  fi
  if [[ -z "$wud_file" || ! -d "${wud_file}.lock" ]]; then
    printf 'missing WUD file lock\\n' >> "$FAKE_UPDATER_LOG"
    exit 22
  fi
fi
printf '%s\\n' "${args[*]}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
exit 0
""",
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
