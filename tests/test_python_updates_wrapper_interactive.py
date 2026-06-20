from __future__ import annotations

from pathlib import Path


from tests.updates_wrapper_helpers import UpdatesWrapperTestCase

class UpdatesWrapperInteractiveTests(UpdatesWrapperTestCase):
    def test_interactive_select_remove_passes_original_line_numbers(self) -> None:
        self.wud_file.write_text(
            "# comment\nrepo/app:one\n\nrepo/app:two\nrepo/app:three\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1,3\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 2,5 --remove-lines-before-run 4 --yes", updater_log)
    def test_interactive_tag_change_passes_original_line_number(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nc\n3.0\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertFalse(self.sudo_log.exists())
        self.assertIn(
            "--only-lines 1 --allow-tag-updates --tag-override 1=3.0 --yes",
            updater_log,
        )
        self.assertIn("Selected tag update(s):", result.stdout)
    def test_interactive_tag_yes_keeps_wud_tag_without_override_prompt(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --allow-tag-updates --yes", updater_log)
        self.assertNotIn("--tag-override", updater_log)
        self.assertIn("[y]es/[n]o/[c]hange", result.stdout)
        self.assertNotIn("Override tag for update", result.stdout)
    def test_interactive_selected_tag_prompt_precedes_remove_prompt(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.0 tag=2.0\nrepo/sidecar:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ny\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --allow-tag-updates --yes", updater_log)
        self.assertNotIn("--remove-lines-before-run", updater_log)
        tag_prompt = result.stdout.index("Apply selected tag update entries?")
        remove_prompt = result.stdout.index("Remove unselected entries")
        self.assertLess(tag_prompt, remove_prompt)
    def test_interactive_tag_exclude_passes_line_and_recreate_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ne\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertFalse(self.sudo_log.exists())
        self.assertIn(
            "--only-lines 1 --exclude-tag-lines 1 --recreate-excluded-services --yes",
            updater_log,
        )
        self.assertNotIn("--allow-tag-updates", updater_log)
        self.assertNotIn("--tag-override", updater_log)
    def test_interactive_tag_exclude_can_skip_recreate(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ne\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --exclude-tag-lines 1 --yes", updater_log)
        self.assertNotIn("--recreate-excluded-services", updater_log)
    def test_interactive_tag_exclude_selects_subset_of_tag_lines(self) -> None:
        self.wud_file.write_text(
            "\n".join(
                [
                    "repo/app:1.0 tag=2.0",
                    "repo/sidecar:latest",
                    "repo/db:1.0 tag=1.1",
                    "repo/cache:1.0 tag=1.2",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1-4\ne\n1,4\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1,2,3,4 --exclude-tag-lines 1,4 --yes",
            updater_log,
        )
        self.assertNotIn("--allow-tag-updates", updater_log)
        self.assertNotIn("--tag-override", updater_log)
    def test_interactive_tag_exclude_rejects_non_tag_selection(self) -> None:
        self.wud_file.write_text(
            "\n".join(
                [
                    "repo/app:1.0 tag=2.0",
                    "repo/sidecar:latest",
                    "repo/db:1.0 tag=1.1",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1-3\ne\n2\n1,3\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "Invalid tag selection. Use listed tag update numbers/ranges like 1,3-5.",
            result.stdout,
        )
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1,2,3 --exclude-tag-lines 1,3 --yes",
            updater_log,
        )
        self.assertNotIn("--allow-tag-updates", updater_log)
        self.assertNotIn("--tag-override", updater_log)
    def test_interactive_declined_tag_updates_do_not_enable_allow_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --yes", updater_log)
        self.assertNotIn("--allow-tag-updates", updater_log)
        self.assertNotIn("--tag-override", updater_log)
    def test_interactive_untagged_tag_token_does_not_prompt(self) -> None:
        self.wud_file.write_text("repo/app tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="a\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("Selected tag update(s):", result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertNotIn("--allow-tag-updates", updater_log)
        self.assertNotIn("--tag-override", updater_log)
    def test_interactive_all_tag_override_aborts_when_snapshot_lines_change(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
        hook = self.root / "change-wud-file"
        hook.write_text(
            f"#!/usr/bin/env bash\nprintf 'repo/app:changed tag=wrong\\n' > {self.wud_file}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="a\nc\n3.0\n",
            env_overrides={"FAKE_COLUMN_HOOK": str(hook)},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "WUD file changed while selecting updates; please rerun updates.",
            result.stderr,
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())
    def test_interactive_holds_wud_lock_for_updater_handoff(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_UPDATER_ASSERT_LOCK": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "WUD_LOCK_HELD_BY_PARENT=1",
            self.updater_log.read_text(encoding="utf-8"),
        )
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())
    def test_interactive_select_aborts_when_snapshot_lines_change(self) -> None:
        self.wud_file.write_text("repo/app:one\nrepo/app:two\n", encoding="utf-8")
        hook = self.root / "change-wud-file"
        hook.write_text(
            f"#!/usr/bin/env bash\nprintf 'repo/app:changed\\nrepo/app:two\\n' > {self.wud_file}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_COLUMN_HOOK": str(hook)},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "WUD file changed while selecting updates; please rerun updates.",
            result.stderr,
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())
