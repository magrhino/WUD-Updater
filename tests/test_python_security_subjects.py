from __future__ import annotations

import unittest

from wudup.platforms import ImagePlatform
from wudup.security_subjects import _request_for_target
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


if __name__ == "__main__":
    unittest.main()
