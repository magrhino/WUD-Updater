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
    insert_pending_update,
    insert_snooze,
    insert_update_event,
    insert_update_run,
    update_pending_update,
    upsert_known_image,
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
                    "pending_updates",
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

    def test_init_db_sets_user_version_to_current_schema(self) -> None:
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

    def test_init_db_migrates_v1_schema_to_v2(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(V1_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 1")

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            pending_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'pending_updates'
                """
            ).fetchone()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(pending_table)

    def test_init_db_rejects_malformed_existing_pending_updates(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(V1_SCHEMA_SQL)
            conn.execute(
                """
                CREATE TABLE pending_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL
                )
                """
            )

            with self.assertRaisesRegex(
                DatabaseError,
                "Unexpected columns for table pending_updates",
            ):
                init_db(conn)

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

    def test_pending_update_helpers_insert_and_update_status(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)
            run_id = insert_update_run(conn)

            pending_id = insert_pending_update(
                conn,
                run_id=run_id,
                line_no=7,
                raw="repo/app:latest",
                image="repo/app:latest",
                target_digest="sha256:target",
                service_key="stack/app",
            )
            update_pending_update(
                conn,
                run_id=run_id,
                line_no=7,
                status="resolved",
                status_reason="updated",
                stack_name="stack",
                service_name="app",
            )
            row = conn.execute(
                "SELECT * FROM pending_updates WHERE id = ?",
                (pending_id,),
            ).fetchone()

        self.assertEqual(row["line_no"], 7)
        self.assertEqual(row["target_digest"], "sha256:target")
        self.assertEqual(row["service_key"], "stack/app")
        self.assertEqual(row["stack_name"], "stack")
        self.assertEqual(row["service_name"], "app")
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["status_reason"], "updated")

    def test_known_image_upsert_replaces_service_state(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)

            upsert_known_image(
                conn,
                service_key="stack/app",
                image="repo/app:1.0",
                image_id="old",
                digest="sha256:old",
                updated_at="2026-05-18T12:00:00+00:00",
            )
            upsert_known_image(
                conn,
                service_key="stack/app",
                image="repo/app:2.0",
                image_id="new",
                digest="sha256:new",
                updated_at="2026-05-18T12:01:00+00:00",
            )
            rows = conn.execute("SELECT * FROM known_images").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service_key"], "stack/app")
        self.assertEqual(rows[0]["image"], "repo/app:2.0")
        self.assertEqual(rows[0]["image_id"], "new")
        self.assertEqual(rows[0]["digest"], "sha256:new")


V1_SCHEMA_SQL = """
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
);

CREATE TABLE update_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    service_name TEXT NOT NULL,
    stack_name TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL,
    target_image TEXT NOT NULL DEFAULT '',
    old_image_id TEXT NOT NULL DEFAULT '',
    new_image_id TEXT NOT NULL DEFAULT '',
    old_digest TEXT NOT NULL DEFAULT '',
    new_digest TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE CASCADE
);

CREATE TABLE snoozes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_key TEXT NOT NULL,
    snoozed_until TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE service_policy (
    service_key TEXT PRIMARY KEY,
    update_mode TEXT NOT NULL DEFAULT '',
    auto_update INTEGER NOT NULL DEFAULT 1,
    snooze_default_seconds INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE known_images (
    service_key TEXT PRIMARY KEY,
    image TEXT NOT NULL,
    image_id TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


if __name__ == "__main__":
    unittest.main()
