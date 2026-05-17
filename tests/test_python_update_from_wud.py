from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater.command import CommandRunner
from wud_updater.updater import UpdaterOptions, UpdateFromWudRunner


class PythonUpdateFromWudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-python-update.")
        self.root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.base = self.root / "base"
        self.wud_file = self.root / "images.todo"
        self.log_dir = self.root / "logs"
        self.fake_root = self.root / "fake"
        for path in (
            self.base,
            self.log_dir,
            self.fake_root / "images",
            self.fake_root / "stacks",
            self.fake_root / "containers",
        ):
            path.mkdir(parents=True, exist_ok=True)
        (self.fake_root / "containers.tsv").write_text("", encoding="utf-8")
        (self.fake_root / "calls.log").write_text("", encoding="utf-8")

        self.env = os.environ.copy()
        self.env["FAKE_DOCKER_ROOT"] = str(self.fake_root)
        self.env["PATH"] = f"{self.repo_root / 'tests' / 'fakes'}:{self.env['PATH']}"
        self.env["PYTHONPATH"] = str(self.repo_root / "src")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_python(self, *args: str, wrapper: bool = False) -> subprocess.CompletedProcess[str]:
        common = [
            "--base",
            str(self.base),
            "--file",
            str(self.wud_file),
            "--log-dir",
            str(self.log_dir),
            "--max-wait",
            "0",
            "--no-color",
            *args,
        ]
        env = dict(self.env)
        if wrapper:
            env["WUD_UPDATER_PYTHON"] = "1"
            env["PYTHON_BIN"] = sys.executable
            command = [str(self.repo_root / "bin" / "docker-update-from-wud"), *common]
        else:
            command = [
                sys.executable,
                "-m",
                "wud_updater.cli",
                "update-from-wud",
                *common,
            ]
        return subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def make_stack(self, stack_id: str, services: list[tuple[str, str, str | None]]) -> Path:
        directory = self.base / stack_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".fake-docker-id").write_text(f"{stack_id}\n", encoding="utf-8")
        stack_state = self.fake_root / "stacks" / stack_id
        stack_state.mkdir(parents=True, exist_ok=True)
        cids: list[str] = []

        compose_lines = ["services:\n"]
        service_rows: list[str] = []
        image_rows: list[str] = []
        for service, image, cid in services:
            compose_lines.extend([f"  {service}:\n", f"    image: {image}\n"])
            service_rows.append(f"{service}\n")
            image_rows.append(f"{image}\n")
            with (stack_state / "service-images.tsv").open("a", encoding="utf-8") as file:
                file.write(f"{service}\t{image}\n")
            if cid is not None:
                cids.append(cid)
                (stack_state / f"cids-{service}.txt").write_text(
                    f"{cid}\n",
                    encoding="utf-8",
                )
                (self.fake_root / "containers" / f"{cid}.summary").write_text(
                    f"/{cid}|running|healthy|0|0\n",
                    encoding="utf-8",
                )

        (directory / "docker-compose.yml").write_text("".join(compose_lines), encoding="utf-8")
        (stack_state / "services.txt").write_text("".join(service_rows), encoding="utf-8")
        (stack_state / "images.txt").write_text("".join(image_rows), encoding="utf-8")
        (stack_state / "cids.txt").write_text(
            "".join(f"{cid}\n" for cid in cids),
            encoding="utf-8",
        )
        return directory

    def set_image_state(self, image: str, image_id: str, digest: str = "") -> None:
        safe = safe_name(image)
        (self.fake_root / "images" / f"{safe}.id").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )
        (self.fake_root / "images" / f"{safe}.digests").write_text(
            f"{image}@{digest}\n" if digest else "",
            encoding="utf-8",
        )

    def set_image_after_pull(self, image: str, image_id: str, digest: str = "") -> None:
        safe = safe_name(image)
        (self.fake_root / "images" / f"{safe}.after_id").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )
        (self.fake_root / "images" / f"{safe}.after_digests").write_text(
            f"{image}@{digest}\n" if digest else "",
            encoding="utf-8",
        )

    def calls(self) -> str:
        return (self.fake_root / "calls.log").read_text(encoding="utf-8")

    def test_wrapper_opt_in_dry_run_plans_without_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")

        result = self.run_python("--dry-run", wrapper=True)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("line 1: repo/app:latest", result.stdout)
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")

    def test_python_updates_matched_service_and_cleans_wud_line(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack(
            "stack",
            [
                ("app", "repo/app:latest", "cid-app"),
                ("db", "repo/db:latest", "cid-db"),
            ],
        )
        self.set_image_state("repo/app:latest", "old-app", "sha256:old-app")
        self.set_image_after_pull("repo/app:latest", "new-app", "sha256:new-app")
        self.set_image_state("repo/db:latest", "old-db", "sha256:old-db")
        self.set_image_after_pull("repo/db:latest", "new-db", "sha256:new-db")

        result = self.run_python("--yes", "--mode", "stop")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")
        self.assertRegex(calls, r"compose -f docker-compose.yml stop app")
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull db")

    def test_digest_mismatch_restores_line_and_skips_recreate(self) -> None:
        self.wud_file.write_text("repo/app@sha256:good\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:bad")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app@sha256:good\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")

    def test_tag_backup_failure_restores_line_without_traceback(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater._backup_compose",
                side_effect=OSError("backup denied"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("Could not back up compose file", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_tag_update_failure_rolls_back_and_writes_incident_log(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            "compose_file=\"${2:?compose file is required}\"\n"
            "if grep -q 'repo/app:2.0' \"$compose_file\"; then\n"
            "  printf '/cid-app|running|unhealthy|1|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "else\n"
            "  printf '/cid-app|running|healthy|0|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        incidents = sorted(stack_dir.glob("error-2.0-*.logs"))
        self.assertTrue(incidents)
        incident = incidents[-1].read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", incident)
        self.assertIn("repo/app:1.0 -> repo/app:2.0", incident)
        self.assertIn("health=unhealthy", incident)
        self.assertIn("new tag failed health check", incident)
        self.assertIn("manual_review_required=no", incident)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    unittest.main()
