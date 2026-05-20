from __future__ import annotations

import unittest
from io import StringIO
from unittest import mock

from wud_updater import banner
from wud_updater.terminal import RICH_AVAILABLE, TerminalRenderer


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


class BannerTests(unittest.TestCase):
    def test_plain_banner_fallback_is_boxed_without_ansi(self) -> None:
        output = StringIO()
        renderer = TerminalRenderer(stream=output)

        renderer.startup_banner(
            art="WUD\nART\n",
            local_tag="v0.10.1",
            release_status=("Up to date: v0.10.1", "success"),
        )

        text = output.getvalue()
        self.assertIn("+-", text)
        self.assertIn("WUD-Updater v0.10.1", text)
        self.assertIn("Up to date: v0.10.1", text)
        self.assertNotIn("\x1b[", text)
        self.assertNotIn("╭", text)

    @unittest.skipUnless(RICH_AVAILABLE, "Rich is not installed")
    def test_rich_banner_uses_panel_text_and_color(self) -> None:
        output = StringIO()
        renderer = TerminalRenderer(stream=output, force_rich=True, width=180)

        renderer.startup_banner(
            art="WUD\nART\n",
            local_tag="v0.10.1",
            release_status=("Update available: v0.10.1 -> v0.11.0", "warning"),
        )

        text = output.getvalue()
        self.assertIn("WUD-Updater v0.10.1", text)
        self.assertIn("Update available: v0.10.1 -> v0.11.0", text)
        self.assertIn("╭", text)
        self.assertIn("\x1b[", text)

    def test_release_status_reports_newer_latest_tag(self) -> None:
        self.assertEqual(
            banner.release_status("v0.10.1", "v0.11.0"),
            ("Update available: v0.10.1 -> v0.11.0", "warning"),
        )

    def test_release_status_reports_same_or_older_tag_as_up_to_date(self) -> None:
        self.assertEqual(
            banner.release_status("v0.10.1", "v0.10.1"),
            ("Up to date: v0.10.1", "success"),
        )
        self.assertEqual(
            banner.release_status("v0.10.1", "v0.9.9"),
            ("Up to date: v0.10.1", "success"),
        )

    def test_fetch_latest_release_tag_normalizes_github_tag(self) -> None:
        with mock.patch.object(
            banner.urllib.request,
            "urlopen",
            return_value=FakeResponse(b'{"tag_name":"0.11.0"}'),
        ):
            self.assertEqual(banner.fetch_latest_release_tag(), "v0.11.0")

    def test_fetch_latest_release_tag_omits_network_failures(self) -> None:
        with mock.patch.object(
            banner.urllib.request,
            "urlopen",
            side_effect=OSError("egress blocked"),
        ):
            self.assertIsNone(banner.fetch_latest_release_tag())

    def test_forced_startup_banner_prints_to_non_tty(self) -> None:
        output = StringIO()

        printed = banner.print_startup_banner(
            environ={
                "WUD_UPDATER_BANNER": "1",
                "WUD_UPDATER_RELEASE_CHECK": "0",
            },
            stream=output,
        )

        self.assertTrue(printed)
        self.assertIn(f"WUD-Updater {banner.current_tag()}", output.getvalue())

    def test_auto_startup_banner_skips_non_tty(self) -> None:
        output = StringIO()

        printed = banner.print_startup_banner(environ={}, stream=output)

        self.assertFalse(printed)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
