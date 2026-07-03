"""LinuxServer.io tag parsing and update classification."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


LSIOChangeType = Literal["upstream_update", "image_rebuild", "unknown"]
LSIOTagKind = Literal["build", "version", "branch", "pseudo_semver", "unknown"]

ARCH_PREFIXES = frozenset(
    {
        "amd64",
        "arm32v6",
        "arm32v7",
        "arm64v8",
        "ppc64le",
        "riscv64",
        "s390x",
    }
)
LSIO_BUILD_RE = re.compile(
    r"^(?P<body>.+)-(?P<build>ls[0-9]+(?:[._-][0-9A-Za-z]+)*)$",
    re.IGNORECASE,
)
VERSION_START_RE = re.compile(r"^[vV]?[0-9]+(?:\.[0-9]+){1,3}")


@dataclass(frozen=True)
class LSIOTagParts:
    raw: str = ""
    kind: LSIOTagKind = "unknown"
    arch: str = ""
    branch: str = ""
    upstream_version: str = ""
    build_suffix: str = ""


@dataclass(frozen=True)
class LSIOUpdateClassification:
    change_type: LSIOChangeType = "unknown"
    reason: str = "ambiguous-tags"
    current: LSIOTagParts = field(default_factory=LSIOTagParts)
    target: LSIOTagParts = field(default_factory=LSIOTagParts)


def parse_lsio_tag(tag: str) -> LSIOTagParts:
    raw = tag.strip()
    if not raw:
        return LSIOTagParts()

    arch, tokens = _split_arch(raw.split("-"))
    marker_index = _index(tokens, "version")
    if marker_index >= 0:
        upstream = "-".join(tokens[marker_index + 1 :])
        if upstream and VERSION_START_RE.match(upstream):
            return LSIOTagParts(
                raw=raw,
                kind="version",
                arch=arch,
                branch="-".join(tokens[:marker_index]),
                upstream_version=upstream,
            )
        return LSIOTagParts(raw=raw, kind="unknown", arch=arch)

    build_match = LSIO_BUILD_RE.match(raw)
    if build_match:
        body = build_match.group("body")
        build_suffix = build_match.group("build")
        arch, body_tokens = _split_arch(body.split("-"))
        version_index = _first_version_index(body_tokens)
        if version_index >= 0:
            return LSIOTagParts(
                raw=raw,
                kind="build",
                arch=arch,
                branch="-".join(body_tokens[:version_index]),
                upstream_version="-".join(body_tokens[version_index:]),
                build_suffix=build_suffix,
            )
        return LSIOTagParts(
            raw=raw,
            kind="unknown",
            arch=arch,
            build_suffix=build_suffix,
        )

    if _first_version_index(tokens) == 0:
        return LSIOTagParts(
            raw=raw,
            kind="pseudo_semver",
            arch=arch,
            upstream_version=raw,
        )

    return LSIOTagParts(raw=raw, kind="branch", arch=arch, branch="-".join(tokens))


def classify_lsio_update(
    *,
    image_repo: str,
    current_tag: str,
    target_tag: str = "",
    lsio_tag: str = "",
    upstream_version: str = "",
) -> LSIOUpdateClassification:
    current = parse_lsio_tag(current_tag)
    target = parse_lsio_tag(target_tag or lsio_tag)
    if not _lsio_repo(image_repo):
        return LSIOUpdateClassification(
            reason="non-lsio-image",
            current=current,
            target=target,
        )

    current_upstream = _trusted_upstream(current)
    target_upstream = _trusted_upstream(target) or normalize_lsio_version(
        upstream_version
    )
    if not current_upstream or not target_upstream:
        return LSIOUpdateClassification(current=current, target=target)

    if current.arch != target.arch or current.branch != target.branch:
        return LSIOUpdateClassification(
            reason="branch-or-arch-mismatch",
            current=current,
            target=target,
        )

    if current_upstream != target_upstream:
        return LSIOUpdateClassification(
            change_type="upstream_update",
            reason="upstream-version-changed",
            current=current,
            target=target,
        )

    if current.kind in {"build", "version", "pseudo_semver"} and (
        target.kind in {"build", "version", "pseudo_semver"} or upstream_version
    ):
        return LSIOUpdateClassification(
            change_type="image_rebuild",
            reason="same-upstream-image-layer-changed",
            current=current,
            target=target,
        )

    return LSIOUpdateClassification(current=current, target=target)


def classification_from_mapping(value: object) -> LSIOUpdateClassification:
    if not isinstance(value, Mapping):
        return LSIOUpdateClassification()
    return LSIOUpdateClassification(
        change_type=_change_type(str(value.get("change_type") or "")),
        reason=str(value.get("reason") or "ambiguous-tags"),
        current=_tag_parts_from_mapping(value.get("current")),
        target=_tag_parts_from_mapping(value.get("target")),
    )


def _tag_parts_from_mapping(value: object) -> LSIOTagParts:
    if not isinstance(value, Mapping):
        return LSIOTagParts()
    return LSIOTagParts(
        raw=str(value.get("raw") or ""),
        kind=_tag_kind(str(value.get("kind") or "")),
        arch=str(value.get("arch") or ""),
        branch=str(value.get("branch") or ""),
        upstream_version=str(value.get("upstream_version") or ""),
        build_suffix=str(value.get("build_suffix") or ""),
    )


def _split_arch(tokens: list[str]) -> tuple[str, list[str]]:
    if tokens and tokens[0].lower() in ARCH_PREFIXES:
        return tokens[0], tokens[1:]
    return "", tokens


def _index(tokens: list[str], value: str) -> int:
    try:
        return [token.lower() for token in tokens].index(value)
    except ValueError:
        return -1


def _first_version_index(tokens: list[str]) -> int:
    for index, token in enumerate(tokens):
        if VERSION_START_RE.match(token):
            return index
    return -1


def _trusted_upstream(parts: LSIOTagParts) -> str:
    if parts.kind not in {"build", "version", "pseudo_semver"}:
        return ""
    return normalize_lsio_version(parts.upstream_version)


def normalize_lsio_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("v") and len(normalized) > 1 and normalized[1].isdigit():
        normalized = normalized[1:]
    return normalized


def _lsio_repo(value: str) -> bool:
    parts = value.lower().split("/")
    return any(part in {"linuxserver", "linuxserver.io"} for part in parts[:-1])


def _change_type(value: str) -> LSIOChangeType:
    if value in {"upstream_update", "image_rebuild", "unknown"}:
        return value  # type: ignore[return-value]
    return "unknown"


def _tag_kind(value: str) -> LSIOTagKind:
    if value in {"build", "version", "branch", "pseudo_semver", "unknown"}:
        return value  # type: ignore[return-value]
    return "unknown"
