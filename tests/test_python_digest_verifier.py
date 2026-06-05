from __future__ import annotations

import unittest
from collections.abc import Mapping
from unittest import mock

from wud_updater.digest_verifier import (
    DigestVerifier,
    ManifestDocument,
    ManifestLookupError,
    RegistryHttpManifestResolver,
    parse_ghcr_image,
    parse_registry_image,
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
        documents: Mapping[tuple[str, str, str], ManifestDocument],
    ) -> None:
        self.documents = dict(documents)
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, image: object, reference: str) -> ManifestDocument:
        registry = getattr(image, "registry")
        repo = getattr(image, "repo")
        self.calls.append((registry, repo, reference))
        try:
            return self.documents[(registry, repo, reference)]
        except KeyError as exc:
            raise ManifestLookupError(f"missing {registry}/{repo}@{reference}") from exc


class FailingResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, image: object, reference: str) -> ManifestDocument:
        registry = getattr(image, "registry")
        repo = getattr(image, "repo")
        self.calls.append((registry, repo, reference))
        raise ManifestLookupError("primary unavailable")


class SequencedHttpResolver(RegistryHttpManifestResolver):
    def __init__(self, documents: tuple[ManifestDocument, ...]) -> None:
        self.documents = list(documents)
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, image: object, reference: str) -> ManifestDocument:
        registry = getattr(image, "registry")
        repo = getattr(image, "repo")
        self.calls.append((registry, repo, reference))
        if not self.documents:
            raise ManifestLookupError("no more documents")
        return self.documents.pop(0)


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
    def test_parse_registry_image_supports_docker_hub_and_explicit_registries(self) -> None:
        alpine = parse_registry_image("alpine:3.20")
        self.assertIsNotNone(alpine)
        assert alpine is not None
        self.assertEqual(alpine.registry, "docker.io")
        self.assertEqual(alpine.http_registry, "registry-1.docker.io")
        self.assertEqual(alpine.repo, "library/alpine")
        self.assertEqual(alpine.tag, "3.20")

        docker = parse_registry_image("docker.io/library/alpine:3.20")
        self.assertIsNotNone(docker)
        assert docker is not None
        self.assertEqual(docker.registry, "docker.io")
        self.assertEqual(docker.http_registry, "registry-1.docker.io")
        self.assertEqual(docker.repo, "library/alpine")
        self.assertEqual(docker.tag, "3.20")

        quay = parse_registry_image("quay.io/prometheus/busybox:latest")
        self.assertIsNotNone(quay)
        assert quay is not None
        self.assertEqual(quay.registry, "quay.io")
        self.assertEqual(quay.http_registry, "quay.io")
        self.assertEqual(quay.repo, "prometheus/busybox")
        self.assertEqual(quay.tag, "latest")

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
                ("ghcr.io", "acme/app", "latest"): index_doc("sha256:index", (expected,)),
                ("ghcr.io", "acme/app", expected): manifest_doc(expected, "sha256:config"),
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
                ("ghcr.io", "acme/app", "latest"): index_doc(expected, (child,)),
                ("ghcr.io", "acme/app", child): manifest_doc(child, "sha256:config"),
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
                ("ghcr.io", "acme/app", "latest"): index_doc(
                    "sha256:index",
                    ("sha256:child",),
                ),
                ("ghcr.io", "acme/app", "sha256:stale"): manifest_doc(
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
                ("ghcr.io", "acme/app", "latest"): index_doc("sha256:index", (expected,)),
                ("ghcr.io", "acme/app", expected): manifest_doc(expected, "sha256:config"),
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
                ("ghcr.io", "acme/app", "latest"): index_doc(
                    "sha256:index",
                    (expected,),
                    source="fallback",
                ),
                ("ghcr.io", "acme/app", expected): manifest_doc(
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
        self.assertIn(("ghcr.io", "acme/app", "latest"), fallback.calls)

    def test_resolve_tag_digest_reuses_primary_http_resolver_for_index_digest(self) -> None:
        resolver = SequencedHttpResolver(
            (
                index_doc("", ("sha256:child",)),
                index_doc("sha256:index", ("sha256:child",)),
            )
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=FailingResolver(),
        )

        with mock.patch(
            "wud_updater.digest_verifier.RegistryHttpManifestResolver.fetch",
            side_effect=AssertionError("fresh HTTP resolver used"),
        ):
            result = verifier.resolve_tag_digest("ghcr.io/acme/app:latest")

        self.assertTrue(result.ok)
        self.assertEqual(result.digest, "sha256:index")
        self.assertEqual(
            resolver.calls,
            [
                ("ghcr.io", "acme/app", "latest"),
                ("ghcr.io", "acme/app", "latest"),
            ],
        )

    def test_non_ghcr_platform_child_digest_matches_local_config_digest(self) -> None:
        expected = "sha256:child"
        resolver = StaticResolver(
            {
                ("quay.io", "acme/app", "latest"): index_doc("sha256:index", (expected,)),
                ("quay.io", "acme/app", expected): manifest_doc(expected, "sha256:config"),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("quay.io/acme/app:latest", expected)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.reason, "registry-platform-manifest-match")
        self.assertEqual(result.matched_child_digest, expected)
        self.assertEqual(result.expected_config_digest, "sha256:config")

    def test_non_ghcr_current_index_digest_matches_local_platform_child(self) -> None:
        expected = "sha256:index"
        child = "sha256:child"
        resolver = StaticResolver(
            {
                ("quay.io", "acme/app", "latest"): index_doc(expected, (child,)),
                ("quay.io", "acme/app", child): manifest_doc(child, "sha256:config"),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(image_id="sha256:config"),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.verify("quay.io/acme/app:latest", expected)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.reason, "registry-index-manifest-match")
        self.assertEqual(result.tag_digest, expected)
        self.assertEqual(result.matched_child_digest, child)

    def test_non_ghcr_stale_digest_fails_when_registry_proves_current_index(self) -> None:
        resolver = StaticResolver(
            {
                ("quay.io", "acme/app", "latest"): index_doc(
                    "sha256:index",
                    ("sha256:child",),
                ),
                ("quay.io", "acme/app", "sha256:stale"): manifest_doc(
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

        result = verifier.verify("quay.io/acme/app:latest", "sha256:stale")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "stale-digest")
        self.assertEqual(result.tag_digest, "sha256:index")

    def test_non_ghcr_manifest_unavailable_is_untrusted(self) -> None:
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
        self.assertEqual(result.status, "untrusted")
        self.assertEqual(result.reason, "manifest-unavailable-untrusted")
        self.assertEqual(result.seen_repo_digests, ("docker.io/acme/app@sha256:other",))

    def test_ghcr_manifest_unavailable_fails_closed(self) -> None:
        verifier = DigestVerifier(
            FakeDocker(
                image_id="sha256:config",
                repo_digests=("ghcr.io/acme/app@sha256:other",),
            ),
            primary_resolver=FailingResolver(),
            fallback_resolver=FailingResolver(),
        )

        result = verifier.verify("ghcr.io/acme/app:latest", "sha256:expected")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "manifest-unavailable")
        self.assertEqual(result.seen_repo_digests, ("ghcr.io/acme/app@sha256:other",))


if __name__ == "__main__":
    unittest.main()
