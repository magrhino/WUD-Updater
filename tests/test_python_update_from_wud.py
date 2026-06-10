from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater import updater_tag_exclusions
from wud_updater.command import CommandRunner
from wud_updater.compose import (
    ComposeBindMount,
    ComposeStack,
    ServiceImage,
)
from wud_updater.compose_rewrite import apply_compose_tag_exclusions
from wud_updater.config import load_config
from wud_updater.digest_verifier import (
    DigestVerifier,
    DockerManifestResolver,
    ManifestDocument,
    ManifestLookupError,
)
from wud_updater.docker_cli import DockerCli
from wud_updater.file_ops import OwnerConfig
from wud_updater.plans import build_dry_run_plan
from wud_updater.digest_verifier import (
    _payload_digest,
)
from wud_updater.images import image_with_digest
from wud_updater.updater import (
    UpdateFromWudRunner,
    _apply_sqlite_owner,
)
from wud_updater.updater_lifecycle_health import _updated_images
from wud_updater.updater_digest_pin import digest_pin_update_from_values
from wud_updater.updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagUpdate,
    ComposeTagRewriteError,
    DigestPinUpdate,
    ImageState,
    TagExclusionUpdate,
    UpdaterError,
    UpdaterOptions,
)


MANIFEST_INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_IMAGE_TYPE = "application/vnd.oci.image.manifest.v1+json"


class FailingManifestResolver:
    def fetch(self, repo: str, reference: str) -> ManifestDocument:
        raise ManifestLookupError("primary unavailable in fake Docker tests")


def manifest_index(*children: str) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": MANIFEST_INDEX_TYPE,
        "manifests": [
            {
                "mediaType": MANIFEST_IMAGE_TYPE,
                "digest": child,
                "platform": {"os": "linux", "architecture": "amd64"},
            }
            for child in children
        ],
    }


def manifest_index_digest(digest: str, *children: str) -> dict[str, object]:
    payload = manifest_index(*children)
    payload["Descriptor"] = {"digest": digest}
    return payload


def verbose_manifest_item(
    digest: str,
    *,
    config_digest: str = "sha256:config",
    architecture: str = "amd64",
) -> dict[str, object]:
    return {
        "Ref": f"docker.io/repo/app:1.0@{digest}",
        "Descriptor": {
            "mediaType": MANIFEST_IMAGE_TYPE,
            "digest": digest,
            "platform": {"os": "linux", "architecture": architecture},
        },
        "SchemaV2Manifest": manifest_image(config_digest),
    }


def manifest_image(config_digest: str) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": MANIFEST_IMAGE_TYPE,
        "config": {"digest": config_digest},
    }


class FakeDockerTestCase(unittest.TestCase):
    tmp_prefix = "wud-python-update."

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix=self.tmp_prefix)
        self.root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.base = self.root / "base"
        self.wud_file = self.root / "images.todo"
        self.log_dir = self.root / "logs"
        self.db_path = self.root / "state" / "wud-updater.sqlite"
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
        self.env["WUD_UPDATER_BANNER"] = "false"
        self.env["WUD_DB_PATH"] = str(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_stack(
        self,
        stack_id: str,
        services: list[tuple[str, str, str | None]],
        *,
        parent: Path | None = None,
    ) -> Path:
        directory = (parent or self.base) / stack_id
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

    def _set_manifest_stdout(self, image: str, payload: object) -> None:
        safe = safe_name(image)
        (self.fake_root / "manifests" / f"{safe}.stdout").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def set_manifest_stdout(self, image: str, payload: object) -> None:
        self._set_manifest_stdout(image, payload)

    def set_manifest_verbose_stdout(self, image: str, payload: object) -> None:
        safe = safe_name(image)
        (self.fake_root / "manifests" / f"{safe}.verbose_stdout").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _set_manifest_failure(self, image: str, stderr: str) -> None:
        safe = safe_name(image)
        (self.fake_root / "manifests" / f"{safe}.fail").write_text("", encoding="utf-8")
        (self.fake_root / "manifests" / f"{safe}.stderr").write_text(
            stderr,
            encoding="utf-8",
        )

    def set_manifest_failure(self, image: str, stderr: str) -> None:
        self._set_manifest_failure(image, stderr)

    def _calls(self) -> str:
        return self.calls()

    def calls(self) -> str:
        return (self.fake_root / "calls.log").read_text(encoding="utf-8")


class PythonUpdateFromWudTests(FakeDockerTestCase):
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

    def updater_options(
        self,
        *,
        assume_yes: bool = True,
        allow_tag_updates: bool = False,
        digest_pin_updates: bool = False,
        db_path: Path | None = None,
    ) -> UpdaterOptions:
        return UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=assume_yes,
            allow_tag_updates=allow_tag_updates,
            digest_pin_updates=digest_pin_updates,
            no_color=True,
            db_path=db_path,
        )

    def make_runner(
        self,
        *,
        command_runner: CommandRunner | None = None,
        digest_verifier: DigestVerifier | None = None,
        assume_yes: bool = True,
        allow_tag_updates: bool = False,
        digest_pin_updates: bool = False,
        db_path: Path | None = None,
    ) -> UpdateFromWudRunner:
        return UpdateFromWudRunner(
            self.updater_options(
                assume_yes=assume_yes,
                allow_tag_updates=allow_tag_updates,
                digest_pin_updates=digest_pin_updates,
                db_path=db_path,
            ),
            environ=self.env,
            command_runner=command_runner or CommandRunner(env=self.env),
            digest_verifier=digest_verifier,
        )

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

    def run_direct(
        self,
        *,
        assume_yes: bool = True,
        allow_tag_updates: bool = False,
        digest_pin_updates: bool = False,
        digest_pin_plan: tuple[DigestPinUpdate, ...] = (),
    ) -> tuple[int, str, str]:
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=assume_yes,
            allow_tag_updates=allow_tag_updates,
            digest_pin_updates=digest_pin_updates,
            digest_pin_plan=digest_pin_plan,
            no_color=True,
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=command_runner,
            digest_verifier=DigestVerifier(
                docker,
                primary_resolver=FailingManifestResolver(),
                fallback_resolver=DockerManifestResolver(docker),
            ),
        )
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = runner.run()
        return status, stdout.getvalue(), stderr.getvalue()

    def latest_error_report(self) -> Path:
        reports = sorted(self.log_dir.glob("update-from-wud-v2-*.errors.log"))
        self.assertTrue(reports, "expected updater error report")
        return reports[-1]

    def db_rows(self, query: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return list(conn.execute(query, params))

    def prepare_digest_pin_latest_update(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        self.set_manifest_stdout(
            "docker.io/repo/app@sha256:child",
            manifest_image("sha256:config"),
        )

    def write_tag_update_health_flip_hook(self) -> None:
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

    def write_media_provider_post_up_hook(self) -> None:
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    'printf "cid-gluetun\\n" > "$FAKE_DOCKER_ROOT/stacks/media/cids-gluetun.txt"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        hook.chmod(0o755)

    def prepare_network_mode_media_stack(
        self,
        *,
        include_provider_cid: bool,
        include_extra_consumer: bool = False,
        write_provider_hook: bool = False,
    ) -> Path:
        self.wud_file.write_text(
            "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=5.2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.base / "media"
        stack_dir.mkdir()
        (stack_dir / ".fake-docker-id").write_text("media\n", encoding="utf-8")
        compose_lines = [
            "services:",
            "  gluetun:",
            "    image: qmcgaw/gluetun:latest",
            "  qbittorrent:",
            "    image: ghcr.io/linuxserver/qbittorrent:5.1.4",
            "    network_mode: service:gluetun",
        ]
        if include_extra_consumer:
            compose_lines.extend(
                [
                    "  mamapi:",
                    "    image: ghcr.io/example/mamapi:latest",
                    "    network_mode: service:gluetun",
                ]
            )
        compose_lines.append("")
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text("\n".join(compose_lines), encoding="utf-8")

        stack_state = self.fake_root / "stacks" / "media"
        stack_state.mkdir()
        cids = ["cid-qbittorrent"]
        if include_provider_cid:
            cids.insert(0, "cid-gluetun")
        if include_extra_consumer:
            cids.append("cid-mamapi")
        (stack_state / "cids.txt").write_text(
            "".join(f"{cid}\n" for cid in cids),
            encoding="utf-8",
        )
        if include_provider_cid:
            (stack_state / "cids-gluetun.txt").write_text(
                "cid-gluetun\n",
                encoding="utf-8",
            )
        (stack_state / "cids-qbittorrent.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        summary_cids = set(cids)
        if write_provider_hook:
            summary_cids.add("cid-gluetun")
        for cid in sorted(summary_cids):
            (self.fake_root / "containers" / f"{cid}.summary").write_text(
                f"/{cid}|running|healthy|0|0\n",
                encoding="utf-8",
            )
        if write_provider_hook:
            self.write_media_provider_post_up_hook()
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
        return compose_file

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
        self.assertFalse(self.db_path.exists())

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
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates")
        events = self.db_rows("SELECT * FROM update_events")
        known = self.db_rows("SELECT * FROM known_images")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")
        self.assertTrue(runs[0]["finished_at"].endswith("+00:00"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "updated")
        self.assertEqual(pending[0]["service_key"], "stack/app")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "success")
        self.assertEqual(events[0]["service_name"], "app")
        self.assertEqual(len(known), 1)
        self.assertEqual(known[0]["service_key"], "stack/app")
        self.assertEqual(known[0]["image"], "repo/app:latest")
        self.assertEqual(known[0]["image_id"], "new-app")
        self.assertTrue(known[0]["digest"].endswith("@sha256:new-app"))

    def test_python_updates_honors_configured_compose_ignore_paths(self) -> None:
        self.wud_file.write_text("repo/ignored:latest\n", encoding="utf-8")
        self.make_stack("active", [("app", "repo/app:latest", "cid-app")])
        self.make_stack(
            "ignored",
            [("app", "repo/ignored:latest", "cid-ignored")],
            parent=self.base / "old",
        )
        self.set_image_state("repo/ignored:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/ignored:latest", "new", "sha256:new")
        self.env["WUD_COMPOSE_IGNORE_PATHS"] = "old"

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/ignored:latest\n",
        )
        self.assertNotRegex(self.calls(), r"repo/ignored")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_remove_lines_before_run_records_discarded_audit_entries(self) -> None:
        self.wud_file.write_text(
            "repo/app:one\nrepo/app:two\nrepo/app:three\n",
            encoding="utf-8",
        )
        self.make_stack("stack", [("app", "repo/app:two", "cid-app")])
        self.set_image_state("repo/app:two", "old", "sha256:old")
        self.set_image_after_pull("repo/app:two", "new", "sha256:new")

        result = self.run_python(
            "--yes",
            "--only-lines",
            "2",
            "--remove-lines-before-run",
            "1,3",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        pending = self.db_rows(
            "SELECT * FROM pending_updates ORDER BY line_no"
        )
        self.assertEqual(len(pending), 3)
        self.assertEqual(
            [(row["line_no"], row["status"], row["status_reason"]) for row in pending],
            [
                (1, "resolved", "removed-before-run"),
                (2, "resolved", "updated"),
                (3, "resolved", "removed-before-run"),
            ],
        )

    def test_non_ghcr_manifest_unavailable_warns_and_allows_update(self) -> None:
        self.wud_file.write_text("quay.io/acme/app:latest@sha256:good\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "old", "sha256:old")
        self.set_image_after_pull("quay.io/acme/app:latest", "new", "sha256:bad")
        self.set_manifest_failure("quay.io/acme/app:latest", "manifest unavailable")

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml up -d .* app")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "updated")
        log_text = sorted(self.log_dir.glob("update-from-wud-v2-*.log"))[-1].read_text(
            encoding="utf-8"
        )
        self.assertIn("Digest verification was inconclusive", log_text)
        self.assertIn("Digest verification reason: manifest-unavailable-untrusted", log_text)

    def test_non_ghcr_platform_digest_allows_registry_verification(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:child\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "quay.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "quay.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "quay.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect quay.io/acme/app:latest", calls)
        self.assertIn("manifest inspect quay.io/acme/app@sha256:child", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")

    def test_non_ghcr_stale_digest_restores_line_and_skips_recreate(self) -> None:
        self.wud_file.write_text("quay.io/acme/app:latest@sha256:stale\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "quay.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "quay.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "quay.io/acme/app@sha256:stale",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "quay.io/acme/app:latest@sha256:stale\n",
        )
        calls = self.calls()
        self.assertIn("manifest inspect quay.io/acme/app:latest", calls)
        self.assertIn("manifest inspect quay.io/acme/app@sha256:stale", calls)
        self.assertNotRegex(calls, r"compose -f .* up -d")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "failure")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "expected-digest-not-reached")

    def test_ghcr_platform_digest_allows_registryless_wud_line(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:child\n", encoding="utf-8")
        self.make_stack("app", [("app", "ghcr.io/acme/app:latest", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:latest", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:child", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")

    def test_ghcr_stale_digest_restores_line_and_skips_recreate(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:stale\n", encoding="utf-8")
        self.make_stack("app", [("app", "ghcr.io/acme/app:latest", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:stale",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "acme/app:latest@sha256:stale\n",
        )
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:latest", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:stale", calls)
        self.assertNotRegex(calls, r"compose -f .* up -d")
        log_text = sorted(self.log_dir.glob("update-from-wud-v2-*.log"))[-1].read_text(
            encoding="utf-8"
        )
        self.assertIn("Digest verification reason: stale-digest", log_text)

    def test_multi_stack_failure_keeps_failure_reason_in_pending_audit(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("ok", [("app", "repo/app:latest", "cid-ok")])
        self.make_stack("zbad", [("app", "repo/app:latest", "cid-bad")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "zbad"
        (stack_state / "pull_fail").write_text("", encoding="utf-8")
        (stack_state / "pull_stderr").write_text("manifest fetch failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "pull-failed")
        self.assertEqual(pending[0]["service_key"], "zbad/app")
        self.assertEqual(pending[0]["stack_name"], "zbad")
        self.assertEqual(pending[0]["service_name"], "app")

    def test_malformed_audit_db_fails_before_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA user_version = 99")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("Could not initialize audit database:", result.stderr)
        self.assertIn("Unsupported database schema version: 99", result.stderr)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")

    def test_container_bridge_bind_mount_preflight_fails_before_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
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
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(ComposeBindMount("app", "/host/docker/app/config", "/config"),),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("helper-only prefix /host", stderr.getvalue())
        self.assertIn("HOST_DOCKER_BASE=/srv/docker", stderr.getvalue())
        self.assertIn("error report:", stderr.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=preflight", report)
        self.assertIn("reason=bind-mount-path-invalid", report)
        self.assertIn("/host/docker/app/config", report)
        self.assertIn("helper-only prefix /host", report)
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertTrue(runs[0]["finished_at"].endswith("+00:00"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "bind-mount-path-invalid")
        self.assertEqual(pending[0]["stack_name"], "app")
        self.assertEqual(pending[0]["service_name"], "app")

    def test_container_bridge_bind_mount_preflight_marks_unaffected_matches_pending(self) -> None:
        self.wud_file.write_text("repo/bad:latest\nrepo/ok:latest\n", encoding="utf-8")
        self.make_stack("bad", [("app", "repo/bad:latest", "cid-bad")])
        self.make_stack("ok", [("app", "repo/ok:latest", "cid-ok")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        def bind_mounts(directory: Path, file: str, **_: object) -> tuple[ComposeBindMount, ...]:
            if Path(directory).name == "bad":
                return (ComposeBindMount("app", "/host/docker/bad/config", "/config"),)
            return ()

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                side_effect=bind_mounts,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/bad:latest\nrepo/ok:latest\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates ORDER BY line_no")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertEqual(
            [
                (
                    row["line_no"],
                    row["status"],
                    row["status_reason"],
                    row["stack_name"],
                    row["service_name"],
                )
                for row in pending
            ],
            [
                (1, "failed", "bind-mount-path-invalid", "bad", "app"),
                (2, "pending", "preflight-skipped", "ok", "app"),
            ],
        )

    def test_container_bridge_bind_mount_preflight_warns_on_dry_run(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            dry_run=True,
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
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(ComposeBindMount("app", "/host/docker/app/config", "/config"),),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("helper-only prefix /host", stdout.getvalue())
        self.assertIn("reported container bind-mount path issue", stdout.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        self.assertFalse(self.db_path.exists())
        self.assertFalse(list(self.log_dir.glob("update-from-wud-v2-*.errors.log")))

    def test_container_bridge_bind_mount_preflight_allows_host_paths(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
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
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(
                    ComposeBindMount("app", "/mnt/nvme-pool/docker/app/config", "/config"),
                ),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml pull app")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml up -d .* app")

    def test_host_docker_base_maps_project_directory_and_allows_binds(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        host_base = self.root / "host-docker"
        expected_project_directory = host_base / "app"
        expected_project_directory.mkdir(parents=True)
        (expected_project_directory / "docker-compose.yml").write_text(
            (self.base / "app" / "docker-compose.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
            host_docker_base=host_base,
            host_docker_base_label=str(host_base),
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()
        project_directories: list[Path | None] = []

        def bind_mounts(
            directory: Path,
            file: str,
            *,
            project_directory: Path | None = None,
        ) -> tuple[ComposeBindMount, ...]:
            self.assertEqual(directory, self.base / "app")
            self.assertEqual(file, "docker-compose.yml")
            project_directories.append(project_directory)
            source = str((project_directory or directory) / "config")
            return (ComposeBindMount("app", source, "/config"),)

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                side_effect=bind_mounts,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(project_directories, [expected_project_directory])
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(f"HostBase: {host_base}", stdout.getvalue())
        self.assertRegex(
            self.calls(),
            rf"compose --project-directory {re.escape(str(expected_project_directory))} "
            r"-f docker-compose.yml pull app",
        )
        self.assertRegex(
            self.calls(),
            rf"compose --project-directory {re.escape(str(expected_project_directory))} "
            r"-f docker-compose.yml up -d .* app",
        )

    def test_audit_owner_failure_marks_started_run_failed(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater._apply_sqlite_owner",
                side_effect=OSError("chown failed"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Could not initialize audit database: chown failed",
            ):
                runner.run()

        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_late_audit_write_failure_marks_run_failed(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater.insert_update_event",
                side_effect=sqlite3.OperationalError("database is locked"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Could not update audit database: database is locked",
            ):
                runner.run()

        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_wud_file_rewrite_failure_is_user_facing(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater.remove_lines_before_run",
                side_effect=OSError("metadata verification failed"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Filesystem operation failed: metadata verification failed",
            ):
                runner.run()

        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_audit_start_applies_configured_owner_to_db_path(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        self.env["OUT_UID"] = str(os.getuid())
        self.env["OUT_GID"] = str(os.getgid())
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch("wud_updater.updater._apply_sqlite_owner") as apply_owner,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        apply_owner.assert_any_call(self.db_path, runner.owner, chown_parent=True)

    def test_apply_sqlite_owner_leaves_existing_db_directory_alone(self) -> None:
        db_path = self.root / "state" / "wud-updater.sqlite"
        sidecars = [
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
            Path(f"{db_path}-journal"),
        ]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for path in sidecars:
            path.write_text("", encoding="utf-8")
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.apply_configured_owner") as apply_owner:
            _apply_sqlite_owner(db_path, owner)

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, sidecars)

    def test_apply_sqlite_owner_updates_created_db_directory_and_sidecars(self) -> None:
        db_path = self.root / "created-state" / "wud-updater.sqlite"
        sidecars = [
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
            Path(f"{db_path}-journal"),
        ]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for path in sidecars:
            path.write_text("", encoding="utf-8")
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.apply_configured_owner") as apply_owner:
            _apply_sqlite_owner(db_path, owner, chown_parent=True)

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, [db_path.parent, *sidecars])

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

    def test_invalid_runtime_port_fails_preflight_before_pull(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        (stack_dir / "docker-compose.yml").write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    image: repo/app:latest",
                    "    expose:",
                    "      - \u201c8083\u201d",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        calls = self.calls()
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=preflight", report)
        self.assertIn("reason=compose-port-invalid", report)
        self.assertIn("Compose service app has invalid expose value", report)
        self.assertIn("\u201c8083\u201d", report)

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

    def test_tag_update_compose_up_failure_unpauses_before_rollback(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "up_fail").write_text("", encoding="utf-8")

        result = self.run_python("--yes", "--allow-tag-updates", "--mode", "pause")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        failed_up = calls.index("compose -f docker-compose.yml up")
        unpause = calls.index("compose -f docker-compose.yml unpause app")
        rollback_up = calls.rindex("compose -f docker-compose.yml up")
        self.assertLess(failed_up, unpause)
        self.assertLess(unpause, rollback_up)

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
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(pending[0]["status_reason"], "tag-update-disabled")

    def test_exclude_tag_line_writes_wud_label_and_cleans_line(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = (stack_dir / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("wud.tag.exclude=^2\\.0$$", content)
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        pending = self.db_rows("SELECT * FROM pending_updates")
        rules = self.db_rows("SELECT * FROM tag_exclusion_rules")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "tag-excluded")
        self.assertEqual(rules[0]["scope"], "image_repo")
        self.assertEqual(rules[0]["image_repo"], "repo/app")
        self.assertEqual(rules[0]["tag"], "2.0")

    def test_exclude_tag_line_updates_all_services_for_image_repo(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        app_stack = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        worker_stack = self.make_stack(
            "worker",
            [("worker", "registry.example.com/repo/app:1.1", "cid-worker")],
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (app_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (worker_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        rules = self.db_rows("SELECT * FROM tag_exclusion_rules")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["scope"], "image_repo")

    def test_exclude_tag_line_can_recreate_affected_services(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python(
            "--yes",
            "--exclude-tag-lines",
            "1",
            "--recreate-excluded-services",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertRegex(
            self.calls(),
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps app",
        )

    def test_exclude_tag_line_does_not_recreate_already_excluded_service(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        initial = self.run_python("--yes", "--exclude-tag-lines", "1")
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)

        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        result = self.run_python(
            "--yes",
            "--exclude-tag-lines",
            "1",
            "--recreate-excluded-services",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertNotRegex(self.calls(), r"compose -f docker-compose.yml up -d")

    def test_can_apply_tag_exclusions_uses_existing_exact_tags(self) -> None:
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        stack = ComposeStack(
            index=0,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )
        update = TagExclusionUpdate(
            stack=stack,
            service="app",
            image="repo/app:1.0",
            image_repo="repo/app",
            tag="3.0",
            source_line=1,
            scope="service",
        )
        captured: dict[str, object] = {}

        class Runner:
            def _existing_exact_tag_exclusions(
                self,
                updates: list[TagExclusionUpdate],
            ) -> dict[str, set[str]]:
                captured["updates"] = updates
                return {"app": {"2.0"}}

        def fake_render_compose_tag_exclusions(
            compose_path: Path,
            updates: list[TagExclusionUpdate],
            *,
            existing_exact_tags: dict[str, set[str]],
        ) -> tuple[str, tuple[object, ...]]:
            captured["compose_path"] = compose_path
            captured["render_updates"] = updates
            captured["existing_exact_tags"] = existing_exact_tags
            return "", ()

        with mock.patch(
            "wud_updater.compose_rewrite.render_compose_tag_exclusions",
            side_effect=fake_render_compose_tag_exclusions,
        ):
            result = updater_tag_exclusions.can_apply_tag_exclusions(
                Runner(),
                (update,),
            )

        self.assertTrue(result)
        self.assertEqual(captured["updates"], [update])
        self.assertEqual(captured["render_updates"], [update])
        self.assertEqual(captured["compose_path"], stack_dir / "docker-compose.yml")
        self.assertEqual(captured["existing_exact_tags"], {"app": {"2.0"}})

    def test_exclude_tag_line_recreate_includes_missing_network_provider(self) -> None:
        compose_file = self.prepare_network_mode_media_stack(
            include_provider_cid=False,
            write_provider_hook=True,
        )

        result = self.run_python(
            "--yes",
            "--exclude-tag-lines",
            "1",
            "--recreate-excluded-services",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "wud.tag.exclude=^5\\.2\\.0$$",
            compose_file.read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans gluetun qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up -d .*--no-deps")

    def test_exclude_tag_line_recreates_only_successful_label_writes(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        app_stack = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        worker_stack = self.make_stack(
            "worker",
            [("worker", "registry.example.com/repo/app:1.1", "cid-worker")],
        )
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
            exclude_tag_lines="1",
            recreate_excluded_services=True,
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )

        def flaky_apply_compose_tag_exclusions(
            compose_path: Path,
            updates: tuple[TagExclusionUpdate, ...],
            *,
            existing_exact_tags: dict[str, set[str]],
        ) -> object:
            if compose_path.parent.name == "worker":
                raise ComposeTagRewriteError("synthetic label write failure")
            return apply_compose_tag_exclusions(
                compose_path,
                updates,
                existing_exact_tags=existing_exact_tags,
            )

        with mock.patch(
            "wud_updater.compose_rewrite.apply_compose_tag_exclusions",
            side_effect=flaky_apply_compose_tag_exclusions,
        ):
            result = runner.run()

        self.assertEqual(result, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        calls = self.calls()
        self.assertIn(
            f"{app_stack}\tcompose -f docker-compose.yml up -d "
            "--remove-orphans --no-deps app",
            calls,
        )
        self.assertNotIn(
            f"{worker_stack}\tcompose -f docker-compose.yml up -d "
            "--remove-orphans --no-deps worker",
            calls,
        )
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (app_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "wud.tag.exclude",
            (worker_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "tag-exclusion-label-failed")

    def test_exclude_tag_line_failure_leaves_line_pending(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "services:\n  app:\n    image: repo/app:1.0\n    labels: unsupported\n",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(
            pending[0]["status_reason"],
            "tag-exclusion-compose-label-unsupported",
        )

    def test_unmatched_entry_remains_pending_with_reason(self) -> None:
        self.wud_file.write_text("repo/missing:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/missing:latest\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(pending[0]["status_reason"], "unmatched")

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
        self.assertFalse(self.db_path.exists())

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

    def test_digest_pin_tag_update_writes_pinned_compose_and_metadata(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:index")
        self.set_image_state("repo/app@sha256:index", "new", "sha256:index")
        self.set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index("sha256:child"),
        )
        self.set_manifest_verbose_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:index", "sha256:child"),
        )

        status, stdout, stderr = self.run_direct(
            allow_tag_updates=True,
            digest_pin_updates=True,
        )

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("# wud-updater.resolved-tag=2.0", content)
        self.assertIn("image: repo/app@sha256:index", content)
        self.assertIn("wud.tag.include=^2\\.0$$", content)
        calls = self.calls()
        self.assertRegex(calls, r"manifest inspect --verbose docker.io/repo/app:2.0")
        self.assertRegex(calls, r"manifest inspect repo/app:2.0")
        self.assertEqual(
            calls.count("manifest inspect --verbose docker.io/repo/app:2.0"),
            2,
        )
        self.assertNotRegex(calls, r"(?m)^manifest inspect docker\.io/repo/app:2\.0$")
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")
        events = self.db_rows("SELECT * FROM update_events")
        known = self.db_rows("SELECT * FROM known_images")
        self.assertEqual(events[0]["target_image"], "repo/app@sha256:index")
        self.assertEqual(known[0]["image"], "repo/app@sha256:index")

    def test_digest_pin_os_error_records_failure_without_tag_rollback(self) -> None:
        self.prepare_digest_pin_latest_update()

        with mock.patch(
            "wud_updater.compose_rewrite.apply_compose_digest_pins",
            side_effect=OSError("write denied"),
        ):
            status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 1, stderr + stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=compose-digest-pin", report)
        self.assertIn("reason=compose-digest-pin-failed", report)
        self.assertIn("write denied", report)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "compose-digest-pin-failed")

    def test_digest_pin_empty_apply_records_failure_without_tag_rollback(self) -> None:
        self.prepare_digest_pin_latest_update()

        with mock.patch(
            "wud_updater.compose_rewrite.apply_compose_digest_pins",
            return_value=(),
        ):
            status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 1, stderr + stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=compose-digest-pin", report)
        self.assertIn("reason=compose-digest-pin-failed", report)
        self.assertIn("No compose image lines were digest pinned.", report)

    def test_applied_rewrite_validators_accept_stack_level_records(self) -> None:
        runner = UpdateFromWudRunner(
            UpdaterOptions(
                docker_base=self.base,
                wud_file=self.wud_file,
                log_dir=self.log_dir,
                max_wait=0,
                no_color=True,
            ),
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied_tag = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=(),
            replacements=1,
        )
        applied_pin = AppliedDigestPinUpdate(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            resolved_image="repo/app:2.0",
            planned_digest="sha256:index",
            final_image="repo/app@sha256:index",
            watch_tag="2.0",
            marker="wud-updater.resolved-tag=2.0",
            label_key="wud.tag.include",
            label_value="^2\\.0$$",
            services=(),
            replacements=1,
        )

        self.assertTrue(runner._validate_applied_tag_updates(stack, (applied_tag,), ()))
        self.assertTrue(runner._validate_applied_digest_pins(stack, (applied_pin,), ()))

    def test_digest_pin_verification_matches_canonical_compose_image(self) -> None:
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="docker-compose.yml",
            name="app",
            images=("docker.io/repo/app:2.0",),
            service_images=(ServiceImage("app", "docker.io/repo/app:2.0"),),
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        self.set_image_state("docker.io/repo/app:2.0", "new", "sha256:index")
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        runner = UpdateFromWudRunner(
            UpdaterOptions(
                docker_base=self.base,
                wud_file=self.wud_file,
                log_dir=self.log_dir,
                max_wait=0,
                digest_pin_updates=True,
                no_color=True,
            ),
            environ=self.env,
            command_runner=command_runner,
            digest_verifier=DigestVerifier(
                docker,
                primary_resolver=FailingManifestResolver(),
                fallback_resolver=DockerManifestResolver(docker),
            ),
        )

        self.assertTrue(
            runner._verify_digest_pin_updates(
                stack,
                (
                    digest_pin_update_from_values(
                        old_image="repo/app:1.0",
                        resolved_tag="2.0",
                        planned_digest="sha256:index",
                        services=("app",),
                    ),
                ),
                stack.images,
            )
        )

    def test_digest_pin_plan_includes_digest_actions_and_hashes_digest(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:first", "sha256:child"),
        )
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
                "WUD_DIGEST_PIN_UPDATES": "true",
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=True,
            environ=self.env,
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:second", "sha256:child"),
        )
        moved_plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=True,
            environ=self.env,
        )

        self.assertEqual(plan.status, "ready")
        self.assertTrue(plan.digest_pin_updates)
        self.assertEqual(plan.stacks[0].lines[0].action, "digest-pin")
        self.assertEqual(plan.stacks[0].lines[0].target_image, "repo/app@sha256:first")
        self.assertEqual(
            plan.stacks[0].digest_pin_updates[0].planned_digest,
            "sha256:first",
        )
        self.assertIn(
            "compose-digest-pin",
            {action.kind for action in plan.stacks[0].actions},
        )
        self.assertNotEqual(plan.plan_id, moved_plan.plan_id)

    def test_digest_pin_plan_accepts_tagged_digest_only_latest_child(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
                "WUD_DIGEST_PIN_UPDATES": "true",
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=False,
            environ=self.env,
        )

        self.assertEqual(plan.status, "ready")
        self.assertTrue(plan.digest_pin_updates)
        self.assertEqual(plan.stacks[0].lines[0].action, "digest-pin")
        self.assertEqual(plan.stacks[0].lines[0].desired_tag, "")
        self.assertEqual(plan.stacks[0].lines[0].target_image, "repo/app@sha256:child")
        digest_pin = plan.stacks[0].digest_pin_updates[0]
        self.assertEqual(digest_pin.resolved_tag, "latest")
        self.assertEqual(digest_pin.watch_tag, "latest")
        self.assertEqual(digest_pin.planned_digest, "sha256:child")
        self.assertEqual(digest_pin.final_image, "repo/app@sha256:child")

    def test_digest_pin_plan_does_not_rematch_label_when_digest_pin_disabled(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app@sha256:old", "cid-app")])
        (stack_dir / "docker-compose.yml").write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    image: repo/app@sha256:old",
                    "    labels:",
                    "      - wud.tag.include=^latest$$",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=False,
            environ=self.env,
        )

        self.assertEqual(plan.status, "blocked")
        self.assertFalse(plan.digest_pin_updates)
        self.assertEqual(plan.summary.matched_target_count, 0)
        self.assertEqual(plan.stacks, ())
        self.assertEqual(plan.targets[0].action, "unmatched")

    def test_digest_pin_plan_blocks_stale_tagged_digest_only_latest_child(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:stale\n",
            encoding="utf-8",
        )
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:current"),
        )
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
                "WUD_DIGEST_PIN_UPDATES": "true",
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=False,
            environ=self.env,
        )

        self.assertEqual(plan.status, "blocked")
        self.assertFalse(plan.can_apply)
        self.assertEqual(plan.issues[0].code, "digest-pin-digest-stale")
        self.assertIn("Digest-pin target moved", plan.issues[0].message)
        self.assertEqual(plan.stacks[0].digest_pin_updates, ())

    def test_digest_pin_plan_blocks_conflicting_tagged_digest_only_digests(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:first\n"
            "repo/app:latest@sha256:second\n",
            encoding="utf-8",
        )
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
                "WUD_DIGEST_PIN_UPDATES": "true",
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1, 2),
            allow_tag_updates=False,
            environ=self.env,
        )

        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.issues[0].code, "digest-pin-conflict")
        self.assertIn("Conflicting digest-pin digests", plan.issues[0].message)
        self.assertEqual(plan.stacks[0].digest_pin_updates, ())

    def test_digest_pin_apply_rejects_moved_planned_digest(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:moved")
        self.set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:moved", "sha256:child"),
        )
        planned = (
            digest_pin_update_from_values(
                old_image="repo/app:1.0",
                resolved_tag="2.0",
                planned_digest="sha256:planned",
                services=("app",),
            ),
        )

        status, stdout, stderr = self.run_direct(
            allow_tag_updates=True,
            digest_pin_updates=True,
            digest_pin_plan=planned,
        )

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("image: repo/app:1.0", content)
        self.assertNotIn("wud-updater.resolved-tag", content)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(
            pending[0]["status_reason"],
            "digest-pin-verification-failed",
        )

    def test_digest_pin_apply_rejects_moved_tagged_digest_only_latest_child(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:planned\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:planned")
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:moved-index", "sha256:moved"),
        )
        planned = (
            digest_pin_update_from_values(
                old_image="repo/app:latest",
                resolved_tag="latest",
                planned_digest="sha256:planned",
                services=("app",),
            ),
        )

        status, stdout, stderr = self.run_direct(
            digest_pin_updates=True,
            digest_pin_plan=planned,
        )

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest@sha256:planned\n",
        )
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("image: repo/app:latest", content)
        self.assertNotIn("wud-updater.resolved-tag", content)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(
            pending[0]["status_reason"],
            "digest-pin-verification-failed",
        )

    def test_digest_pin_apply_writes_tagged_digest_only_latest_child(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:latest", "sha256:old-config", "sha256:old")
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_image_state(
            "repo/app@sha256:child",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        self.set_manifest_stdout(
            "docker.io/repo/app@sha256:child",
            manifest_image("sha256:new-config"),
        )

        status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("# wud-updater.resolved-tag=latest", content)
        self.assertIn("image: repo/app@sha256:child", content)
        events = self.db_rows("SELECT * FROM update_events")
        known = self.db_rows("SELECT * FROM known_images")
        self.assertEqual(events[0]["target_image"], "repo/app@sha256:child")
        self.assertEqual(known[0]["image"], "repo/app@sha256:child")

    def test_digest_pin_only_health_failure_rolls_back_compose(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:latest", "sha256:old-config", "sha256:old")
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_image_state(
            "repo/app@sha256:child",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        self.set_manifest_stdout(
            "docker.io/repo/app@sha256:child",
            manifest_image("sha256:new-config"),
        )
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "digest-pinned image failed health check\n",
            encoding="utf-8",
        )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            "compose_file=\"${2:?compose file is required}\"\n"
            "if grep -q 'repo/app@sha256:child' \"$compose_file\"; then\n"
            "  printf '/cid-app|running|unhealthy|1|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "else\n"
            "  printf '/cid-app|running|healthy|0|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest@sha256:child\n",
        )
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("image: repo/app:latest", content)
        self.assertNotIn("image: repo/app@sha256:child", content)
        self.assertNotIn("wud-updater.resolved-tag", content)
        incidents = sorted(stack_dir.glob("error-*.logs"))
        self.assertTrue(incidents)
        incident = incidents[-1].read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", incident)
        self.assertIn("manual_review_required=no", incident)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "health-failed")

    def test_digest_pin_apply_revalidates_tagged_digest_with_verbose_docker(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        self.set_image_state("repo/app:latest", "sha256:old-config", "sha256:old")
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_image_state(
            "repo/app@sha256:child",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            [verbose_manifest_item("sha256:child")],
        )

        status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("image: repo/app@sha256:child", content)
        calls = self.calls()
        self.assertEqual(
            calls.count("manifest inspect --verbose docker.io/repo/app:latest"),
            2,
        )
        self.assertTrue(
            all(
                "--verbose" in call.split()
                for call in calls.splitlines()
                if call.startswith("manifest inspect ")
                and "docker.io/repo/app:latest" in call.split()
            ),
            calls,
        )

    def test_digest_pin_apply_updates_existing_tagged_digest_pin(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app@sha256:old", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    # wud-updater.resolved-tag=latest",
                    "    image: repo/app@sha256:old",
                    "    labels:",
                    "      - wud.tag.include=^latest$$",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.set_image_state(
            "repo/app@sha256:old",
            "sha256:old-config",
            "sha256:old",
        )
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_image_state(
            "repo/app@sha256:child",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )
        self.set_manifest_stdout(
            "docker.io/repo/app@sha256:child",
            manifest_image("sha256:new-config"),
        )

        status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("# wud-updater.resolved-tag=latest", content)
        self.assertIn("image: repo/app@sha256:child", content)
        self.assertIn("wud.tag.include=^latest$$", content)
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml pull app")
        events = self.db_rows("SELECT * FROM update_events")
        self.assertEqual(events[0]["target_image"], "repo/app@sha256:child")

    def test_digest_pin_apply_updates_existing_tagged_digest_pin_with_tag_ref(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:latest@sha256:old", "cid-app")],
        )
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    # wud-updater.resolved-tag=latest",
                    "    image: repo/app:latest@sha256:old",
                    "    labels:",
                    "      - wud.tag.include=^latest$$",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.set_image_state(
            "repo/app:latest@sha256:old",
            "sha256:old-config",
            "sha256:old",
        )
        self.set_image_after_pull(
            "repo/app:latest",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_image_state(
            "repo/app@sha256:child",
            "sha256:new-config",
            "sha256:child",
        )
        self.set_manifest_stdout(
            "docker.io/repo/app:latest",
            manifest_index_digest("sha256:index", "sha256:child"),
        )

        status, stdout, stderr = self.run_direct(digest_pin_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("# wud-updater.resolved-tag=latest", content)
        self.assertIn("image: repo/app@sha256:child", content)
        self.assertNotIn("image: repo/app:latest@sha256:old", content)
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml pull app")
        events = self.db_rows("SELECT * FROM update_events")
        self.assertEqual(events[0]["target_image"], "repo/app@sha256:child")

    def test_digest_pin_disabled_does_not_rematch_existing_tagged_digest_pin(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app@sha256:old", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    # wud-updater.resolved-tag=latest",
                    "    image: repo/app@sha256:old",
                    "    labels:",
                    "      - wud.tag.include=^latest$$",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.set_image_state(
            "repo/app@sha256:old",
            "sha256:old-config",
            "sha256:old",
        )

        status, stdout, stderr = self.run_direct(digest_pin_updates=False)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest@sha256:child\n",
        )
        self.assertIn(
            "image: repo/app@sha256:old",
            compose_file.read_text(encoding="utf-8"),
        )
        self.assertNotRegex(self.calls(), r"compose -f docker-compose.yml pull app")
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(pending[0]["status_reason"], "unmatched")

    def test_digest_pin_plan_does_not_rematch_existing_pin_when_disabled(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest@sha256:child\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app@sha256:old", "cid-app")])
        (stack_dir / "docker-compose.yml").write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    # wud-updater.resolved-tag=latest",
                    "    image: repo/app@sha256:old",
                    "    labels:",
                    "      - wud.tag.include=^latest$$",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        config = load_config(
            {
                "DOCKER_BASE": str(self.base),
                "WUD_OUT_FILE": str(self.wud_file),
                "WUD_LOG_DIR": str(self.log_dir),
                "WUD_DIGEST_PIN_UPDATES": "false",
            },
            home=str(self.root),
        )

        plan = build_dry_run_plan(
            config,
            line_numbers=(1,),
            allow_tag_updates=False,
            environ=self.env,
        )

        self.assertEqual(plan.status, "blocked")
        self.assertFalse(plan.digest_pin_updates)
        self.assertEqual(plan.summary.matched_target_count, 0)
        self.assertEqual(plan.targets[0].action, "unmatched")
        self.assertEqual(plan.issues[0].code, "unmatched")

    def test_network_mode_consumer_tag_update_stays_service_scoped(self) -> None:
        compose_file = self.prepare_network_mode_media_stack(
            include_provider_cid=True,
            include_extra_consumer=True,
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

    def test_network_mode_consumer_up_includes_missing_provider(self) -> None:
        compose_file = self.prepare_network_mode_media_stack(
            include_provider_cid=False,
            write_provider_hook=True,
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
            r"compose -f docker-compose.yml up -d --remove-orphans gluetun qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up -d .*--no-deps")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*gluetun")

    def test_exclude_tag_line_materializes_service_merged_labels(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "x-base: &base",
                    "  labels:",
                    "    wud.tag.exclude: ^beta",
                    "    foo: bar",
                    "services:",
                    "  app:",
                    "    <<: *base",
                    "    image: repo/app:1.0",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertIn("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)", content)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "tag-excluded")

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
        runner = self.make_runner(allow_tag_updates=True)
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
        runner = self.make_runner(allow_tag_updates=True)
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

    def test_tag_update_pull_rollback_reports_pull_progress_failure(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        (self.fake_root / "stacks" / "app" / "pull_fail").write_text(
            "",
            encoding="utf-8",
        )
        progress = []
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
            progress_callback=progress.append,
        )
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
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
        pull_failures = [
            event
            for event in progress
            if event.phase == "pull" and event.status == "failure"
        ]
        self.assertEqual(len(pull_failures), 1)
        self.assertEqual(pull_failures[0].stack, "app")
        self.assertEqual(pull_failures[0].services, ("app",))
        self.assertEqual(pull_failures[0].line_numbers, (1,))
        self.assertIn("Pull failed after tag rewrite", pull_failures[0].message)
        event_keys = [(event.phase, event.status) for event in progress]
        self.assertLess(
            event_keys.index(("pull", "failure")),
            event_keys.index(("completion", "failure")),
        )

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

    def test_ghcr_tag_update_with_digest_checks_rewritten_tag(self) -> None:
        self.wud_file.write_text(
            "acme/app:1.0@sha256:child tag=2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "ghcr.io/acme/app:1.0", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:1.0", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:2.0",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:2.0",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct(allow_tag_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/acme/app:2.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:2.0", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:child", calls)

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
                "wud_updater.compose_rewrite._backup_compose",
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
        self.write_tag_update_health_flip_hook()

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

    def test_tag_update_incident_log_uses_configured_owner(self) -> None:
        self.env["OUT_UID"] = str(os.getuid())
        self.env["OUT_GID"] = str(os.getgid())
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        runner = self.make_runner(allow_tag_updates=True)
        stack = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=("app",),
            replacements=1,
        )

        def fake_create(path: Path, content: str, **_: object) -> Path:
            self.assertIn("reason=health-failed", content)
            return path

        with mock.patch(
            "wud_updater.updater_logging._create_unique_text_file_exclusive",
            side_effect=fake_create,
        ) as create_file:
            runner._write_tag_incident_log(
                stack,
                ("app",),
                (applied,),
                "health-failed",
                "restored-and-healthy",
                "health=unhealthy\n",
            )

        self.assertEqual(create_file.call_args.kwargs["owner"], runner.owner)

    def test_tag_incident_log_creation_failure_warns_without_raising(self) -> None:
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        runner = self.make_runner(allow_tag_updates=True)
        stack = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=("app",),
            replacements=1,
        )
        with (
            mock.patch(
                "wud_updater.updater_logging._create_unique_text_file_exclusive",
                side_effect=OSError("permission denied"),
            ),
            mock.patch.object(runner.log, "warn") as warn,
        ):
            runner._write_tag_incident_log(
                stack,
                ("app",),
                (applied,),
                "health-failed",
                "restored-and-healthy",
                "health=unhealthy\n",
            )

        warning = warn.call_args.args[0]
        self.assertIn("Could not create tag update incident log", warning)
        self.assertIn("permission denied", warning)

    def test_tag_incident_creation_does_not_follow_existing_symlink(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        self.write_tag_update_health_flip_hook()
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
            mock.patch("wud_updater.updater_logging.file_timestamp", return_value="fixed"),
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


class ImageWithDigestTests(unittest.TestCase):
    def test_basic_image_with_digest(self) -> None:
        self.assertEqual(
            image_with_digest("repo/app:1.0", "sha256:abc123"),
            "repo/app@sha256:abc123",
        )

    def test_image_with_digest_strips_existing_tag(self) -> None:
        self.assertEqual(
            image_with_digest("repo/app:2.0", "sha256:digest"),
            "repo/app@sha256:digest",
        )

    def test_image_with_digest_preserves_registry(self) -> None:
        self.assertEqual(
            image_with_digest("ghcr.io/org/app:1.0", "sha256:abc"),
            "ghcr.io/org/app@sha256:abc",
        )

    def test_image_with_digest_strips_existing_digest(self) -> None:
        self.assertEqual(
            image_with_digest("repo/app@sha256:old", "sha256:new"),
            "repo/app@sha256:new",
        )

    def test_image_with_digest_normalizes_bare_hash(self) -> None:
        result = image_with_digest("repo/app:1.0", "abc123")
        self.assertIn("sha256:abc123", result)

    def test_image_with_digest_docker_hub_registry(self) -> None:
        self.assertEqual(
            image_with_digest("docker.io/library/nginx:latest", "sha256:hash"),
            "docker.io/library/nginx@sha256:hash",
        )


class UpdatedImagesTests(unittest.TestCase):
    def test_matches_rewritten_image_reference_by_repository_identity(self) -> None:
        before = {
            "repo/app:1.0": ImageState(
                image_id="sha256:old",
                digest="repo/app:1.0@sha256:old",
            ),
        }
        after = {
            "repo/app:2.0": ImageState(
                image_id="sha256:new",
                digest="repo/app:2.0@sha256:new",
            ),
        }

        self.assertEqual(
            _updated_images(before, after),
            [("repo/app:1.0", after["repo/app:2.0"])],
        )


class PayloadDigestTests(unittest.TestCase):
    def test_direct_digest_field(self) -> None:
        payload = {"digest": "sha256:abc123", "other": "value"}
        self.assertEqual(_payload_digest(payload), "sha256:abc123")

    def test_descriptor_digest_field(self) -> None:
        payload = {"Descriptor": {"digest": "sha256:desc456"}}
        self.assertEqual(_payload_digest(payload), "sha256:desc456")

    def test_direct_digest_takes_precedence_over_descriptor(self) -> None:
        payload = {
            "digest": "sha256:direct",
            "Descriptor": {"digest": "sha256:descriptor"},
        }
        self.assertEqual(_payload_digest(payload), "sha256:direct")

    def test_non_sha256_direct_digest_falls_through_to_descriptor(self) -> None:
        payload = {
            "digest": "md5:notsha",
            "Descriptor": {"digest": "sha256:descriptor"},
        }
        self.assertEqual(_payload_digest(payload), "sha256:descriptor")

    def test_no_digest_returns_empty_string(self) -> None:
        self.assertEqual(_payload_digest({}), "")

    def test_descriptor_without_sha256_returns_empty(self) -> None:
        payload = {"Descriptor": {"digest": "notsha256"}}
        self.assertEqual(_payload_digest(payload), "")

    def test_non_string_digest_returns_empty(self) -> None:
        self.assertEqual(_payload_digest({"digest": 12345}), "")

    def test_non_mapping_descriptor_is_skipped(self) -> None:
        payload = {"Descriptor": "not-a-mapping"}
        self.assertEqual(_payload_digest(payload), "")

    def test_descriptor_with_non_string_digest_returns_empty(self) -> None:
        payload = {"Descriptor": {"digest": None}}
        self.assertEqual(_payload_digest(payload), "")


class DockerManifestResolverVerboseTests(FakeDockerTestCase):
    def test_verbose_false_uses_regular_manifest_inspect(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:1.0",
            {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json"},
        )
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        resolver = DockerManifestResolver(docker, verbose=False)

        from wud_updater.digest_verifier import parse_registry_image
        reg_image = parse_registry_image("docker.io/repo/app:1.0")
        assert reg_image is not None
        doc = resolver.fetch(reg_image, reg_image.tag)

        self.assertEqual(doc.source, "docker-manifest")
        self.assertEqual(doc.digest, "")
        self.assertIn("manifest inspect docker.io/repo/app:1.0", self._calls())
        self.assertNotIn("--verbose", self._calls())

    def test_verbose_true_uses_verbose_manifest_inspect(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:1.0",
            manifest_index_digest("sha256:idx", "sha256:child"),
        )
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        resolver = DockerManifestResolver(docker, verbose=True)

        from wud_updater.digest_verifier import parse_registry_image
        reg_image = parse_registry_image("docker.io/repo/app:1.0")
        assert reg_image is not None
        doc = resolver.fetch(reg_image, reg_image.tag)

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "sha256:idx")
        self.assertIn("manifest inspect --verbose docker.io/repo/app:1.0", self._calls())

    def test_verbose_true_with_direct_digest_field(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:2.0",
            {"digest": "sha256:direct", "schemaVersion": 2},
        )
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        resolver = DockerManifestResolver(docker, verbose=True)

        from wud_updater.digest_verifier import parse_registry_image
        reg_image = parse_registry_image("docker.io/repo/app:2.0")
        assert reg_image is not None
        doc = resolver.fetch(reg_image, reg_image.tag)

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "sha256:direct")

    def test_verbose_true_accepts_manifest_list_array(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:3.0",
            [
                verbose_manifest_item("sha256:amd64"),
                verbose_manifest_item("sha256:arm64", architecture="arm64"),
            ],
        )
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        resolver = DockerManifestResolver(docker, verbose=True)

        from wud_updater.digest_verifier import parse_registry_image
        reg_image = parse_registry_image("docker.io/repo/app:3.0")
        assert reg_image is not None
        doc = resolver.fetch(reg_image, reg_image.tag)

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "")
        self.assertTrue(doc.is_index())
        self.assertEqual(doc.child_digests(), ("sha256:amd64", "sha256:arm64"))


class DigestVerifierResolveTagDigestTests(FakeDockerTestCase):
    def _make_verifier(self) -> "DigestVerifier":
        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        resolver = DockerManifestResolver(docker, verbose=True)
        return DigestVerifier(docker, primary_resolver=resolver, fallback_resolver=resolver)

    def test_unsupported_image_reference_returns_not_ok(self) -> None:
        verifier = self._make_verifier()
        result = verifier.resolve_tag_digest("local-image-no-registry")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "untrusted")
        self.assertEqual(result.reason, "unsupported-image-reference")

    def test_failed_manifest_lookup_returns_not_ok(self) -> None:
        self._set_manifest_failure("docker.io/repo/app:1.0", "manifest not found\n")
        verifier = self._make_verifier()
        result = verifier.resolve_tag_digest("repo/app:1.0")
        self.assertFalse(result.ok)
        self.assertIn("unavailable", result.reason)
        self.assertIn("manifest", result.error.lower())

    def test_manifest_without_digest_returns_not_ok(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:1.0",
            {"schemaVersion": 2},
        )
        verifier = self._make_verifier()
        result = verifier.resolve_tag_digest("repo/app:1.0")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "manifest-digest-missing")

    def test_success_with_descriptor_digest(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:2.0",
            manifest_index_digest("sha256:resolved", "sha256:child"),
        )
        verifier = self._make_verifier()
        result = verifier.resolve_tag_digest("repo/app:2.0")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.reason, "tag-digest-resolved")
        self.assertEqual(result.digest, "sha256:resolved")

    def test_success_source_is_populated(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:3.0",
            manifest_index_digest("sha256:abc", "sha256:child"),
        )
        verifier = self._make_verifier()
        result = verifier.resolve_tag_digest("repo/app:3.0")
        self.assertTrue(result.ok)
        self.assertIn("docker-manifest", result.source)

    def test_verbose_manifest_list_uses_registry_header_for_index_digest(self) -> None:
        self._set_manifest_stdout(
            "docker.io/repo/app:4.0",
            [
                verbose_manifest_item("sha256:amd64"),
                verbose_manifest_item("sha256:arm64", architecture="arm64"),
            ],
        )
        verifier = self._make_verifier()

        with mock.patch(
            "wud_updater.digest_verifier.RegistryHttpManifestResolver.fetch",
            return_value=ManifestDocument(
                source="registry-http:registry-1.docker.io",
                digest="sha256:index",
                media_type=MANIFEST_INDEX_TYPE,
                payload=manifest_index("sha256:amd64", "sha256:arm64"),
            ),
        ):
            result = verifier.resolve_tag_digest("repo/app:4.0")

        self.assertTrue(result.ok)
        self.assertEqual(result.digest, "sha256:index")


class DigestPinUpdateFromValuesTests(unittest.TestCase):
    def test_produces_correct_fields(self) -> None:
        update = digest_pin_update_from_values(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            planned_digest="sha256:abcdef",
            services=("app", "worker"),
        )
        self.assertEqual(update.old_image, "repo/app:1.0")
        self.assertEqual(update.resolved_tag, "2.0")
        self.assertEqual(update.resolved_image, "repo/app:2.0")
        self.assertEqual(update.planned_digest, "sha256:abcdef")
        self.assertEqual(update.final_image, "repo/app@sha256:abcdef")
        self.assertEqual(update.watch_tag, "2.0")
        self.assertEqual(update.marker, "wud-updater.resolved-tag=2.0")
        self.assertEqual(update.label_key, "wud.tag.include")
        self.assertIn("2", update.label_value)
        self.assertEqual(update.services, ("app", "worker"))

    def test_services_are_sorted(self) -> None:
        update = digest_pin_update_from_values(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            planned_digest="sha256:abc",
            services=("worker", "app"),
        )
        self.assertEqual(update.services, ("app", "worker"))

    def test_normalizes_bare_digest(self) -> None:
        update = digest_pin_update_from_values(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            planned_digest="abcdef",
            services=("app",),
        )
        self.assertTrue(update.planned_digest.startswith("sha256:"))
        self.assertTrue(update.final_image.startswith("repo/app@sha256:"))

    def test_label_value_is_exact_regex_for_tag(self) -> None:
        update = digest_pin_update_from_values(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            planned_digest="sha256:abc",
            services=("app",),
        )
        # The label value should be an escaped exact tag regex with $$ for Compose
        self.assertIn("2\\.0", update.label_value)
        self.assertIn("^", update.label_value)
        self.assertIn("$", update.label_value)

    def test_ghcr_registry_preserved_in_final_image(self) -> None:
        update = digest_pin_update_from_values(
            old_image="ghcr.io/org/app:1.0",
            resolved_tag="2.0",
            planned_digest="sha256:hash",
            services=("app",),
        )
        self.assertTrue(update.final_image.startswith("ghcr.io/org/app@sha256:"))


class DigestPinNoTagRequiredTests(FakeDockerTestCase):
    """Tests for _validate_digest_pin_plan rejecting lines without resolved tags."""

    def test_digest_pin_without_tag_rejects_at_preflight(self) -> None:
        """digest_pin_updates=True without a tag token should fail at preflight."""
        self.wud_file.write_text("repo/app:1.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        command_runner = CommandRunner(env=self.env)
        docker = DockerCli(runner=command_runner)
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
            digest_pin_updates=True,
            no_color=True,
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=command_runner,
            digest_verifier=DigestVerifier(
                docker,
                primary_resolver=FailingManifestResolver(),
                fallback_resolver=DockerManifestResolver(docker),
            ),
        )
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = runner.run()

        # A non-tag-update line with digest_pin_updates=True should fail closed
        self.assertEqual(status, 1)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    unittest.main()
