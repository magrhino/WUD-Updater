from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wud_updater.db import connect_db, init_db
from wud_updater.release_notes import (
    GitHubClient,
    detect_breaking,
    release_note_contexts,
    refresh_release_notes,
)
from wud_updater.wud_file import parse_wud_text


class ReleaseNotesTests(unittest.TestCase):
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
        with connect_db(":memory:") as conn:
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

        with connect_db(":memory:") as conn:
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
            with connect_db(":memory:") as conn:
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
            with connect_db(db_path) as conn:
                init_db(conn)
                with conn:
                    conn.execute("DROP TABLE release_note_cache")
                    conn.execute("DELETE FROM schema_migrations WHERE version = 5")
                    conn.execute("PRAGMA user_version = 4")

            with connect_db(db_path) as conn:
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

        self.assertEqual(version, 5)
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
