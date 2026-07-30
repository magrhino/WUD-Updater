from __future__ import annotations

import json
from pathlib import Path

import pytest

from wudup import web_file_selection_store
from wudup.db import open_db
from wudup.updater_models import CompletedUpdateSelection


def test_file_selection_checkpoint_survives_unrelated_file_changes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state" / "wudup.sqlite"
    pending_file = tmp_path / "state" / "images.todo"
    pending_file.parent.mkdir(parents=True)
    text = "repo/shared:latest\n"
    pending_file.write_text(text, encoding="utf-8")
    selection = CompletedUpdateSelection(
        target_key="target-key",
        completion_id="done-v1-selection",
    )

    web_file_selection_store.replace_completed_update_selections(
        db_path,
        pending_file=pending_file,
        selections=(selection,),
    )

    assert web_file_selection_store.load_completed_update_selections(
        db_path,
        pending_file=pending_file,
        pending_target_keys={"target-key"},
    ) == (selection,)
    with open_db(db_path) as conn:
        stored = conn.execute(
            "SELECT value FROM web_settings WHERE key = ?",
            (web_file_selection_store.FILE_SELECTIONS_SETTING_KEY,),
        ).fetchone()
    assert stored is not None
    stored_value = str(stored["value"])
    assert isinstance(json.loads(stored_value), dict)
    assert str(pending_file) not in stored_value

    replacement = tmp_path / "replacement.todo"
    replacement.write_text(text, encoding="utf-8")
    replacement.replace(pending_file)
    pending_file.write_text(f"{text}repo/other:latest\n", encoding="utf-8")

    assert web_file_selection_store.load_completed_update_selections(
        db_path,
        pending_file=pending_file,
        pending_target_keys={"target-key", "other-key"},
    ) == (selection,)
    assert web_file_selection_store.load_completed_update_selections(
        db_path,
        pending_file=pending_file,
        pending_target_keys={"other-key"},
    ) == ()


def test_file_selection_checkpoint_rejects_malformed_stored_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state" / "wudup.sqlite"
    pending_file = tmp_path / "state" / "images.todo"
    pending_file.parent.mkdir(parents=True)
    text = "repo/shared:latest\n"
    pending_file.write_text(text, encoding="utf-8")
    selection = CompletedUpdateSelection(
        target_key="target-key",
        completion_id="done-v1-selection",
    )
    web_file_selection_store.replace_completed_update_selections(
        db_path,
        pending_file=pending_file,
        selections=(selection,),
    )
    with open_db(db_path) as conn:
        with conn:
            conn.execute(
                "UPDATE web_settings SET value = ? WHERE key = ?",
                ("{", web_file_selection_store.FILE_SELECTIONS_SETTING_KEY),
            )

    with pytest.raises(
        web_file_selection_store.FileSelectionStoreError,
        match="Could not read partial update completion state",
    ):
        web_file_selection_store.load_completed_update_selections(
            db_path,
            pending_file=pending_file,
            pending_target_keys={"target-key"},
        )


def test_file_selection_checkpoint_rejects_nonpersistent_database(
    tmp_path: Path,
) -> None:
    pending_file = tmp_path / "images.todo"
    pending_file.write_text("repo/shared:latest\n", encoding="utf-8")

    with pytest.raises(web_file_selection_store.FileSelectionStoreError):
        web_file_selection_store.load_completed_update_selections(
            ":memory:",
            pending_file=pending_file,
            pending_target_keys=set(),
        )
    with pytest.raises(web_file_selection_store.FileSelectionStoreError):
        web_file_selection_store.replace_completed_update_selections(
            ":memory:",
            pending_file=pending_file,
            selections=(),
        )


def test_retained_completions_prune_obsolete_identities() -> None:
    current = CompletedUpdateSelection("target", "current")
    sibling = CompletedUpdateSelection("target", "sibling")
    obsolete = CompletedUpdateSelection("target", "obsolete")
    other_target = CompletedUpdateSelection("other", "other-current")

    retained = web_file_selection_store.retained_completed_update_selections(
        pending_target_keys={"target", "other"},
        previous=(obsolete, current, other_target),
        successful=(),
        discovered=(current, sibling),
    )

    assert retained == (other_target, current)


def test_retained_completions_reset_only_broad_target() -> None:
    selected = CompletedUpdateSelection("selected", "selected-current")
    sibling = CompletedUpdateSelection("selected", "selected-sibling")
    other = CompletedUpdateSelection("other", "other-current")

    retained = web_file_selection_store.retained_completed_update_selections(
        pending_target_keys={"selected", "other"},
        previous=(selected, other),
        successful=(sibling,),
        discovered=(selected, sibling),
        reset_target_keys={"selected"},
    )

    assert retained == (other,)
