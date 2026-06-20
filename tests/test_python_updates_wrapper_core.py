from __future__ import annotations


from wudup.updates import (
    _parse_display_spec,
    _parse_todo_entries,
)

from tests.updates_wrapper_helpers import UpdatesWrapperTestCase

class UpdatesWrapperCoreTests(UpdatesWrapperTestCase):
    def test_dry_run_does_not_invoke_updater(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())
        self.assertIn("Dry-run mode: not running updates", result.stdout)
    def test_todo_entries_use_canonical_wud_parsing(self) -> None:
        entries = _parse_todo_entries(
            "# header\n"
            "\n"
            "repo/app:1.0 tag=2.0 sha256=abc\n"
            "repo/db:latest\n"
        )

        self.assertEqual([entry.line_no for entry in entries], [3, 4])
        self.assertEqual(entries[0].raw, "repo/app:1.0 tag=2.0 sha256=abc")
        self.assertEqual(entries[0].display_raw, "repo/app:1.0 tag=2.0")
        self.assertEqual(entries[0].first, "repo/app:1.0")
        self.assertEqual(entries[0].desired_tag, "2.0")
        self.assertEqual(entries[1].desired_tag, "")
    def test_display_spec_uses_canonical_line_spec_rules(self) -> None:
        self.assertEqual(_parse_display_spec(" 3,1-2 ", 3), [1, 2, 3])
        with self.assertRaises(ValueError):
            _parse_display_spec("1,", 3)
