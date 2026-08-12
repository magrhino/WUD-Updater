from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class UpdatesWrapperTestCase(unittest.TestCase):
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
        self.docker_log = self.root / "docker.log"
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
            "WUDUP_UPDATER": str(self.updater),
            "WUDUP_CONFIG": str(self.root / "missing-env"),
            "FAKE_SUDO_LOG": str(self.sudo_log),
            "FAKE_UPDATER_LOG": str(self.updater_log),
            "FAKE_WUD_FILE": str(self.wud_file),
            "WUDUP_BANNER": "false",
            "WUDUP_RELEASE_CHECK": "false",
        }
        if include_pythonpath:
            env_defaults["PYTHONPATH"] = str(self.repo_root / "src")
        else:
            env.pop("PYTHONPATH", None)
        env.update(env_defaults)
        if env_overrides is not None:
            env.update(env_overrides)

        if command is None:
            command = [sys.executable, "-m", "wudup.cli", "updates"]
        if include_file:
            command = [*command, "--file", str(self.wud_file)]
        command = [*command, *args]

        return subprocess.run(
            command,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
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
            self.fake_bin / "docker",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_DOCKER_LOG:-}" ]]; then
  printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
fi
if [[ "$1" == "pull" ]]; then
  exit "${FAKE_DOCKER_PULL_RETURN:-0}"
fi
if [[ "$1 $2" == "container inspect" ]]; then
  if [[ "${FAKE_DOCKER_INSPECT_RETURN:-0}" != "0" ]]; then
    exit "$FAKE_DOCKER_INSPECT_RETURN"
  fi
  out_dir="$(dirname "${FAKE_WUD_FILE:?FAKE_WUD_FILE is required}")"
  printf '[{"Config":{"Image":"wudup:test"},"Mounts":[{"Type":"volume","Name":"wud-out","Destination":"%s"}]}]\\n' "$out_dir"
  exit 0
fi
if [[ "$1" == "run" ]]; then
  if [[ "${FAKE_DOCKER_RUN_RETURN:-0}" != "0" ]]; then
    exit "$FAKE_DOCKER_RUN_RETURN"
  fi
  if [[ "${FAKE_DOCKER_STATUS_RESPONSE:-}" == "invalid" ]]; then
    printf 'not json\\n'
    exit 0
  fi
  case "${FAKE_TRUENAS_UPDATE_STATUS:-available}" in
    unavailable)
      update_data='{"status":"UNAVAILABLE"}'
      ;;
    error)
      update_data='{"status":"ERROR","reason":"update train failed"}'
      ;;
    *)
      update_data='{"status":"AVAILABLE","version":"25.10.1"}'
      ;;
  esac
  case "${FAKE_TRUENAS_ALERT_STATUS:-active}" in
    none)
      alert_data='[]'
      ;;
    *)
      alert_data='["Pool needs attention"]'
      ;;
  esac
  printf '{"update":{"ok":true,"data":%s,"reason":""},"alerts":{"ok":true,"data":%s,"reason":""}}\\n' "$update_data" "$alert_data"
  exit 0
fi
exit 1
""",
        )
        self._write_executable(
            self.fake_bin / "midclt",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_MIDCLT_LOG:-}" ]]; then
  printf '%s\\n' "$*" >> "$FAKE_MIDCLT_LOG"
fi
if [[ "${FAKE_MIDCLT_RETURN:-0}" != "0" ]]; then
  exit "$FAKE_MIDCLT_RETURN"
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "empty" ]]; then
  exit 0
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "invalid" ]]; then
  printf 'not json\\n'
  exit 0
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "timeout" ]]; then
  sleep 1
fi
case "$*" in
  *"call update.status")
    case "${FAKE_TRUENAS_UPDATE_STATUS:-available}" in
      unavailable)
        printf '{"code":"NORMAL","status":{"new_version":null},"error":null}\\n'
        ;;
      error)
        printf '{"code":"ERROR","status":null,"error":{"reason":"update train failed"}}\\n'
        ;;
      *)
        printf '{"code":"NORMAL","status":{"new_version":{"version":"25.10.1"}},"error":null,"private":"private-update-detail"}\\n'
        ;;
    esac
    ;;
  *"call alert.list")
    case "${FAKE_TRUENAS_ALERT_STATUS:-active}" in
      none)
        printf '[]\\n'
        ;;
      *)
        printf '[{"dismissed":false,"formatted":"Pool needs attention","args":{"private":"private-alert-arg"},"mail":{"to":"private@example.test"}},{"dismissed":true,"formatted":"Dismissed alert"}]\\n'
        ;;
    esac
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
only_lines=""
while (($#)); do
  case "$1" in
    --file)
      wud_file="${2:-}"
      shift 2
      ;;
    --only-lines)
      only_lines="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'OUT_UID=%s OUT_GID=%s WUD_LOCK_TIMEOUT=%s WUD_LOCK_HELD_BY_PARENT=%s WUD_DB_PATH=%s HOST_DOCKER_BASE=%s WUD_COMPOSE_IGNORE_PATHS=%s\\n' "${OUT_UID:-}" "${OUT_GID:-}" "${WUD_LOCK_TIMEOUT:-}" "${WUD_LOCK_HELD_BY_PARENT:-}" "${WUD_DB_PATH:-}" "${HOST_DOCKER_BASE:-}" "${WUD_COMPOSE_IGNORE_PATHS:-}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
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
if [[ -n "$wud_file" && "${FAKE_UPDATER_LOG_WUD_CONTENT:-}" = "1" ]]; then
  printf 'WUD_CONTENT=%s\\n' "$(tr '\\n' '|' < "$wud_file")" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
fi
if [[ -n "$wud_file" && -n "$only_lines" && "${FAKE_UPDATER_REMOVE_ONLY_LINES:-}" = "1" ]]; then
  tmp="${wud_file}.fake-update.$$"
  awk -v spec="$only_lines" 'BEGIN {
    split(spec, items, ",")
    for (idx in items) {
      if (items[idx] != "") {
        remove[items[idx]] = 1
      }
    }
  }
  !(FNR in remove)' "$wud_file" > "$tmp"
  mv "$tmp" "$wud_file"
fi
printf '%s\\n' "${args[*]}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
exit 0
""",
        )
    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


def _updater_arg_lines(log: str) -> list[str]:
    return [line for line in log.splitlines() if line.startswith("--base ")]
