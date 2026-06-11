"""Runner parsing, matching, and progress helpers for ``update-from-wud``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from . import updater_audit
from .compose import ComposeStack
from .images import image_has_tag
from .line_specs import parse_line_spec
from .updater_matching import _services_for_target_match
from .updater_models import Match, UpdaterError, UpdaterProgressEvent
from .wud_file import ParsedWudFile, WudTarget, parse_wud_file


class _RunnerMatchingMixin:
    def _parse_wud_files(self) -> tuple[ParsedWudFile, ParsedWudFile]:
        opts = self.options
        full_parse = parse_wud_file(opts.wud_file)
        only_lines = parse_line_spec(opts.only_lines, len(full_parse.lines), "--only-lines")
        exclude_lines = parse_line_spec(
            opts.exclude_tag_lines,
            len(full_parse.lines),
            "--exclude-tag-lines",
        )
        parse_line_spec(
            opts.remove_lines_before_run,
            len(full_parse.lines),
            "--remove-lines-before-run",
        )
        update_lines: set[int] | None = set(only_lines) if only_lines else None
        if exclude_lines:
            if update_lines is None:
                update_lines = {
                    line.line_no for line in full_parse.lines if line.actionable
                }
            update_lines -= set(exclude_lines)
        parsed = parse_wud_file(
            opts.wud_file,
            selected_lines=sorted(update_lines) if update_lines is not None else None,
        )
        excluded = parse_wud_file(opts.wud_file, selected_lines=exclude_lines)
        for warning in parsed.warnings:
            self.log.warn(warning)
        for warning in excluded.warnings:
            self.log.warn(warning)
        return self._apply_tag_overrides(parsed), excluded

    def _apply_tag_overrides(
        self,
        parsed: ParsedWudFile,
        *,
        log: bool = True,
    ) -> ParsedWudFile:
        overrides = {item.line_no: item.tag for item in self.options.tag_overrides}
        if not overrides:
            return parsed

        targets_by_line = {target.line_no: target for target in parsed.targets}
        missing = sorted(set(overrides) - set(targets_by_line))
        if missing:
            line_list = ", ".join(str(line_no) for line_no in missing)
            raise UpdaterError(
                f"--tag-override line(s) did not match selected WUD entries: {line_list}"
            )

        updated_targets: list[WudTarget] = []
        for target in parsed.targets:
            override = overrides.get(target.line_no)
            if override is None:
                updated_targets.append(target)
                continue
            if not target.desired_tag:
                raise UpdaterError(
                    f"--tag-override line {target.line_no} does not target a tag update"
                )
            if log:
                self.log.info(
                    "Tag override: "
                    f"line {target.line_no} uses tag {override} "
                    f"instead of {target.desired_tag}"
                )
            updated_targets.append(replace(target, desired_tag=override))

        return ParsedWudFile(
            lines=parsed.lines,
            targets=tuple(updated_targets),
            warnings=parsed.warnings,
        )

    def _audit_parsed_file(
        self,
        parsed: ParsedWudFile,
        audit_lines: Sequence[int],
    ) -> ParsedWudFile:
        return updater_audit.audit_parsed_file(self, parsed, audit_lines)

    def _build_matches(
        self,
        parsed: ParsedWudFile,
        stacks: Sequence[ComposeStack],
    ) -> tuple[list[Match], list[WudTarget]]:
        container_images = {item.name: item.image for item in self.docker.try_container_images()}
        matches: list[Match] = []
        seen: set[tuple[int, int, str, str, str]] = set()
        targets, skipped_tags = self._prefilter_targets(parsed.targets)

        for target in targets:
            for stack in stacks:
                for resolved, image, service in self._match_target_in_stack(
                    target,
                    stack,
                    container_images,
                ):
                    self._append_match_if_new(
                        matches,
                        seen,
                        stack,
                        target,
                        resolved,
                        image,
                        service,
                    )

        matches.sort(
            key=lambda item: (
                item.stack.index,
                item.target.line_no,
                item.target.first,
                item.resolved,
                item.compose_image,
                item.service,
            )
        )
        return matches, skipped_tags

    def _prefilter_targets(
        self,
        targets: Sequence[WudTarget],
    ) -> tuple[list[WudTarget], list[WudTarget]]:
        filtered: list[WudTarget] = []
        skipped_tags: list[WudTarget] = []
        for target in targets:
            if target.desired_tag and not self.options.allow_tag_updates:
                skipped_tags.append(target)
                continue
            filtered.append(target)
        return filtered, skipped_tags

    def _match_target_in_stack(
        self,
        target: WudTarget,
        stack: ComposeStack,
        container_images: Mapping[str, str],
    ) -> list[tuple[str, str, str]]:
        resolved = container_images.get(target.first, target.first)
        allow_repo = (
            target.allow_repo or resolved != target.first or not image_has_tag(resolved)
        )
        candidates: list[tuple[str, str, str]] = []

        for image in stack.images:
            services = _services_for_target_match(
                stack.service_images,
                image,
                target,
                resolved,
                allow_repo,
                allow_digest_pin_rematch=self.options.digest_pin_updates,
            )
            if services is None:
                continue
            if services:
                candidates.extend((resolved, image, service) for service in services)
            else:
                candidates.append((resolved, image, ""))

        return candidates

    def _append_match_if_new(
        self,
        matches: list[Match],
        seen: set[tuple[int, int, str, str, str]],
        stack: ComposeStack,
        target: WudTarget,
        resolved: str,
        image: str,
        service: str,
    ) -> None:
        key = (stack.index, target.line_no, resolved, image, service)
        if key in seen:
            return
        matches.append(Match(stack, target, resolved, image, service))
        seen.add(key)

    def _progress(
        self,
        phase: str,
        status: str,
        message: str,
        *,
        stack: str = "",
        services: Sequence[str] | None = (),
        matches: Sequence[Match] = (),
    ) -> None:
        if self.progress_callback is None:
            return
        line_numbers = tuple(sorted({match.target.line_no for match in matches}))
        self.progress_callback(
            UpdaterProgressEvent(
                phase=phase,
                status=status,
                message=message,
                stack=stack,
                services=tuple(services or ()),
                line_numbers=line_numbers,
            )
        )
