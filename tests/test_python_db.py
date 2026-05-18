from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from wud_updater.db import (
    DatabaseError,
    SCHEMA_VERSION,
    active_snooze,
    connect_db,
    init_db,
    insert_snooze,
    insert_update_event,
    insert_update_run,
)


class DatabaseTests(unittest.TestCase):
    def test_initial_db_creation_creates_expected_tables(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-db.") as tmpdir:
            db_path = Path(tmpdir) / "state" / "wud-updater.sqlite"

            with connect_db(db_path) as conn:
                init_db(conn)
                tables = {
                    row["name"]
                    for row in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    )
                }

            self.assertTrue(db_path.is_file())
            self.assertGreaterEqual(
                tables,
                {
                    "update_runs",
                    "update_events",
                    "snoozes",
                    "service_policy",
                    "known_images",
                },
            )

    def test_init_db_is_idempotent(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)
            run_id = insert_update_run(
                conn,
                started_at="2026-05-18T12:00:00+00:00",
                status="started",
            )
            init_db(conn)

            row = conn.execute(
                "SELECT id, status FROM update_runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "started")

    def test_init_db_sets_user_version_to_one(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            init_db(conn)

            version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION)

    def test_init_db_accepts_matching_version_zero_table(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.execute(
                """
                CREATE TABLE update_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT '',
                    wud_file TEXT NOT NULL DEFAULT '',
                    log_file TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION)

    def test_init_db_rejects_existing_table_with_missing_columns(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.execute(
                """
                CREATE TABLE update_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL
                )
                """
            )

            with self.assertRaisesRegex(
                DatabaseError,
                "Unexpected columns for table update_runs",
            ):
                init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            created_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'update_events'
                """
            ).fetchone()

        self.assertEqual(version, 0)
        self.assertIsNone(created_table)

    def test_init_db_rejects_existing_table_with_wrong_column_definition(
        self,
    ) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.execute(
                """
                CREATE TABLE snoozes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_key TEXT NOT NULL,
                    snoozed_until INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

            with self.assertRaisesRegex(
                DatabaseError,
                "Unexpected column definition for table snoozes",
            ):
                init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, 0)

    def test_init_db_rejects_current_version_with_missing_schema(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.execute("PRAGMA user_version = 1")

            with self.assertRaisesRegex(
                DatabaseError,
                "Missing expected table: update_runs",
            ):
                init_db(conn)

    def test_insert_update_run(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)

            run_id = insert_update_run(
                conn,
                started_at="2026-05-18T12:00:00+00:00",
                status="success",
                dry_run=True,
                mode="stop",
                wud_file="/tmp/images.todo",
                log_file="/tmp/update.log",
            )
            row = conn.execute(
                "SELECT * FROM update_runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["dry_run"], 1)
        self.assertEqual(row["mode"], "stop")
        self.assertEqual(row["metadata_json"], "{}")

    def test_insert_update_event(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)
            run_id = insert_update_run(
                conn,
                started_at="2026-05-18T12:00:00+00:00",
            )

            event_id = insert_update_event(
                conn,
                run_id=run_id,
                created_at="2026-05-18T12:01:00+00:00",
                service_name="app",
                stack_name="stack",
                image="repo/app:1.0",
                target_image="repo/app:2.0",
                status="updated",
            )
            row = conn.execute(
                "SELECT * FROM update_events WHERE id = ?",
                (event_id,),
            ).fetchone()

        self.assertEqual(row["run_id"], run_id)
        self.assertEqual(row["service_name"], "app")
        self.assertEqual(row["target_image"], "repo/app:2.0")
        self.assertEqual(row["metadata_json"], "{}")

    def test_active_snooze_lookup_returns_latest_unexpired_snooze(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)
            insert_snooze(
                conn,
                service_key="stack/app",
                snoozed_until="2026-05-18T11:00:00+00:00",
                reason="expired",
                created_at="2026-05-18T10:00:00+00:00",
            )
            insert_snooze(
                conn,
                service_key="stack/app",
                snoozed_until="2026-05-18T13:00:00+00:00",
                reason="maintenance",
                created_at="2026-05-18T10:00:00+00:00",
            )
            insert_snooze(
                conn,
                service_key="stack/other",
                snoozed_until="2026-05-18T14:00:00+00:00",
                reason="other service",
                created_at="2026-05-18T10:00:00+00:00",
            )

            row = active_snooze(
                conn,
                service_key="stack/app",
                now="2026-05-18T12:00:00+00:00",
            )
            missing = active_snooze(
                conn,
                service_key="stack/missing",
                now="2026-05-18T12:00:00+00:00",
            )

        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "maintenance")
        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()
