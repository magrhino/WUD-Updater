from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from wudup.digest_verifier import DigestResolveResult
from wudup.platforms import ImagePlatform
from wudup.security_subjects import (
    PendingSecurityRequest,
    _request_for_target,
    pending_security_context,
)
from wudup.web_pending_sources import PendingSourceResult
from wudup.wud_file import parse_wud_text


class SecuritySubjectTests(unittest.TestCase):
    def test_request_prefers_compose_platform_and_reports_conflict(self) -> None:
        target = parse_wud_text(
            "repo/app:1.0 tag=2.0 platform=linux/amd64 "
            "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        ).targets[0]

        request = _request_for_target(
            target,
            compose_platform=ImagePlatform("linux", "arm64"),
            wud_platform=target.platform,
        )

        self.assertEqual(request.identity_status, "mismatch")
        self.assertEqual(request.error, "Compose platform conflicts with WUD platform")
        self.assertEqual(request.candidate_image, "repo/app:2.0")
        self.assertEqual(request.platform, ImagePlatform("linux", "arm64"))
        self.assertEqual(request.platform_source, "compose")

    def test_request_rejects_ambiguous_compose_platforms(self) -> None:
        target = parse_wud_text(
            "repo/app:1.0 platform=linux/amd64 "
            "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        ).targets[0]

        request = _request_for_target(
            target,
            compose_platform=None,
            compose_platform_conflict=True,
            wud_platform=target.platform,
        )

        self.assertEqual(request.identity_status, "mismatch")
        self.assertEqual(request.error, "Multiple Compose platforms matched WUD line")
        self.assertEqual(request.platform, ImagePlatform("linux", "amd64"))
        self.assertEqual(request.platform_source, "wud")

    def test_request_requires_reported_digest_and_platform(self) -> None:
        no_digest = _request_for_target(
            parse_wud_text("repo/app:1.0 platform=linux/amd64\n").targets[0],
            compose_platform=None,
            wud_platform=ImagePlatform("linux", "amd64"),
        )
        no_platform = _request_for_target(
            parse_wud_text(
                "repo/app:1.0 "
                "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            ).targets[0],
            compose_platform=None,
            wud_platform=None,
        )

        self.assertEqual(no_digest.identity_status, "unsupported")
        self.assertEqual(no_digest.error, "reported digest is required")
        self.assertEqual(no_platform.identity_status, "unsupported")
        self.assertEqual(no_platform.error, "platform is required")

    def test_request_key_includes_platform(self) -> None:
        request = PendingSecurityRequest(
            line_no=1,
            raw=(
                "repo/app:1.0 tag=2.0 "
                "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            image="repo/app:1.0",
            candidate_image="repo/app:2.0",
            reported_digest=(
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            platform=ImagePlatform("linux", "amd64"),
            platform_source="wud",
        )

        self.assertNotEqual(
            request.request_key,
            replace(request, platform=ImagePlatform("linux", "arm64")).request_key,
        )
        self.assertNotEqual(
            request.request_key,
            replace(request, platform=None, platform_source="").request_key,
        )

    def test_context_resolves_missing_digest_once_per_candidate(self) -> None:
        digest = f"sha256:{'b' * 64}"
        verifier = _FakeDigestVerifier(
            DigestResolveResult(
                ok=True,
                status="resolved",
                reason="tag-digest-resolved",
                digest=digest,
            )
        )
        source = _pending_source(
            "repo/app:1.0 tag=2.0 platform=linux/amd64\n"
            "repo/app:1.0 tag=2.0 platform=linux/amd64\n"
        )

        with mock.patch(
            "wudup.security_subjects.resolve_pending_source",
            return_value=source,
        ):
            context = pending_security_context(
                _settings(),
                include_compose=False,
                digest_verifier=verifier,
            )

        self.assertEqual(verifier.calls, ["repo/app:2.0"])
        self.assertEqual(
            [request.reported_digest for request in context.requests],
            [digest, digest],
        )
        self.assertEqual(
            [request.identity_status for request in context.requests],
            ["pending", "pending"],
        )
        self.assertEqual([request.error for request in context.requests], ["", ""])

    def test_context_keeps_missing_digest_unsupported_when_lookup_fails(self) -> None:
        verifier = _FakeDigestVerifier(
            DigestResolveResult(
                ok=False,
                status="failed",
                reason="manifest-unavailable",
                error="registry auth failed",
            )
        )
        source = _pending_source("repo/app:1.0 tag=2.0 platform=linux/amd64\n")

        with mock.patch(
            "wudup.security_subjects.resolve_pending_source",
            return_value=source,
        ):
            context = pending_security_context(
                _settings(),
                include_compose=False,
                digest_verifier=verifier,
            )

        request = context.requests[0]
        self.assertEqual(verifier.calls, ["repo/app:2.0"])
        self.assertEqual(request.identity_status, "unsupported")
        self.assertEqual(request.error, "reported digest is required")
        self.assertEqual(request.reported_digest, "")
        self.assertEqual(
            request.warnings,
            (
                "Could not resolve reported digest for repo/app:2.0: "
                "registry auth failed",
            ),
        )


class _FakeDigestVerifier:
    def __init__(self, result: DigestResolveResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def resolve_tag_digest(self, image: str) -> DigestResolveResult:
        self.calls.append(image)
        return self.result


def _settings():
    return SimpleNamespace(security_scan=SimpleNamespace(enabled=True))


def _pending_source(text: str) -> PendingSourceResult:
    return PendingSourceResult(
        configured="api",
        active="api",
        label="WUD API",
        source_file="WUD API",
        exists=True,
        parsed=parse_wud_text(text),
        text=text,
        source_hash="test",
    )


if __name__ == "__main__":
    unittest.main()
