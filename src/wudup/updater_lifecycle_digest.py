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
    STALE_PENDING_DIGEST_REASON,
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
)
from .updater_planning import (
    _tag_updates as _shared_tag_updates,
)


def _expected_digest_requirement(match: Match) -> str:
    if not match.target.digest:
        return ""
    if "@sha256:" not in match.target.first:
        return ""
    return match.target.digest


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
                expected_digest,
            )
            for match in matches
            if (expected_digest := _expected_digest_requirement(match))
        }
        for requirement in sorted(requirements):
            if not self._verify_expected_digest_requirement(
                stack,
                requirement,
                images,
            ):
                ok = False
        return ok

    def _verify_expected_digest_requirement(
        self,
        stack: ComposeStack,
        requirement: tuple[int, str, str, bool, str],
        images: Sequence[str],
    ) -> bool:
        line_no, target, expected_image, allow_repo, expected = requirement
        digest_result, stale_result, matched = self._verify_expected_digest_images(
            expected_image,
            allow_repo,
            expected,
            images,
        )
        if digest_result is not None and digest_result.status == "untrusted":
            self.log.warning(
                f"[{stack.name}] Digest verification was inconclusive for line {line_no} ({target}): wanted {expected}"
            )
            self._log_digest_untrusted(stack.name, digest_result)
            return True
        if digest_result is not None and digest_result.ok:
            return True
        self.log.error(
            f"[{stack.name}] Expected digest not reached for line {line_no} ({target}): wanted {expected}"
        )
        if digest_result is not None:
            self._log_digest_mismatch(stack.name, digest_result)
        if stale_result is not None:
            self._mark_stale_pending_digest(
                stack,
                line_no,
                target,
                expected,
                stale_result,
            )
        if not matched:
            self.log.plain(
                "ERROR",
                f"[{stack.name}] No compose image matched line {line_no} while checking expected digest",
            )
        return False

    def _verify_expected_digest_images(
        self,
        expected_image: str,
        allow_repo: bool,
        expected: str,
        images: Sequence[str],
    ) -> tuple[DigestCheckResult | None, DigestCheckResult | None, bool]:
        matched = False
        digest_result: DigestCheckResult | None = None
        stale_result: DigestCheckResult | None = None
        for image in images:
            if not image_matches_resolved_target(image, expected_image, allow_repo):
                continue
            matched = True
            digest_result = self.digest_verifier.verify(image, expected)
            if digest_result.reason == "stale-digest":
                stale_result = digest_result
            if digest_result.ok:
                break
        return digest_result, stale_result, matched

    def _mark_stale_pending_digest(
        self,
        stack: ComposeStack,
        line_no: int,
        target: str,
        expected: str,
        result: DigestCheckResult,
    ) -> None:
        self.stale_pending_digest_lines.add((stack.index, line_no))
        current = normalize_digest(result.tag_digest)
        current_text = f"; current tag digest is {current}" if current else ""
        self.log.plain(
            "ERROR",
            f"[{stack.name}] Pending WUD entry for line {line_no} is stale: "
            f"{target} requested {expected}{current_text}. "
            "The queued digest was not restored; refresh or replace the pending entry.",
        )

    def _expected_digest_failure_reason(
        self,
        stack: ComposeStack,
        matches: Sequence[Match],
    ) -> str:
        match_lines = {(stack.index, match.target.line_no) for match in matches}
        if match_lines and match_lines.issubset(self.stale_pending_digest_lines):
            return STALE_PENDING_DIGEST_REASON
        return "expected-digest-not-reached"

    def _verify_digest_pin_updates(
        self,
        stack: ComposeStack,
        updates: Sequence[DigestPinUpdate],
        images: Sequence[str],
    ) -> bool:
        ok = True
        for update in updates:
            if not self._verify_digest_pin_update(stack, update, images):
                ok = False
        return ok

    def _verify_digest_pin_update(
        self,
        stack: ComposeStack,
        update: DigestPinUpdate,
        images: Sequence[str],
    ) -> bool:
        current = self._verify_digest_pin_update_target(update)
        if not current.ok:
            self._log_digest_pin_resolution_failure(stack, update, current)
            return False
        digest_result, matched = self._verify_digest_pin_images(update, images)
        if digest_result is not None and digest_result.ok:
            self.log.info(
                f"[{stack.name}] Verified digest-pin target: "
                f"{update.resolved_image} -> {update.planned_digest}"
            )
            return True
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
        return False

    def _log_digest_pin_resolution_failure(
        self,
        stack: ComposeStack,
        update: DigestPinUpdate,
        current: DigestResolveResult,
    ) -> None:
        if current.reason == "stale-digest":
            current_digest = normalize_digest(current.digest)
            suffix = f", current {current_digest}" if current_digest else ""
            self.log.plain(
                "ERROR",
                f"[{stack.name}] Digest-pin target moved for "
                f"{update.resolved_image}: planned {update.planned_digest}{suffix}",
            )
            return
        self.log.error(
            f"[{stack.name}] Could not re-resolve digest-pin target "
            f"{update.resolved_image}: {current.reason}"
        )
        if current.error:
            self.log.plain(
                "ERROR",
                f"[{stack.name}] Digest resolution error: {updater_logging.sanitize_stream(current.error)}",
            )

    def _verify_digest_pin_images(
        self,
        update: DigestPinUpdate,
        images: Sequence[str],
    ) -> tuple[DigestCheckResult | None, bool]:
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
        return digest_result, matched

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
