"""Startup banner and opportunistic release-status check."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections.abc import Mapping
from importlib.resources import files
from typing import TextIO

from . import __version__
from .naming import DISPLAY_NAME, REPOSITORY, env_value
from .terminal import TerminalRenderer

LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
DEFAULT_RELEASE_TIMEOUT = 1.0

_SEMVER_TAG_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+].*)?$")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def print_startup_banner(
    *,
    environ: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    no_color: bool = False,
    timeout: float = DEFAULT_RELEASE_TIMEOUT,
) -> bool:
    env = dict(os.environ if environ is None else environ)
    target = sys.stdout if stream is None else stream
    if not _banner_enabled(env, target):
        return False

    local_tag = current_tag()
    latest_tag = None
    if _release_check_enabled(env):
        latest_tag = fetch_latest_release_tag(timeout=timeout)

    renderer = TerminalRenderer(no_color=no_color, environ=env, stream=target)
    renderer.startup_banner(
        art=load_ascii_art(),
        local_tag=local_tag,
        release_status=release_status(local_tag, latest_tag),
    )
    return True


def current_tag(version: str = __version__) -> str:
    return _normalize_tag(version)


def load_ascii_art() -> str:
    try:
        return files("wudup").joinpath("ascii-text-art.txt").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError, ValueError):
        pass
    return f"{DISPLAY_NAME}\n"


def fetch_latest_release_tag(*, timeout: float = DEFAULT_RELEASE_TIMEOUT) -> str | None:
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"wudup/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(65536)
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        return None

    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str) or tag.strip() == "":
        return None
    return _normalize_tag(tag.strip())


def release_status(
    local_tag: str,
    latest_tag: str | None,
) -> tuple[str, str] | None:
    if latest_tag is None:
        return None

    comparison = _compare_semver_tags(latest_tag, local_tag)
    if comparison is None:
        if latest_tag == local_tag:
            return (f"Up to date: {local_tag}", "success")
        return None
    if comparison > 0:
        return (f"Update available: {local_tag} -> {latest_tag}", "warning")
    return (f"Up to date: {local_tag}", "success")


def release_update_available(local_tag: str, latest_tag: str | None) -> bool:
    if latest_tag is None:
        return False
    comparison = _compare_semver_tags(latest_tag, local_tag)
    if comparison is None:
        return False
    return comparison > 0


def release_check_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = dict(os.environ if environ is None else environ)
    return _release_check_enabled(env)


def main() -> int:
    print_startup_banner()
    return 0


def _banner_enabled(env: dict[str, str], stream: TextIO) -> bool:
    value = _normalized_env_value(env_value(env, "WUDUP_BANNER", "WUD_UPDATER_BANNER"))
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return _stream_is_tty(stream)


def _release_check_enabled(env: dict[str, str]) -> bool:
    value = _normalized_env_value(
        env_value(env, "WUDUP_RELEASE_CHECK", "WUD_UPDATER_RELEASE_CHECK")
    )
    return value not in _FALSE_VALUES


def _normalized_env_value(value: str | None) -> str:
    if value is None or value.strip() == "":
        return "auto"
    return value.strip().lower()


def _stream_is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _normalize_tag(tag: str) -> str:
    normalized = tag.strip()
    if normalized.startswith("v"):
        return normalized
    return f"v{normalized}"


def _compare_semver_tags(left: str, right: str) -> int | None:
    left_key = _semver_key(left)
    right_key = _semver_key(right)
    if left_key is None or right_key is None:
        return None
    if left_key > right_key:
        return 1
    if left_key < right_key:
        return -1
    return 0


def _semver_key(tag: str) -> tuple[int, int, int] | None:
    match = _SEMVER_TAG_RE.fullmatch(tag)
    if match is None:
        return None
    return (
        int(match.group(1), 10),
        int(match.group(2), 10),
        int(match.group(3), 10),
    )


if __name__ == "__main__":
    raise SystemExit(main())
