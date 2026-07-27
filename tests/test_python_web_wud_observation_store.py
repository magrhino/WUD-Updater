from __future__ import annotations

import sqlite3
from pathlib import Path

from wudup import web_wud_observation_store


def _observation(
    name: str,
    *,
    observed_at: str = "2026-07-27T12:00:00+00:00",
) -> web_wud_observation_store.StoredPendingObservation:
    identity = (
        "local",
        f"docker.local.{name}",
        name,
        f"registry.example/acme/{name}:1.0.0",
        f"sha256:{name}",
        "sha256:local",
        "linux/amd64",
    )
    return web_wud_observation_store.StoredPendingObservation(
        identity=identity,
        observation={
            "id": identity[1],
            "name": name,
            "image": identity[3],
            "remote_tag": "1.1.0",
        },
        observed_at=observed_at,
    )


def test_pending_observation_store_round_trips_and_replaces_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wudup.sqlite"
    source = web_wud_observation_store.source_key("https://wud.test:3000")

    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=source,
        observations=[_observation("app"), _observation("worker")],
    )
    initial = web_wud_observation_store.load_pending_observations(
        db_path,
        source=source,
    )

    assert [item.identity[2] for item in initial] == ["app", "worker"]
    assert initial[0].observation["remote_tag"] == "1.1.0"

    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=source,
        observations=[_observation("app", observed_at="2026-07-27T13:00:00+00:00")],
    )
    replaced = web_wud_observation_store.load_pending_observations(
        db_path,
        source=source,
    )

    assert len(replaced) == 1
    assert replaced[0].identity[2] == "app"
    assert replaced[0].observed_at == "2026-07-27T13:00:00+00:00"


def test_pending_observation_store_is_scoped_by_hashed_source(tmp_path: Path) -> None:
    db_path = tmp_path / "wudup.sqlite"
    first_source = web_wud_observation_store.source_key("https://wud-a.test:3000")
    second_source = web_wud_observation_store.source_key("https://wud-b.test:3000")

    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=first_source,
        observations=[_observation("first")],
    )
    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=second_source,
        observations=[_observation("second")],
    )
    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=first_source,
        observations=[],
    )

    assert web_wud_observation_store.load_pending_observations(
        db_path,
        source=first_source,
    ) == ()
    assert [
        item.identity[2]
        for item in web_wud_observation_store.load_pending_observations(
            db_path,
            source=second_source,
        )
    ] == ["second"]


def test_pending_observation_store_ignores_malformed_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "wudup.sqlite"
    source = web_wud_observation_store.source_key("https://wud.test:3000")
    web_wud_observation_store.replace_pending_observations(
        db_path,
        source=source,
        observations=[_observation("app")],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE wud_pending_observation_cache
            SET observation_json = '[]'
            WHERE source_key = ?
            """,
            (source,),
        )

    assert web_wud_observation_store.load_pending_observations(
        db_path,
        source=source,
    ) == ()
