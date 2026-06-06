from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from tests.test_python_db import V4_SCHEMA_SQL
except ModuleNotFoundError:
    from test_python_db import V4_SCHEMA_SQL

from wud_updater.db import SCHEMA_VERSION, init_db, open_db
from wud_updater.release_notes import (
    SEMVER_RE,
    GitHubClient,
    _block_header_text,
    _markdown_bullet,
    _strip_lsio_suffix,
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


class BlockHeaderTextTests(unittest.TestCase):
    def test_plain_header_with_colon(self) -> None:
        self.assertEqual(_block_header_text("Remote Changes:"), "Remote Changes:")

    def test_markdown_h2_header_stripped(self) -> None:
        self.assertEqual(_block_header_text("## Remote Changes:"), "Remote Changes:")

    def test_markdown_h3_header_stripped(self) -> None:
        self.assertEqual(_block_header_text("### LinuxServer Changes:"), "LinuxServer Changes:")

    def test_markdown_h1_header_stripped(self) -> None:
        self.assertEqual(_block_header_text("# Top Level:"), "Top Level:")

    def test_bold_markdown_header_unwrapped(self) -> None:
        self.assertEqual(_block_header_text("**Remote Changes:**"), "Remote Changes:")

    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        self.assertEqual(_block_header_text("  Remote Changes:  "), "Remote Changes:")

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(_block_header_text(""), "")

    def test_plain_text_without_colon_returned_as_is(self) -> None:
        self.assertEqual(_block_header_text("Just a sentence"), "Just a sentence")

    def test_h6_header_stripped(self) -> None:
        self.assertEqual(_block_header_text("###### Deep:"), "Deep:")


class MarkdownBulletTests(unittest.TestCase):
    def test_star_bullet_returns_true(self) -> None:
        self.assertTrue(_markdown_bullet("* item"))

    def test_dash_bullet_returns_true(self) -> None:
        self.assertTrue(_markdown_bullet("- item"))

    def test_plus_bullet_returns_true(self) -> None:
        self.assertTrue(_markdown_bullet("+ item"))

    def test_unicode_bullet_returns_true(self) -> None:
        self.assertTrue(_markdown_bullet("• item"))

    def test_non_bullet_plain_text_returns_false(self) -> None:
        self.assertFalse(_markdown_bullet("Remote Changes:"))

    def test_hash_header_returns_false(self) -> None:
        self.assertFalse(_markdown_bullet("## Header"))

    def test_empty_string_returns_false(self) -> None:
        self.assertFalse(_markdown_bullet(""))

    def test_bullet_requires_whitespace_after_marker(self) -> None:
        # A bare "*" without trailing space should not match
        self.assertFalse(_markdown_bullet("*no-space"))


class StripLsioSuffixTests(unittest.TestCase):
    def test_strips_simple_ls_suffix(self) -> None:
        self.assertEqual(_strip_lsio_suffix("1.2.3-ls14"), "1.2.3")

    def test_strips_ls_suffix_with_extra_segment(self) -> None:
        self.assertEqual(_strip_lsio_suffix("1.2.3-ls14-beta"), "1.2.3")

    def test_strips_ls_suffix_case_insensitive(self) -> None:
        self.assertEqual(_strip_lsio_suffix("5.1.0-LS4"), "5.1.0")

    def test_strips_ls_suffix_with_dot_separator(self) -> None:
        self.assertEqual(_strip_lsio_suffix("1.2.3.ls14"), "1.2.3")

    def test_no_suffix_returns_value_unchanged(self) -> None:
        self.assertEqual(_strip_lsio_suffix("1.2.3"), "1.2.3")

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(_strip_lsio_suffix(""), "")

    def test_strips_only_trailing_ls_suffix(self) -> None:
        # "lsio" embedded in the version should not be affected
        self.assertEqual(_strip_lsio_suffix("1.2.3-ls14-patch1"), "1.2.3")

    def test_does_not_strip_non_ls_suffix(self) -> None:
        self.assertEqual(_strip_lsio_suffix("1.2.3-beta"), "1.2.3-beta")


class SemverReTests(unittest.TestCase):
    def test_matches_three_part_version(self) -> None:
        m = SEMVER_RE.search("version 1.2.3 available")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "1.2.3")  # type: ignore[union-attr]

    def test_matches_two_part_version(self) -> None:
        m = SEMVER_RE.search("Upgrade to v2.0")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "v2.0")  # type: ignore[union-attr]

    def test_matches_four_part_version(self) -> None:
        m = SEMVER_RE.search("1.2.3.4")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "1.2.3.4")  # type: ignore[union-attr]

    def test_does_not_match_version_embedded_in_word(self) -> None:
        # "python3.11" should not be matched since 3 is preceded by a letter
        m = SEMVER_RE.search("python3.11 package")
        self.assertIsNone(m)

    def test_does_not_match_version_followed_by_alphanumeric(self) -> None:
        # A version immediately followed by a letter should not match
        m = SEMVER_RE.search("abc1.2.3xyz")
        self.assertIsNone(m)

    def test_matches_version_with_prerelease_suffix(self) -> None:
        m = SEMVER_RE.search("v1.2.3-beta.1")
        self.assertIsNotNone(m)
        self.assertTrue(m.group(0).startswith("v1.2.3"))  # type: ignore[union-attr]

    def test_v_prefix_is_optional(self) -> None:
        m1 = SEMVER_RE.search("1.0.0")
        m2 = SEMVER_RE.search("v1.0.0")
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)

    def test_major_group_captures_major_number(self) -> None:
        m = SEMVER_RE.search("v3.4.5")
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 3)  # type: ignore[union-attr]

    def test_detect_breaking_with_two_part_major_bump(self) -> None:
        # Regression: two-part versions like v1.2 -> v2.0 should be detected as breaking
        breaking, reasons = detect_breaking("Routine update", "v1.2", "v2.0")

        self.assertTrue(breaking)
        self.assertTrue(any("Major version" in reason for reason in reasons))

    def test_detect_breaking_two_part_minor_bump_not_breaking(self) -> None:
        breaking, _ = detect_breaking("Routine update", "v1.2", "v1.3")

        self.assertFalse(breaking)


if __name__ == "__main__":
    unittest.main()
