from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wudup.updates import (
    UpdateSelectionState,
    UpdatesError,
    UpdatesFileLock,
)

class UpdateSelectionStateTests(unittest.TestCase):
    def test_defaults_are_empty_and_false(self) -> None:
        state = UpdateSelectionState()

        self.assertEqual(state.selected_line_spec, "")
        self.assertEqual(state.remove_line_spec, "")
        self.assertFalse(state.allow_tag_updates)
        self.assertEqual(state.tag_override_specs, ())
        self.assertEqual(state.exclude_tag_line_spec, "")
        self.assertFalse(state.recreate_excluded_services)

    def test_custom_values_are_preserved(self) -> None:
        state = UpdateSelectionState(
            selected_line_spec="2,4",
            remove_line_spec="1,3",
            allow_tag_updates=True,
            tag_override_specs=("2=3.0", "4=1.5"),
            exclude_tag_line_spec="5",
            recreate_excluded_services=True,
        )

        self.assertEqual(state.selected_line_spec, "2,4")
        self.assertEqual(state.remove_line_spec, "1,3")
        self.assertTrue(state.allow_tag_updates)
        self.assertEqual(state.tag_override_specs, ("2=3.0", "4=1.5"))
        self.assertEqual(state.exclude_tag_line_spec, "5")
        self.assertTrue(state.recreate_excluded_services)


class UpdatesFileLockTests(unittest.TestCase):
    def test_existing_lock_times_out_without_permission_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-lock.") as tmp:
            wud_file = Path(tmp) / "images.todo"
            lock_dir = Path(f"{wud_file}.lock")
            lock_dir.mkdir()
            sleep = mock.Mock()
            lock = UpdatesFileLock(
                str(wud_file),
                "0",
                {},
                use_sudo=False,
                sleep=sleep,
            )

            with self.assertRaisesRegex(UpdatesError, "Timed out waiting"):
                lock.acquire()

        sleep.assert_not_called()
