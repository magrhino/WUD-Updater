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
from wud_updater.compose import ComposeStack, ServiceImage
from wud_updater.file_ops import OwnerConfig
from wud_updater.updater import (
    ComposeTagRewriteError,
    TagUpdate,
    UpdaterOptions,
    UpdateFromWudRunner,
    apply_compose_tag_updates,
    prepare_log_file,
)


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
            self.fake_root / "manifests",
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
        self.env["WUD_UPDATER_BANNER"] = "0"

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

    def set_manifest_failure(self, image: str, stderr: str) -> None:
        safe = safe_name(image)
        (self.fake_root / "manifests" / f"{safe}.fail").write_text(
            "",
            encoding="utf-8",
        )
        (self.fake_root / "manifests" / f"{safe}.stderr").write_text(
            stderr,
            encoding="utf-8",
        )

    def calls(self) -> str:
        return (self.fake_root / "calls.log").read_text(encoding="utf-8")

    def latest_error_report(self) -> Path:
        reports = sorted(self.log_dir.glob("update-from-wud-v2-*.errors.log"))
        self.assertTrue(reports, "expected updater error report")
        return reports[-1]

    def test_wrapper_default_dry_run_plans_without_mutation(self) -> None:
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

    def test_up_wait_failure_writes_error_report_with_command_output(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", None)])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "up_stdout").write_text("compose stdout before failure\n", encoding="utf-8")
        (stack_state / "up_stderr").write_text("network create failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("error report:", result.stderr)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=up", report)
        self.assertIn("reason=up-or-health-failed", report)
        self.assertIn("wud_entries_restored=yes", report)
        self.assertIn("exit_code=19", report)
        self.assertIn("--wait --wait-timeout 0 app", report)
        self.assertIn("compose stdout before failure", report)
        self.assertIn("network create failed", report)
        self.assertIn("health: docker compose ps -q returned no containers", report)

    def test_pull_failure_writes_error_report(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "pull_fail").write_text("", encoding="utf-8")
        (stack_state / "pull_stderr").write_text("manifest fetch failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=pull", report)
        self.assertIn("reason=pull-failed", report)
        self.assertIn("exit_code=17", report)
        self.assertIn("manifest fetch failed", report)
        self.assertIn("health: container=cid-app status=running health=healthy", report)

    def test_stop_failure_reports_failed_phase_after_recovery(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "stop_fail").write_text("", encoding="utf-8")
        (stack_state / "stop_stderr").write_text("container stop failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=stop", report)
        self.assertIn("reason=down-failed", report)
        self.assertIn("exit_code=18", report)
        self.assertIn("container stop failed", report)
        self.assertIn("Compose up recovery succeeded", report)

    def test_tag_update_stack_recreate_reports_recovery_up_failure(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        (stack_state / "stop_fail").write_text("", encoding="utf-8")
        (stack_state / "stop_stderr").write_text(
            "container stop failed\n",
            encoding="utf-8",
        )
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "up_stderr").write_text(
            "recovery up failed\n",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=stop", report)
        self.assertIn("reason=down-failed", report)
        self.assertIn("argv=docker compose -f docker-compose.yml up", report)
        self.assertNotIn("--force-recreate", report)
        self.assertIn("recovery up failed", report)
        self.assertNotIn("argv=docker compose -f docker-compose.yml down", report)

    def test_tag_update_requires_explicit_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("require --allow-tag-updates", result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")

    def test_tag_update_dry_run_does_not_rewrite_compose(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--dry-run", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("repo/app:1.0 -> repo/app:2.0 (tag update)", result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")

    def test_allowed_tag_update_rewrites_compose_and_cleans_line(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.chmod(0o640)
        before_stat = compose_file.stat()
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn("image: repo/app:2.0", compose_file.read_text(encoding="utf-8"))
        after_stat = compose_file.stat()
        self.assertEqual(after_stat.st_mode & 0o7777, before_stat.st_mode & 0o7777)
        self.assertEqual(after_stat.st_uid, before_stat.st_uid)
        self.assertEqual(after_stat.st_gid, before_stat.st_gid)
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")

    def test_network_mode_consumer_tag_update_stays_service_scoped(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=5.2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.base / "media"
        stack_dir.mkdir()
        (stack_dir / ".fake-docker-id").write_text("media\n", encoding="utf-8")
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  gluetun:",
                    "    image: qmcgaw/gluetun:latest",
                    "  qbittorrent:",
                    "    image: ghcr.io/linuxserver/qbittorrent:5.1.4",
                    "    network_mode: service:gluetun",
                    "  mamapi:",
                    "    image: ghcr.io/example/mamapi:latest",
                    "    network_mode: service:gluetun",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack_state = self.fake_root / "stacks" / "media"
        stack_state.mkdir()
        (stack_state / "cids.txt").write_text(
            "cid-gluetun\ncid-qbittorrent\ncid-mamapi\n",
            encoding="utf-8",
        )
        (stack_state / "cids-qbittorrent.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        for cid in ("cid-gluetun", "cid-qbittorrent", "cid-mamapi"):
            (self.fake_root / "containers" / f"{cid}.summary").write_text(
                f"/{cid}|running|healthy|0|0\n",
                encoding="utf-8",
            )
        self.set_image_state(
            "ghcr.io/linuxserver/qbittorrent:5.1.4",
            "old-qbit",
            "sha256:old-qbit",
        )
        self.set_image_after_pull(
            "ghcr.io/linuxserver/qbittorrent:5.2.0",
            "new-qbit",
            "sha256:new-qbit",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/linuxserver/qbittorrent:5.2.0",
            compose_file.read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull qbittorrent")
        self.assertRegex(calls, r"compose -f docker-compose.yml stop qbittorrent")
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull mamapi")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*mamapi")

    def test_surgical_tag_rewrite_preserves_unrelated_compose_content(self) -> None:
        compose_file = self.root / "compose.yml"
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    image: \"repo/app:1.0\" # keep comment\n"
            "    labels:\n"
            "      image: repo/app:1.0\n"
            "  db:\n"
            "    image: repo/db:1.0\n"
        )
        compose_file.write_text(original, encoding="utf-8")

        applied = apply_compose_tag_updates(
            compose_file,
            (
                TagUpdate(
                    old_image="repo/app:1.0",
                    desired_tag="2.0",
                    new_image="repo/app:2.0",
                    services=("app",),
                ),
            ),
        )

        self.assertEqual(applied[0].replacements, 1)
        self.assertEqual(
            compose_file.read_text(encoding="utf-8"),
            original.replace(
                '    image: "repo/app:1.0" # keep comment',
                '    image: "repo/app:2.0" # keep comment',
            ),
        )

    def test_surgical_tag_rewrite_rejects_interpolated_image(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "services:\n  app:\n    image: repo/app:${TAG}\n"
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "interpolation"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:${TAG}",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_surgical_tag_rewrite_rejects_extension_only_image(self) -> None:
        compose_file = self.root / "compose.yml"
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "      image: repo/app:1.0\n"
        )
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "direct string"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_surgical_tag_rewrite_rejects_invalid_yaml(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "services:\n  app:\n    image: [repo/app:1.0\n"
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "could not be parsed"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_conflicting_duplicate_tag_updates_fail_before_manifest(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.0 tag=2.0\nrepo/app:1.0 tag=3.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\nrepo/app:1.0 tag=3.0\n",
        )
        self.assertIn("Conflicting tag updates", result.stderr)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotIn("manifest inspect", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_update_without_service_map_fails_before_manifest(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
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
            mock.patch.object(runner.compose, "try_service_image_pairs", return_value=()),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("could not be mapped", stderr.getvalue())
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotIn("manifest inspect", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_update_validation_failure_rolls_back_before_pull(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
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
        refreshed = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage(service="app", image="repo/app:1.0"),),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch.object(runner, "_refresh_stack_images", return_value=refreshed),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn("did not resolve to rewritten image", stderr.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_tag_override_requires_allow_tag_updates(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python("--yes", "--tag-override", "1=3.0")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--tag-override requires --allow-tag-updates", result.stderr)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.calls(), "")

    def test_tag_override_rejects_invalid_tag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_python(
            "--yes",
            "--allow-tag-updates",
            "--tag-override",
            "1=bad:value",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("--tag-override line 1 has invalid tag", result.stderr)

    def test_tag_override_dry_run_validates_manifest_without_mutation(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        result = self.run_python(
            "--dry-run",
            "--allow-tag-updates",
            "--tag-override",
            "1=3.0",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("Tag override: line 1 uses tag 3.0 instead of 2.0", result.stdout)
        self.assertIn(
            "Validated remote tag: repo/app:1.0 -> repo/app:3.0",
            result.stdout,
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:3.0", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_manifest_validation_failure_leaves_line_and_compose(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_manifest_failure("repo/app:2.0", "manifest unknown\n")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn("Invalid or unavailable remote tag", result.stderr)
        self.assertIn("manifest unknown", result.stderr)
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:2.0", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_override_live_success_rewrites_to_override(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:3.0", "new", "sha256:new")

        result = self.run_python(
            "--yes",
            "--allow-tag-updates",
            "--tag-override",
            "1=3.0",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: repo/app:3.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:3.0", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")

    def test_tag_update_with_digest_checks_rewritten_tag(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.0@sha256:good tag=2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:good")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: repo/app:2.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )

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

    def test_log_file_creation_does_not_follow_existing_symlink(self) -> None:
        target = self.root / "symlink-target.log"
        target.write_text("keep\n", encoding="utf-8")
        (self.log_dir / "update-from-wud-v2-fixed.log").symlink_to(target)
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.file_timestamp", return_value="fixed"):
            log_file = prepare_log_file(self.log_dir, owner)

        self.assertEqual(log_file.name, "update-from-wud-v2-fixed-1.log")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        self.assertFalse(log_file.is_symlink())
        self.assertEqual(log_file.read_text(encoding="utf-8"), "")
        after_stat = log_file.stat()
        self.assertEqual((after_stat.st_uid, after_stat.st_gid), (os.getuid(), os.getgid()))

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

    def test_tag_incident_creation_does_not_follow_existing_symlink(self) -> None:
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
        target = self.root / "incident-target.logs"
        target.write_text("keep\n", encoding="utf-8")
        (stack_dir / "error-2.0-fixed.logs").symlink_to(target)
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
            mock.patch("wud_updater.updater.file_timestamp", return_value="fixed"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        incident = stack_dir / "error-2.0-fixed-1.logs"
        self.assertFalse(incident.is_symlink())
        content = incident.read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", content)
        self.assertIn("repo/app:1.0 -> repo/app:2.0", content)
        self.assertIn("manual_review_required=no", content)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    unittest.main()
