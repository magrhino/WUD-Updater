from __future__ import annotations

import unittest
from collections.abc import Mapping

from wud_updater.digest_verifier import (
    DigestVerifier,
    ManifestDocument,
    ManifestLookupError,
    parse_ghcr_image,
)


INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"


class FakeDocker:
    def __init__(
        self,
        *,
        image_id: str = "sha256:config",
        repo_digests: tuple[str, ...] = (),
    ) -> None:
        self.image_id_value = image_id
        self.repo_digest_values = repo_digests

    def image_repo_digests(self, image: str) -> list[str]:
        return list(self.repo_digest_values)

    def image_id(self, image: str) -> str:
        return self.image_id_value


class StaticResolver:
    def __init__(
        self,
        documents: Mapping[tuple[str, str], ManifestDocument],
    ) -> None:
        self.documents = dict(documents)
        self.calls: list[tuple[str, str]] = []

    def fetch(self, repo: str, reference: str) -> ManifestDocument:
        self.calls.append((repo, reference))
        try:
            return self.documents[(repo, reference)]
        except KeyError as exc:
            raise ManifestLookupError(f"missing {repo}@{reference}") from exc


class FailingResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch(self, repo: str, reference: str) -> ManifestDocument:
        self.calls.append((repo, reference))
        raise ManifestLookupError("primary unavailable")


def index_doc(
    digest: str,
    children: tuple[str, ...],
    *,
    source: str = "static",
) -> ManifestDocument:
    return ManifestDocument(
        source=source,
        digest=digest,
        media_type=INDEX_TYPE,
        payload={
            "schemaVersion": 2,
            "mediaType": INDEX_TYPE,
            "manifests": [
                {
                    "mediaType": MANIFEST_TYPE,
                    "digest": child,
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
                for child in children
            ],
        },
    )


def manifest_doc(
    digest: str,
    config_digest: str,
    *,
    source: str = "static",
) -> ManifestDocument:
    return ManifestDocument(
        source=source,
        digest=digest,
        media_type=MANIFEST_TYPE,
        payload={
            "schemaVersion": 2,
            "mediaType": MANIFEST_TYPE,
            "config": {"digest": config_digest},
        },
    )


class DigestVerifierTests(unittest.TestCase):
    def test_parse_ghcr_image_requires_tagged_ghcr_reference(self) -> None:
        parsed = parse_ghcr_image("ghcr.io/acme/app:latest@sha256:old")

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.repo, "acme/app")
        self.assertEqual(parsed.tag, "latest")
        self.assertIsNone(parse_ghcr_image("acme/app:latest"))
        self.assertIsNone(parse_ghcr_image("ghcr.io/acme/app"))

    def test_platform_child_digest_matches_local_config_digest(self) -> None:
        expected = "sha256:child"
        resolver = StaticResolver(
            {
                ("acme/app", "latest"): index_doc("sha256:index", (expected,)),
                ("acme/app", expected): manifest_doc(expected, "sha256:config"),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("ghcr.io/acme/app:latest", expected)

        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ghcr-platform-manifest-match")
        self.assertEqual(result.matched_child_digest, expected)
        self.assertEqual(result.expected_config_digest, "sha256:config")

    def test_current_index_digest_matches_local_platform_child_config(self) -> None:
        expected = "sha256:index"
        child = "sha256:child"
        resolver = StaticResolver(
            {
                ("acme/app", "latest"): index_doc(expected, (child,)),
                ("acme/app", child): manifest_doc(child, "sha256:config"),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("ghcr.io/acme/app:latest", expected)

        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ghcr-index-manifest-match")
        self.assertEqual(result.tag_digest, expected)
        self.assertEqual(result.matched_child_digest, child)

    def test_stale_digest_fails_when_absent_from_current_index(self) -> None:
        resolver = StaticResolver(
            {
                ("acme/app", "latest"): index_doc("sha256:index", ("sha256:child",)),
                ("acme/app", "sha256:stale"): manifest_doc(
                    "sha256:stale",
                    "sha256:config",
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("ghcr.io/acme/app:latest", "sha256:stale")

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "stale-digest")
        self.assertEqual(result.tag_digest, "sha256:index")

    def test_platform_child_digest_fails_when_local_image_id_differs(self) -> None:
        expected = "sha256:child"
        resolver = StaticResolver(
            {
                ("acme/app", "latest"): index_doc("sha256:index", (expected,)),
                ("acme/app", expected): manifest_doc(expected, "sha256:config"),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:other"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("ghcr.io/acme/app:latest", expected)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "platform-mismatch")
        self.assertEqual(result.expected_config_digest, "sha256:config")
        self.assertEqual(result.local_image_id, "sha256:other")

    def test_primary_failure_uses_fallback_manifest_data(self) -> None:
        expected = "sha256:child"
        primary = FailingResolver()
        fallback = StaticResolver(
            {
                ("acme/app", "latest"): index_doc(
                    "sha256:index",
                    (expected,),
                    source="fallback",
                ),
                ("acme/app", expected): manifest_doc(
                    expected,
                    "sha256:config",
                    source="fallback",
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=primary,
            fallback_resolver=fallback,
        )

        result = verifier.verify("ghcr.io/acme/app:latest", expected)

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "fallback")
        self.assertGreaterEqual(len(primary.calls), 1)
        self.assertIn(("acme/app", "latest"), fallback.calls)

    def test_non_ghcr_digest_mismatch_keeps_existing_behavior(self) -> None:
        verifier = DigestVerifier(
            FakeDocker(
                image_id="sha256:config",
                repo_digests=("docker.io/acme/app@sha256:other",),
            ),
            primary_resolver=FailingResolver(),
            fallback_resolver=FailingResolver(),
        )

        result = verifier.verify("docker.io/acme/app:latest", "sha256:expected")

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "repo-digest-mismatch")
        self.assertEqual(result.seen_repo_digests, ("docker.io/acme/app@sha256:other",))


if __name__ == "__main__":
    unittest.main()
