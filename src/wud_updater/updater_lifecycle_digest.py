"""Digest and tag-planning helpers for updater lifecycle execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from . import updater_logging
from .command import CommandError
from .compose import ComposeStack
from .digest_verifier import (
    DigestCheckResult,
    DigestResolveResult,
    DigestVerifier,
    DockerManifestResolver,
)
from .images import (
    image_matches_resolved_target,
    normalize_digest,
)
from .updater_digest_pin import (
    _digest_pin_candidates,
    _digest_pin_resolve_error,
    _resolve_digest_pin_candidate,
    digest_pin_update_from_values,
)
from .updater_models import (
    DigestPinCandidate,
    DigestPinUpdate,
    DigestUnpinUpdate,
    Match,
    TagUpdate,
    UpdaterError,
)
from .updater_planning import (
    _digest_check_allow_repo,
    _digest_check_image,
    _tag_updates as _shared_tag_updates,
)


class _LifecycleDigestMixin:
    def _verify_expected_digests(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
        images: Sequence[str],
    ) -> bool:
        ok = True
        requirements = {
            (
                match.target.line_no,
                match.target.first,
                _digest_check_image(match),
                _digest_check_allow_repo(match),
                match.target.digest,
            )
            for match in matches
            if match.target.digest
        }
        for line_no, target, expected_image, allow_repo, expected in sorted(requirements):
            matched = False
            digest_result: DigestCheckResult | None = None
            for image in images:
                if not image_matches_resolved_target(image, expected_image, allow_repo):
                    continue
                matched = True
                digest_result = self.digest_verifier.verify(image, expected)
                if digest_result.ok:
                    break
            if digest_result is not None and digest_result.status == "untrusted":
                self.log.warn(
                    f"[{stack.name}] Digest verification was inconclusive for line {line_no} ({target}): wanted {expected}"
                )
                self._log_digest_untrusted(stack.name, digest_result)
                continue
            if digest_result is None or not digest_result.ok:
                ok = False
                self.log.error(
                    f"[{stack.name}] Expected digest not reached for line {line_no} ({target}): wanted {expected}"
                )
                if digest_result is not None:
                    self._log_digest_mismatch(stack.name, digest_result)
                if not matched:
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] No compose image matched line {line_no} while checking expected digest",
                    )
        return ok

    def _verify_digest_pin_updates(
        self,
        stack: ComposeStack,
        updates: Sequence[DigestPinUpdate],
        images: Sequence[str],
    ) -> bool:
        ok = True
        for update in updates:
            current = self._verify_digest_pin_update_target(update)
            if not current.ok:
                ok = False
                if current.reason == "stale-digest":
                    current_digest = normalize_digest(current.digest)
                    suffix = f", current {current_digest}" if current_digest else ""
                    self.log.plain(
                        "ERROR",
                        f"[{stack.name}] Digest-pin target moved for "
                        f"{update.resolved_image}: planned {update.planned_digest}"
                        f"{suffix}",
                    )
                else:
                    self.log.error(
                        f"[{stack.name}] Could not re-resolve digest-pin target "
                        f"{update.resolved_image}: {current.reason}"
                    )
                    if current.error:
                        self.log.plain(
                            "ERROR",
                            f"[{stack.name}] Digest resolution error: {updater_logging.sanitize_stream(current.error)}",
                        )
                continue
            matched = False
            digest_result: DigestCheckResult | None = None
            for image in images:
                if not image_matches_resolved_target(
                    image,
                    update.resolved_image,
                    False,
                ):
                    continue
                matched = True
                digest_result = self.digest_verifier.verify(
                    image,
                    update.planned_digest,
                )
                if digest_result.ok:
                    break
            if digest_result is not None and digest_result.ok:
                self.log.info(
                    f"[{stack.name}] Verified digest-pin target: "
                    f"{update.resolved_image} -> {update.planned_digest}"
                )
                continue
            ok = False
            self.log.error(
                f"[{stack.name}] Digest-pin target did not verify for "
                f"{update.resolved_image}: wanted {update.planned_digest}"
            )
            if digest_result is not None:
                self._log_digest_mismatch(stack.name, digest_result)
            if not matched:
                self.log.plain(
                    "ERROR",
                    f"[{stack.name}] No compose image matched digest-pin target "
                    f"{update.resolved_image}",
                )
        return ok

    def _log_digest_untrusted(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.log.plain(
            "WARN",
            f"[{stack_name}] Digest verification reason: {result.reason}",
        )
        self._log_digest_details("WARN", stack_name, result)

    def _log_digest_mismatch(
        self,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        self.log.plain(
            "ERROR",
            f"[{stack_name}] Digest verification reason: {result.reason}",
        )
        self._log_digest_details("ERROR", stack_name, result)

    def _log_digest_details(
        self,
        level: str,
        stack_name: str,
        result: DigestCheckResult,
    ) -> None:
        if result.local_image_id:
            self.log.plain(
                level,
                f"[{stack_name}] Local image id: {result.local_image_id}",
            )
        if result.seen_repo_digests:
            for digest in result.seen_repo_digests:
                self.log.plain(
                    level,
                    f"[{stack_name}] RepoDigest seen: {digest}",
                )
        if result.tag_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Current tag digest: {result.tag_digest}",
            )
        if result.matched_child_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Matched platform digest: {result.matched_child_digest}",
            )
        if result.expected_config_digest:
            self.log.plain(
                level,
                f"[{stack_name}] Expected config digest: {result.expected_config_digest}",
            )
        if result.source:
            self.log.plain(
                level,
                f"[{stack_name}] Digest verification source: {result.source}",
            )
        if result.error:
            self.log.plain(
                level,
                f"[{stack_name}] Digest verification error: {updater_logging.sanitize_stream(result.error)}",
            )

    def _tag_updates(self, matches: Sequence[Match]) -> tuple[TagUpdate, ...]:
        return _shared_tag_updates(matches)

    def _digest_pin_updates(
        self,
        matches: Sequence[Match],
    ) -> tuple[DigestPinUpdate, ...]:
        if not self.options.digest_pin_updates:
            return ()
        candidates = _digest_pin_candidates(matches)
        cached = self.digest_pin_update_cache.get(candidates)
        if cached is not None:
            return cached
        planned = {
            (update.old_image, update.resolved_tag): update
            for update in self.options.digest_pin_plan
        }
        updates: list[DigestPinUpdate] = []
        for candidate in candidates:
            planned_update = planned.get(
                (candidate.old_image, candidate.resolved_tag)
            )
            if planned_update is not None:
                updates.append(replace(planned_update, services=candidate.services))
                continue
            resolved = self._resolve_digest_pin_candidate(candidate)
            if not resolved.ok:
                raise UpdaterError(
                    _digest_pin_resolve_error(candidate.resolved_image, resolved)
                    + (f" ({resolved.error})" if resolved.error else "")
                )
            updates.append(
                digest_pin_update_from_values(
                    old_image=candidate.old_image,
                    resolved_tag=candidate.resolved_tag,
                    planned_digest=resolved.digest,
                    services=candidate.services,
                )
            )
        result = tuple(updates)
        self.digest_pin_update_cache[candidates] = result
        return result

    def _digest_unpin_updates(
        self,
        matches: Sequence[Match],
    ) -> tuple[DigestUnpinUpdate, ...]:
        if not self.options.digest_unpin_plan:
            return ()
        updates: list[DigestUnpinUpdate] = []
        seen: set[tuple[str, str, str]] = set()
        for update in self.options.digest_unpin_plan:
            services = tuple(
                sorted(
                    {
                        match.service
                        for match in matches
                        if match.compose_image == update.old_image
                        and match.resolved == update.tag_image
                        and match.service in update.services
                    }
                )
            )
            if not services:
                continue
            key = (update.old_image, update.resolved_tag, update.target_digest)
            if key in seen:
                continue
            seen.add(key)
            updates.append(replace(update, services=services))
        return tuple(updates)

    def _resolve_digest_pin(self, image: str) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return verifier.resolve_tag_digest(image)

    def _resolve_digest_pin_candidate(
        self,
        candidate: DigestPinCandidate,
    ) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return _resolve_digest_pin_candidate(verifier, candidate)

    def _verify_digest_pin_update_target(
        self,
        update: DigestPinUpdate,
    ) -> DigestResolveResult:
        resolver = DockerManifestResolver(self.docker, verbose=True)
        verifier = DigestVerifier(
            self.docker,
            primary_resolver=resolver,
            fallback_resolver=resolver,
        )
        return verifier.verify_tag_digest(
            update.resolved_image,
            update.planned_digest,
        )

    def _refresh_stack_images(self, stack: ComposeStack) -> ComposeStack | None:
        try:
            images = tuple(
                self.compose.config_images(
                    stack.directory,
                    stack.file,
                    project_directory=stack.project_directory,
                )
            )
        except CommandError:
            self.log.error(f"[{stack.name}] Could not refresh compose images after tag rewrite.")
            return None
        return ComposeStack(
            index=stack.index,
            directory=stack.directory,
            file=stack.file,
            name=stack.name,
            images=images,
            service_images=self.compose.try_service_image_pairs(
                stack.directory,
                stack.file,
                project_directory=stack.project_directory,
            ),
            project_directory=stack.project_directory,
        )
