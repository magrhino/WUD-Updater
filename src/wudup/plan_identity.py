"""Stable identity helpers for WebUI dry-run plans and cleanup previews."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .config import UpdaterConfig
from .plan_models import DryRunPlan, DryRunPlanCleanupItem, PlanFileMissing
from .updater_models import DigestPinLabelRewriteApproval, TagOverride


def _file_sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise PlanFileMissing(f"WUD file not found: {path}") from exc
    return hashlib.sha256(data).hexdigest()


def _plan_id(
    plan: DryRunPlan,
    *,
    config: UpdaterConfig,
    allow_tag_updates: bool,
    tag_overrides: Sequence[TagOverride],
    digest_pin_label_rewrite_approvals: Sequence[DigestPinLabelRewriteApproval],
    host_docker_base: Path | None,
    wud_file_hash: str,
    source_file: str | None = None,
) -> str:
    plan_payload = asdict(plan)
    plan_payload.pop("plan_id", None)
    plan_payload.pop("can_apply", None)
    payload = {
        "version": 1,
        "allow_tag_updates": allow_tag_updates,
        "tag_overrides": [
            {"line_no": item.line_no, "tag": item.tag}
            for item in sorted(tag_overrides, key=lambda item: item.line_no)
        ],
        "digest_pin_label_rewrite_approvals": [
            {
                "stack": item.stack,
                "service": item.service,
                "label_key": item.label_key,
                "current_label_value": item.current_label_value,
                "planned_tag": item.planned_tag,
                "proposed_label_value": item.proposed_label_value,
            }
            for item in sorted(
                digest_pin_label_rewrite_approvals,
                key=lambda item: (
                    item.stack,
                    item.service,
                    item.label_key,
                    item.current_label_value,
                    item.planned_tag,
                    item.proposed_label_value,
                ),
            )
        ],
        "docker_base": str(config.docker_base),
        "host_docker_base": "" if host_docker_base is None else str(host_docker_base),
        "max_wait": config.max_wait,
        "mode": config.update_mode,
        "plan": plan_payload,
        "source_file": source_file or str(config.wud_out_file),
        "wud_file_sha256": wud_file_hash,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cleanup_id(
    config: UpdaterConfig,
    items: Sequence[DryRunPlanCleanupItem],
    *,
    host_docker_base: Path | None,
) -> str:
    payload = {
        "version": 1,
        "docker_base": str(config.docker_base),
        "digest_pin_updates": config.digest_pin_updates,
        "host_docker_base": "" if host_docker_base is None else str(host_docker_base),
        "items": [
            {
                "line_no": item.line_no,
                "raw": item.raw,
                "image": item.image,
                "desired_tag": item.desired_tag,
                "digest": item.digest,
                "reason": item.reason,
            }
            for item in items
        ],
        "source_file": str(config.wud_out_file),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
