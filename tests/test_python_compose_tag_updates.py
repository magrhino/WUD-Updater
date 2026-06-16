from __future__ import annotations

from pathlib import Path

from compose_rewrite_helpers import ComposeRewriteTestCase
from wud_updater.compose_rewrite import apply_compose_tag_updates
from wud_updater.updater_models import ComposeTagRewriteError, TagUpdate


class ComposeTagUpdateTests(ComposeRewriteTestCase):
    def test_rewrites_only_direct_service_image_source_span(self) -> None:
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            '    image: "repo/app:1.0" # keep comment\n'
            "    labels:\n"
            "      image: repo/app:1.0\n"
            "  db:\n"
            "    image: repo/db:1.0\n"
        )
        compose_file = self.write_compose(original)

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

    def test_rewrites_multiline_digest_image_to_one_line_tag(self) -> None:
        digest = "d771c6193517d7ccbbf9bf5142e235234fc5888a583eab8c4538589351374a79"
        old_image = f"ghcr.io/vavallee/bindery@sha256:{digest}"
        new_image = "ghcr.io/vavallee/bindery:latest"
        original = (
            "services:\n"
            "  bindery:\n"
            "    image:\n"
            f"      {old_image}\n"
            "    container_name: bindery\n"
        )
        compose_file = self.write_compose(original)

        applied = apply_compose_tag_updates(
            compose_file,
            (
                TagUpdate(
                    old_image=old_image,
                    desired_tag="latest",
                    new_image=new_image,
                    services=("bindery",),
                ),
            ),
        )

        self.assertEqual(applied[0].replacements, 1)
        self.assertEqual(
            compose_file.read_text(encoding="utf-8"),
            (
                "services:\n"
                "  bindery:\n"
                f"    image: {new_image}\n"
                "    container_name: bindery\n"
            ),
        )

    def test_apply_compose_tag_updates_early_return(self) -> None:
        # If updates is empty, it returns early and does not read the file
        result = apply_compose_tag_updates(Path("does_not_exist.yml"), ())
        self.assertEqual(result, ())

    def test_missing_services_mapped(self) -> None:
        compose_file = self.write_compose(
            "services:\n  app:\n    image: repo/app:1.0\n"
        )

        with self.assertRaisesRegex(
            ComposeTagRewriteError, "No compose service was mapped for repo/app:1.0"
        ):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=(),
                    ),
                ),
            )

    def test_mismatched_old_image(self) -> None:
        compose_file = self.write_compose(
            "services:\n  app:\n    image: repo/app:2.0\n"
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "expected repo/app:1.0"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="3.0",
                        new_image="repo/app:3.0",
                        services=("app",),
                    ),
                ),
            )

    def test_line_end_eof_without_newline(self) -> None:
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0")
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
        self.assertIn("repo/app:2.0", compose_file.read_text(encoding="utf-8"))

    def test_apply_compose_tag_updates_service_not_map(self) -> None:
        compose_file = self.write_compose("services:\n  app: stringval\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "is not a mapping"):
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
