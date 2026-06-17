
from __future__ import annotations

from pathlib import Path

from wud_updater.db import init_db, open_db, upsert_known_image
from wud_updater.digest_provenance import DigestTagProvenance

def _seed_known_digest_provenance(
    tmp_path: Path,
    *,
    service_key: str = "stack/app",
    image: str = "repo/app@sha256:old",
    tag: str = "latest",
) -> None:
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        upsert_known_image(
            conn,
            service_key=service_key,
            image=image,
            image_id="sha256:old-id",
            digest=image,
            digest_provenance=DigestTagProvenance(
                source_image=f"repo/app:{tag}",
                resolved_tag=tag,
                watch_tag=tag,
                target_digest="sha256:old",
                final_image=image,
                provenance_source="apply",
                provenance_confidence="verified",
            ),
        )
