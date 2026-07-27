"""Restart-safe storage for last-known-good WUD pending observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .db import init_db, open_db

WudContainerIdentity = tuple[str, str, str, str, str, str, str]


@dataclass(frozen=True)
class StoredPendingObservation:
    identity: WudContainerIdentity
    observation: Mapping[str, object]
    observed_at: str


def source_key(normalized_base_url: str) -> str:
    """Return a stable, non-reversible key without persisting the API URL."""

    return hashlib.sha256(normalized_base_url.encode("utf-8")).hexdigest()


def load_pending_observations(
    db_path: str | Path,
    *,
    source: str,
) -> tuple[StoredPendingObservation, ...]:
    if str(db_path) == ":memory:":
        return ()
    with open_db(db_path) as conn:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT identity_json, observation_json, observed_at
            FROM wud_pending_observation_cache
            WHERE source_key = ?
            ORDER BY identity_json
            """,
            (source,),
        ).fetchall()

    result: list[StoredPendingObservation] = []
    for row in rows:
        identity = _identity_from_json(str(row["identity_json"]))
        observation = _observation_from_json(str(row["observation_json"]))
        observed_at = str(row["observed_at"])
        if identity is None or observation is None or not observed_at:
            continue
        result.append(
            StoredPendingObservation(
                identity=identity,
                observation=observation,
                observed_at=observed_at,
            )
        )
    return tuple(result)


def replace_pending_observations(
    db_path: str | Path,
    *,
    source: str,
    observations: Sequence[StoredPendingObservation],
) -> None:
    if str(db_path) == ":memory:":
        return
    rows = [
        (
            source,
            json.dumps(item.identity, separators=(",", ":")),
            json.dumps(
                dict(item.observation),
                sort_keys=True,
                separators=(",", ":"),
            ),
            item.observed_at,
        )
        for item in observations
    ]
    with open_db(db_path) as conn:
        init_db(conn)
        with conn:
            conn.execute("DELETE FROM wud_pending_observation_cache")
            conn.executemany(
                """
                INSERT INTO wud_pending_observation_cache (
                    source_key,
                    identity_json,
                    observation_json,
                    observed_at
                )
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )


def _identity_from_json(raw: str) -> WudContainerIdentity | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 7
        or not all(isinstance(item, str) for item in value)
    ):
        return None
    return cast(WudContainerIdentity, tuple(value))


def _observation_from_json(raw: str) -> Mapping[str, object] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return value
