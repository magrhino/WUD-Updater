"""Digest verification helpers for WUD-reported image updates."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .command import CommandError
from .docker_cli import DockerCli
from .images import strip_digest


GHCR_REGISTRY = "ghcr.io"
DEFAULT_GHCR_TIMEOUT = 5.0
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
INDEX_MEDIA_TYPES = frozenset(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)
IMAGE_MANIFEST_MEDIA_TYPES = frozenset(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class ManifestLookupError(RuntimeError):
    """Raised when a registry manifest cannot be resolved or parsed."""


class ManifestResolver(Protocol):
    def fetch(self, repo: str, reference: str) -> "ManifestDocument":
        """Return a manifest or index document for ``repo`` and ``reference``."""


@dataclass(frozen=True)
class GhcrImageRef:
    repo: str
    tag: str


@dataclass(frozen=True)
class ManifestDocument:
    source: str
    digest: str
    media_type: str
    payload: Mapping[str, Any]

    def is_index(self) -> bool:
        return self.media_type in INDEX_MEDIA_TYPES or isinstance(
            self.payload.get("manifests"), list
        )

    def is_image_manifest(self) -> bool:
        return self.media_type in IMAGE_MANIFEST_MEDIA_TYPES or isinstance(
            self.payload.get("config"), Mapping
        )

    def child_digest(self, digest: str) -> str:
        for manifest in self._manifest_items():
            if manifest.get("digest") == digest:
                return digest
        return ""

    def child_digests(self) -> tuple[str, ...]:
        return tuple(
            digest
            for manifest in self._manifest_items()
            if isinstance((digest := manifest.get("digest")), str) and digest
        )

    def config_digest(self) -> str:
        config = self.payload.get("config")
        if not isinstance(config, Mapping):
            return ""
        digest = config.get("digest")
        return digest if isinstance(digest, str) else ""

    def _manifest_items(self) -> tuple[Mapping[str, Any], ...]:
        manifests = self.payload.get("manifests")
        if not isinstance(manifests, list):
            return ()
        return tuple(item for item in manifests if isinstance(item, Mapping))


@dataclass(frozen=True)
class DigestCheckResult:
    ok: bool
    reason: str
    seen_repo_digests: tuple[str, ...] = ()
    tag_digest: str = ""
    matched_child_digest: str = ""
    expected_config_digest: str = ""
    local_image_id: str = ""
    source: str = ""
    error: str = ""


class GhcrHttpManifestResolver:
    """Resolve public GHCR manifests through the registry HTTP API."""

    def __init__(self, *, timeout: float = DEFAULT_GHCR_TIMEOUT) -> None:
        self.timeout = timeout
        self._tokens: dict[str, str] = {}

    def fetch(self, repo: str, reference: str) -> ManifestDocument:
        token = self._token(repo)
        url = f"https://{GHCR_REGISTRY}/v2/{repo}/manifests/{reference}"
        headers, payload = self._request_json(url, token=token)
        return ManifestDocument(
            source="ghcr-http",
            digest=_header_value(headers, "Docker-Content-Digest"),
            media_type=_content_type(_header_value(headers, "Content-Type")),
            payload=payload,
        )

    def _token(self, repo: str) -> str:
        cached = self._tokens.get(repo)
        if cached:
            return cached
        query = urllib.parse.urlencode(
            {"service": GHCR_REGISTRY, "scope": f"repository:{repo}:pull"}
        )
        _headers, payload = self._request_json(
            f"https://{GHCR_REGISTRY}/token?{query}",
            token="",
            accept="application/json",
        )
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ManifestLookupError(f"GHCR token response for {repo} did not include a token")
        self._tokens[repo] = token
        return token

    def _request_json(
        self,
        url: str,
        *,
        token: str,
        accept: str = MANIFEST_ACCEPT,
    ) -> tuple[Mapping[str, str], Mapping[str, Any]]:
        request = urllib.request.Request(url)
        request.add_header("Accept", accept)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                headers = {key: value for key, value in response.headers.items()}
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ManifestLookupError(f"GHCR request failed for {url}: {exc}") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestLookupError(f"GHCR response was not valid JSON for {url}") from exc
        if not isinstance(payload, Mapping):
            raise ManifestLookupError(f"GHCR response was not a JSON object for {url}")
        return headers, payload


class DockerManifestResolver:
    """Resolve manifests through ``docker manifest inspect``."""

    def __init__(self, docker: DockerCli) -> None:
        self.docker = docker

    def fetch(self, repo: str, reference: str) -> ManifestDocument:
        image = (
            f"{GHCR_REGISTRY}/{repo}@{reference}"
            if reference.startswith("sha256:")
            else f"{GHCR_REGISTRY}/{repo}:{reference}"
        )
        try:
            result = self.docker.manifest_inspect(image)
        except CommandError as exc:
            raise ManifestLookupError(f"docker manifest inspect failed for {image}") from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ManifestLookupError(f"docker manifest inspect returned invalid JSON for {image}") from exc
        if not isinstance(payload, Mapping):
            raise ManifestLookupError(f"docker manifest inspect returned non-object JSON for {image}")
        return ManifestDocument(
            source="docker-manifest",
            digest="",
            media_type=str(payload.get("mediaType") or ""),
            payload=payload,
        )


class DigestVerifier:
    """Verify that a pulled local image satisfies a WUD-reported digest."""

    def __init__(
        self,
        docker: DockerCli,
        *,
        primary_resolver: ManifestResolver | None = None,
        fallback_resolver: ManifestResolver | None = None,
    ) -> None:
        self.docker = docker
        self.primary_resolver = primary_resolver or GhcrHttpManifestResolver()
        self.fallback_resolver = fallback_resolver or DockerManifestResolver(docker)

    def verify(self, image: str, expected: str) -> DigestCheckResult:
        repo_digests = tuple(self.docker.image_repo_digests(image))
        local_image_id = self.docker.image_id(image)
        if any(digest.rsplit("@", 1)[-1] == expected for digest in repo_digests):
            return DigestCheckResult(
                ok=True,
                reason="repo-digest-match",
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
            )

        ghcr = parse_ghcr_image(image)
        if ghcr is None:
            return DigestCheckResult(
                ok=False,
                reason="repo-digest-mismatch",
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
            )
        if not local_image_id:
            return DigestCheckResult(
                ok=False,
                reason="missing-local-image-id",
                seen_repo_digests=repo_digests,
            )

        try:
            tag_document = self._fetch(ghcr.repo, ghcr.tag)
        except ManifestLookupError as exc:
            return DigestCheckResult(
                ok=False,
                reason="manifest-unavailable",
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
                error=str(exc),
            )

        if tag_document.digest == expected:
            return self._verify_tag_document(
                ghcr.repo,
                tag_document,
                expected,
                repo_digests,
                local_image_id,
            )

        if tag_document.is_index() and tag_document.child_digest(expected):
            return self._verify_expected_manifest(
                ghcr.repo,
                expected,
                tag_document,
                repo_digests,
                local_image_id,
            )

        if not tag_document.digest:
            expected_document = self._try_fetch(ghcr.repo, expected)
            if expected_document is not None and _same_manifest(
                tag_document.payload,
                expected_document.payload,
            ):
                return self._verify_tag_document(
                    ghcr.repo,
                    tag_document,
                    expected,
                    repo_digests,
                    local_image_id,
                )

        return DigestCheckResult(
            ok=False,
            reason="stale-digest",
            seen_repo_digests=repo_digests,
            tag_digest=tag_document.digest,
            local_image_id=local_image_id,
            source=tag_document.source,
        )

    def _verify_expected_manifest(
        self,
        repo: str,
        expected: str,
        tag_document: ManifestDocument,
        repo_digests: tuple[str, ...],
        local_image_id: str,
    ) -> DigestCheckResult:
        try:
            expected_document = self._fetch(repo, expected)
        except ManifestLookupError as exc:
            return DigestCheckResult(
                ok=False,
                reason="manifest-unavailable",
                seen_repo_digests=repo_digests,
                tag_digest=tag_document.digest,
                matched_child_digest=expected,
                local_image_id=local_image_id,
                source=tag_document.source,
                error=str(exc),
            )
        expected_config = expected_document.config_digest()
        if expected_config and expected_config == local_image_id:
            return DigestCheckResult(
                ok=True,
                reason="ghcr-platform-manifest-match",
                seen_repo_digests=repo_digests,
                tag_digest=tag_document.digest,
                matched_child_digest=expected,
                expected_config_digest=expected_config,
                local_image_id=local_image_id,
                source=expected_document.source,
            )
        return DigestCheckResult(
            ok=False,
            reason="platform-mismatch" if expected_config else "manifest-config-missing",
            seen_repo_digests=repo_digests,
            tag_digest=tag_document.digest,
            matched_child_digest=expected,
            expected_config_digest=expected_config,
            local_image_id=local_image_id,
            source=expected_document.source,
        )

    def _verify_tag_document(
        self,
        repo: str,
        tag_document: ManifestDocument,
        expected: str,
        repo_digests: tuple[str, ...],
        local_image_id: str,
    ) -> DigestCheckResult:
        if tag_document.is_image_manifest():
            config_digest = tag_document.config_digest()
            if config_digest and config_digest == local_image_id:
                return DigestCheckResult(
                    ok=True,
                    reason="ghcr-tag-manifest-match",
                    seen_repo_digests=repo_digests,
                    tag_digest=tag_document.digest or expected,
                    expected_config_digest=config_digest,
                    local_image_id=local_image_id,
                    source=tag_document.source,
                )
            return DigestCheckResult(
                ok=False,
                reason="platform-mismatch" if config_digest else "manifest-config-missing",
                seen_repo_digests=repo_digests,
                tag_digest=tag_document.digest or expected,
                expected_config_digest=config_digest,
                local_image_id=local_image_id,
                source=tag_document.source,
            )

        for child_digest in tag_document.child_digests():
            child = self._try_fetch(repo, child_digest)
            if child is None:
                continue
            config_digest = child.config_digest()
            if config_digest and config_digest == local_image_id:
                return DigestCheckResult(
                    ok=True,
                    reason="ghcr-index-manifest-match",
                    seen_repo_digests=repo_digests,
                    tag_digest=tag_document.digest or expected,
                    matched_child_digest=child_digest,
                    expected_config_digest=config_digest,
                    local_image_id=local_image_id,
                    source=child.source,
                )
        return DigestCheckResult(
            ok=False,
            reason="platform-mismatch",
            seen_repo_digests=repo_digests,
            tag_digest=tag_document.digest or expected,
            local_image_id=local_image_id,
            source=tag_document.source,
        )

    def _fetch(self, repo: str, reference: str) -> ManifestDocument:
        primary_error: ManifestLookupError | None = None
        try:
            return self.primary_resolver.fetch(repo, reference)
        except ManifestLookupError as exc:
            primary_error = exc
        try:
            return self.fallback_resolver.fetch(repo, reference)
        except ManifestLookupError as exc:
            raise ManifestLookupError(f"{primary_error}; fallback failed: {exc}") from exc

    def _try_fetch(self, repo: str, reference: str) -> ManifestDocument | None:
        try:
            return self._fetch(repo, reference)
        except ManifestLookupError:
            return None


def parse_ghcr_image(image: str) -> GhcrImageRef | None:
    image = strip_digest(image).strip()
    registry, sep, remainder = image.partition("/")
    if sep == "" or registry.lower() != GHCR_REGISTRY or not remainder:
        return None
    repo_path, tag_sep, tag = remainder.rpartition(":")
    if tag_sep == "" or "/" in tag:
        return None
    return GhcrImageRef(repo=repo_path, tag=tag)


def _content_type(value: str) -> str:
    return value.split(";", 1)[0].strip()


def _header_value(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def _same_manifest(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right,
        sort_keys=True,
        separators=(",", ":"),
    )
