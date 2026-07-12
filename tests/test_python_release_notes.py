from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wudup import release_notes as release_notes_module

try:
    from tests.test_python_db import V4_SCHEMA_SQL
except ModuleNotFoundError:
    from test_python_db import V4_SCHEMA_SQL

from wudup.db import SCHEMA_VERSION, init_db, open_db
from wudup.release_notes import (
    GitHubClient,
    ReleaseNoteInfo,
    ReleaseNoteLink,
    _github_release_link_tag,
    cached_release_notes,
    detect_breaking,
    github_latest_candidate_from_info,
    release_note_contexts,
    refresh_release_notes,
)
from wudup.wud_file import parse_wud_text

PARITY_SPEC = Path(__file__).with_name("fixtures") / "release-note-parity.json"


def parity_case(name: str) -> dict[str, object]:
    return json.loads(PARITY_SPEC.read_text(encoding="utf-8"))[name]


def qbittorrent_upstream_responses(composite_tag: str) -> dict[str, dict[str, str]]:
    base_url = "https://api.github.com/repos/qbittorrent/qBittorrent/releases/tags"
    return {
        f"{base_url}/v{composite_tag}": {"message": "Not Found"},
        f"{base_url}/{composite_tag}": {"message": "Not Found"},
        f"{base_url}/v5.2.2": {
            "tag_name": "v5.2.2",
            "name": "qBittorrent v5.2.2",
            "html_url": (
                "https://github.com/qbittorrent/qBittorrent/releases/tag/"
                "release-5.2.2"
            ),
            "body": "qBittorrent upstream release notes.",
            "published_at": "2026-06-16T04:33:00Z",
        },
    }


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
            cached_body = conn.execute(
                "SELECT body FROM release_note_cache LIMIT 1"
            ).fetchone()[0]

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].provider, "github")
        self.assertEqual(items[0].release_tag, "v2.0.0")
        self.assertEqual(items[0].body, "Routine update")
        self.assertEqual(cached_body, "Routine update")
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

    def test_latest_target_tag_uses_latest_release_endpoint(self) -> None:
        parsed = parse_wud_text("advplyr/audiobookshelf:latest\n")
        calls: list[str] = []

        def fetch_json(url: str) -> object:
            calls.append(url)
            return {
                "tag_name": "v2.35.1",
                "name": "v2.35.1",
                "html_url": (
                    "https://github.com/advplyr/audiobookshelf/releases/tag/v2.35.1"
                ),
                "body": "Routine update",
                "published_at": "2026-05-27T20:00:00Z",
            }

        with open_db(":memory:") as conn:
            init_db(conn)
            items = refresh_release_notes(
                conn,
                parsed.targets,
                {},
                client=GitHubClient(fetch_json=fetch_json),
                source_resolver=lambda _target: (
                    "https://github.com/advplyr/audiobookshelf"
                ),
                target_tag_resolver=lambda _target: "latest",
            )

        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].release_tag, "v2.35.1")
        self.assertEqual(
            calls,
            ["https://api.github.com/repos/advplyr/audiobookshelf/releases/latest"],
        )

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
            calls: list[str] = []

            def fetch_json(url: str) -> object:
                calls.append(url)
                return responses[url]

            client = GitHubClient(fetch_json=fetch_json)
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
        self.assertTrue(
            any("/repos/Radarr/Radarr/releases/tags/v5.1.0" in call for call in calls)
        )
        self.assertEqual(
            [(link.label, link.kind) for link in items[0].links],
            [("LSIO release", "lsio_release"), ("Upstream release", "github_release")],
        )

    def test_lsio_classification_persists_in_release_note_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-radarr: Radarr/Radarr\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/radarr:5.1.0-ls1 tag=5.1.0-ls2\n")
            lsio_url = (
                "https://api.github.com/repos/linuxserver/docker-radarr/"
                "releases/tags/5.1.0-ls2"
            )
            responses = {
                lsio_url: {
                    "tag_name": "5.1.0-ls2",
                    "name": "5.1.0-ls2",
                    "html_url": "https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls2",
                    "body": "LinuxServer Changes:\n- Rebase to Alpine 3.20",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            calls: list[str] = []

            def fetch_json(url: str) -> object:
                calls.append(url)
                return responses[url]

            client = GitHubClient(fetch_json=fetch_json)
            environ = {"UPSTREAM_MAP": str(upstream_map)}
            with open_db(":memory:") as conn:
                init_db(conn)
                items = refresh_release_notes(
                    conn,
                    parsed.targets,
                    environ,
                    client=client,
                )
                cached = cached_release_notes(conn, parsed.targets, environ)

        self.assertEqual(items[0].classification.change_type, "image_rebuild")
        self.assertEqual(items[0].status, "ready")
        self.assertEqual(items[0].release_tag, "5.1.0-ls2")
        self.assertEqual(
            [(link.label, link.kind) for link in items[0].links],
            [("LSIO release", "lsio_release")],
        )
        self.assertIn(lsio_url, calls)
        self.assertFalse(any(call.endswith("/releases/latest") for call in calls))
        self.assertFalse(any("/repos/Radarr/Radarr" in call for call in calls))
        self.assertEqual(
            items[0].classification.target.build_suffix,
            "ls2",
        )
        self.assertEqual(cached[0].classification.change_type, "image_rebuild")

    def test_lsio_legacy_cache_without_classification_is_reclassified_and_refreshed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-radarr: Radarr/Radarr\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text("linuxserver/radarr:5.1.0-ls1 tag=5.1.0-ls2\n")
            lsio_url = (
                "https://api.github.com/repos/linuxserver/docker-radarr/"
                "releases/tags/5.1.0-ls2"
            )
            responses = {
                lsio_url: {
                    "tag_name": "5.1.0-ls2",
                    "name": "5.1.0-ls2",
                    "html_url": "https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls2",
                    "body": "LinuxServer Changes:\n- Rebase to Alpine 3.20",
                    "published_at": "2026-01-02T00:00:00Z",
                },
            }
            environ = {"UPSTREAM_MAP": str(upstream_map)}
            calls: list[str] = []

            def fetch_json(url: str) -> object:
                calls.append(url)
                return responses[url]

            with open_db(":memory:") as conn:
                init_db(conn)
                refresh_release_notes(
                    conn,
                    parsed.targets,
                    environ,
                    client=GitHubClient(fetch_json=lambda url: responses[url]),
                )
                conn.execute(
                    "UPDATE release_note_cache SET metadata_json = ?",
                    (json.dumps({"line_no": 1}),),
                )

                cached = cached_release_notes(conn, parsed.targets, environ)
                calls.clear()
                refreshed = refresh_release_notes(
                    conn,
                    parsed.targets,
                    environ,
                    client=GitHubClient(fetch_json=fetch_json),
                )
                row = conn.execute(
                    "SELECT metadata_json FROM release_note_cache"
                ).fetchone()

        self.assertEqual(cached[0].classification.change_type, "image_rebuild")
        self.assertGreater(len(calls), 0)
        self.assertEqual(refreshed[0].classification.change_type, "image_rebuild")
        self.assertIn("classification", json.loads(str(row["metadata_json"])))

    def test_lsio_branch_tracking_fetches_matching_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-qbittorrent: qbittorrent/qBittorrent\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(
                "linuxserver/qbittorrent:libtorrentv1-version-v5.2.1_v1.2.20 "
                "tag=libtorrentv1-version-v5.2.2_v1.2.20\n"
            )
            releases_url = (
                "https://api.github.com/repos/"
                "linuxserver/docker-qbittorrent/releases?per_page=30"
            )
            responses = {
                releases_url: [
                    {
                        "tag_name": "5.2.2_v2.0.13-ls464",
                        "name": "5.2.2_v2.0.13-ls464",
                        "html_url": "https://github.com/linuxserver/docker-qbittorrent/releases/tag/5.2.2_v2.0.13-ls464",
                        "body": "Remote Changes:\n- Updating to 5.2.2_v2.0.13",
                        "published_at": "2026-06-28T09:57:00Z",
                    },
                    {
                        "tag_name": "libtorrentv1-5.2.2_v1.2.20-ls122",
                        "name": "libtorrentv1-5.2.2_v1.2.20-ls122",
                        "html_url": "https://github.com/linuxserver/docker-qbittorrent/releases/tag/libtorrentv1-5.2.2_v1.2.20-ls122",
                        "body": "Remote Changes:\n- Updating to 5.2.2_v1.2.20",
                        "published_at": "2026-06-28T09:57:00Z",
                    },
                ],
                **qbittorrent_upstream_responses("5.2.2_v1.2.20"),
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
        self.assertEqual(items[0].release_tag, "v5.2.2")
        self.assertTrue(
            items[0].links[0].url.endswith(
                "/libtorrentv1-5.2.2_v1.2.20-ls122"
            )
        )
        self.assertEqual(items[0].classification.target.branch, "libtorrentv1")
        self.assertEqual(items[0].classification.change_type, "upstream_update")

    def test_lsio_branch_tracking_requires_matching_arch(self) -> None:
        def lsio_release(tag: str) -> dict[str, str]:
            return {
                "tag_name": tag,
                "name": tag,
                "html_url": (
                    "https://github.com/linuxserver/docker-qbittorrent/releases/tag/"
                    f"{tag}"
                ),
                "body": f"Remote Changes:\n- Updating to {tag}",
                "published_at": "2026-06-28T09:57:00Z",
            }

        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-qbittorrent: qbittorrent/qBittorrent\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(
                "linuxserver/qbittorrent:"
                "amd64-libtorrentv1-version-v5.2.1_v1.2.20 "
                "tag=amd64-libtorrentv1-version-v5.2.2_v1.2.20\n"
            )
            releases_url = (
                "https://api.github.com/repos/"
                "linuxserver/docker-qbittorrent/releases?per_page=30"
            )
            responses = {
                releases_url: [
                    lsio_release("arm64v8-libtorrentv1-5.2.2_v1.2.20-ls122"),
                    lsio_release("libtorrentv1-5.2.2_v1.2.20-ls122"),
                    lsio_release("amd64-libtorrentv1-5.2.2_v1.2.20-ls122"),
                ],
                **qbittorrent_upstream_responses("5.2.2_v1.2.20"),
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
        self.assertTrue(
            items[0].links[0].url.endswith(
                "/amd64-libtorrentv1-5.2.2_v1.2.20-ls122"
            )
        )
        self.assertEqual(items[0].classification.target.arch, "amd64")

    def test_lsio_branch_tracking_matches_target_release_across_pages(self) -> None:
        def lsio_release(tag: str) -> dict[str, str]:
            return {
                "tag_name": tag,
                "name": tag,
                "html_url": (
                    "https://github.com/linuxserver/docker-qbittorrent/releases/tag/"
                    f"{tag}"
                ),
                "body": f"Remote Changes:\n- Updating to {tag}",
                "published_at": "2026-06-28T09:57:00Z",
            }

        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-qbittorrent: qbittorrent/qBittorrent\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(
                "linuxserver/qbittorrent:libtorrentv1-version-5.2.1_v1.2.20 "
                "tag=libtorrentv1-version-5.2.2_v1.2.20\n"
            )
            releases_url = (
                "https://api.github.com/repos/"
                "linuxserver/docker-qbittorrent/releases?per_page=30"
            )
            responses = {
                releases_url: [
                    lsio_release("libtorrentv1-5.2.3_v1.2.20-ls123"),
                    *[
                        lsio_release(f"5.2.{index}_v2.0.13-ls{index}")
                        for index in range(29)
                    ],
                ],
                f"{releases_url}&page=2": [
                    lsio_release("libtorrentv1-5.2.2_v1.2.20-ls122")
                ],
                **qbittorrent_upstream_responses("5.2.2_v1.2.20"),
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
        self.assertTrue(
            items[0].links[0].url.endswith(
                "/libtorrentv1-5.2.2_v1.2.20-ls122"
            )
        )

    def test_lsio_branch_tracking_stops_after_page_limit_without_match(self) -> None:
        def lsio_release(index: int) -> dict[str, str]:
            tag = f"5.2.{index}_v2.0.13-ls{index}"
            return {
                "tag_name": tag,
                "name": tag,
                "html_url": (
                    "https://github.com/linuxserver/docker-qbittorrent/releases/tag/"
                    f"{tag}"
                ),
                "body": f"Remote Changes:\n- Updating to {tag}",
                "published_at": "2026-06-28T09:57:00Z",
            }

        releases_url = (
            "https://api.github.com/repos/"
            "linuxserver/docker-qbittorrent/releases?per_page=30"
        )
        calls: list[str] = []

        def fetch_json(url: str) -> object:
            calls.append(url)
            if len(calls) > release_notes_module.LSIO_RELEASE_SCAN_MAX_PAGES:
                self.fail("LSIO release scan exceeded the page cap")
            return [lsio_release(index) for index in range(30)]

        client = GitHubClient(fetch_json=fetch_json)
        context = release_notes_module.ReleaseNoteContext(
            line_no=1,
            cache_key="linuxserver/qbittorrent",
            provider="lsio",
            image_repo="linuxserver/docker-qbittorrent",
            upstream_repo="qbittorrent/qBittorrent",
            current_tag="libtorrentv1-version-5.2.1_v1.2.20",
            target_tag="libtorrentv1-version-5.2.2_v1.2.20",
        )

        release = release_notes_module._fetch_lsio_release(client, context)

        self.assertIsNone(release)
        self.assertEqual(
            len(calls),
            release_notes_module.LSIO_RELEASE_SCAN_MAX_PAGES,
        )
        self.assertEqual(
            calls[-1],
            f"{releases_url}&page={release_notes_module.LSIO_RELEASE_SCAN_MAX_PAGES}",
        )

    def test_lsio_composite_upstream_falls_back_to_semver_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-qbittorrent: qbittorrent/qBittorrent\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(
                "linuxserver/qbittorrent:version-5.2.1_v2.0.13 "
                "tag=version-5.2.2_v2.0.13\n"
            )
            responses = {
                "https://api.github.com/repos/linuxserver/docker-qbittorrent/releases/latest": {
                    "tag_name": "5.2.2_v2.0.13-ls464",
                    "name": "5.2.2_v2.0.13-ls464",
                    "html_url": "https://github.com/linuxserver/docker-qbittorrent/releases/tag/5.2.2_v2.0.13-ls464",
                    "body": "Remote Changes:\n- Updating to 5.2.2_v2.0.13",
                    "published_at": "2026-06-28T09:57:00Z",
                },
                **qbittorrent_upstream_responses("5.2.2_v2.0.13"),
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
        self.assertEqual(items[0].release_tag, "v5.2.2")
        self.assertEqual(items[0].classification.change_type, "upstream_update")

    def test_lsio_release_body_overrides_plain_wud_remote_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upstream_map = Path(tmp) / "upstreams.txt"
            upstream_map.write_text(
                "linuxserver/docker-qbittorrent: qbittorrent/qBittorrent\n",
                encoding="utf-8",
            )
            parsed = parse_wud_text(
                "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=14.3.9\n"
            )
            responses = {
                "https://api.github.com/repos/linuxserver/docker-qbittorrent/releases/latest": {
                    "tag_name": "5.2.2_v2.0.13-ls465",
                    "name": "5.2.2_v2.0.13-ls465",
                    "html_url": "https://github.com/linuxserver/docker-qbittorrent/releases/tag/5.2.2_v2.0.13-ls465",
                    "body": "Remote Changes:\n- Updating to 5.2.2_v2.0.13",
                    "published_at": "2026-07-05T09:42:00Z",
                },
                **qbittorrent_upstream_responses("5.2.2_v2.0.13"),
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
        self.assertEqual(items[0].release_tag, "v5.2.2")
        self.assertTrue(items[0].links[0].url.endswith("/5.2.2_v2.0.13-ls465"))
        self.assertEqual(items[0].classification.change_type, "upstream_update")

    def test_github_latest_candidate_from_lsio_info_requires_release_link(self) -> None:
        for status in ("ready", "not_found"):
            with self.subTest(status=status):
                info = ReleaseNoteInfo(
                    line_no=1,
                    status=status,
                    provider="lsio",
                    image_repo="linuxserver/some-image",
                    upstream_repo="Some/Image",
                )

                candidate = github_latest_candidate_from_info(info)

                self.assertIsNone(candidate)

    def test_github_latest_candidate_from_lsio_info_ignores_malformed_links(
        self,
    ) -> None:
        for url in (
            "https://github.com/linuxserver/some-image/releases",
            "https://github.com/linuxserver/some-image/tags",
            "https://github.com/linuxserver/some-image/releases/tag/",
            "https://github.com/linuxserver/some-image/releases/tag",
            "https://example.com/linuxserver/some-image/releases/tag/v1.2.3",
        ):
            with self.subTest(url=url):
                info = ReleaseNoteInfo(
                    line_no=1,
                    status="ready",
                    provider="lsio",
                    image_repo="linuxserver/some-image",
                    upstream_repo="Some/Image",
                    links=[ReleaseNoteLink("LSIO release", url, "lsio_release")],
                )

                candidate = github_latest_candidate_from_info(info)

                self.assertIsNone(candidate)

    def test_github_release_link_tag_extracts_valid_tags(self) -> None:
        cases = {
            "https://github.com/linuxserver/some-image/releases/tag/v1.2.3": (
                "v1.2.3"
            ),
            "https://github.com/linuxserver/some-image/releases/tag/1.2.3": "1.2.3",
            "https://github.com/linuxserver/some-image/releases/tag/v1.2.3?foo=bar#baz": (
                "v1.2.3"
            ),
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(_github_release_link_tag(url), expected)

    def test_github_release_link_tag_rejects_incomplete_urls(self) -> None:
        for url in (
            "",
            "not-a-url",
            "https://github.com/linuxserver/some-image",
            "https://github.com/linuxserver/some-image/releases",
            "https://github.com/linuxserver/some-image/releases/tag/",
            "https://example.com/linuxserver/some-image/releases/tag/v1.2.3",
        ):
            with self.subTest(url=url):
                self.assertEqual(_github_release_link_tag(url), "")

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
