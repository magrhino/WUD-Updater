from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path

from wud_updater.db import (
    DatabaseError,
    SCHEMA_VERSION,
    active_snooze,
    active_tag_exclusion_rules,
    open_db,
    init_db,
    insert_pending_update,
    insert_snooze,
    insert_update_event,
    insert_update_run,
    upsert_tag_exclusion_rule,
    update_pending_update,
    upsert_known_image,
)
from wud_updater.digest_provenance import (
    DIGEST_PROVENANCE_SQL_COLUMNS,
    DigestTagProvenance,
    digest_provenance_from_row,
    empty_digest_provenance_sql_values,
)


class DatabaseTests(unittest.TestCase):
    def test_empty_digest_provenance_sql_values_returns_empty_columns(self) -> None:
        self.assertEqual(
            empty_digest_provenance_sql_values(),
            dict.fromkeys(DIGEST_PROVENANCE_SQL_COLUMNS, ""),
        )

    def test_digest_provenance_from_row_treats_missing_columns_as_empty(self) -> None:
        class SparseRow(Mapping[str, str]):
            def __getitem__(self, key: str) -> str:
                if key == "digest_source_image":
                    return "repo/app:latest"
                raise KeyError(key)

            def __iter__(self) -> Iterator[str]:
                return iter(("digest_source_image",))

            def __len__(self) -> int:
                return 1

        self.assertEqual(
            digest_provenance_from_row({"digest_source_image": "repo/app:latest"}),
            DigestTagProvenance(source_image="repo/app:latest"),
        )
        self.assertEqual(
            digest_provenance_from_row(SparseRow()),
            DigestTagProvenance(source_image="repo/app:latest"),
        )
        self.assertIsNone(digest_provenance_from_row({}))

    def test_initial_db_creation_creates_expected_tables(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-db.") as tmpdir:
            db_path = Path(tmpdir) / "state" / "wud-updater.sqlite"

            with open_db(db_path) as conn:
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
                    "schema_migrations",
                    "update_runs",
                    "update_events",
                    "snoozes",
                    "service_policy",
                    "auto_update_schedule_runs",
                    "known_images",
                    "pending_updates",
                    "release_note_cache",
                    "tag_exclusion_rules",
                    "web_users",
                    "web_sessions",
                    "web_settings",
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

    def test_init_db_records_schema_migrations(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            init_db(conn)

            rows = conn.execute(
                """
                SELECT version
                FROM schema_migrations
                ORDER BY version
                """
            ).fetchall()

        self.assertEqual([row[0] for row in rows], [1, 2, 3, 4, 5, 6, 7])

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

    def test_init_db_migrates_v1_schema_to_current(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(V1_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 1")

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                )
            }

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertGreaterEqual(tables, {"pending_updates", "tag_exclusion_rules"})

    def test_init_db_migrates_v2_schema_to_current(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(V2_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 2")

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            exclusion_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'tag_exclusion_rules'
                """
            ).fetchone()
            web_users_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'web_users'
                """
            ).fetchone()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(exclusion_table)
        self.assertIsNotNone(web_users_table)

    def test_init_db_migrates_v3_schema_and_preserves_update_rows(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(V3_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 3")
            conn.execute(
                """
                INSERT INTO update_runs (started_at, status)
                VALUES ('2026-05-18T12:00:00+00:00', 'success')
                """
            )

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            run = conn.execute("SELECT status FROM update_runs").fetchone()
            migration_versions = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT version
                    FROM schema_migrations
                    ORDER BY version
                    """
                )
            ]

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(run[0], "success")
        self.assertEqual(migration_versions, [1, 2, 3, 4, 5, 6, 7])

    def test_init_db_migrates_v5_schema_and_preserves_policy_rows(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(V5_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 5")
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    snooze_default_seconds,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    'stack/app',
                    'live',
                    0,
                    3600,
                    '2026-05-28T12:00:00+00:00',
                    '2026-05-28T12:00:00+00:00',
                    '{"source":"test"}'
                )
                """
            )

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            policy = conn.execute(
                """
                SELECT *
                FROM service_policy
                WHERE service_key = 'stack/app'
                """
            ).fetchone()
            schedule_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'auto_update_schedule_runs'
                """
            ).fetchone()
            migration_versions = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT version
                    FROM schema_migrations
                    ORDER BY version
                    """
                )
            ]

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(schedule_table)
        self.assertEqual(policy["update_mode"], "live")
        self.assertEqual(policy["auto_update"], 0)
        self.assertIsNone(policy["auto_update_time"])
        self.assertEqual(policy["auto_update_days_json"], "[]")
        self.assertEqual(migration_versions, [1, 2, 3, 4, 5, 6, 7])

    def test_init_db_migrates_v6_schema_and_preserves_digestless_rows(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(V6_SCHEMA_SQL)
            conn.execute("PRAGMA user_version = 6")
            conn.execute(
                """
                INSERT INTO update_runs (id, started_at, status)
                VALUES (1, '2026-06-01T12:00:00+00:00', 'success')
                """
            )
            conn.execute(
                """
                INSERT INTO update_events (
                    run_id,
                    created_at,
                    service_name,
                    image,
                    status
                )
                VALUES (
                    1,
                    '2026-06-01T12:01:00+00:00',
                    'app',
                    'repo/app:latest',
                    'success'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO pending_updates (
                    run_id,
                    line_no,
                    raw,
                    image,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    1,
                    7,
                    'repo/app:latest',
                    'repo/app:latest',
                    'resolved',
                    '2026-06-01T12:00:00+00:00',
                    '2026-06-01T12:01:00+00:00'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO known_images (
                    service_key,
                    image,
                    updated_at
                )
                VALUES (
                    'stack/app',
                    'repo/app:latest',
                    '2026-06-01T12:01:00+00:00'
                )
                """
            )

            init_db(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            event = conn.execute("SELECT * FROM update_events").fetchone()
            pending = conn.execute("SELECT * FROM pending_updates").fetchone()
            known = conn.execute("SELECT * FROM known_images").fetchone()
            migration_versions = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT version
                    FROM schema_migrations
                    ORDER BY version
                    """
                )
            ]

        self.assertEqual(version, SCHEMA_VERSION)
        for row in (event, pending, known):
            self.assertEqual(row["digest_source_image"], "")
            self.assertEqual(row["digest_resolved_tag"], "")
            self.assertEqual(row["digest_watch_tag"], "")
            self.assertEqual(row["digest_target_digest"], "")
            self.assertEqual(row["digest_final_image"], "")
            self.assertEqual(row["digest_provenance_source"], "")
            self.assertEqual(row["digest_provenance_confidence"], "")
        self.assertEqual(migration_versions, [1, 2, 3, 4, 5, 6, 7])

    def test_init_db_rejects_malformed_existing_pending_updates(self) -> None:
        with sqlite3.connect(":memory:") as conn:
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
                digest_provenance=DigestTagProvenance(
                    source_image="repo/app:latest",
                    resolved_tag="latest",
                    watch_tag="latest",
                    target_digest="sha256:target",
                    final_image="repo/app@sha256:target",
                    provenance_source="apply",
                    provenance_confidence="verified",
                ),
            )
            row = conn.execute(
                "SELECT * FROM update_events WHERE id = ?",
                (event_id,),
            ).fetchone()

        self.assertEqual(row["run_id"], run_id)
        self.assertEqual(row["service_name"], "app")
        self.assertEqual(row["target_image"], "repo/app:2.0")
        self.assertEqual(row["metadata_json"], "{}")
        self.assertEqual(row["digest_source_image"], "repo/app:latest")
        self.assertEqual(row["digest_resolved_tag"], "latest")
        self.assertEqual(row["digest_target_digest"], "sha256:target")
        self.assertEqual(row["digest_final_image"], "repo/app@sha256:target")
        self.assertEqual(row["digest_provenance_source"], "apply")
        self.assertEqual(row["digest_provenance_confidence"], "verified")

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
                digest_provenance=DigestTagProvenance(
                    source_image="repo/app:latest",
                    resolved_tag="latest",
                    watch_tag="latest",
                    target_digest="sha256:target",
                    final_image="repo/app@sha256:target",
                    provenance_source="apply",
                    provenance_confidence="verified",
                ),
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
        self.assertEqual(row["digest_source_image"], "repo/app:latest")
        self.assertEqual(row["digest_watch_tag"], "latest")
        self.assertEqual(row["digest_target_digest"], "sha256:target")
        self.assertEqual(row["digest_provenance_source"], "apply")

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
                digest_provenance=DigestTagProvenance(
                    source_image="repo/app:latest",
                    resolved_tag="latest",
                    watch_tag="latest",
                    target_digest="sha256:target",
                    final_image="repo/app@sha256:target",
                    provenance_source="apply",
                    provenance_confidence="verified",
                ),
            )
            rows = conn.execute("SELECT * FROM known_images").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service_key"], "stack/app")
        self.assertEqual(rows[0]["image"], "repo/app:2.0")
        self.assertEqual(rows[0]["image_id"], "new")
        self.assertEqual(rows[0]["digest"], "sha256:new")
        self.assertEqual(rows[0]["digest_source_image"], "repo/app:latest")
        self.assertEqual(rows[0]["digest_resolved_tag"], "latest")
        self.assertEqual(rows[0]["digest_target_digest"], "sha256:target")
        self.assertEqual(rows[0]["digest_provenance_source"], "apply")

    def test_tag_exclusion_upsert_is_idempotent_and_active_lookup_merges_scopes(
        self,
    ) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            init_db(conn)

            first_id = upsert_tag_exclusion_rule(
                conn,
                scope="image_repo",
                image_repo="repo/app",
                tag="2.0",
                regex_fragment="2\\.0",
                created_at="2026-05-18T12:00:00+00:00",
                updated_at="2026-05-18T12:00:00+00:00",
            )
            second_id = upsert_tag_exclusion_rule(
                conn,
                scope="image_repo",
                image_repo="repo/app",
                tag="2.0",
                regex_fragment="2\\.0",
                updated_at="2026-05-18T12:01:00+00:00",
            )
            upsert_tag_exclusion_rule(
                conn,
                scope="service",
                image_repo="repo/app",
                service_key="app/api",
                tag="3.0",
                regex_fragment="3\\.0",
            )
            upsert_tag_exclusion_rule(
                conn,
                scope="service",
                image_repo="repo/app",
                service_key="app/other",
                tag="4.0",
                regex_fragment="4\\.0",
            )

            rows = active_tag_exclusion_rules(
                conn,
                image_repo="repo/app",
                service_key="app/api",
            )

        self.assertEqual(first_id, second_id)
        self.assertEqual([row["tag"] for row in rows], ["2.0", "3.0"])


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

V2_SCHEMA_SQL = (
    V1_SCHEMA_SQL
    + """
CREATE TABLE pending_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    raw TEXT NOT NULL,
    image TEXT NOT NULL,
    target_digest TEXT NOT NULL DEFAULT '',
    desired_tag TEXT NOT NULL DEFAULT '',
    service_key TEXT NOT NULL DEFAULT '',
    stack_name TEXT NOT NULL DEFAULT '',
    service_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    status_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, line_no),
    FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE CASCADE
);
"""
)

V3_SCHEMA_SQL = (
    V2_SCHEMA_SQL
    + """
CREATE TABLE tag_exclusion_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    image_repo TEXT NOT NULL,
    service_key TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL,
    tag TEXT NOT NULL,
    regex_fragment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (scope, image_repo, service_key, match_type, tag)
);
"""
)

V4_SCHEMA_SQL = (
    V3_SCHEMA_SQL
    + """
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE web_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL,
    password_updated_at TEXT NOT NULL,
    disabled_at TEXT
);

CREATE TABLE web_sessions (
    id_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent_hash TEXT NOT NULL DEFAULT '',
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES web_users(id) ON DELETE CASCADE
);

CREATE TABLE web_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
)

V5_SCHEMA_SQL = (
    V4_SCHEMA_SQL
    + """
CREATE TABLE release_note_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    image_repo TEXT NOT NULL DEFAULT '',
    upstream_repo TEXT NOT NULL DEFAULT '',
    current_tag TEXT NOT NULL DEFAULT '',
    target_tag TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    release_tag TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    breaking INTEGER NOT NULL DEFAULT 0,
    breaking_reasons_json TEXT NOT NULL DEFAULT '[]',
    links_json TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""
)

V6_SCHEMA_SQL = (
    V5_SCHEMA_SQL
    + """
ALTER TABLE service_policy
    ADD COLUMN auto_update_time TEXT;
ALTER TABLE service_policy
    ADD COLUMN auto_update_days_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE auto_update_schedule_runs (
    schedule_key TEXT PRIMARY KEY,
    service_key TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    run_id INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES update_runs(id) ON DELETE SET NULL
);
"""
)


if __name__ == "__main__":
    unittest.main()
