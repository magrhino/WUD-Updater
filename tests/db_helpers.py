from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def db_connection(database: str | Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(database)) as conn:
        yield conn
