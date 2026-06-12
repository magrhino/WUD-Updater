from __future__ import annotations

import os
import stat
import tempfile
import unittest
from ruamel.yaml import YAML
from wud_updater.compose_rewrite import _reject_yaml_anchor_or_alias_image_value, _reject_yaml_anchor_or_alias_service_config, _reject_yaml_anchor_or_alias_labels, _backup_compose, _exact_tag_include_matches
from unittest import mock
from pathlib import Path

from wud_updater import compose_rewrite
from wud_updater.compose import ComposeStack, ServiceImage
from wud_updater.compose_rewrite import (
    apply_compose_digest_pins,
    apply_compose_digest_unpins,
    apply_compose_tag_exclusions,
    apply_compose_tag_updates,
    compose_escape_dollars,
    exact_tags_regex,
    merge_wud_exclude_regex,
    render_compose_digest_pins,
    render_compose_digest_unpins,
    render_compose_tag_exclusions,
    _is_simple_exact_tag_include,
)
from wud_updater.updater_models import (
    ComposeTagRewriteError,
    DigestPinLabelRewriteApproval,
    DigestPinLabelRewriteApprovalRequired,
    DigestPinUpdate,
    DigestUnpinUpdate,
    TagExclusionUpdate,
    TagUpdate,
)


class ComposeRewriteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-compose-rewrite.")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_compose(self, source: str, name: str = "compose.yml") -> Path:
        compose_path = self.root / name
        compose_path.write_text(source, encoding="utf-8")
        return compose_path

    def stack(
        self,
        service_images: tuple[tuple[str, str], ...] = (("app", "repo/app:1.0"),),
    ) -> ComposeStack:
        return ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="stack",
            images=tuple(image for _service, image in service_images),
            service_images=tuple(
                ServiceImage(service, image) for service, image in service_images
            ),
        )

    def tag_exclusion_update(
        self,
        *,
        service: str = "app",
        image: str = "repo/app:1.0",
        image_repo: str = "repo/app",
        tag: str = "2.0",
        scope: str = "service",
    ) -> TagExclusionUpdate:
        return TagExclusionUpdate(
            stack=self.stack(((service, image),)),
            service=service,
            image=image,
            image_repo=image_repo,
            tag=tag,
            source_line=1,
            scope=scope,
        )

    def digest_pin_update(
        self,
        *,
        old_image: str = "repo/app:1.0",
        resolved_tag: str = "2.0",
        planned_digest: str = "sha256:pin",
        services: tuple[str, ...] = ("app",),
    ) -> DigestPinUpdate:
        image_repo = old_image.rsplit(":", 1)[0]
        return DigestPinUpdate(
            old_image=old_image,
            resolved_tag=resolved_tag,
            resolved_image=f"{image_repo}:{resolved_tag}",
            planned_digest=planned_digest,
            final_image=f"{image_repo}@{planned_digest}",
            watch_tag=resolved_tag,
            marker=f"wud-updater.resolved-tag={resolved_tag}",
            label_key="wud.tag.include",
            label_value=compose_escape_dollars(exact_tags_regex((resolved_tag,))),
            services=services,
        )

    def digest_unpin_update(
        self,
        *,
        old_image: str = "repo/app@sha256:old",
        resolved_tag: str = "latest",
        target_digest: str = "sha256:new",
        services: tuple[str, ...] = ("app",),
    ) -> DigestUnpinUpdate:
        image_repo = old_image.split("@", 1)[0].rsplit(":", 1)[0]
        return DigestUnpinUpdate(
            old_image=old_image,
            resolved_tag=resolved_tag,
            tag_image=f"{image_repo}:{resolved_tag}",
            current_digest="sha256:old",
            target_digest=target_digest,
            watch_tag=resolved_tag,
            marker=f"wud-updater.resolved-tag={resolved_tag}",
            label_key="wud.tag.include",
            label_value=compose_escape_dollars(exact_tags_regex((resolved_tag,))),
            services=services,
        )


class ComposeRewriteCompatibilityTests(unittest.TestCase):
    def test_updater_reexports_compose_rewrite_helpers(self) -> None:
        from wud_updater import updater

        names = (
            "apply_compose_tag_updates",
            "apply_compose_tag_exclusions",
            "apply_compose_digest_pins",
            "render_compose_digest_pins",
            "render_compose_tag_exclusions",
            "exact_tags_regex",
            "merge_wud_exclude_regex",
            "_is_simple_exact_tag_include",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(updater, name), getattr(compose_rewrite, name))


class ComposeRegexTests(unittest.TestCase):
    def test_exact_tags_regex_sorts_deduplicates_and_escapes_tags(self) -> None:
        self.assertEqual(exact_tags_regex(()), "")
        self.assertEqual(exact_tags_regex(("2.0",)), r"^2\.0$")
        self.assertEqual(
            exact_tags_regex(("3+hotfix", "2.0", "2.0")),
            r"^(?:2\.0|3\+hotfix)$",
        )

    def test_merge_wud_exclude_regex_replaces_or_extends_managed_regex(self) -> None:
        self.assertEqual(
            merge_wud_exclude_regex(
                "",
                previous_managed="",
                next_managed=r"^2\.0$",
            ),
            r"^2\.0$",
        )
        self.assertEqual(
            merge_wud_exclude_regex(
                r"^1\.0$",
                previous_managed=r"^1\.0$",
                next_managed=r"^(?:1\.0|2\.0)$",
            ),
            r"^(?:1\.0|2\.0)$",
        )
        self.assertEqual(
            merge_wud_exclude_regex(
                r"^beta",
                previous_managed=r"^1\.0$",
                next_managed=r"^(?:1\.0|2\.0)$",
            ),
            r"(?:^beta)|(?:^(?:1\.0|2\.0)$)",
        )
        self.assertEqual(
            merge_wud_exclude_regex(
                r"^beta",
                previous_managed=r"^1\.0$",
                next_managed="",
            ),
            r"^beta",
        )

    def test_simple_exact_tag_include_accepts_only_exact_valid_tags(self) -> None:
        valid_values = (
            r"^1\.2\.3$",
            "^latest$",
            "^v1-alpha$",
            "^my_tag$",
            "^20240101$",
        )
        invalid_values = (
            r"^beta|stable$",
            r"^1\.*$",
            "latest$",
            "^latest",
            "^$",
            "^",
            "",
            "^1.2$",
            "^1+2$",
            "^(abc)$",
            r"^abc\$",
            r"^abc\\def$",
            r"^abc\adef$",
            "^ $",
        )

        for value in valid_values:
            with self.subTest(value=value):
                self.assertTrue(_is_simple_exact_tag_include(value))
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(_is_simple_exact_tag_include(value))


class ComposeTagUpdateTests(ComposeRewriteTestCase):
    def test_rewrites_only_direct_service_image_source_span(self) -> None:
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

    def test_rejects_invalid_yaml_without_write(self) -> None:
        original = "services:\n  app:\n    image: [repo/app:1.0\n"
        compose_file = self.write_compose(original)

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

    def test_rejects_interpolated_image_without_write(self) -> None:
        original = "services:\n  app:\n    image: repo/app:${TAG}\n"
        compose_file = self.write_compose(original)

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

    def test_rejects_service_without_direct_image_without_write(self) -> None:
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "      image: repo/app:1.0\n"
        )
        compose_file = self.write_compose(original)

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

    def test_rejects_anchored_and_inherited_images_without_write(self) -> None:
        cases = (
            (
                "alias.yml",
                "x-base: &base\n"
                "  image: repo/app:1.0\n"
                "services:\n"
                "  app: *base\n",
                "YAML anchors or aliases",
            ),
            (
                "merge.yml",
                "x-base: &base\n"
                "  image: repo/app:1.0\n"
                "services:\n"
                "  app:\n"
                "    <<: *base\n",
                "inherited",
            ),
        )

        for name, original, expected_error in cases:
            with self.subTest(name=name):
                compose_file = self.write_compose(original, name=name)

                with self.assertRaisesRegex(ComposeTagRewriteError, expected_error):
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


class ComposeTagExclusionTests(ComposeRewriteTestCase):
    def test_render_merges_custom_label_with_existing_exact_tags(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.exclude: ^beta\n"
        )

        rendered, applied = render_compose_tag_exclusions(
            compose_file,
            (
                self.tag_exclusion_update(
                    tag="3.0",
                    scope="service",
                ),
            ),
            existing_exact_tags={"app": {"2.0"}},
        )

        self.assertEqual(applied[0].tags, ("2.0", "3.0"))
        self.assertIn("wud.tag.exclude: (?:^beta)|(?:^(?:2\\.0|3\\.0)$$)", rendered)
        self.assertNotIn(
            "3\\.0",
            compose_file.read_text(encoding="utf-8"),
        )

    def test_apply_writes_atomically_and_preserves_mode_and_owner(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
        )
        os.chmod(compose_file, 0o600)
        before = compose_file.stat()

        applied = apply_compose_tag_exclusions(
            compose_file,
            (self.tag_exclusion_update(tag="2.0"),),
            existing_exact_tags={},
        )

        after = compose_file.stat()
        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(applied[0].tags, ("2.0",))
        self.assertIn("wud.tag.exclude=^2\\.0$$", content)
        self.assertEqual(stat.S_IMODE(after.st_mode), stat.S_IMODE(before.st_mode))
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
        self.assertEqual(list(self.root.glob(".compose.yml.exclude.*")), [])

    def test_materializes_service_merged_map_labels(self) -> None:
        compose_file = self.write_compose(
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
                    "  worker:",
                    "    <<: *base",
                    "    image: repo/worker:1.0",
                    "",
                ]
            )
        )

        apply_compose_tag_exclusions(
            compose_file,
            (self.tag_exclusion_update(tag="2.0"),),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertEqual(
            content.count("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn(
            "  app:\n"
            "    <<: *base\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)\n"
            "      foo: bar\n",
            content,
        )
        self.assertIn(
            "  worker:\n"
            "    <<: *base\n"
            "    image: repo/worker:1.0\n",
            content,
        )
        self.assertNotIn("repo/worker:1.0\n    labels:", content)

    def test_materializes_service_merged_list_labels(self) -> None:
        compose_file = self.write_compose(
            "\n".join(
                [
                    "x-base: &base",
                    "  labels:",
                    "    - wud.tag.exclude=^beta",
                    "    - foo=bar",
                    "services:",
                    "  app:",
                    "    <<: *base",
                    "    image: repo/app:1.0",
                    "",
                ]
            )
        )

        apply_compose_tag_exclusions(
            compose_file,
            (self.tag_exclusion_update(tag="2.0"),),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("- wud.tag.exclude=^beta"), 1)
        self.assertEqual(
            content.count("- wud.tag.exclude=(?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn(
            "  app:\n"
            "    <<: *base\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "    - wud.tag.exclude=(?:^beta)|(?:^2\\.0$$)\n"
            "    - foo=bar\n",
            content,
        )

    def test_preserves_internal_label_merge(self) -> None:
        compose_file = self.write_compose(
            "\n".join(
                [
                    "x-labels: &common",
                    "  wud.tag.exclude: ^beta",
                    "  foo: bar",
                    "services:",
                    "  app:",
                    "    image: repo/app:1.0",
                    "    labels:",
                    "      <<: *common",
                    "      baz: qux",
                    "",
                ]
            )
        )

        apply_compose_tag_exclusions(
            compose_file,
            (self.tag_exclusion_update(tag="2.0"),),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertEqual(
            content.count("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn("      <<: *common\n", content)
        self.assertIn("      baz: qux\n", content)

    def test_rejects_interpolated_image_without_write(self) -> None:
        original = "services:\n  app:\n    image: repo/app:${TAG}\n"
        compose_file = self.write_compose(original)

        with self.assertRaisesRegex(ComposeTagRewriteError, "interpolation"):
            apply_compose_tag_exclusions(
                compose_file,
                (
                    self.tag_exclusion_update(
                        image="repo/app:${TAG}",
                        tag="2.0",
                    ),
                ),
                existing_exact_tags={},
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_rejects_service_anchor_without_write(self) -> None:
        original = "\n".join(
            [
                "x-base: &base",
                "  image: repo/app:1.0",
                "services:",
                "  app: *base",
                "",
            ]
        )
        compose_file = self.write_compose(original)

        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            apply_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(tag="2.0"),),
                existing_exact_tags={},
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_rejects_shared_label_alias_without_write(self) -> None:
        original = (
            "x-labels: &common\n"
            "  - foo=bar\n"
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels: *common\n"
            "  worker:\n"
            "    image: repo/worker:1.0\n"
            "    labels: *common\n"
        )
        compose_file = self.write_compose(original)

        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            apply_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(tag="2.0"),),
                existing_exact_tags={},
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)


class ComposeDigestPinTests(ComposeRewriteTestCase):
    def test_render_empty_updates_returns_source_without_applied_updates(self) -> None:
        original = "services:\n  app:\n    image: repo/app:1.0\n"
        compose_file = self.write_compose(original)

        rendered, applied = render_compose_digest_pins(compose_file, ())

        self.assertEqual(rendered, original)
        self.assertEqual(applied, ())

    def test_render_writes_image_marker_label_and_rewrite_metadata(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=1.0\n"
            "    image: repo/app:1.0\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
            stack_name="stack",
        )

        self.assertEqual(applied[0].replacements, 1)
        self.assertIn("# wud-updater.resolved-tag=2.0", rendered)
        self.assertIn("image: repo/app@sha256:pin", rendered)
        self.assertIn("wud.tag.include=^2\\.0$$", rendered)
        self.assertEqual(
            applied[0].label_rewrites[0].reason,
            "plain-tag-normalized",
        )
        self.assertEqual(applied[0].label_rewrites[0].current_label_value, "1.0")

    def test_apply_writes_digest_pin_file(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
        )

        applied = apply_compose_digest_pins(compose_file, (self.digest_pin_update(),))

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(applied[0].final_image, "repo/app@sha256:pin")
        self.assertIn("# wud-updater.resolved-tag=2.0", content)
        self.assertIn("image: repo/app@sha256:pin", content)

    def test_apply_rejects_empty_digest_pin_render_without_write(self) -> None:
        original = "services:\n  app:\n    image: repo/app:1.0\n"
        compose_file = self.write_compose(original)

        with (
            mock.patch(
                "wud_updater.compose_rewrite.render_compose_digest_pins",
                return_value=("", ()),
            ),
            mock.patch("wud_updater.compose_rewrite._atomic_replace_compose") as replace,
        ):
            with self.assertRaisesRegex(ComposeTagRewriteError, "produced no output"):
                apply_compose_digest_pins(compose_file, (self.digest_pin_update(),))

        replace.assert_not_called()
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_render_requires_approval_for_custom_include_label(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired) as raised:
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                stack_name="stack",
            )

        self.assertEqual(raised.exception.service, "app")
        self.assertEqual(raised.exception.current_label_value, "^beta|^stable")
        self.assertEqual(raised.exception.proposed_label_value, "^2\\.0$$")
        self.assertEqual(raised.exception.proposed_label_regex, "^2\\.0$")

    def test_render_normalizes_plain_planned_tag_label(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=latest\n"
            "    image: repo/app:latest\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (
                self.digest_pin_update(
                    old_image="repo/app:latest",
                    resolved_tag="latest",
                ),
            ),
            stack_name="stack",
        )

        self.assertIn("wud.tag.include=^latest$$", rendered)
        self.assertEqual(applied[0].label_rewrites[0].reason, "plain-tag-normalized")
        self.assertEqual(applied[0].label_rewrites[0].current_label_value, "latest")

    def test_render_requires_approval_for_different_plain_tag_label(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=stable\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired) as raised:
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                stack_name="stack",
            )

        self.assertEqual(raised.exception.current_label_value, "stable")
        self.assertEqual(raised.exception.proposed_label_value, "^2\\.0$$")

    def test_render_accepts_matching_custom_include_label_approval(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
            label_rewrite_approvals=(
                DigestPinLabelRewriteApproval(
                    stack="stack",
                    service="app",
                    label_key="wud.tag.include",
                    current_label_value="^beta|^stable",
                    planned_tag="2.0",
                    proposed_label_value="^2\\.0$$",
                ),
            ),
            stack_name="stack",
        )

        self.assertIn("wud.tag.include=^2\\.0$$", rendered)
        self.assertEqual(applied[0].label_rewrites[0].reason, "approved")
        self.assertTrue(applied[0].label_rewrites[0].approved)

    def test_render_rejects_stale_custom_include_label_approval(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired):
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                label_rewrite_approvals=(
                    DigestPinLabelRewriteApproval(
                        stack="stack",
                        service="app",
                        label_key="wud.tag.include",
                        current_label_value="^beta|^stable",
                        planned_tag="2.0",
                        proposed_label_value="^3\\.0$$",
                    ),
                ),
                stack_name="stack",
            )

    def test_render_label_already_matching_proposed_regex_has_no_rewrite(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^2\\.0$$\n"
            "    image: repo/app:1.0\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
            stack_name="stack",
        )

        self.assertEqual(applied[0].label_rewrites, ())
        self.assertIn("wud.tag.include=^2\\.0$$", rendered)

    def test_render_service_without_include_label_has_no_rewrite(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
        )

        _rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
            stack_name="stack",
        )

        self.assertEqual(applied[0].label_rewrites, ())

    def test_render_normalizes_exact_regex_label(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^1\\.0$\n"
            "    image: repo/app:1.0\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
            stack_name="stack",
        )

        self.assertIn("wud.tag.include=^2\\.0$$", rendered)
        self.assertEqual(applied[0].label_rewrites[0].reason, "exact-regex-normalized")
        self.assertEqual(applied[0].label_rewrites[0].current_label_value, "^1\\.0$")
        self.assertFalse(applied[0].label_rewrites[0].approved)

    def test_render_rejects_approval_with_wrong_stack(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^custom|regex\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired):
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                label_rewrite_approvals=(
                    DigestPinLabelRewriteApproval(
                        stack="other-stack",
                        service="app",
                        label_key="wud.tag.include",
                        current_label_value="^custom|regex",
                        planned_tag="2.0",
                        proposed_label_value="^2\\.0$$",
                    ),
                ),
                stack_name="stack",
            )

    def test_render_rejects_approval_with_wrong_service(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^custom|regex\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired):
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                label_rewrite_approvals=(
                    DigestPinLabelRewriteApproval(
                        stack="stack",
                        service="other-service",
                        label_key="wud.tag.include",
                        current_label_value="^custom|regex",
                        planned_tag="2.0",
                        proposed_label_value="^2\\.0$$",
                    ),
                ),
                stack_name="stack",
            )

    def test_render_rejects_approval_with_wrong_current_label_value(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "    - wud.tag.include=^custom|regex\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired):
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(),),
                label_rewrite_approvals=(
                    DigestPinLabelRewriteApproval(
                        stack="stack",
                        service="app",
                        label_key="wud.tag.include",
                        current_label_value="^different|regex",
                        planned_tag="2.0",
                        proposed_label_value="^2\\.0$$",
                    ),
                ),
                stack_name="stack",
            )

    def test_approval_required_exception_exposes_rewrite_fields(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  myservice:\n"
            "    labels:\n"
            "    - wud.tag.include=^custom.*regex\n"
            "    image: repo/myimage:1.0\n"
        )

        with self.assertRaises(DigestPinLabelRewriteApprovalRequired) as raised:
            render_compose_digest_pins(
                compose_file,
                (
                    self.digest_pin_update(
                        old_image="repo/myimage:1.0",
                        services=("myservice",),
                    ),
                ),
                stack_name="mystack",
            )

        exc = raised.exception
        self.assertEqual(exc.service, "myservice")
        self.assertEqual(exc.label_key, "wud.tag.include")
        self.assertEqual(exc.current_label_value, "^custom.*regex")
        self.assertEqual(exc.planned_tag, "2.0")
        self.assertEqual(exc.proposed_label_value, "^2\\.0$$")
        self.assertEqual(exc.proposed_label_regex, "^2\\.0$")
        self.assertIn("myservice", str(exc))
        self.assertIn("^custom.*regex", str(exc))

    def test_render_rejects_service_not_in_compose(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  other:\n"
            "    image: repo/other:1.0\n"
        )

        with self.assertRaises(ComposeTagRewriteError):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_rejects_image_mismatch(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/different:1.0\n"
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "expected"):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_rejects_empty_services_list(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "No compose service"):
            render_compose_digest_pins(
                compose_file,
                (self.digest_pin_update(services=()),),
            )

    def test_render_accepts_resolved_image_already_written(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:2.0\n"
        )

        rendered, applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
        )

        self.assertEqual(len(applied), 1)
        self.assertIn("repo/app@sha256:pin", rendered)

    def test_render_updates_map_style_labels(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.include: ^1\\.0$\n"
        )

        rendered, _applied = render_compose_digest_pins(
            compose_file,
            (self.digest_pin_update(),),
        )

        self.assertIn("wud.tag.include", rendered)
        self.assertIn("2", rendered)

    def test_apply_rejects_inherited_image_without_write(self) -> None:
        original = (
            "x-base: &base\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    <<: *base\n"
        )
        compose_file = self.write_compose(original)

        with self.assertRaisesRegex(ComposeTagRewriteError, "inherited"):
            apply_compose_digest_pins(compose_file, (self.digest_pin_update(),))

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)


class ComposeDigestUnpinTests(ComposeRewriteTestCase):
    def test_render_empty_updates_returns_source_without_applied_updates(self) -> None:
        original = "services:\n  app:\n    image: repo/app@sha256:old\n"
        compose_file = self.write_compose(original)

        rendered, applied = render_compose_digest_unpins(compose_file, ())

        self.assertEqual(rendered, original)
        self.assertEqual(applied, ())

    def test_render_writes_tag_image_and_removes_resolved_tag_marker(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    # wud-updater.resolved-tag=latest\n"
            "    image: repo/app@sha256:old\n"
            "    labels:\n"
            "    - wud.tag.include=^latest$$\n"
        )

        rendered, applied = render_compose_digest_unpins(
            compose_file,
            (self.digest_unpin_update(),),
            stack_name="stack",
        )

        self.assertEqual(applied[0].replacements, 1)
        self.assertIn("image: repo/app:latest", rendered)
        self.assertIn("wud.tag.include=^latest$$", rendered)
        self.assertNotIn("wud-updater.resolved-tag", rendered)
        self.assertNotIn(
            "repo/app:latest",
            compose_file.read_text(encoding="utf-8"),
        )

    def test_apply_rejects_empty_digest_unpin_render_without_write(self) -> None:
        original = "services:\n  app:\n    image: repo/app@sha256:old\n"
        compose_file = self.write_compose(original)

        with (
            mock.patch(
                "wud_updater.compose_rewrite.render_compose_digest_unpins",
                return_value=("", ()),
            ),
            mock.patch("wud_updater.compose_rewrite._atomic_replace_compose") as replace,
        ):
            with self.assertRaisesRegex(ComposeTagRewriteError, "produced no output"):
                apply_compose_digest_unpins(
                    compose_file,
                    (self.digest_unpin_update(),),
                )

        replace.assert_not_called()
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)


class ComposeBackupTests(ComposeRewriteTestCase):
    def test_backup_removes_created_temp_file_when_copy_fails(self) -> None:
        compose_file = self.write_compose("services: {}\n")

        with mock.patch(
            "wud_updater.compose_rewrite.shutil.copy2",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                compose_rewrite._backup_compose(compose_file)

        self.assertEqual(list(self.root.glob(".compose.yml.backup.*")), [])


class MalformedYamlTests(ComposeRewriteTestCase):
    def test_apply_compose_tag_updates_root_not_mapping(self) -> None:
        compose_file = self.write_compose("- services\n- app\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file is not a YAML mapping"):
            apply_compose_tag_updates(
                compose_file,
                (TagUpdate(old_image="repo/app:1.0", desired_tag="2.0", new_image="repo/app:2.0", services=("app",)),)
            )

    def test_apply_compose_tag_updates_services_not_mapping(self) -> None:
        compose_file = self.write_compose("services: []\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file has no services mapping"):
            apply_compose_tag_updates(
                compose_file,
                (TagUpdate(old_image="repo/app:1.0", desired_tag="2.0", new_image="repo/app:2.0", services=("app",)),)
            )

    def test_render_compose_digest_pins_yaml_error(self) -> None:
        compose_file = self.write_compose("services:\n  app:\n    image: [repo/app:1.0\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "could not be parsed"):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_digest_pins_root_not_mapping(self) -> None:
        compose_file = self.write_compose("- services\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file is not a YAML mapping"):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_digest_pins_services_not_mapping(self) -> None:
        compose_file = self.write_compose("services: []\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file has no services mapping"):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_tag_exclusions_yaml_error(self) -> None:
        compose_file = self.write_compose("services:\n  app:\n    image: [repo/app:1.0\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "could not be parsed"):
            render_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(),),
                existing_exact_tags={}
            )

    def test_render_compose_tag_exclusions_root_not_mapping(self) -> None:
        compose_file = self.write_compose("- services\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file is not a YAML mapping"):
            render_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(),),
                existing_exact_tags={}
            )

    def test_render_compose_tag_exclusions_services_not_mapping(self) -> None:
        compose_file = self.write_compose("services: []\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "Compose file has no services mapping"):
            render_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(),),
                existing_exact_tags={}
            )

    def test_render_compose_digest_pins_unsupported_label_type(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      - 123\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "unsupported non-string list entries"):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_tag_exclusions_unsupported_label_type(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      - 123\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "unsupported non-string list entries"):
            render_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(),),
                existing_exact_tags={}
            )

    def test_render_compose_digest_pins_label_dict_non_string(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.include: 123\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "Label wud.tag.include is not a string value."):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_tag_exclusions_label_dict_non_string(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.exclude: 123\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "Label wud.tag.exclude is not a string value."):
            render_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(),),
                existing_exact_tags={}
            )

    def test_render_compose_digest_pins_labels_unsupported_syntax_direct(self) -> None:
        compose_file = self.write_compose(
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels: my_label_string\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "Service labels use unsupported YAML syntax."):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

    def test_render_compose_digest_pins_labels_unsupported_syntax_inherited(self) -> None:
        compose_file = self.write_compose(
            "x-base: &base\n"
            "  labels: my_label_string\n"
            "services:\n"
            "  app:\n"
            "    <<: *base\n"
            "    image: repo/app:1.0\n"
        )
        with self.assertRaisesRegex(ComposeTagRewriteError, "Service app labels use unsupported YAML syntax."):
            render_compose_digest_pins(compose_file, (self.digest_pin_update(),))

class YamlAnchorAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = YAML(typ="rt")
        self.yaml.preserve_quotes = True

    def _parse_services(self, yaml_str: str) -> dict:
        parsed = self.yaml.load(yaml_str)
        return parsed.get("services", {})

    def test_rejects_direct_anchor_image_value(self) -> None:
        yaml_str = """
services:
  app:
    image: &img repo/app:1.0
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_image_value(services, "app", services["app"])

    def test_rejects_shared_alias_image_value(self) -> None:
        yaml_str = """
services:
  app:
    image: &img repo/app:1.0
  worker:
    image: *img
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_image_value(services, "worker", services["worker"])
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_image_value(services, "app", services["app"])

    def test_rejects_alias_from_extension_field_image(self) -> None:
        yaml_str = """
x-image: &img repo/app:1.0
services:
  app:
    image: *img
"""
        parsed = self.yaml.load(yaml_str)
        services = parsed.get("services", {})
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_image_value(services, "app", services["app"])

    def test_rejects_direct_anchor_service_config(self) -> None:
        yaml_str = """
services:
  app: &svc
    image: repo/app:1.0
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_service_config(services, "app", services["app"])

    def test_rejects_shared_alias_service_config(self) -> None:
        yaml_str = """
services:
  app: &svc
    image: repo/app:1.0
  worker: *svc
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_service_config(services, "worker", services["worker"])
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_service_config(services, "app", services["app"])

    def test_rejects_alias_from_extension_field_service_config(self) -> None:
        yaml_str = """
x-base: &base
  image: repo/app:1.0
services:
  app: *base
"""
        parsed = self.yaml.load(yaml_str)
        services = parsed.get("services", {})
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_service_config(services, "app", services["app"])

    def test_rejects_direct_anchor_labels(self) -> None:
        yaml_str = """
services:
  app:
    image: repo/app:1.0
    labels: &lbls
      - foo=bar
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_labels(services, "app", services["app"]["labels"])

    def test_rejects_shared_alias_labels(self) -> None:
        yaml_str = """
services:
  app:
    image: repo/app:1.0
    labels: &lbls
      - foo=bar
  worker:
    image: repo/worker:1.0
    labels: *lbls
"""
        services = self._parse_services(yaml_str)
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_labels(services, "worker", services["worker"]["labels"])
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_labels(services, "app", services["app"]["labels"])

    def test_rejects_alias_from_extension_field_labels(self) -> None:
        yaml_str = """
x-labels: &lbls
  - foo=bar
services:
  app:
    image: repo/app:1.0
    labels: *lbls
"""
        parsed = self.yaml.load(yaml_str)
        services = parsed.get("services", {})
        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            _reject_yaml_anchor_or_alias_labels(services, "app", services["app"]["labels"])

    def test_accepts_clean_yaml(self) -> None:
        yaml_str = """
services:
  app:
    image: repo/app:1.0
    labels:
      - foo=bar
  worker:
    image: repo/worker:1.0
    labels:
      - foo=bar
"""
        services = self._parse_services(yaml_str)
        # Should not raise any exceptions
        _reject_yaml_anchor_or_alias_image_value(services, "app", services["app"])
        _reject_yaml_anchor_or_alias_service_config(services, "app", services["app"])
        _reject_yaml_anchor_or_alias_labels(services, "app", services["app"]["labels"])
        
        _reject_yaml_anchor_or_alias_image_value(services, "worker", services["worker"])
        _reject_yaml_anchor_or_alias_service_config(services, "worker", services["worker"])
        _reject_yaml_anchor_or_alias_labels(services, "worker", services["worker"]["labels"])

class ComposeRewriteEdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-compose-rewrite-edge.")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_compose(self, source: str, name: str = "compose.yml") -> Path:
        compose_path = self.root / name
        compose_path.write_text(source, encoding="utf-8")
        return compose_path

    def stack(
        self,
        service_images: tuple[tuple[str, str], ...] = (("app", "repo/app:1.0"),),
    ) -> ComposeStack:
        return ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="stack",
            images=tuple(image for _service, image in service_images),
            service_images=tuple(
                ServiceImage(service, image) for service, image in service_images
            ),
        )

    def tag_exclusion_update(
        self,
        *,
        service: str = "app",
        image: str = "repo/app:1.0",
        image_repo: str = "repo/app",
        tag: str = "2.0",
        scope: str = "service",
    ) -> TagExclusionUpdate:
        return TagExclusionUpdate(
            stack=self.stack(((service, image),)),
            service=service,
            image=image,
            image_repo=image_repo,
            tag=tag,
            source_line=1,
            scope=scope,
        )

    def test_apply_compose_tag_updates_early_return(self) -> None:
        # If updates is empty, it returns early and does not read the file
        result = apply_compose_tag_updates(Path("does_not_exist.yml"), ())
        self.assertEqual(result, ())

    def test_apply_compose_tag_exclusions_early_return(self) -> None:
        # If updates is empty, render returns source, and apply skips the write.
        compose_file = self.write_compose("services:\n  app:\n    image: a\n")
        result = apply_compose_tag_exclusions(compose_file, (), existing_exact_tags={})
        self.assertEqual(result, ())
        self.assertEqual(compose_file.read_text(encoding="utf-8"), "services:\n  app:\n    image: a\n")

    def test_apply_compose_tag_exclusions_skips_write_for_noop_existing_exact_tag(
        self,
    ) -> None:
        original = (
            "services:\n"
            "  app:\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "    - wud.tag.exclude=^2\\.0$$\n"
        )
        compose_file = self.write_compose(original)

        with mock.patch("wud_updater.compose_rewrite._atomic_replace_compose") as replace:
            applied = apply_compose_tag_exclusions(
                compose_file,
                (self.tag_exclusion_update(tag="2.0"),),
                existing_exact_tags={"app": {"2.0"}},
            )

        self.assertEqual(applied, ())
        replace.assert_not_called()
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_merge_wud_exclude_regex_same_as_next(self) -> None:
        # Testing line 798: if current_regex == next_managed: return current_regex
        self.assertEqual(
            merge_wud_exclude_regex(r"^1\.0$", previous_managed="", next_managed=r"^1\.0$"),
            r"^1\.0$"
        )

    def test_exact_tag_include_matches(self) -> None:
        # Testing line 803
        self.assertTrue(_exact_tag_include_matches(r"^1\.0$$", "1.0"))
        self.assertFalse(_exact_tag_include_matches(r"^2\.0$$", "1.0"))

    def test_duplicate_span_rejection(self) -> None:
        # Testing rejection of duplicate spans in apply_compose_tag_updates
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0\n")
        
        with self.assertRaisesRegex(ComposeTagRewriteError, "was selected more than once"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app", "app"),
                    ),
                ),
            )

    def test_missing_services_mapped(self) -> None:
        # Testing line 65: if not update.services
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0\n")
        
        with self.assertRaisesRegex(ComposeTagRewriteError, "No compose service was mapped for repo/app:1.0"):
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
        # Testing line 475: if image_value != old_image
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:2.0\n")
        
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

    def test_backup_compose_file_not_found_on_unlink(self) -> None:
        # Testing line 758-762: try: backup.unlink() except FileNotFoundError: pass
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0\n")
        
        with mock.patch("wud_updater.compose_rewrite.shutil.copy2") as mock_copy2:
            mock_copy2.side_effect = RuntimeError("copy failed")
            
            with mock.patch("pathlib.Path.unlink") as mock_unlink:
                mock_unlink.side_effect = FileNotFoundError("already deleted")
                
                with self.assertRaisesRegex(RuntimeError, "copy failed"):
                    _backup_compose(compose_file)

class MoreCoverageTests(ComposeRewriteTestCase):
    def test_render_compose_tag_exclusions_service_not_map(self) -> None:
        compose_file = self.write_compose("services:\n  app: repo/app:1.0\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "is not a mapping"):
            render_compose_tag_exclusions(compose_file, (self.tag_exclusion_update(),), existing_exact_tags={})

    def test_line_end_eof_without_newline(self) -> None:
        # Line 494
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0")
        apply_compose_tag_updates(compose_file, (TagUpdate(old_image="repo/app:1.0", desired_tag="2.0", new_image="repo/app:2.0", services=("app",)),))
        self.assertIn("repo/app:2.0", compose_file.read_text(encoding="utf-8"))

    def test_apply_compose_tag_updates_service_not_map(self) -> None:
        compose_file = self.write_compose("services:\n  app: stringval\n")
        with self.assertRaisesRegex(ComposeTagRewriteError, "is not a mapping"):
            apply_compose_tag_updates(compose_file, (TagUpdate(old_image="repo/app:1.0", desired_tag="2.0", new_image="repo/app:2.0", services=("app",)),))

    def test_get_service_label_value_none(self) -> None:
        compose_file = self.write_compose("services:\n  app:\n    image: repo/app:1.0\n    labels:\n      wud.tag.exclude: \n")
        # Line 553
        render_compose_tag_exclusions(compose_file, (self.tag_exclusion_update(tag="2.0"),), existing_exact_tags={})


if __name__ == "__main__":
    unittest.main()
