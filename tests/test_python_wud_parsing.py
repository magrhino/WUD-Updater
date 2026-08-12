from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wudup.images import (
    drop_registry,
    image_matches_resolved_target,
    image_repo_ref,
    image_tag,
    image_with_digest,
    image_with_tag,
    normalize_digest,
    strip_digest,
    tag_value_valid,
)
from wudup.line_specs import LineSpecError, parse_line_spec
from wudup.wud_file import parse_wud_file, parse_wud_text


class ImageHelperTests(unittest.TestCase):
    def test_tagged_image_matching_ignores_registry(self) -> None:
        self.assertTrue(
            image_matches_resolved_target(
                "docker.io/library/nginx:1.25",
                "library/nginx:1.25",
                allow_repo=False,
            )
        )
        self.assertFalse(
            image_matches_resolved_target(
                "library/nginx:1.26",
                "library/nginx:1.25",
                allow_repo=False,
            )
        )

    def test_untagged_repo_matching_requires_repo_allowed(self) -> None:
        self.assertTrue(
            image_matches_resolved_target(
                "ghcr.io/team/app:1.0",
                "team/app",
                allow_repo=True,
            )
        )
        self.assertFalse(
            image_matches_resolved_target(
                "ghcr.io/team/app:1.0",
                "team/app",
                allow_repo=False,
            )
        )

    def test_registry_stripping_matches_shell_rules(self) -> None:
        self.assertEqual(
            drop_registry("ghcr.io/team/app:1.0@sha256:abc"),
            "team/app:1.0",
        )
        self.assertEqual(
            drop_registry("localhost:5000/team/app:1.0"),
            "team/app:1.0",
        )
        self.assertEqual(drop_registry("localhost/team/app:1.0"), "team/app:1.0")
        self.assertEqual(drop_registry("team/app:1.0"), "team/app:1.0")

    def test_digest_normalization(self) -> None:
        self.assertEqual(strip_digest("repo/app:latest@sha256:abc"), "repo/app:latest")
        self.assertEqual(normalize_digest(""), "")
        self.assertEqual(normalize_digest("sha256:abc"), "sha256:abc")
        self.assertEqual(normalize_digest("abc"), "sha256:abc")
        self.assertEqual(normalize_digest("repo/app@sha256:abc"), "sha256:abc")

    def test_image_tag_parsing(self) -> None:
        self.assertEqual(image_tag("repo/app:latest"), "latest")
        self.assertEqual(image_tag("localhost:5000/repo/app:1.0@sha256:abc"), "1.0")
        self.assertEqual(image_tag("repo/app@sha256:abc"), "")

    def test_image_reference_rewrite_preserves_registry_and_drops_digest(self) -> None:
        self.assertEqual(
            image_repo_ref("registry.example.com/team/app:1.0@sha256:abc"),
            "registry.example.com/team/app",
        )
        self.assertEqual(
            image_with_tag("registry.example.com/team/app:1.0@sha256:abc", "2.0"),
            "registry.example.com/team/app:2.0",
        )

    def test_digest_and_registry_are_ignored_when_matching_tagged_target(self) -> None:
        self.assertTrue(
            image_matches_resolved_target(
                "docker.io/library/nginx:1.25@sha256:old",
                "library/nginx:1.25@sha256:new",
                allow_repo=False,
            )
        )

    def test_tag_value_validity(self) -> None:
        self.assertTrue(tag_value_valid("v1.2_3-alpha"))
        self.assertTrue(tag_value_valid("a" * 128))
        self.assertFalse(tag_value_valid(""))
        self.assertFalse(tag_value_valid("-bad"))
        self.assertFalse(tag_value_valid("bad:value"))
        self.assertFalse(tag_value_valid("a" * 129))


class LineSpecTests(unittest.TestCase):
    def test_line_spec_strips_whitespace_sorts_and_deduplicates(self) -> None:
        self.assertEqual(parse_line_spec(" 2,1-3,003 ", 5, "--only-lines"), [1, 2, 3])

    def test_line_spec_accepts_single_trailing_comma_like_shell(self) -> None:
        self.assertEqual(parse_line_spec("1,", 3, "--only-lines"), [1])

    def test_empty_line_spec_returns_no_lines(self) -> None:
        self.assertEqual(parse_line_spec("", 3, "--only-lines"), [])
        self.assertEqual(parse_line_spec(None, 3, "--only-lines"), [])

    def test_line_spec_rejects_whitespace_only(self) -> None:
        with self.assertRaisesRegex(LineSpecError, "--only-lines must not be empty"):
            parse_line_spec(" \t ", 3, "--only-lines")

    def test_line_spec_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(LineSpecError, "Invalid --only-lines value"):
            parse_line_spec("1,,2", 3, "--only-lines")
        with self.assertRaisesRegex(LineSpecError, "Invalid --only-lines value"):
            parse_line_spec("1,,", 3, "--only-lines")
        with self.assertRaisesRegex(LineSpecError, "line numbers must be 1 or greater"):
            parse_line_spec("0", 3, "--only-lines")
        with self.assertRaisesRegex(LineSpecError, "ranges must ascend"):
            parse_line_spec("3-2", 3, "--only-lines")
        with self.assertRaisesRegex(LineSpecError, "references line 4"):
            parse_line_spec("4", 3, "--only-lines")

    def test_line_spec_rejects_ranges_past_file_length(self) -> None:
        with self.assertRaisesRegex(LineSpecError, "references line 5"):
            parse_line_spec("2-5", 3, "--remove-lines-before-run")


class WudFileParsingTests(unittest.TestCase):
    def test_comments_blank_lines_and_original_line_numbers(self) -> None:
        parsed = parse_wud_text("# header\n\nrepo/app:latest\n  # footer\n")

        self.assertEqual(
            [(line.line_no, line.actionable, line.raw) for line in parsed.lines],
            [
                (1, False, "# header"),
                (2, False, ""),
                (3, True, "repo/app:latest"),
                (4, False, "  # footer"),
            ],
        )
        self.assertEqual([target.line_no for target in parsed.targets], [3])
        self.assertEqual(parsed.targets[0].raw, "repo/app:latest")
        self.assertEqual(parsed.targets[0].key, "repo/app:latest")
        self.assertEqual(parsed.targets[0].repo, "repo/app")
        self.assertTrue(parsed.targets[0].has_tag)
        self.assertFalse(parsed.targets[0].allow_repo)

    def test_duplicate_raw_lines_remain_distinct_targets(self) -> None:
        parsed = parse_wud_text("repo/app:latest\nrepo/app:latest\n")

        self.assertEqual(
            [(target.line_no, target.raw) for target in parsed.targets],
            [(1, "repo/app:latest"), (2, "repo/app:latest")],
        )

    def test_final_line_without_newline_is_parsed(self) -> None:
        parsed = parse_wud_text("repo/app:latest")

        self.assertEqual(len(parsed.lines), 1)
        self.assertEqual(parsed.targets[0].first, "repo/app:latest")

    def test_crlf_line_endings_match_shell_trimming(self) -> None:
        parsed = parse_wud_text("repo/app:latest\r\n# comment\r\n")

        self.assertEqual(parsed.lines[0].raw, "repo/app:latest\r")
        self.assertEqual(parsed.targets[0].first, "repo/app:latest")
        self.assertFalse(parsed.lines[1].actionable)

    def test_selected_lines_filter_targets_without_renumbering(self) -> None:
        parsed = parse_wud_text("repo/a:latest\n# comment\nrepo/b:latest\n", selected_lines=[3])

        self.assertEqual([line.line_no for line in parsed.lines], [1, 2, 3])
        self.assertEqual([target.line_no for target in parsed.targets], [3])
        self.assertEqual(parsed.targets[0].first, "repo/b:latest")

    def test_pinned_digest_target_is_normalized(self) -> None:
        parsed = parse_wud_text("registry.example.com/repo/app@sha256:good\n")
        target = parsed.targets[0]

        self.assertEqual(target.first, "registry.example.com/repo/app@sha256:good")
        self.assertEqual(target.digest, "sha256:good")
        self.assertEqual(target.key, "repo/app")
        self.assertEqual(target.repo, "repo/app")
        self.assertFalse(target.has_tag)
        self.assertTrue(target.allow_repo)

    def test_desired_tag_parsing(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 note=ignored tag=2.0\n")
        target = parsed.targets[0]

        self.assertEqual(target.desired_tag, "2.0")
        self.assertEqual(target.tag_token, "2.0")
        self.assertEqual(image_with_tag(target.first, target.desired_tag), "repo/app:2.0")
        self.assertEqual(parsed.warnings, ())

    def test_bare_digest_tag_token_is_rejected_without_source_tag(self) -> None:
        parsed = parse_wud_text("repo/app@sha256:good tag=2.0\n")
        target = parsed.targets[0]

        self.assertEqual(target.desired_tag, "")
        self.assertEqual(target.tag_token, "")
        self.assertEqual(
            parsed.warnings,
            (
                (
                    "Ignoring tag update without a tagged source image on WUD line 1: "
                    "repo/app@sha256:good"
                ),
            ),
        )

    def test_platform_and_trailing_digest_parsing(self) -> None:
        parsed = parse_wud_text(
            "repo/app:1.0 platform=linux/amd64/v7 "
            "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        )
        target = parsed.targets[0]

        self.assertEqual(
            target.digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(target.platform_value, "linux/amd64/v7")
        self.assertIsNotNone(target.platform)
        assert target.platform is not None
        self.assertEqual(target.platform.os, "linux")
        self.assertEqual(target.platform.architecture, "amd64")
        self.assertEqual(target.platform.variant, "v7")
        self.assertEqual(parsed.warnings, ())

    def test_invalid_platform_is_warned_and_ignored(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 platform=linux\n")

        self.assertIsNone(parsed.targets[0].platform)
        self.assertEqual(
            parsed.warnings,
            ("Ignoring invalid platform on WUD line 1: linux",),
        )

    def test_unknown_platform_component_is_warned_and_ignored(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 platform=linux/amd64/UNKNOWN\n")

        self.assertIsNone(parsed.targets[0].platform)
        self.assertEqual(
            parsed.warnings,
            ("Ignoring invalid platform on WUD line 1: linux/amd64/UNKNOWN",),
        )

    def test_trailing_platform_separator_is_warned_and_ignored(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 platform=linux/amd64/\n")

        self.assertIsNone(parsed.targets[0].platform)
        self.assertEqual(
            parsed.warnings,
            ("Ignoring invalid platform on WUD line 1: linux/amd64/",),
        )

    def test_only_final_invalid_platform_token_is_warned(self) -> None:
        parsed = parse_wud_text(
            "repo/app:1.0 platform=linux/amd64 platform=linux platform=bad\n"
        )

        self.assertIsNone(parsed.targets[0].platform)
        self.assertEqual(
            parsed.warnings,
            ("Ignoring invalid platform on WUD line 1: bad",),
        )

    def test_last_desired_tag_token_wins(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 tag=2.0 note=ignored tag=3.0\n")

        self.assertEqual(parsed.targets[0].desired_tag, "3.0")
        self.assertEqual(parsed.targets[0].tag_token, "3.0")
        self.assertEqual(parsed.warnings, ())

    def test_later_invalid_desired_tag_overrides_earlier_valid_tag(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 tag=2.0 tag=bad:value\n")

        self.assertEqual(parsed.targets[0].desired_tag, "")
        self.assertEqual(parsed.targets[0].tag_token, "")
        self.assertEqual(
            parsed.warnings,
            ("Ignoring invalid tag value on WUD line 1: bad:value",),
        )

    def test_invalid_tag_values_are_warned_and_ignored(self) -> None:
        parsed = parse_wud_text("repo/app:1.0 tag=bad:value\nrepo/app tag=2.0\n")

        self.assertEqual([target.desired_tag for target in parsed.targets], ["", ""])
        self.assertEqual(
            parsed.warnings,
            (
                "Ignoring invalid tag value on WUD line 1: bad:value",
                "Ignoring tag update without a tagged source image on WUD line 2: repo/app",
            ),
        )

    def test_parse_wud_file_reads_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "images.todo"
            path.write_text("repo/a:latest\nrepo/b:latest\n", encoding="utf-8")

            parsed = parse_wud_file(path, selected_lines=[2])

            self.assertEqual([target.line_no for target in parsed.targets], [2])
            self.assertEqual(path.read_text(encoding="utf-8"), "repo/a:latest\nrepo/b:latest\n")


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


if __name__ == "__main__":
    unittest.main()
