#!/usr/bin/env python3
"""Live Docker/registry digest verification probe.

This script is intentionally not part of default CI. It pulls small public images
and compares Docker's local image metadata with registry manifest data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
IMAGE_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
DEFAULT_IMAGES = (
    "alpine:3.20",
    "quay.io/prometheus/busybox:latest",
)


@dataclass(frozen=True)
class ImageRef:
    pull_ref: str
    registry: str
    repo: str
    reference: str


@dataclass(frozen=True)
class ManifestDocument:
    digest: str
    media_type: str
    payload: dict[str, Any]

    def is_index(self) -> bool:
        return self.media_type in INDEX_MEDIA_TYPES or isinstance(
            self.payload.get("manifests"),
            list,
        )

    def is_image_manifest(self) -> bool:
        return self.media_type in IMAGE_MEDIA_TYPES or isinstance(
            self.payload.get("config"),
            dict,
        )

    def child_digests(self) -> tuple[str, ...]:
        manifests = self.payload.get("manifests")
        if not isinstance(manifests, list):
            return ()
        digests: list[str] = []
        for item in manifests:
            if isinstance(item, dict) and isinstance(item.get("digest"), str):
                digests.append(item["digest"])
        return tuple(digests)

    def config_digest(self) -> str:
        config = self.payload.get("config")
        if not isinstance(config, dict):
            return ""
        digest = config.get("digest")
        return digest if isinstance(digest, str) else ""


@dataclass(frozen=True)
class ProbeResult:
    image: str
    tag_digest: str
    repo_digests: tuple[str, ...]
    local_image_id: str
    matched_child_digest: str
    matched_config_digest: str

    @property
    def repo_digest_values(self) -> tuple[str, ...]:
        return tuple(item.rsplit("@", 1)[-1] for item in self.repo_digests)

    @property
    def tag_digest_in_repo_digests(self) -> bool:
        return self.tag_digest in self.repo_digest_values

    @property
    def child_digest_in_repo_digests(self) -> bool:
        return bool(
            self.matched_child_digest
            and self.matched_child_digest in self.repo_digest_values
        )

    @property
    def config_matches_local_image(self) -> bool:
        return bool(
            self.matched_config_digest
            and self.local_image_id
            and self.matched_config_digest == self.local_image_id
        )


class ProbeError(RuntimeError):
    """Raised when a live digest probe cannot be completed."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        default=list(DEFAULT_IMAGES),
        help="Tagged images to pull and verify.",
    )
    parser.add_argument(
        "--skip-pull",
        action="store_true",
        help="Inspect existing local images instead of running docker pull first.",
    )
    args = parser.parse_args()

    failures = 0
    for image in args.images:
        try:
            result = probe_image(image, skip_pull=args.skip_pull)
        except ProbeError as exc:
            failures += 1
            print(f"[FAIL] {image}: {exc}", file=sys.stderr)
            continue
        print_result(result)
        if not result.tag_digest_in_repo_digests:
            failures += 1
            print(
                f"[FAIL] {image}: tag digest was not present in Docker RepoDigests",
                file=sys.stderr,
            )
        if not result.config_matches_local_image:
            failures += 1
            print(
                f"[FAIL] {image}: no registry manifest config matched local image id",
                file=sys.stderr,
            )
    return 1 if failures else 0


def probe_image(image: str, *, skip_pull: bool = False) -> ProbeResult:
    ref = parse_image_ref(image)
    if not skip_pull:
        docker("pull", ref.pull_ref)
    tag_document = fetch_manifest(ref)
    local_image_id = docker_output(
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        ref.pull_ref,
    ).strip()
    repo_digests = tuple(
        line
        for line in docker_output(
            "image",
            "inspect",
            "--format",
            "{{range .RepoDigests}}{{println .}}{{end}}",
            ref.pull_ref,
        ).splitlines()
        if line.strip()
    )
    child_digest, config_digest = find_matching_child_config(
        ref,
        tag_document,
        local_image_id,
    )
    return ProbeResult(
        image=ref.pull_ref,
        tag_digest=tag_document.digest,
        repo_digests=repo_digests,
        local_image_id=local_image_id,
        matched_child_digest=child_digest,
        matched_config_digest=config_digest,
    )


def find_matching_child_config(
    ref: ImageRef,
    tag_document: ManifestDocument,
    local_image_id: str,
) -> tuple[str, str]:
    if tag_document.is_image_manifest():
        config = tag_document.config_digest()
        return (tag_document.digest, config) if config == local_image_id else ("", config)

    if not tag_document.is_index():
        return "", ""

    last_config = ""
    for child_digest in tag_document.child_digests():
        child = fetch_manifest(
            ImageRef(
                pull_ref=ref.pull_ref,
                registry=ref.registry,
                repo=ref.repo,
                reference=child_digest,
            )
        )
        config = child.config_digest()
        if config:
            last_config = config
        if config == local_image_id:
            return child_digest, config
    return "", last_config


def fetch_manifest(ref: ImageRef) -> ManifestDocument:
    url = f"https://{ref.registry}/v2/{ref.repo}/manifests/{ref.reference}"
    request = urllib.request.Request(url)
    request.add_header("Accept", MANIFEST_ACCEPT)
    try:
        return read_manifest_response(urllib.request.urlopen(request, timeout=20), url)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise ProbeError(f"registry request failed for {url}: {exc}") from exc
        token = fetch_bearer_token(exc.headers.get("WWW-Authenticate", ""))
        retry = urllib.request.Request(url)
        retry.add_header("Accept", MANIFEST_ACCEPT)
        retry.add_header("Authorization", f"Bearer {token}")
        try:
            return read_manifest_response(urllib.request.urlopen(retry, timeout=20), url)
        except (OSError, urllib.error.URLError) as retry_exc:
            raise ProbeError(f"authenticated registry request failed for {url}: {retry_exc}") from retry_exc
    except (OSError, urllib.error.URLError) as exc:
        raise ProbeError(f"registry request failed for {url}: {exc}") from exc


def read_manifest_response(response: Any, url: str) -> ManifestDocument:
    with response:
        body = response.read()
        digest = header_value(response.headers, "Docker-Content-Digest")
        media_type = content_type(header_value(response.headers, "Content-Type"))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"registry response was not JSON for {url}") from exc
    if not isinstance(payload, dict):
        raise ProbeError(f"registry response was not a JSON object for {url}")
    if not digest:
        raise ProbeError(f"registry response did not include Docker-Content-Digest for {url}")
    return ManifestDocument(digest=digest, media_type=media_type, payload=payload)


def fetch_bearer_token(challenge: str) -> str:
    scheme, _, rest = challenge.partition(" ")
    if scheme.lower() != "bearer" or not rest:
        raise ProbeError(f"unsupported registry auth challenge: {challenge}")
    values = urllib.request.parse_keqv_list(urllib.request.parse_http_list(rest))
    realm = values.get("realm")
    if not realm:
        raise ProbeError(f"registry auth challenge did not include a realm: {challenge}")
    query = {
        key: value
        for key in ("service", "scope")
        if isinstance((value := values.get(key)), str) and value
    }
    separator = "&" if urllib.parse.urlparse(realm).query else "?"
    url = realm + (separator + urllib.parse.urlencode(query) if query else "")
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"registry token request failed for {url}: {exc}") from exc
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ProbeError(f"registry token response did not include a token for {url}")
    return token


def parse_image_ref(image: str) -> ImageRef:
    image = image.strip()
    if not image or "@" in image:
        raise ProbeError("expected a tagged image reference, not an empty or digest-pinned ref")
    first, sep, remainder = image.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        registry = first
        repo_tag = remainder
    else:
        registry = "registry-1.docker.io"
        repo_tag = image
        if "/" not in repo_tag:
            repo_tag = f"library/{repo_tag}"

    repo, tag_sep, tag = repo_tag.rpartition(":")
    if not tag_sep or "/" in tag:
        repo = repo_tag
        tag = "latest"
    if not repo or not tag:
        raise ProbeError(f"could not parse image reference: {image}")
    return ImageRef(pull_ref=image, registry=registry, repo=repo, reference=tag)


def docker(*args: str) -> None:
    try:
        subprocess.run(
            ("docker", *args),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ProbeError("docker executable was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ProbeError(f"docker {' '.join(args)} failed: {detail}") from exc


def docker_output(*args: str) -> str:
    try:
        return subprocess.run(
            ("docker", *args),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except FileNotFoundError as exc:
        raise ProbeError("docker executable was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ProbeError(f"docker {' '.join(args)} failed: {detail}") from exc


def print_result(result: ProbeResult) -> None:
    print(f"[OK] {result.image}")
    print(f"  registry tag digest: {result.tag_digest}")
    print(f"  local image id     : {result.local_image_id}")
    print(f"  matched child      : {result.matched_child_digest or 'none'}")
    print(f"  matched config     : {result.matched_config_digest or 'none'}")
    print("  repo digests:")
    for digest in result.repo_digests:
        print(f"    {digest}")
    print(
        "  current repo-digest check accepts tag digest      : "
        f"{yes_no(result.tag_digest_in_repo_digests)}"
    )
    print(
        "  current repo-digest check accepts platform child  : "
        f"{yes_no(result.child_digest_in_repo_digests)}"
    )
    print(
        "  registry config proves local platform image       : "
        f"{yes_no(result.config_matches_local_image)}"
    )


def header_value(headers: Any, name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def content_type(value: str) -> str:
    return value.split(";", 1)[0].strip()


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
