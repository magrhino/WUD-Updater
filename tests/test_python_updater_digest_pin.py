
from __future__ import annotations

import unittest

from wudup.updater_digest_pin import digest_pin_update_from_values

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
        self.assertEqual(update.marker, "wudup.resolved-tag=2.0")
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
        self.assertIn("$$", update.label_value)

    def test_ghcr_registry_preserved_in_final_image(self) -> None:
        update = digest_pin_update_from_values(
            old_image="ghcr.io/org/app:1.0",
            resolved_tag="2.0",
            planned_digest="sha256:hash",
            services=("app",),
        )
        self.assertTrue(update.final_image.startswith("ghcr.io/org/app@sha256:"))
