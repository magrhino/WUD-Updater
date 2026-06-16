from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from tests.test_python_db import V4_SCHEMA_SQL
except ModuleNotFoundError:
    from test_python_db import V4_SCHEMA_SQL

from wud_updater.db import SCHEMA_VERSION, init_db, open_db
from wud_updater.release_notes import (
    GitHubClient,
    detect_breaking,
    release_note_contexts,
    refresh_release_notes,
)
from wud_updater.wud_file import parse_wud_text

PARITY_SPEC = Path(__file__).with_name("fixtures") / "release-note-parity.json"


def parity_case(name: str) -> dict[str, object]:
    return json.loads(PARITY_SPEC.read_text(encoding="utf-8"))[name]


class ReleaseNotesTests(unittest.TestCase):
    def test_shared_parity_spec_covers_repo_routing(self) -> None:
        ghcr = parity_case("ghcr_major")
        parsed = parse_wud_text(str(ghcr["image"]))

        contexts = release_note_contexts(parsed.targets, {})

        self.assertEqual(contexts[0].provider, ghcr["provider"])
        self.assertEqual(contexts[0].image_repo, ghcr["repo"])
        self.assertEqual(contexts[0].upstream_repo, ghcr["repo"])
        self.assertEqual(contexts[0].current_tag, ghcr["current_tag"])

        oci = parity_case("oci_source")
        parsed = parse_wud_text(str(oci["image"]))
        contexts = release_note_contexts(
            parsed.targets,
            {},
            source_resolver=lambda _target: str(oci["source"]),
        )

        self.assertEqual(contexts[0].provider, oci["provider"])
        self.assertEqual(contexts[0].image_repo, oci["repo"])
        self.assertEqual(contexts[0].upstream_repo, oci["repo"])

        lsio = parity_case("lsio_radarr")
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                f"{lsio['lsio_repo']}: {lsio['upstream_repo']}\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(str(lsio["image"]))
            contexts = release_note_contexts(
                parsed.targets,
                {"UPSTREAM_MAP": str(upstream_map)},
            )

        self.assertEqual(contexts[0].provider, lsio["provider"])
        self.assertEqual(contexts[0].image_repo, lsio["lsio_repo"])
        self.assertEqual(contexts[0].upstream_repo, lsio["upstream_repo"])

    def test_shared_parity_spec_covers_breaking_and_lsio_semver(self) -> None:
        ghcr = parity_case("ghcr_major")
        breaking, _reasons = detect_breaking(
            str(ghcr["release_body"]),
            str(ghcr["current_tag"]),
            str(ghcr["release_tag"]),
        )

        self.assertEqual(breaking, ghcr["breaking"])

        lsio = parity_case("lsio_remote_semver")
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                f"{lsio['lsio_repo']}: {lsio['upstream_repo']}\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(str(lsio["image"]))
            responses = {
                f"https://api.github.com/repos/{lsio['lsio_repo']}/releases/latest": {
                    "tag_name": lsio["lsio_tag"],
                    "name": lsio["lsio_tag"],
                    "html_url": (
                        "https://github.com/"
                        f"{lsio['lsio_repo']}/releases/tag/{lsio['lsio_tag']}"
                    ),
                    "body": lsio["lsio_body"],
                    "published_at": "2026-01-02T00:00:00Z",
                },
                (
                    "https://api.github.com/repos/"
                    f"{lsio['upstream_repo']}/releases/tags/{lsio['upstream_tag']}"
                ): {
                    "tag_name": lsio["upstream_tag"],
                    "name": lsio["upstream_tag"],
                    "html_url": (
                        "https://github.com/"
                        f"{lsio['upstream_repo']}/releases/tag/{lsio['upstream_tag']}"
                    ),
                    "body": "Routine update",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            client = GitHubClient(fetch_json=lambda url: responses[url])
            with open_db(":memory:") as conn:
                init_db(conn)
                items = refresh_release_notes(
                    conn,
                    parsed.targets,
                    {"UPSTREAM_MAP": str(upstream_map)},
                    client=client,
                )

        self.assertEqual(items[0].provider, "lsio")
        self.assertEqual(items[0].release_tag, lsio["upstream_tag"])

    def test_detect_breaking_uses_keywords_and_major_bumps(self) -> None:
        breaking, reasons = detect_breaking(
            "This release includes a required migration.",
            "1.4.0",
            "1.5.0",
        )

        self.assertTrue(breaking)
        self.assertTrue(any("migration" in reason for reason in reasons))

        breaking, reasons = detect_breaking("Routine update", "1.4.0", "2.0.0")

        self.assertTrue(breaking)
        self.assertTrue(any("Major version" in reason for reason in reasons))

        breaking, reasons = detect_breaking("Routine update", "v1.2", "v2.0")

        self.assertTrue(breaking)
        self.assertTrue(any("Major version" in reason for reason in reasons))

    def test_ghcr_release_metadata_marks_breaking_major_bump(self) -> None:
        parsed = parse_wud_text("ghcr.io/acme/app:1.0.0\n")
        client = GitHubClient(
            fetch_json=lambda url: {
                "https://api.github.com/repos/acme/app/releases/latest": {
                    "tag_name": "v2.0.0",
                    "name": "v2.0.0",
                    "html_url": "https://github.com/acme/app/releases/tag/v2.0.0",
                    "body": "Routine update",
                    "published_at": "2026-01-02T00:00:00Z",
                }
            }[url]
        )
        with open_db(":memory:") as conn:
            init_db(conn)
            items = refresh_release_notes(conn, parsed.targets, {}, client=client)

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].provider, "github")
        self.assertEqual(items[0].release_tag, "v2.0.0")
        self.assertTrue(items[0].breaking)
        self.assertEqual(items[0].links[0].label, "GitHub release")

    def test_ghcr_detection_requires_registry_component(self) -> None:
        parsed = parse_wud_text("registry.example.com/ghcr.io/acme/app:1.0.0\n")

        contexts = release_note_contexts(parsed.targets, {})

        self.assertEqual(contexts[0].provider, "unsupported")
        self.assertEqual(contexts[0].error, "no supported GitHub release source found")

    def test_docker_source_label_routes_docker_hub_image_to_github(self) -> None:
        parsed = parse_wud_text("advplyr/audiobookshelf:latest\n")

        contexts = release_note_contexts(
            parsed.targets,
            {},
            source_resolver=lambda _target: "https://github.com/advplyr/audiobookshelf",
        )

        self.assertEqual(contexts[0].provider, "github")
        self.assertEqual(contexts[0].image_repo, "advplyr/audiobookshelf")
        self.assertEqual(contexts[0].upstream_repo, "advplyr/audiobookshelf")

    def test_docker_source_label_release_metadata_includes_github_link(self) -> None:
        parsed = parse_wud_text("advplyr/audiobookshelf:latest\n")
        client = GitHubClient(
            fetch_json=lambda url: {
                "https://api.github.com/repos/advplyr/audiobookshelf/releases/latest": {
                    "tag_name": "v2.35.1",
                    "name": "v2.35.1",
                    "html_url": (
                        "https://github.com/advplyr/audiobookshelf/releases/tag/v2.35.1"
                    ),
                    "body": "Routine update",
                    "published_at": "2026-05-27T20:00:00Z",
                }
            }[url]
        )

        with open_db(":memory:") as conn:
            init_db(conn)
            items = refresh_release_notes(
                conn,
                parsed.targets,
                {},
                client=client,
                source_resolver=lambda _target: (
                    "https://github.com/advplyr/audiobookshelf"
                ),
            )

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].provider, "github")
        self.assertEqual(items[0].release_tag, "v2.35.1")
        self.assertEqual(items[0].links[0].label, "GitHub release")

    def test_lsio_release_metadata_includes_both_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-radarr: Radarr/Radarr\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/radarr:latest\n")
            responses = {
                "https://api.github.com/repos/linuxserver/docker-radarr/releases/latest": {
                    "tag_name": "5.1.0-ls1",
                    "name": "5.1.0-ls1",
                    "html_url": "https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls1",
                    "body": "LinuxServer Changes:\n- Rebase to Alpine 3.20\n\nRemote Changes:\n- Updating to 5.1.0",
                    "published_at": "2026-01-02T00:00:00Z",
                },
                "https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0": {
                    "tag_name": "v5.1.0",
                    "name": "v5.1.0",
                    "html_url": "https://github.com/Radarr/Radarr/releases/tag/v5.1.0",
                    "body": "Routine update",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            client = GitHubClient(fetch_json=lambda url: responses[url])
            with open_db(":memory:") as conn:
                init_db(conn)
                items = refresh_release_notes(
                    conn,
                    parsed.targets,
                    {"UPSTREAM_MAP": str(upstream_map)},
                    client=client,
                )

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].provider, "lsio")
        self.assertEqual(
            [(link.label, link.kind) for link in items[0].links],
            [("LSIO release", "lsio_release"), ("Upstream release", "github_release")],
        )

    def test_lsio_remote_changes_accept_markdown_header_and_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-radarr: Radarr/Radarr\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/radarr:latest\n")
            responses = {
                "https://api.github.com/repos/linuxserver/docker-radarr/releases/latest": {
                    "tag_name": "1.2.3-ls14",
                    "name": "1.2.3-ls14",
                    "html_url": "https://github.com/linuxserver/docker-radarr/releases/tag/1.2.3-ls14",
                    "body": (
                        "### Remote Changes:\n"
                        "- Updated dependencies:\n"
                        "  - package one\n"
                        "- Updating to v1.2.3-beta.1.\n"
                        "\n"
                        "LinuxServer Changes:\n"
                        "- Rebase to Alpine 3.20"
                    ),
                    "published_at": "2026-01-02T00:00:00Z",
                },
                "https://api.github.com/repos/Radarr/Radarr/releases/tags/v1.2.3-beta.1": {
                    "tag_name": "v1.2.3-beta.1",
                    "name": "v1.2.3-beta.1",
                    "html_url": "https://github.com/Radarr/Radarr/releases/tag/v1.2.3-beta.1",
                    "body": "Routine update",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            client = GitHubClient(fetch_json=lambda url: responses[url])
            with open_db(":memory:") as conn:
                init_db(conn)
                items = refresh_release_notes(
                    conn,
                    parsed.targets,
                    {"UPSTREAM_MAP": str(upstream_map)},
                    client=client,
                )

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].release_tag, "v1.2.3-beta.1")

    def test_lsio_tag_fallback_strips_linuxserver_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-radarr: Radarr/Radarr\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/radarr:latest\n")
            responses = {
                "https://api.github.com/repos/linuxserver/docker-radarr/releases/latest": {
                    "tag_name": "5.1.0-ls14-beta",
                    "name": "5.1.0-ls14-beta",
                    "html_url": "https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls14-beta",
                    "body": "LinuxServer Changes:\n- Rebase to Alpine 3.20",
                    "published_at": "2026-01-02T00:00:00Z",
                },
                "https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0": {
                    "tag_name": "v5.1.0",
                    "name": "v5.1.0",
                    "html_url": "https://github.com/Radarr/Radarr/releases/tag/v5.1.0",
                    "body": "Routine update",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            client = GitHubClient(fetch_json=lambda url: responses[url])
            with open_db(":memory:") as conn:
                init_db(conn)
                items = refresh_release_notes(
                    conn,
                    parsed.targets,
                    {"UPSTREAM_MAP": str(upstream_map)},
                    client=client,
                )

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].release_tag, "v5.1.0")

    def test_lsio_mapping_takes_precedence_over_docker_source_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-calibre: kovidgoyal/calibre\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/calibre:latest\n")

            contexts = release_note_contexts(
                parsed.targets,
                {"UPSTREAM_MAP": str(upstream_map)},
                source_resolver=lambda _target: (
                    "https://github.com/linuxserver/docker-calibre"
                ),
            )

        self.assertEqual(contexts[0].provider, "lsio")
        self.assertEqual(contexts[0].image_repo, "linuxserver/docker-calibre")
        self.assertEqual(contexts[0].upstream_repo, "kovidgoyal/calibre")

    def test_v4_database_migrates_release_note_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wud.sqlite"
            with open_db(db_path) as conn:
                conn.executescript(V4_SCHEMA_SQL)
                with conn:
                    conn.execute("PRAGMA user_version = 4")

            with open_db(db_path) as conn:
                init_db(conn)
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                row = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'release_note_cache'
                    """
                ).fetchone()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
