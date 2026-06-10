"""Compose YAML rewrite helpers for updater-managed image and label changes."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from .images import image_tag, tag_value_valid
from .updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagExclusion,
    AppliedTagUpdate,
    ComposeTagRewriteError,
    DigestPinLabelRewrite,
    DigestPinLabelRewriteApproval,
    DigestPinLabelRewriteApprovalRequired,
    DigestPinUpdate,
    TagExclusionUpdate,
    TagUpdate,
)


DIGEST_PIN_MARKER_PREFIX = "wud-updater.resolved-tag="
WUD_TAG_INCLUDE_LABEL = "wud.tag.include"
_JS_REGEX_SPECIAL_RE = re.compile(r"([\\^$.*+?()[\]{}|])")


def apply_compose_tag_updates(
    compose_path: Path,
    updates: Sequence[TagUpdate],
) -> tuple[AppliedTagUpdate, ...]:
    if not updates:
        return ()

    source = compose_path.read_text(encoding="utf-8")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        parsed = yaml.load(source)
    except YAMLError as exc:
        raise ComposeTagRewriteError(
            f"Compose file YAML could not be parsed: {exc}"
        ) from exc
    if not isinstance(parsed, CommentedMap):
        raise ComposeTagRewriteError("Compose file is not a YAML mapping.")
    services = parsed.get("services")
    if not isinstance(services, CommentedMap):
        raise ComposeTagRewriteError("Compose file has no services mapping.")

    line_offsets = _line_start_offsets(source)
    spans: list[tuple[int, int, str, TagUpdate]] = []
    counts = {id(update): 0 for update in updates}
    seen_spans: set[tuple[int, int]] = set()

    for update in updates:
        if not update.services:
            raise ComposeTagRewriteError(
                f"No compose service was mapped for {update.old_image}."
            )
        for service in update.services:
            service_config = _direct_service_config(services, service)
            _reject_yaml_anchor_or_alias_service_config(
                services,
                service,
                service_config,
            )
            if (
                not _commented_map_has_direct_key(service_config, "image")
                and service_config.get("image") is not None
            ):
                raise ComposeTagRewriteError(
                    f"Service {service} image is inherited and needs manual review."
                )
            _reject_yaml_anchor_or_alias_image_value(services, service, service_config)
            span = _service_image_scalar_span(
                services,
                service,
                update.old_image,
                source,
                line_offsets,
            )
            if span in seen_spans:
                raise ComposeTagRewriteError(
                    f"Service {service} image for {update.old_image} was "
                    "selected more than once."
                )
            seen_spans.add(span)
            spans.append((*span, update.new_image, update))
            counts[id(update)] += 1

    rendered = source
    for start, end, replacement, _update in sorted(
        spans,
        key=lambda item: item[0],
        reverse=True,
    ):
        rendered = f"{rendered[:start]}{replacement}{rendered[end:]}"

    applied = tuple(
        AppliedTagUpdate(
            old_image=update.old_image,
            desired_tag=update.desired_tag,
            new_image=update.new_image,
            services=update.services,
            replacements=counts[id(update)],
        )
        for update in updates
    )
    if any(item.replacements < 1 for item in applied):
        return ()

    _atomic_replace_compose(compose_path, rendered, prefix="tag")
    return applied


def apply_compose_tag_exclusions(
    compose_path: Path,
    updates: Sequence[TagExclusionUpdate],
    *,
    existing_exact_tags: Mapping[str, set[str]],
) -> tuple[AppliedTagExclusion, ...]:
    """Write WUD exact-tag exclusions into service labels."""

    rendered, applied = render_compose_tag_exclusions(
        compose_path,
        updates,
        existing_exact_tags=existing_exact_tags,
    )
    if not applied:
        return applied
    _atomic_replace_compose(compose_path, rendered, prefix="exclude")
    return applied


def apply_compose_digest_pins(
    compose_path: Path,
    updates: Sequence[DigestPinUpdate],
    *,
    label_rewrite_approvals: Sequence[DigestPinLabelRewriteApproval] = (),
    stack_name: str = "",
) -> tuple[AppliedDigestPinUpdate, ...]:
    """Write final digest-pinned images plus WUD watch metadata."""

    rendered, applied = render_compose_digest_pins(
        compose_path,
        updates,
        label_rewrite_approvals=label_rewrite_approvals,
        stack_name=stack_name,
    )
    if updates and not rendered:
        raise ComposeTagRewriteError("Compose digest-pin rewrite produced no output.")
    _atomic_replace_compose(compose_path, rendered, prefix="digest-pin")
    return applied


def render_compose_digest_pins(
    compose_path: Path,
    updates: Sequence[DigestPinUpdate],
    *,
    label_rewrite_approvals: Sequence[DigestPinLabelRewriteApproval] = (),
    stack_name: str = "",
) -> tuple[str, tuple[AppliedDigestPinUpdate, ...]]:
    """Return Compose YAML with digest-pin image and watch metadata applied."""

    if not updates:
        return compose_path.read_text(encoding="utf-8"), ()

    source = compose_path.read_text(encoding="utf-8")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        parsed = yaml.load(source)
    except YAMLError as exc:
        raise ComposeTagRewriteError(
            f"Compose file YAML could not be parsed: {exc}"
        ) from exc
    if not isinstance(parsed, CommentedMap):
        raise ComposeTagRewriteError("Compose file is not a YAML mapping.")
    services = parsed.get("services")
    if not isinstance(services, CommentedMap):
        raise ComposeTagRewriteError("Compose file has no services mapping.")

    line_offsets = _line_start_offsets(source)
    counts = {id(update): 0 for update in updates}
    label_rewrites = {id(update): [] for update in updates}
    seen_spans: set[tuple[int, int]] = set()

    for update in updates:
        if not update.services:
            raise ComposeTagRewriteError(
                f"No compose service was mapped for {update.old_image}."
            )
        for service in update.services:
            service_config = _direct_service_config(services, service)
            _reject_yaml_anchor_or_alias_service_config(
                services,
                service,
                service_config,
            )
            if not _commented_map_has_direct_key(service_config, "image"):
                raise ComposeTagRewriteError(
                    f"Service {service} image is inherited and needs manual review."
                )
            _reject_yaml_anchor_or_alias_image_value(services, service, service_config)
            current_image = service_config.get("image")
            if current_image == update.resolved_image:
                expected_image = update.resolved_image
            elif current_image == update.old_image:
                expected_image = update.old_image
            else:
                raise ComposeTagRewriteError(
                    f"Service {service} image is {current_image}, expected "
                    f"{update.old_image} or {update.resolved_image}."
                )
            span = _service_image_scalar_span(
                services,
                service,
                expected_image,
                source,
                line_offsets,
            )
            if span in seen_spans:
                raise ComposeTagRewriteError(
                    f"Service {service} image for {update.old_image} was "
                    "selected more than once."
                )
            seen_spans.add(span)

            _materialize_inherited_service_labels(service_config, service)
            labels = service_config.get("labels")
            if labels is not None:
                _reject_yaml_anchor_or_alias_labels(services, service, labels)
            current_include = compose_unescape_dollars(
                _get_service_label_value(service_config, update.label_key)
            )
            label_rewrite = _digest_pin_label_rewrite(
                stack_name=stack_name,
                service=service,
                current_image=str(current_image),
                current_label_value=current_include,
                update=update,
                approvals=label_rewrite_approvals,
            )
            if label_rewrite is not None:
                label_rewrites[id(update)].append(label_rewrite)
                if label_rewrite.reason == "approval-required":
                    raise DigestPinLabelRewriteApprovalRequired(
                        service=label_rewrite.service,
                        label_key=label_rewrite.label_key,
                        current_label_value=label_rewrite.current_label_value,
                        planned_tag=label_rewrite.planned_tag,
                        proposed_label_value=label_rewrite.proposed_label_value,
                        proposed_label_regex=label_rewrite.proposed_label_regex,
                    )
            _set_service_label_value(
                service_config,
                update.label_key,
                update.label_value,
            )
            service_config["image"] = update.final_image
            service_config.yaml_set_comment_before_after_key(
                "image",
                before=update.marker,
            )
            counts[id(update)] += 1

    output = StringIO()
    yaml.dump(parsed, output)
    applied = tuple(
        AppliedDigestPinUpdate(
            old_image=update.old_image,
            resolved_tag=update.resolved_tag,
            resolved_image=update.resolved_image,
            planned_digest=update.planned_digest,
            final_image=update.final_image,
            watch_tag=update.watch_tag,
            marker=update.marker,
            label_key=update.label_key,
            label_value=update.label_value,
            services=update.services,
            replacements=counts[id(update)],
            label_rewrites=tuple(label_rewrites[id(update)]),
        )
        for update in updates
    )
    if any(item.replacements < 1 for item in applied):
        return "", ()
    return output.getvalue(), applied


def render_compose_tag_exclusions(
    compose_path: Path,
    updates: Sequence[TagExclusionUpdate],
    *,
    existing_exact_tags: Mapping[str, set[str]],
) -> tuple[str, tuple[AppliedTagExclusion, ...]]:
    """Return Compose YAML with WUD exact-tag exclusions applied."""

    if not updates:
        return compose_path.read_text(encoding="utf-8"), ()

    source = compose_path.read_text(encoding="utf-8")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        parsed = yaml.load(source)
    except YAMLError as exc:
        raise ComposeTagRewriteError(
            f"Compose file YAML could not be parsed: {exc}"
        ) from exc
    if not isinstance(parsed, CommentedMap):
        raise ComposeTagRewriteError("Compose file is not a YAML mapping.")
    services = parsed.get("services")
    if not isinstance(services, CommentedMap):
        raise ComposeTagRewriteError("Compose file has no services mapping.")

    line_offsets = _line_start_offsets(source)
    service_tags: dict[str, set[str]] = {}
    service_repos: dict[str, str] = {}
    service_images: dict[str, str] = {}
    for update in updates:
        _service_image_scalar_span(
            services,
            update.service,
            update.image,
            source,
            line_offsets,
        )
        service_tags.setdefault(update.service, set()).add(update.tag)
        service_repos[update.service] = update.image_repo
        service_images[update.service] = update.image

    applied: list[AppliedTagExclusion] = []
    for service in sorted(service_tags):
        service_config = services.get(service)
        if not isinstance(service_config, CommentedMap):
            raise ComposeTagRewriteError(
                f"Service {service} is not a mapping with direct labels."
            )
        _reject_yaml_anchor_or_alias_service_config(services, service, service_config)
        _materialize_inherited_service_labels(service_config, service)
        labels = service_config.get("labels")
        if labels is not None:
            _reject_yaml_anchor_or_alias_labels(services, service, labels)
        existing_tags = set(existing_exact_tags.get(service, set()))
        new_tags = existing_tags | service_tags[service]
        current_value = _get_service_label_value(service_config, "wud.tag.exclude")
        current_regex = compose_unescape_dollars(current_value)
        previous_managed = exact_tags_regex(existing_tags)
        next_managed = exact_tags_regex(new_tags)
        next_regex = merge_wud_exclude_regex(
            current_regex,
            previous_managed=previous_managed,
            next_managed=next_managed,
        )
        if current_regex == next_regex:
            continue
        _set_service_label_value(
            service_config,
            "wud.tag.exclude",
            compose_escape_dollars(next_regex),
        )
        applied.append(
            AppliedTagExclusion(
                service=service,
                image_repo=service_repos[service],
                tags=tuple(sorted(new_tags)),
            )
        )

    output = StringIO()
    yaml.dump(parsed, output)
    return output.getvalue(), tuple(applied)


def _atomic_replace_compose(compose_path: Path, rendered: str, *, prefix: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{compose_path.name}.{prefix}.",
        dir=str(compose_path.parent),
    )
    tmp_path: Path | None = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            tmp.write(rendered)
        st = compose_path.stat()
        os.chown(tmp_path, st.st_uid, st.st_gid)
        os.chmod(tmp_path, st.st_mode & 0o7777)
        os.replace(tmp_path, compose_path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def _materialize_inherited_service_labels(
    service_config: CommentedMap,
    service: str,
) -> None:
    if _commented_map_has_direct_key(service_config, "labels"):
        return

    labels = service_config.get("labels")
    if labels is None:
        return
    if isinstance(labels, CommentedMap):
        service_config["labels"] = _copy_label_map(labels)
        return
    if isinstance(labels, CommentedSeq):
        service_config["labels"] = _copy_label_sequence(labels)
        return
    raise ComposeTagRewriteError(
        f"Service {service} labels use unsupported YAML syntax."
    )


def _commented_map_has_direct_key(mapping: CommentedMap, key: str) -> bool:
    try:
        direct_items = mapping.non_merged_items()
    except AttributeError:
        return key in mapping
    return any(item_key == key for item_key, _item_value in direct_items)


def _copy_label_map(labels: CommentedMap) -> CommentedMap:
    copied = CommentedMap()
    for key, value in labels.items():
        copied[key] = value
    return copied


def _copy_label_sequence(labels: CommentedSeq) -> CommentedSeq:
    copied = CommentedSeq()
    for item in labels:
        copied.append(item)
    return copied


def _line_start_offsets(source: str) -> list[int]:
    offsets = [0]
    for match in re.finditer("\n", source):
        offsets.append(match.end())
    return offsets


def _service_image_scalar_span(
    services: CommentedMap,
    service: str,
    old_image: str,
    source: str,
    line_offsets: Sequence[int],
) -> tuple[int, int]:
    service_config = services.get(service)
    if not isinstance(service_config, CommentedMap):
        raise ComposeTagRewriteError(
            f"Service {service} is not a mapping with a direct image field."
        )
    image_value = service_config.get("image")
    if not isinstance(image_value, str):
        raise ComposeTagRewriteError(
            f"Service {service} image is not a direct string scalar."
        )
    if "$" in image_value:
        raise ComposeTagRewriteError(
            f"Service {service} image uses interpolation and needs manual review."
        )
    if image_value != old_image:
        raise ComposeTagRewriteError(
            f"Service {service} image is {image_value}, expected {old_image}."
        )

    try:
        line_no, _col = service_config.lc.value("image")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ComposeTagRewriteError(
            f"Service {service} image source location is unavailable."
        ) from exc

    if line_no < 0 or line_no >= len(line_offsets):
        raise ComposeTagRewriteError(
            f"Service {service} image source location is invalid."
        )

    line_start = line_offsets[line_no]
    line_end = source.find("\n", line_start)
    if line_end == -1:
        line_end = len(source)
    line = source[line_start:line_end]
    body = line[:-1] if line.endswith("\r") else line
    pattern = re.compile(
        r"^([ \t]*(?:[\"']image[\"']|image)[ \t]*:[ \t]*)"
        r"([\"']?)"
        + re.escape(old_image)
        + r"\2"
        r"([ \t]*(?:#.*)?)$"
    )
    match = pattern.fullmatch(body)
    if match is None:
        raise ComposeTagRewriteError(
            f"Service {service} image uses unsupported YAML syntax for automatic "
            "rewrite."
        )

    start = line_start + len(match.group(1)) + len(match.group(2))
    end = start + len(old_image)
    return start, end


def _direct_service_config(services: CommentedMap, service: str) -> CommentedMap:
    service_config = services.get(service)
    if not isinstance(service_config, CommentedMap):
        raise ComposeTagRewriteError(
            f"Service {service} is not a mapping with a direct image field."
        )
    return service_config


def _reject_yaml_anchor_or_alias_image_value(
    services: CommentedMap,
    service: str,
    service_config: CommentedMap,
) -> None:
    image_value = service_config.get("image")
    anchor = getattr(image_value, "anchor", None)
    if getattr(anchor, "value", None):
        raise ComposeTagRewriteError(
            f"Service {service} image uses YAML anchors or aliases and needs manual review."
        )
    for other_service, other_config in services.items():
        if other_service == service or not isinstance(other_config, CommentedMap):
            continue
        other_image = other_config.get("image")
        if other_image is image_value and getattr(image_value, "anchor", None) is not None:
            raise ComposeTagRewriteError(
                f"Service {service} image uses YAML anchors or aliases and needs manual review."
            )


def _get_service_label_value(service_config: CommentedMap, key: str) -> str:
    labels = service_config.get("labels")
    if labels is None:
        return ""
    if isinstance(labels, CommentedMap):
        value = labels.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ComposeTagRewriteError(f"Label {key} is not a string value.")
        return value
    if isinstance(labels, CommentedSeq):
        for item in labels:
            if not isinstance(item, str):
                raise ComposeTagRewriteError(
                    "Service labels use unsupported non-string list entries."
                )
            label_key, sep, label_value = item.partition("=")
            if sep and label_key == key:
                return label_value
        return ""
    raise ComposeTagRewriteError("Service labels use unsupported YAML syntax.")


def _is_simple_exact_tag_include(value: str) -> bool:
    if len(value) < 3 or not value.startswith("^") or not value.endswith("$"):
        return False
    tag_chars: list[str] = []
    index = 1
    end = len(value) - 1
    while index < end:
        char = value[index]
        if char == "\\":
            index += 1
            if index >= end:
                return False
            escaped = value[index]
            if escaped not in "\\^$.*+?()[]{}|":
                return False
            tag_chars.append(escaped)
            index += 1
            continue
        if char in "\\^$.*+?()[]{}|":
            return False
        tag_chars.append(char)
        index += 1
    return tag_value_valid("".join(tag_chars))


def _digest_pin_label_rewrite(
    *,
    stack_name: str,
    service: str,
    current_image: str,
    current_label_value: str,
    update: DigestPinUpdate,
    approvals: Sequence[DigestPinLabelRewriteApproval],
) -> DigestPinLabelRewrite | None:
    if not current_label_value:
        return None

    proposed_label_regex = exact_tags_regex((update.watch_tag,))
    if current_label_value == proposed_label_regex:
        return None

    if _is_simple_exact_tag_include(current_label_value):
        return DigestPinLabelRewrite(
            service=service,
            label_key=update.label_key,
            current_label_value=current_label_value,
            planned_tag=update.watch_tag,
            proposed_label_value=update.label_value,
            proposed_label_regex=proposed_label_regex,
            approved=False,
            reason="exact-regex-normalized",
        )

    if tag_value_valid(current_label_value) and current_label_value in {
        update.watch_tag,
        image_tag(current_image),
    }:
        return DigestPinLabelRewrite(
            service=service,
            label_key=update.label_key,
            current_label_value=current_label_value,
            planned_tag=update.watch_tag,
            proposed_label_value=update.label_value,
            proposed_label_regex=proposed_label_regex,
            approved=False,
            reason="plain-tag-normalized",
        )

    approved = any(
        _digest_pin_label_rewrite_approval_matches(
            approval,
            stack_name=stack_name,
            service=service,
            label_key=update.label_key,
            current_label_value=current_label_value,
            planned_tag=update.watch_tag,
            proposed_label_value=update.label_value,
        )
        for approval in approvals
    )
    return DigestPinLabelRewrite(
        service=service,
        label_key=update.label_key,
        current_label_value=current_label_value,
        planned_tag=update.watch_tag,
        proposed_label_value=update.label_value,
        proposed_label_regex=proposed_label_regex,
        approved=approved,
        reason="approved" if approved else "approval-required",
    )


def _digest_pin_label_rewrite_approval_matches(
    approval: DigestPinLabelRewriteApproval,
    *,
    stack_name: str,
    service: str,
    label_key: str,
    current_label_value: str,
    planned_tag: str,
    proposed_label_value: str,
) -> bool:
    return (
        approval.stack == stack_name
        and approval.service == service
        and approval.label_key == label_key
        and approval.current_label_value == current_label_value
        and approval.planned_tag == planned_tag
        and approval.proposed_label_value == proposed_label_value
    )


def _reject_yaml_anchor_or_alias_service_config(
    services: CommentedMap,
    service: str,
    service_config: CommentedMap,
) -> None:
    anchor = getattr(service_config, "anchor", None)
    if getattr(anchor, "value", None):
        raise ComposeTagRewriteError(
            f"Service {service} uses YAML anchors or aliases and needs manual review."
        )
    for other_service, other_config in services.items():
        if other_service == service or not isinstance(other_config, CommentedMap):
            continue
        if other_config is service_config:
            raise ComposeTagRewriteError(
                f"Service {service} uses YAML anchors or aliases and needs manual review."
            )


def _reject_yaml_anchor_or_alias_labels(
    services: CommentedMap,
    service: str,
    labels: object,
) -> None:
    anchor = getattr(labels, "anchor", None)
    if getattr(anchor, "value", None):
        raise ComposeTagRewriteError(
            f"Service {service} labels use YAML anchors or aliases and need manual review."
        )
    for other_service, other_config in services.items():
        if other_service == service or not isinstance(other_config, CommentedMap):
            continue
        if other_config.get("labels") is labels:
            raise ComposeTagRewriteError(
                f"Service {service} labels use YAML anchors or aliases and need manual review."
            )


def _set_service_label_value(
    service_config: CommentedMap,
    key: str,
    value: str,
) -> None:
    labels = service_config.get("labels")
    if labels is None:
        labels = CommentedSeq()
        service_config["labels"] = labels
    if isinstance(labels, CommentedMap):
        labels[key] = value
        return
    if isinstance(labels, CommentedSeq):
        replacement = f"{key}={value}"
        for index, item in enumerate(labels):
            if not isinstance(item, str):
                raise ComposeTagRewriteError(
                    "Service labels use unsupported non-string list entries."
                )
            label_key, sep, _label_value = item.partition("=")
            if sep and label_key == key:
                labels[index] = replacement
                return
        labels.append(replacement)
        return
    raise ComposeTagRewriteError("Service labels use unsupported YAML syntax.")


def _backup_compose(compose_path: Path) -> Path:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{compose_path.name}.backup.",
        dir=str(compose_path.parent),
    )
    os.close(fd)
    backup = Path(tmp_name)
    try:
        shutil.copy2(compose_path, backup)
    except Exception:
        try:
            backup.unlink()
        except FileNotFoundError:
            pass
        raise
    return backup


def js_regex_escape(value: str) -> str:
    return _JS_REGEX_SPECIAL_RE.sub(r"\\\1", value)


def exact_tags_regex(tags: Iterable[str]) -> str:
    fragments = [js_regex_escape(tag) for tag in sorted(set(tags))]
    if not fragments:
        return ""
    if len(fragments) == 1:
        return f"^{fragments[0]}$"
    return f"^(?:{'|'.join(fragments)})$"


def compose_escape_dollars(value: str) -> str:
    return value.replace("$", "$$")


def compose_unescape_dollars(value: str) -> str:
    return value.replace("$$", "$")


def merge_wud_exclude_regex(
    current_regex: str,
    *,
    previous_managed: str,
    next_managed: str,
) -> str:
    if not next_managed:
        return current_regex
    if not current_regex or current_regex == previous_managed:
        return next_managed
    if current_regex == next_managed:
        return current_regex
    return f"(?:{current_regex})|(?:{next_managed})"


def _exact_tag_include_matches(value: str, tag: str) -> bool:
    return compose_unescape_dollars(value) == exact_tags_regex((tag,))
