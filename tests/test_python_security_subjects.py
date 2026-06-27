from __future__ import annotations

import unittest
from dataclasses import replace

from wudup.platforms import ImagePlatform
from wudup.security_subjects import PendingSecurityRequest, _request_for_target
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


if __name__ == "__main__":
    unittest.main()
