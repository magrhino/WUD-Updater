"""Self-update detection helpers for the ``updates`` wrappers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .banner import (
    current_tag,
    fetch_latest_release_tag,
    release_check_enabled,
    release_update_available,
)
from .container_identity import container_identity_candidates
from .images import repo_key, tag_value_valid


DEFAULT_SELF_UPDATE_IMAGE = "ghcr.io/magrhino/wud-updater:latest"
DEFAULT_SELF_UPDATE_REPOSITORY = "ghcr.io/magrhino/wud-updater"
SELF_UPDATE_REPOS = frozenset({"magrhino/wud-updater", "wud-updater"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_SEMVER_IMAGE_TAG_RE = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+].*)?$")


@dataclass(frozen=True)
class ReleaseSelfUpdate:
    local_tag: str
    latest_tag: str
    target: str


def self_update_enabled(
    environ: Mapping[str, str] | None = None,
    *,
    cli_value: bool | None = None,
) -> bool:
    if cli_value is not None:
        return cli_value
    env = os.environ if environ is None else environ
    return _normalized_env_value(env.get("WUD_UPDATER_SELF_UPDATE")) not in FALSE_VALUES


def is_self_update_target(value: str) -> bool:
    return repo_key(value).casefold() in SELF_UPDATE_REPOS


def self_update_display_numbers(entries: Sequence[object]) -> list[int]:
    result: list[int] = []
    for display_no, entry in enumerate(entries, start=1):
        first = getattr(entry, "first", "")
        if isinstance(first, str) and is_self_update_target(first):
            result.append(display_no)
    return result


def github_release_self_update(
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = 1.0,
) -> ReleaseSelfUpdate | None:
    env = os.environ if environ is None else environ
    if not release_check_enabled(env):
        return None

    local_tag = current_tag()
    latest_tag = fetch_latest_release_tag(timeout=timeout)
    if not release_update_available(local_tag, latest_tag):
        return None
    latest_tag = latest_tag or ""

    return ReleaseSelfUpdate(
        local_tag=local_tag,
        latest_tag=latest_tag,
        target=release_self_update_target(
            current_container_image(env),
            local_tag,
            latest_tag,
        ),
    )


def release_self_update_target(
    current_image: str,
    local_tag: str,
    latest_tag: str,
) -> str:
    if current_image == "":
        if _is_release_image_tag(local_tag) and tag_value_valid(local_tag):
            return f"{DEFAULT_SELF_UPDATE_REPOSITORY}:{local_tag} tag={latest_tag}"
        return DEFAULT_SELF_UPDATE_IMAGE

    current_tag = _image_reference_tag(current_image)
    if _is_release_image_tag(current_tag) and _normalize_tag(current_tag) != latest_tag:
        return f"{current_image} tag={latest_tag}"
    return current_image


def current_container_image(
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = 5.0,
) -> str:
    env = dict(os.environ if environ is None else environ)
    candidates = container_identity_candidates(env)
    if not candidates:
        return ""

    for candidate in candidates:
        try:
            result = subprocess.run(
                ["docker", "container", "inspect", candidate],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            continue

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, list) or not payload:
            return ""
        container = payload[0]
        if not isinstance(container, dict):
            return ""
        return _inspected_container_image(container)
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["github-target"]:
        print("Usage: python -m wud_updater.self_update github-target", file=sys.stderr)
        return 2

    update = github_release_self_update()
    if update is not None:
        print(update.target)
    return 0


def _inspected_container_image(container: Mapping[str, object]) -> str:
    config = container.get("Config")
    if isinstance(config, dict):
        image = config.get("Image")
        if isinstance(image, str) and image:
            return image
    image = container.get("Image")
    if isinstance(image, str) and image:
        return image
    return ""


def _normalized_env_value(value: str | None) -> str:
    if value is None or value.strip() == "":
        return "auto"
    return value.strip().lower()


def _image_reference_tag(image: str) -> str:
    without_digest = image.split("@sha256:", 1)[0]
    last = without_digest.rsplit("/", 1)[-1]
    if ":" not in last:
        return ""
    return last.rsplit(":", 1)[1]


def _is_release_image_tag(tag: str) -> bool:
    return bool(_SEMVER_IMAGE_TAG_RE.fullmatch(tag))


def _normalize_tag(tag: str) -> str:
    return tag if tag.startswith("v") else f"v{tag}"


if __name__ == "__main__":
    raise SystemExit(main())
