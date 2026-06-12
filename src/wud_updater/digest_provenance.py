"""Digest/tag provenance helpers for digest-pinned image state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .images import (
    image_has_tag,
    image_tag,
    image_with_digest,
    image_with_tag,
    normalize_digest,
)
from .updater_models import DigestPinUpdate


DIGEST_PROVENANCE_SQL_COLUMNS = (
    "digest_source_image",
    "digest_resolved_tag",
    "digest_watch_tag",
    "digest_target_digest",
    "digest_final_image",
    "digest_provenance_source",
    "digest_provenance_confidence",
)


@dataclass(frozen=True)
class DigestTagProvenance:
    source_image: str = ""
    resolved_tag: str = ""
    watch_tag: str = ""
    target_digest: str = ""
    final_image: str = ""
    provenance_source: str = ""
    provenance_confidence: str = ""

    def is_empty(self) -> bool:
        return not any(asdict(self).values())

    def sql_values(self) -> dict[str, str]:
        return {
            "digest_source_image": self.source_image,
            "digest_resolved_tag": self.resolved_tag,
            "digest_watch_tag": self.watch_tag,
            "digest_target_digest": self.target_digest,
            "digest_final_image": self.final_image,
            "digest_provenance_source": self.provenance_source,
            "digest_provenance_confidence": self.provenance_confidence,
        }


def empty_digest_provenance_sql_values() -> dict[str, str]:
    return {column: "" for column in DIGEST_PROVENANCE_SQL_COLUMNS}


def digest_provenance_from_update(
    update: DigestPinUpdate,
    *,
    provenance_source: str,
    provenance_confidence: str,
) -> DigestTagProvenance:
    return DigestTagProvenance(
        source_image=update.old_image,
        resolved_tag=update.resolved_tag,
        watch_tag=update.watch_tag,
        target_digest=update.planned_digest,
        final_image=update.final_image,
        provenance_source=provenance_source,
        provenance_confidence=provenance_confidence,
    )


def digest_provenance_from_digest_target(
    source_image: str,
    target_digest: str,
    *,
    provenance_source: str,
    provenance_confidence: str,
) -> DigestTagProvenance | None:
    tag = image_tag(source_image)
    digest = normalize_digest(target_digest)
    if not image_has_tag(source_image) or not tag or not digest:
        return None
    source_tag_image = image_with_tag(source_image, tag)
    return DigestTagProvenance(
        source_image=source_tag_image,
        resolved_tag=tag,
        watch_tag=tag,
        target_digest=digest,
        final_image=image_with_digest(source_tag_image, digest),
        provenance_source=provenance_source,
        provenance_confidence=provenance_confidence,
    )


def digest_provenance_from_row(row: Mapping[str, Any]) -> DigestTagProvenance | None:
    values = {
        "source_image": str(row["digest_source_image"] or ""),
        "resolved_tag": str(row["digest_resolved_tag"] or ""),
        "watch_tag": str(row["digest_watch_tag"] or ""),
        "target_digest": str(row["digest_target_digest"] or ""),
        "final_image": str(row["digest_final_image"] or ""),
        "provenance_source": str(row["digest_provenance_source"] or ""),
        "provenance_confidence": str(row["digest_provenance_confidence"] or ""),
    }
    provenance = DigestTagProvenance(**values)
    return None if provenance.is_empty() else provenance


def digest_provenance_or_empty(
    provenance: DigestTagProvenance | None,
) -> dict[str, str]:
    if provenance is None:
        return empty_digest_provenance_sql_values()
    return provenance.sql_values()


def digest_from_image(image: str) -> str:
    if "@sha256:" not in image:
        return ""
    return normalize_digest(image.split("@", 1)[1])
