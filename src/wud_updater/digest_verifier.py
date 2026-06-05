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
DOCKER_HUB_REGISTRIES = frozenset(
    ("docker.io", "index.docker.io", "registry-1.docker.io")
)
DOCKER_HUB_HTTP_REGISTRY = "registry-1.docker.io"
DEFAULT_REGISTRY_TIMEOUT = 5.0
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
VERBOSE_MANIFEST_LIST_MEDIA_TYPE = (
    "application/vnd.docker.distribution.manifest.list.v2+json"
)


class ManifestLookupError(RuntimeError):
    """Raised when a registry manifest cannot be resolved or parsed."""


class ManifestResolver(Protocol):
    def fetch(self, image: "RegistryImageRef", reference: str) -> "ManifestDocument":
        """Return a manifest or index document for ``image`` and ``reference``."""


@dataclass(frozen=True)
class RegistryImageRef:
    registry: str
    http_registry: str
    repo: str
    tag: str

    def is_ghcr(self) -> bool:
        return self.registry == GHCR_REGISTRY

    def manifest_ref(self, reference: str) -> str:
        if reference.startswith("sha256:"):
            return f"{self.registry}/{self.repo}@{reference}"
        return f"{self.registry}/{self.repo}:{reference}"


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
    status: str
    reason: str
    seen_repo_digests: tuple[str, ...] = ()
    tag_digest: str = ""
    matched_child_digest: str = ""
    expected_config_digest: str = ""
    local_image_id: str = ""
    source: str = ""
    error: str = ""


@dataclass(frozen=True)
class DigestResolveResult:
    ok: bool
    status: str
    reason: str
    digest: str = ""
    source: str = ""
    error: str = ""


class RegistryHttpManifestResolver:
    """Resolve public registry manifests through the distribution HTTP API."""

    def __init__(self, *, timeout: float = DEFAULT_REGISTRY_TIMEOUT) -> None:
        self.timeout = timeout
        self._tokens: dict[str, str] = {}

    def fetch(self, image: RegistryImageRef, reference: str) -> ManifestDocument:
        url = f"https://{image.http_registry}/v2/{image.repo}/manifests/{reference}"
        headers, payload = self._request_json(url)
        return ManifestDocument(
            source=f"registry-http:{image.http_registry}",
            digest=_header_value(headers, "Docker-Content-Digest"),
            media_type=_content_type(_header_value(headers, "Content-Type")),
            payload=payload,
        )

    def _request_json(
        self,
        url: str,
        *,
        accept: str = MANIFEST_ACCEPT,
        token: str = "",
    ) -> tuple[Mapping[str, str], Mapping[str, Any]]:
        request = urllib.request.Request(url)
        request.add_header("Accept", accept)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                headers = {key: value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            if exc.code != 401 or token:
                raise ManifestLookupError(
                    f"registry request failed for {url}: {exc}"
                ) from exc
            challenge = exc.headers.get("WWW-Authenticate", "")
            return self._request_json(
                url,
                accept=accept,
                token=self._token(challenge),
            )
        except (OSError, urllib.error.URLError) as exc:
            raise ManifestLookupError(f"registry request failed for {url}: {exc}") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestLookupError(
                f"registry response was not valid JSON for {url}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ManifestLookupError(
                f"registry response was not a JSON object for {url}"
            )
        return headers, payload

    def _token(self, challenge: str) -> str:
        cached = self._tokens.get(challenge)
        if cached:
            return cached
        scheme, _sep, rest = challenge.partition(" ")
        if scheme.lower() != "bearer" or not rest:
            raise ManifestLookupError(
                f"unsupported registry auth challenge: {challenge}"
            )
        values = urllib.request.parse_keqv_list(urllib.request.parse_http_list(rest))
        realm = values.get("realm")
        if not realm:
            raise ManifestLookupError(
                f"registry auth challenge did not include a realm: {challenge}"
            )
        query = {
            key: value
            for key in ("service", "scope")
            if isinstance((value := values.get(key)), str) and value
        }
        separator = "&" if urllib.parse.urlparse(realm).query else "?"
        url = realm + (separator + urllib.parse.urlencode(query) if query else "")
        _headers, payload = self._request_json(url, accept="application/json")
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ManifestLookupError(
                f"registry token response for {url} did not include a token"
            )
        self._tokens[challenge] = token
        return token


class DockerManifestResolver:
    """Resolve manifests through ``docker manifest inspect``."""

    def __init__(self, docker: DockerCli, *, verbose: bool = False) -> None:
        self.docker = docker
        self.verbose = verbose

    def fetch(self, image: RegistryImageRef, reference: str) -> ManifestDocument:
        manifest_ref = image.manifest_ref(reference)
        try:
            result = (
                self.docker.manifest_inspect_verbose(manifest_ref)
                if self.verbose
                else self.docker.manifest_inspect(manifest_ref)
            )
        except CommandError as exc:
            raise ManifestLookupError(
                f"docker manifest inspect failed for {manifest_ref}"
            ) from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ManifestLookupError(
                f"docker manifest inspect returned invalid JSON for {manifest_ref}"
            ) from exc
        if self.verbose:
            payload = _normalize_verbose_manifest_payload(payload, manifest_ref)
        elif not isinstance(payload, Mapping):
            raise ManifestLookupError(
                f"docker manifest inspect returned non-object JSON for {manifest_ref}"
            )
        return ManifestDocument(
            source="docker-manifest-verbose" if self.verbose else "docker-manifest",
            digest=_payload_digest(payload) if self.verbose else "",
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
        self.primary_resolver = primary_resolver or RegistryHttpManifestResolver()
        self.fallback_resolver = fallback_resolver or DockerManifestResolver(docker)

    def verify(self, image: str, expected: str) -> DigestCheckResult:
        repo_digests = tuple(self.docker.image_repo_digests(image))
        local_image_id = self.docker.image_id(image)
        if any(digest.rsplit("@", 1)[-1] == expected for digest in repo_digests):
            return DigestCheckResult(
                ok=True,
                status="verified",
                reason="repo-digest-match",
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
            )

        registry_image = parse_registry_image(image)
        if registry_image is None:
            return DigestCheckResult(
                ok=False,
                status="untrusted",
                reason="repo-digest-mismatch",
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
            )
        if not local_image_id:
            return DigestCheckResult(
                ok=False,
                status=_failure_status(registry_image),
                reason="missing-local-image-id",
                seen_repo_digests=repo_digests,
            )

        try:
            tag_document = self._fetch(registry_image, registry_image.tag)
        except ManifestLookupError as exc:
            return DigestCheckResult(
                ok=False,
                status=_failure_status(registry_image),
                reason=_manifest_unavailable_reason(registry_image),
                seen_repo_digests=repo_digests,
                local_image_id=local_image_id,
                error=str(exc),
            )

        if tag_document.digest == expected:
            return self._verify_tag_document(
                registry_image,
                tag_document,
                expected,
                repo_digests,
                local_image_id,
            )

        if tag_document.is_index() and tag_document.child_digest(expected):
            return self._verify_expected_manifest(
                registry_image,
                expected,
                tag_document,
                repo_digests,
                local_image_id,
            )

        if not tag_document.digest:
            expected_document = self._try_fetch(registry_image, expected)
            if expected_document is not None and _same_manifest(
                tag_document.payload,
                expected_document.payload,
            ):
                return self._verify_tag_document(
                    registry_image,
                    tag_document,
                    expected,
                    repo_digests,
                    local_image_id,
                )

        return DigestCheckResult(
            ok=False,
            status="failed",
            reason="stale-digest",
            seen_repo_digests=repo_digests,
            tag_digest=tag_document.digest,
            local_image_id=local_image_id,
            source=tag_document.source,
        )

    def resolve_tag_digest(self, image: str) -> DigestResolveResult:
        registry_image = parse_registry_image(image)
        if registry_image is None:
            return DigestResolveResult(
                ok=False,
                status="untrusted",
                reason="unsupported-image-reference",
            )
        try:
            tag_document = self._fetch(registry_image, registry_image.tag)
        except ManifestLookupError as exc:
            return DigestResolveResult(
                ok=False,
                status=_failure_status(registry_image),
                reason=_manifest_unavailable_reason(registry_image),
                error=str(exc),
            )
        digest = tag_document.digest or _payload_digest(tag_document.payload)
        if not digest and tag_document.is_index():
            digest = self._resolve_index_digest(registry_image)
        if not digest:
            return DigestResolveResult(
                ok=False,
                status=_failure_status(registry_image),
                reason="manifest-digest-missing",
                source=tag_document.source,
            )
        return DigestResolveResult(
            ok=True,
            status="resolved",
            reason="tag-digest-resolved",
            digest=digest,
            source=tag_document.source,
        )

    def _resolve_index_digest(
        self,
        image: RegistryImageRef,
    ) -> str:
        resolver = (
            self.primary_resolver
            if isinstance(self.primary_resolver, RegistryHttpManifestResolver)
            else RegistryHttpManifestResolver()
        )
        try:
            document = resolver.fetch(image, image.tag)
        except ManifestLookupError:
            return ""
        if not document.is_index():
            return ""
        return document.digest or _payload_digest(document.payload)

    def _verify_expected_manifest(
        self,
        image: RegistryImageRef,
        expected: str,
        tag_document: ManifestDocument,
        repo_digests: tuple[str, ...],
        local_image_id: str,
    ) -> DigestCheckResult:
        try:
            expected_document = self._fetch(image, expected)
        except ManifestLookupError as exc:
            return DigestCheckResult(
                ok=False,
                status=_failure_status(image),
                reason=_manifest_unavailable_reason(image),
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
                status="verified",
                reason=_reason(image, "platform-manifest-match"),
                seen_repo_digests=repo_digests,
                tag_digest=tag_document.digest,
                matched_child_digest=expected,
                expected_config_digest=expected_config,
                local_image_id=local_image_id,
                source=expected_document.source,
            )
        return DigestCheckResult(
            ok=False,
            status="failed",
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
        image: RegistryImageRef,
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
                    status="verified",
                    reason=_reason(image, "tag-manifest-match"),
                    seen_repo_digests=repo_digests,
                    tag_digest=tag_document.digest or expected,
                    expected_config_digest=config_digest,
                    local_image_id=local_image_id,
                    source=tag_document.source,
                )
            return DigestCheckResult(
                ok=False,
                status="failed",
                reason="platform-mismatch" if config_digest else "manifest-config-missing",
                seen_repo_digests=repo_digests,
                tag_digest=tag_document.digest or expected,
                expected_config_digest=config_digest,
                local_image_id=local_image_id,
                source=tag_document.source,
            )

        for child_digest in tag_document.child_digests():
            child = self._try_fetch(image, child_digest)
            if child is None:
                continue
            config_digest = child.config_digest()
            if config_digest and config_digest == local_image_id:
                return DigestCheckResult(
                    ok=True,
                    status="verified",
                    reason=_reason(image, "index-manifest-match"),
                    seen_repo_digests=repo_digests,
                    tag_digest=tag_document.digest or expected,
                    matched_child_digest=child_digest,
                    expected_config_digest=config_digest,
                    local_image_id=local_image_id,
                    source=child.source,
                )
        return DigestCheckResult(
            ok=False,
            status="failed",
            reason="platform-mismatch",
            seen_repo_digests=repo_digests,
            tag_digest=tag_document.digest or expected,
            local_image_id=local_image_id,
            source=tag_document.source,
        )

    def _fetch(self, image: RegistryImageRef, reference: str) -> ManifestDocument:
        primary_error: ManifestLookupError | None = None
        try:
            return self.primary_resolver.fetch(image, reference)
        except ManifestLookupError as exc:
            primary_error = exc
        try:
            return self.fallback_resolver.fetch(image, reference)
        except ManifestLookupError as exc:
            raise ManifestLookupError(f"{primary_error}; fallback failed: {exc}") from exc

    def _try_fetch(
        self,
        image: RegistryImageRef,
        reference: str,
    ) -> ManifestDocument | None:
        try:
            return self._fetch(image, reference)
        except ManifestLookupError:
            return None


def parse_registry_image(image: str) -> RegistryImageRef | None:
    image = strip_digest(image).strip()
    if not image:
        return None
    first, sep, remainder = image.partition("/")
    if sep and _is_registry_prefix(first):
        registry = first.lower()
        repo_tag = remainder
    else:
        registry = "docker.io"
        repo_tag = image
        if "/" not in repo_tag:
            repo_tag = f"library/{repo_tag}"
    if not repo_tag:
        return None
    repo_path, tag_sep, tag = repo_tag.rpartition(":")
    if tag_sep == "" or "/" in tag or not repo_path or not tag:
        return None
    return RegistryImageRef(
        registry=registry,
        http_registry=(
            DOCKER_HUB_HTTP_REGISTRY
            if registry in DOCKER_HUB_REGISTRIES
            else registry
        ),
        repo=repo_path,
        tag=tag,
    )


def parse_ghcr_image(image: str) -> RegistryImageRef | None:
    parsed = parse_registry_image(image)
    if parsed is None or not parsed.is_ghcr():
        return None
    return parsed


def _failure_status(image: RegistryImageRef) -> str:
    return "failed" if image.is_ghcr() else "untrusted"


def _manifest_unavailable_reason(image: RegistryImageRef) -> str:
    return "manifest-unavailable" if image.is_ghcr() else "manifest-unavailable-untrusted"


def _reason(image: RegistryImageRef, suffix: str) -> str:
    prefix = "ghcr" if image.is_ghcr() else "registry"
    return f"{prefix}-{suffix}"


def _is_registry_prefix(value: str) -> bool:
    return "." in value or ":" in value or value == "localhost"


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


def _payload_digest(payload: Mapping[str, Any]) -> str:
    digest = payload.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest
    descriptor = payload.get("Descriptor")
    if isinstance(descriptor, Mapping):
        digest = descriptor.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            return digest
    return ""


def _normalize_verbose_manifest_payload(
    payload: Any,
    manifest_ref: str,
) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if not isinstance(payload, list):
        raise ManifestLookupError(
            f"docker manifest inspect --verbose returned unsupported JSON for {manifest_ref}"
        )

    manifests: list[Mapping[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise ManifestLookupError(
                f"docker manifest inspect --verbose returned unsupported JSON for {manifest_ref}"
            )
        descriptor = item.get("Descriptor")
        if not isinstance(descriptor, Mapping):
            raise ManifestLookupError(
                f"docker manifest inspect --verbose omitted descriptors for {manifest_ref}"
            )
        digest = descriptor.get("digest")
        if not isinstance(digest, str) or not digest:
            raise ManifestLookupError(
                f"docker manifest inspect --verbose omitted descriptor digests for {manifest_ref}"
            )
        manifests.append(dict(descriptor))

    if not manifests:
        raise ManifestLookupError(
            f"docker manifest inspect --verbose returned an empty manifest list for {manifest_ref}"
        )
    return {
        "schemaVersion": 2,
        "mediaType": VERBOSE_MANIFEST_LIST_MEDIA_TYPE,
        "manifests": manifests,
    }
