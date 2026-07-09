#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = REPO_ROOT / "wud" / "upstreams.txt"
HEADER = """# /wud/upstreams.txt
# Format: linuxserver/docker-<image>: <Owner>/<Repo>
# Keep entries sorted by the linuxserver/docker-* key.
"""

ENTRY_RE = re.compile(
    r"^(linuxserver/docker-[A-Za-z0-9._-]+): "
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$"
)
PROJECT_URL_RE = re.compile(r"^project_url:\s*(.*?)\s*$")
GITHUB_PROJECT_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class MapEntry:
    key: str
    value: str
    comments: tuple[str, ...] = ()

    @property
    def is_override(self) -> bool:
        return bool(self.comments)


def read_map(path: Path) -> dict[str, MapEntry]:
    entries: dict[str, MapEntry] = {}
    pending_comments: list[str] = []
    seen_entry = False

    if not path.exists():
        return entries

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.rstrip()
        if not line:
            pending_comments.clear()
            continue
        if line.startswith("#"):
            if seen_entry:
                pending_comments.append(line)
            continue

        match = ENTRY_RE.match(line)
        if match is None:
            raise ValueError(f"{path}:{line_no}: invalid upstream map line")

        key, value = match.groups()
        entries[key] = MapEntry(key, value, tuple(pending_comments))
        pending_comments.clear()
        seen_entry = True

    return entries


def extract_project_url(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            continue
        match = PROJECT_URL_RE.match(line)
        if match is None:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return None


def normalize_github_project(value: str | None) -> str | None:
    if not value:
        return None
    match = GITHUB_PROJECT_RE.match(value)
    if match is None:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def read_source_repo(repo_dir: Path) -> str | None:
    for filename in ("readme-vars.yml", "jenkins-vars.yml"):
        path = repo_dir / filename
        if not path.exists():
            continue
        raw_url = extract_project_url(path.read_text(encoding="utf-8"))
        if raw_url is None:
            continue
        return normalize_github_project(raw_url)
    return None


def source_entries_from_dir(source_dir: Path) -> dict[str, str]:
    repo_dirs = (
        [source_dir]
        if source_dir.name.startswith("docker-")
        else sorted(
            path
            for path in source_dir.iterdir()
            if path.is_dir() and path.name.startswith("docker-")
        )
    )
    entries: dict[str, str] = {}
    for repo_dir in repo_dirs:
        upstream = read_source_repo(repo_dir)
        if upstream is not None:
            entries[f"linuxserver/{repo_dir.name}"] = upstream
    return entries


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "wudup-lsio-upstreams",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def github_json(url: str) -> object:
    request = urllib.request.Request(url, headers=github_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def github_file(repo: str, branch: str, filename: str) -> str | None:
    ref = urllib.parse.quote(branch, safe="")
    url = (
        f"https://api.github.com/repos/linuxserver/{repo}/contents/"
        f"{filename}?ref={ref}"
    )
    try:
        data = github_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    content = data.get("content")
    if not isinstance(content, str):
        return None
    return base64.b64decode(content).decode("utf-8")


def source_entries_from_github() -> dict[str, str]:
    repos: list[tuple[str, str]] = []
    page = 1
    while True:
        url = (
            "https://api.github.com/orgs/linuxserver/repos"
            f"?type=public&per_page=100&page={page}"
        )
        data = github_json(url)
        if not isinstance(data, list) or not data:
            break

        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name.startswith("docker-"):
                branch = item.get("default_branch")
                repos.append((name, branch if isinstance(branch, str) else "master"))

        if len(data) < 100:
            break
        page += 1

    entries: dict[str, str] = {}
    for repo, branch in sorted(repos):
        for filename in ("readme-vars.yml", "jenkins-vars.yml"):
            content = github_file(repo, branch, filename)
            if content is None:
                continue
            raw_url = extract_project_url(content)
            if raw_url is None:
                continue
            upstream = normalize_github_project(raw_url)
            if upstream is not None:
                entries[f"linuxserver/{repo}"] = upstream
            break
    return entries


def compare_entries(
    current: dict[str, MapEntry],
    source: dict[str, str],
) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str, str]],
    list[tuple[str, str]],
]:
    missing = [
        (key, source[key])
        for key in sorted(source)
        if key not in current
    ]
    changed = [
        (key, current[key].value, source[key])
        for key in sorted(source)
        if key in current
        and not current[key].is_override
        and current[key].value != source[key]
    ]
    removed = [
        (key, entry.value)
        for key, entry in sorted(current.items())
        if key not in source and not entry.is_override
    ]
    return missing, changed, removed


def build_output_entries(
    current: dict[str, MapEntry],
    source: dict[str, str],
) -> dict[str, MapEntry]:
    entries: dict[str, MapEntry] = {}
    for key, value in source.items():
        current_entry = current.get(key)
        if current_entry is not None and current_entry.is_override:
            entries[key] = current_entry
        else:
            entries[key] = MapEntry(key, value)

    for key, entry in current.items():
        if key not in entries and entry.is_override:
            entries[key] = entry

    return entries


def render_map(entries: dict[str, MapEntry]) -> str:
    lines = [*HEADER.rstrip("\n").splitlines(), ""]
    for key in sorted(entries):
        entry = entries[key]
        lines.extend(entry.comments)
        lines.append(f"{entry.key}: {entry.value}")
    return "\n".join(lines) + "\n"


def repair_command(map_path: Path) -> str:
    command = ["scripts/update-lsio-upstreams.py", "--write"]
    if map_path.resolve() != DEFAULT_MAP.resolve():
        command.extend(["--map", str(map_path)])
    return " ".join(shlex.quote(part) for part in command)


def print_drift(
    missing: list[tuple[str, str]],
    changed: list[tuple[str, str, str]],
    removed: list[tuple[str, str]],
    map_path: Path,
) -> None:
    if not (missing or changed or removed):
        print("ok - LSIO upstream map is current")
        return

    print("LSIO upstream map drift found:")
    for key, value in missing:
        print(f"missing: {key}: {value}")
    for key, current, expected in changed:
        print(f"changed: {key}: {current} -> {expected}")
    for key, value in removed:
        print(f"removed: {key}: {value}")
    print(f"Regenerate with: {repair_command(map_path)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or update the checked-in LSIO upstream map."
    )
    parser.add_argument("--write", action="store_true", help="rewrite the map")
    parser.add_argument("--map", default=DEFAULT_MAP, type=Path, help="upstream map path")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="local directory containing linuxserver docker-* source checkouts",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    current = read_map(args.map)
    if args.source_dir is None and not github_token():
        print(
            "error: GitHub mode requires GITHUB_TOKEN or GH_TOKEN; "
            "pass --source-dir to use local LSIO checkouts.",
            file=sys.stderr,
        )
        return 2
    source = (
        source_entries_from_dir(args.source_dir)
        if args.source_dir is not None
        else source_entries_from_github()
    )

    if args.write:
        args.map.write_text(
            render_map(build_output_entries(current, source)),
            encoding="utf-8",
        )
        print(f"wrote {args.map}")
        return 0

    missing, changed, removed = compare_entries(current, source)
    print_drift(missing, changed, removed, args.map)
    return 1 if missing or changed or removed else 0


if __name__ == "__main__":
    raise SystemExit(main())
