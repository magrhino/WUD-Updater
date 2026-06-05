from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from unittest.mock import MagicMock

from wud_updater.command import CommandResult
from wud_updater.digest_verifier import (
    DigestVerifier,
    DockerManifestResolver,
    ManifestDocument,
    ManifestLookupError,
    _payload_digest,
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


class PayloadDigestTests(unittest.TestCase):
    def test_returns_top_level_digest_when_sha256_prefixed(self) -> None:
        result = _payload_digest({"digest": "sha256:abc123"})

        self.assertEqual(result, "sha256:abc123")

    def test_returns_descriptor_digest_when_top_level_absent(self) -> None:
        result = _payload_digest({"Descriptor": {"digest": "sha256:def456"}})

        self.assertEqual(result, "sha256:def456")

    def test_top_level_digest_takes_precedence_over_descriptor(self) -> None:
        result = _payload_digest(
            {
                "digest": "sha256:top",
                "Descriptor": {"digest": "sha256:inner"},
            }
        )

        self.assertEqual(result, "sha256:top")

    def test_returns_empty_string_when_top_level_digest_lacks_sha256_prefix(self) -> None:
        result = _payload_digest({"digest": "md5:abc123"})

        self.assertEqual(result, "")

    def test_returns_descriptor_digest_when_top_level_not_sha256(self) -> None:
        result = _payload_digest(
            {
                "digest": "md5:abc",
                "Descriptor": {"digest": "sha256:fallback"},
            }
        )

        self.assertEqual(result, "sha256:fallback")

    def test_returns_empty_string_when_descriptor_digest_lacks_sha256_prefix(self) -> None:
        result = _payload_digest({"Descriptor": {"digest": "md5:xyz"}})

        self.assertEqual(result, "")

    def test_returns_empty_string_for_empty_payload(self) -> None:
        result = _payload_digest({})

        self.assertEqual(result, "")

    def test_returns_empty_string_when_digest_is_none(self) -> None:
        result = _payload_digest({"digest": None})

        self.assertEqual(result, "")

    def test_returns_empty_string_when_descriptor_is_not_a_mapping(self) -> None:
        result = _payload_digest({"Descriptor": "not-a-dict"})

        self.assertEqual(result, "")

    def test_returns_empty_string_when_descriptor_digest_is_none(self) -> None:
        result = _payload_digest({"Descriptor": {"digest": None}})

        self.assertEqual(result, "")


def _make_docker_cli(stdout: str) -> MagicMock:
    """Return a mocked DockerCli that returns ``stdout`` from manifest commands."""
    cli = MagicMock()
    cli.manifest_inspect.return_value = CommandResult(
        args=(), cwd=None, returncode=0, stdout=stdout
    )
    cli.manifest_inspect_verbose.return_value = CommandResult(
        args=(), cwd=None, returncode=0, stdout=stdout
    )
    return cli


class DockerManifestResolverVerboseModeTests(unittest.TestCase):
    def test_non_verbose_mode_sets_docker_manifest_source_and_empty_digest(self) -> None:
        payload = {"mediaType": INDEX_TYPE, "schemaVersion": 2}
        cli = _make_docker_cli(json.dumps(payload))
        image = parse_registry_image("ghcr.io/acme/app:latest")
        assert image is not None
        resolver = DockerManifestResolver(cli, verbose=False)

        doc = resolver.fetch(image, "latest")

        self.assertEqual(doc.source, "docker-manifest")
        self.assertEqual(doc.digest, "")
        cli.manifest_inspect.assert_called_once()
        cli.manifest_inspect_verbose.assert_not_called()

    def test_verbose_mode_sets_verbose_source_and_extracts_digest_from_top_level(
        self,
    ) -> None:
        payload = {
            "mediaType": INDEX_TYPE,
            "schemaVersion": 2,
            "digest": "sha256:index-digest",
        }
        cli = _make_docker_cli(json.dumps(payload))
        image = parse_registry_image("ghcr.io/acme/app:latest")
        assert image is not None
        resolver = DockerManifestResolver(cli, verbose=True)

        doc = resolver.fetch(image, "latest")

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "sha256:index-digest")
        cli.manifest_inspect_verbose.assert_called_once()
        cli.manifest_inspect.assert_not_called()

    def test_verbose_mode_extracts_digest_from_descriptor(self) -> None:
        payload = {
            "mediaType": INDEX_TYPE,
            "schemaVersion": 2,
            "Descriptor": {"digest": "sha256:descriptor-digest"},
        }
        cli = _make_docker_cli(json.dumps(payload))
        image = parse_registry_image("docker.io/repo/app:1.0")
        assert image is not None
        resolver = DockerManifestResolver(cli, verbose=True)

        doc = resolver.fetch(image, "1.0")

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "sha256:descriptor-digest")

    def test_verbose_mode_returns_empty_digest_when_payload_has_no_digest(self) -> None:
        payload = {"mediaType": INDEX_TYPE, "schemaVersion": 2}
        cli = _make_docker_cli(json.dumps(payload))
        image = parse_registry_image("ghcr.io/acme/app:latest")
        assert image is not None
        resolver = DockerManifestResolver(cli, verbose=True)

        doc = resolver.fetch(image, "latest")

        self.assertEqual(doc.source, "docker-manifest-verbose")
        self.assertEqual(doc.digest, "")

    def test_verbose_mode_propagates_media_type(self) -> None:
        payload = {
            "mediaType": INDEX_TYPE,
            "schemaVersion": 2,
            "digest": "sha256:abc",
        }
        cli = _make_docker_cli(json.dumps(payload))
        image = parse_registry_image("ghcr.io/acme/app:latest")
        assert image is not None
        resolver = DockerManifestResolver(cli, verbose=True)

        doc = resolver.fetch(image, "latest")

        self.assertEqual(doc.media_type, INDEX_TYPE)


class DigestVerifierResolveTagDigestTests(unittest.TestCase):
    def test_returns_untrusted_for_unsupported_image_reference(self) -> None:
        # An image reference without a tag (e.g. no colon) is not parseable
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=FailingResolver(),
            fallback_resolver=FailingResolver(),
        )

        # Empty string and tag-less bare names return None from parse_registry_image
        result = verifier.resolve_tag_digest("")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "untrusted")
        self.assertEqual(result.reason, "unsupported-image-reference")

    def test_returns_ok_true_when_document_has_direct_digest(self) -> None:
        expected_digest = "sha256:abc"
        resolver = StaticResolver(
            {
                ("ghcr.io", "acme/app", "latest"): ManifestDocument(
                    source="static",
                    digest=expected_digest,
                    media_type=INDEX_TYPE,
                    payload={},
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.resolve_tag_digest("ghcr.io/acme/app:latest")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.reason, "tag-digest-resolved")
        self.assertEqual(result.digest, expected_digest)
        self.assertEqual(result.source, "static")

    def test_returns_ok_true_when_digest_comes_from_payload(self) -> None:
        expected_digest = "sha256:from-payload"
        resolver = StaticResolver(
            {
                ("ghcr.io", "acme/app", "v2.0"): ManifestDocument(
                    source="static",
                    digest="",
                    media_type=INDEX_TYPE,
                    payload={"digest": expected_digest},
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.resolve_tag_digest("ghcr.io/acme/app:v2.0")

        self.assertTrue(result.ok)
        self.assertEqual(result.digest, expected_digest)

    def test_returns_ok_false_when_manifest_lookup_fails(self) -> None:
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=FailingResolver(),
            fallback_resolver=FailingResolver(),
        )

        result = verifier.resolve_tag_digest("ghcr.io/acme/app:latest")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertNotEqual(result.error, "")

    def test_returns_failed_for_non_ghcr_manifest_lookup_error(self) -> None:
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=FailingResolver(),
            fallback_resolver=FailingResolver(),
        )

        result = verifier.resolve_tag_digest("quay.io/acme/app:latest")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "untrusted")

    def test_returns_manifest_digest_missing_when_no_digest_available(self) -> None:
        resolver = StaticResolver(
            {
                ("ghcr.io", "acme/app", "latest"): ManifestDocument(
                    source="static",
                    digest="",
                    media_type=INDEX_TYPE,
                    payload={},
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.resolve_tag_digest("ghcr.io/acme/app:latest")

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "manifest-digest-missing")
        self.assertEqual(result.source, "static")

    def test_returns_ok_true_for_docker_hub_image(self) -> None:
        resolver = StaticResolver(
            {
                ("docker.io", "library/alpine", "3.20"): ManifestDocument(
                    source="static",
                    digest="sha256:alpine-index",
                    media_type=INDEX_TYPE,
                    payload={},
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.resolve_tag_digest("alpine:3.20")

        self.assertTrue(result.ok)
        self.assertEqual(result.digest, "sha256:alpine-index")

    def test_direct_digest_takes_precedence_over_payload_digest(self) -> None:
        resolver = StaticResolver(
            {
                ("ghcr.io", "acme/app", "latest"): ManifestDocument(
                    source="static",
                    digest="sha256:direct-wins",
                    media_type=INDEX_TYPE,
                    payload={"digest": "sha256:payload-loses"},
                ),
            }
        )
        verifier = DigestVerifier(
            FakeDocker(),
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )

        result = verifier.resolve_tag_digest("ghcr.io/acme/app:latest")

        self.assertTrue(result.ok)
        self.assertEqual(result.digest, "sha256:direct-wins")


if __name__ == "__main__":
    unittest.main()
