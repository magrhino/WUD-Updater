"""Image reference helpers ported from ``bin/docker-update-from-wud``."""

from __future__ import annotations

import re


_SHELL_SPACE = " \t\n\r\v\f"
_TAG_VALUE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def trim(value: str) -> str:
    """Trim shell ``[[:space:]]`` characters from both ends of ``value``."""

    return value.strip(_SHELL_SPACE)


def strip_digest(image: str) -> str:
    """Remove a pinned sha256 digest suffix from an image reference."""

    return image.split("@sha256:", 1)[0]


def normalize_digest(digest: str) -> str:
    """Normalize a digest value to the ``sha256:<value>`` form."""

    if digest == "":
        return ""
    digest = digest.split("@", 1)[1] if "@" in digest else digest
    if digest.startswith("sha256:"):
        return digest
    return f"sha256:{digest}"


def drop_registry(image: str) -> str:
    """Drop a Docker registry prefix when the first path segment is a registry."""

    image = strip_digest(image)
    left, sep, rest = image.partition("/")
    if sep == "":
        return image
    if "." in left or ":" in left or left == "localhost":
        return rest
    return image


def image_has_tag(image: str) -> bool:
    """Return whether the image reference has a tag in its final path segment."""

    image = strip_digest(image)
    last = image.rsplit("/", 1)[-1]
    return ":" in last


def image_tag(image: str) -> str:
    """Return the tag from an image reference, or an empty string."""

    image = strip_digest(image)
    last = image.rsplit("/", 1)[-1]
    if ":" not in last:
        return ""
    return last.rsplit(":", 1)[1]


def image_key(image: str) -> str:
    """Return the matching key for an image, ignoring registry and digest."""

    return drop_registry(image)


def repo_key(image: str) -> str:
    """Return the repository matching key for an image, ignoring tag."""

    key = image_key(image)
    last = key.rsplit("/", 1)[-1]
    if ":" in last:
        return key.rsplit(":", 1)[0]
    return key


def image_repo_ref(image: str) -> str:
    """Return the image reference without tag or digest, preserving registry."""

    image = strip_digest(image)
    prefix, sep, last = image.rpartition("/")
    if ":" in last:
        last = last.rsplit(":", 1)[0]
    if sep:
        return f"{prefix}/{last}"
    return last


def image_with_tag(image: str, tag: str) -> str:
    """Return ``image`` with ``tag`` applied to its repository reference."""

    return f"{image_repo_ref(image)}:{tag}"


def tag_value_valid(tag: str) -> bool:
    """Return whether ``tag`` is valid for the updater's tag rewrite option."""

    return bool(_TAG_VALUE_RE.fullmatch(tag))


def image_matches_resolved_target(
    image: str,
    resolved: str,
    allow_repo: bool,
) -> bool:
    """Return whether a compose image matches a resolved WUD target."""

    resolved_key = image_key(resolved)
    resolved_repo = repo_key(resolved)
    image_match_key = image_key(image)
    image_repo_match_key = repo_key(image)

    if image_has_tag(resolved) and image_match_key == resolved_key:
        return True
    if allow_repo and image_repo_match_key == resolved_repo:
        return True
    return False
