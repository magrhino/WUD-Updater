"""Create disposable demo state and generated static WebUI fixtures."""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_FIXTURE_PATH = REPO_ROOT / "webui" / "src" / "api" / "demo" / "generatedFixtures.ts"
DEMO_FIXTURE_STARTED_AT = "2026-05-30T20:12:26+00:00"
DEMO_FIXTURE_FINISHED_AT = "2026-05-30T20:12:28+00:00"
DEMO_TAG_OVERRIDE_PREFIX = "demooverride"
DEMO_FIXTURE_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)"
)
DEMO_FIXTURE_LOG_TIMESTAMP_RE = re.compile(
    r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]"
)
DEMO_COMPOSE_CONFIG_CODE_RE = re.compile(
    r"compose-config-[a-z0-9._-]+-state-docker-([a-z0-9._-]+)-docker-compose-yml"
)
DEMO_TEMP_LOG_PATH_RE = re.compile(
    r"/[^\s\"']*wud-static-demo-[^\s\"']*\.log"
)

from wud_updater.db import (  # noqa: E402
    open_db,
    init_db,
    insert_dependency_snooze,
    insert_snooze,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
    upsert_known_image,
    upsert_tag_exclusion_rule,
)
from wud_updater import command as command_module  # noqa: E402
from wud_updater.digest_provenance import DigestTagProvenance  # noqa: E402


_WEB_FIXTURE_IMPORTS_READY = False
Request: Any = None
web_app: Any = None
web_auth: Any = None
web_diagnostics: Any = None
web_health: Any = None
web_jobs: Any = None
web_onboarding: Any = None
web_pending: Any = None
web_plans: Any = None
web_release_notes: Any = None
web_retags: Any = None
web_runs: Any = None
web_self_update: Any = None
web_settings: Any = None
web_state: Any = None
web_static: Any = None
web_wud_api: Any = None
GitHubClient: Any = None
refresh_release_notes: Any = None
ApplyJobLogResponse: Any = None
PlanRequest: Any = None
TagOverrideRequest: Any = None
RetagChoiceRequest: Any = None
RetagPlanRequest: Any = None
RetagPreviewJobResponse: Any = None
SelfUpdateResponse: Any = None
SelfUpdatePlanResponse: Any = None
WebSettings: Any = None


def _ensure_web_fixture_imports() -> None:
    global _WEB_FIXTURE_IMPORTS_READY
    global Request
    global web_app, web_auth, web_diagnostics, web_health, web_jobs
    global web_onboarding, web_pending, web_plans, web_release_notes, web_retags
    global web_runs, web_self_update, web_settings, web_state, web_static
    global web_wud_api
    global GitHubClient, refresh_release_notes
    global ApplyJobLogResponse, PlanRequest, TagOverrideRequest
    global RetagChoiceRequest, RetagPlanRequest, RetagPreviewJobResponse
    global SelfUpdateResponse, SelfUpdatePlanResponse
    global WebSettings

    if _WEB_FIXTURE_IMPORTS_READY:
        return

    from starlette.requests import Request as _Request
    from wud_updater import web as _web_app
    from wud_updater import web_auth as _web_auth
    from wud_updater import web_diagnostics as _web_diagnostics
    from wud_updater import web_health as _web_health
    from wud_updater import web_jobs as _web_jobs
    from wud_updater import web_onboarding as _web_onboarding
    from wud_updater import web_pending as _web_pending
    from wud_updater import web_plans as _web_plans
    from wud_updater import web_release_notes as _web_release_notes
    from wud_updater import web_retags as _web_retags
    from wud_updater import web_runs as _web_runs
    from wud_updater import web_self_update as _web_self_update
    from wud_updater import web_settings as _web_settings
    from wud_updater import web_state as _web_state
    from wud_updater import web_static as _web_static
    from wud_updater import web_wud_api as _web_wud_api
    from wud_updater.release_notes import (
        GitHubClient as _GitHubClient,
        refresh_release_notes as _refresh_release_notes,
    )
    from wud_updater.web_models import (
        ApplyJobLogResponse as _ApplyJobLogResponse,
        PlanRequest as _PlanRequest,
        TagOverrideRequest as _TagOverrideRequest,
        RetagChoiceRequest as _RetagChoiceRequest,
        RetagPlanRequest as _RetagPlanRequest,
        RetagPreviewJobResponse as _RetagPreviewJobResponse,
        SelfUpdateResponse as _SelfUpdateResponse,
        SelfUpdatePlanResponse as _SelfUpdatePlanResponse,
        WebSettings as _WebSettings,
    )

    Request = _Request
    web_app = _web_app
    web_auth = _web_auth
    web_diagnostics = _web_diagnostics
    web_health = _web_health
    web_jobs = _web_jobs
    web_onboarding = _web_onboarding
    web_pending = _web_pending
    web_plans = _web_plans
    web_release_notes = _web_release_notes
    web_retags = _web_retags
    web_runs = _web_runs
    web_self_update = _web_self_update
    web_settings = _web_settings
    web_state = _web_state
    web_static = _web_static
    web_wud_api = _web_wud_api
    GitHubClient = _GitHubClient
    refresh_release_notes = _refresh_release_notes
    ApplyJobLogResponse = _ApplyJobLogResponse
    PlanRequest = _PlanRequest
    TagOverrideRequest = _TagOverrideRequest
    RetagChoiceRequest = _RetagChoiceRequest
    RetagPlanRequest = _RetagPlanRequest
    RetagPreviewJobResponse = _RetagPreviewJobResponse
    SelfUpdateResponse = _SelfUpdateResponse
    SelfUpdatePlanResponse = _SelfUpdatePlanResponse
    WebSettings = _WebSettings
    _WEB_FIXTURE_IMPORTS_READY = True


DEMO_WUD_UPDATER_LATEST_IMAGE = "ghcr.io/magrhino/wud-updater:latest"
DEMO_WUD_UPDATER_TARGET_TAG = "v0.16.1"
DEMO_WUD_UPDATER_REPO_URL = "https://github.com/magrhino/WUD-Updater"
DEMO_HOME_ASSISTANT_CORE_URL = "https://github.com/home-assistant/core"
DEMO_OCI_SOURCE_LABEL = "org.opencontainers.image.source"
DEMO_POSTGRES_IMAGE = "postgres:16"
DEMO_POSTGRES_DIGEST = (
    "sha256:1111111111111111111111111111111111111111111111111111111111111111"
)
DEMO_RADARR_SERVICE_KEY = "media/radarr"
DEMO_SOURCE_METADATA_JSON = '{"source":"demo"}'
DEMO_CREATED_AT = "2026-05-28T12:00:00+00:00"

PENDING_LINES = (
    "# Demo WUD pending update file for local WebUI development.",
    "ghcr.io/home-assistant/home-assistant:2026.5.1 tag=2026.5.3",
    "lscr.io/linuxserver/radarr:5.21.1 tag=5.22.4",
    f"{DEMO_POSTGRES_IMAGE}@{DEMO_POSTGRES_DIGEST}",
    f"{DEMO_WUD_UPDATER_LATEST_IMAGE} tag={DEMO_WUD_UPDATER_TARGET_TAG}",
    "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
    "vaultwarden/server:1.31.0 tag=1.32.0",
    "containrrr/watchtower:1.7.1 tag=1.7.2",
)

DEMO_WUD_UPDATER_DIGEST = (
    "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
)

DEMO_STACKS = (
    {
        "name": "home",
        "services": (
            ("home-assistant", "ghcr.io/home-assistant/home-assistant:2026.5.1"),
        ),
    },
    {
        "name": "media",
        "services": (
            ("radarr", "lscr.io/linuxserver/radarr:5.21.1"),
            ("wud-updater", DEMO_WUD_UPDATER_LATEST_IMAGE),
        ),
    },
    {
        "name": "data",
        "services": (
            ("postgres", DEMO_POSTGRES_IMAGE),
        ),
    },
)

DEMO_UNMATCHED_CONTAINERS = (
    ("homepage", "ghcr.io/gethomepage/homepage:v0.9.12"),
    ("vaultwarden", "vaultwarden/server:1.31.0"),
    ("watchtower", "containrrr/watchtower:1.7.1"),
)

DEMO_CONTAINER_LABELS = {
    "cid-data-postgres": {
        "WUD-UPDATER-RECREATE-STACK": "true",
    },
}

DEMO_COMPOSE_LABELS = {
    ("media", "wud-updater"): {
        "wud.tag.include": "^latest$$",
    },
}

DEMO_KNOWN_IMAGES = (
    {
        "service_key": "media/wud-updater",
        "image": DEMO_WUD_UPDATER_LATEST_IMAGE,
        "image_id": "sha256:demo-wud-updater-current",
        "digest": DEMO_WUD_UPDATER_DIGEST,
        "digest_provenance": DigestTagProvenance(
            source_image=DEMO_WUD_UPDATER_LATEST_IMAGE,
            resolved_tag=DEMO_WUD_UPDATER_TARGET_TAG,
            watch_tag="latest",
            target_digest=DEMO_WUD_UPDATER_DIGEST,
            final_image=f"ghcr.io/magrhino/wud-updater@{DEMO_WUD_UPDATER_DIGEST}",
            provenance_source="demo",
            provenance_confidence="verified",
        ),
    },
)

DEMO_PULL_TARGETS = (
    (
        "ghcr.io/home-assistant/home-assistant:2026.5.3",
        "sha256:demo-home-assistant-new",
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ),
    (
        "lscr.io/linuxserver/radarr:5.22.4",
        "sha256:demo-radarr-new",
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ),
    (
        DEMO_POSTGRES_IMAGE,
        "sha256:demo-postgres-new",
        DEMO_POSTGRES_DIGEST,
    ),
    (
        f"ghcr.io/magrhino/wud-updater:{DEMO_WUD_UPDATER_TARGET_TAG}",
        "sha256:demo-wud-updater-new",
        DEMO_WUD_UPDATER_DIGEST,
    ),
)

DEMO_SERVICE_POLICIES = (
    {
        "service_key": "home/home-assistant",
        "update_mode": "live",
        "auto_update": True,
        "snooze_default_seconds": None,
        "auto_update_time": "03:30",
        "auto_update_days_json": '["mon","wed","fri"]',
    },
    {
        "service_key": DEMO_RADARR_SERVICE_KEY,
        "update_mode": "stop",
        "auto_update": False,
        "snooze_default_seconds": 86400,
        "auto_update_time": None,
        "auto_update_days_json": "[]",
    },
)

DEMO_SNOOZES = (
    {
        "service_key": DEMO_RADARR_SERVICE_KEY,
        "snoozed_until": "2099-01-01T00:00:00+00:00",
        "reason": "demo maintenance window",
        "created_at": DEMO_CREATED_AT,
    },
    {
        "service_key": "data/postgres",
        "snoozed_until": "2020-01-01T00:00:00+00:00",
        "reason": "expired demo snooze",
        "created_at": "2020-01-01T00:00:00+00:00",
    },
)

DEMO_DEPENDENCY_SNOOZES = (
    {
        "service_key": "media/sonarr",
        "wait_for_service_key": "media/prowlarr",
        "reason": "wait for indexer update",
        "created_at": DEMO_CREATED_AT,
    },
)

DEMO_TAG_EXCLUSIONS = (
    {
        "scope": "image_repo",
        "image_repo": "ghcr.io/home-assistant/home-assistant",
        "service_key": "",
        "tag": "2026.5.3",
        "status": "active",
    },
    {
        "scope": "service",
        "image_repo": "lscr.io/linuxserver/radarr",
        "service_key": DEMO_RADARR_SERVICE_KEY,
        "tag": "5.22.4",
        "status": "disabled",
    },
)

RUNS = (
    {
        "started_at": "2026-05-28T12:12:00+00:00",
        "finished_at": "2026-05-28T12:13:41+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "stop",
        "log": "demo-success.log",
        "metadata": {"source": "demo", "summary": "updated two services"},
        "pending": (
            {
                "line_no": 1,
                "raw": "lscr.io/linuxserver/sonarr:4.0.14 tag=4.0.15",
                "image": "lscr.io/linuxserver/sonarr:4.0.14",
                "desired_tag": "4.0.15",
                "service_key": "media/sonarr",
                "stack_name": "media",
                "service_name": "sonarr",
                "status": "success",
                "status_reason": "container recreated and healthy",
            },
            {
                "line_no": 2,
                "raw": "redis:7.2 tag=7.4",
                "image": "redis:7.2",
                "desired_tag": "7.4",
                "service_key": "infra/redis",
                "stack_name": "infra",
                "service_name": "redis",
                "status": "success",
                "status_reason": "service updated",
            },
        ),
        "events": (
            {
                "service_name": "sonarr",
                "stack_name": "media",
                "image": "lscr.io/linuxserver/sonarr:4.0.14",
                "target_image": "lscr.io/linuxserver/sonarr:4.0.15",
                "status": "success",
                "old_digest": "sha256:sonarr-old",
                "new_digest": "sha256:sonarr-new",
            },
            {
                "service_name": "redis",
                "stack_name": "infra",
                "image": "redis:7.2",
                "target_image": "redis:7.4",
                "status": "success",
                "old_digest": "sha256:redis-old",
                "new_digest": "sha256:redis-new",
            },
        ),
        "log_content": """[2026-05-28T12:12:00+00:00] docker-update-from-wud-v2
[2026-05-28T12:12:02+00:00] Found 2 matching services.
[2026-05-28T12:12:38+00:00] [media/sonarr] Recreated container and health check passed.
[2026-05-28T12:13:40+00:00] [infra/redis] Recreated container and health check passed.
[2026-05-28T12:13:41+00:00] Done.
""",
    },
    {
        "started_at": "2026-05-28T10:04:00+00:00",
        "finished_at": "2026-05-28T10:05:09+00:00",
        "status": "failed",
        "dry_run": False,
        "mode": "pause",
        "log": "demo-failed.log",
        "metadata": {"source": "demo", "summary": "health check failed"},
        "pending": (
            {
                "line_no": 1,
                "raw": "ghcr.io/example/api:2.8.0 tag=2.9.0",
                "image": "ghcr.io/example/api:2.8.0",
                "desired_tag": "2.9.0",
                "service_key": "apps/api",
                "stack_name": "apps",
                "service_name": "api",
                "status": "failed",
                "status_reason": "container health check timed out",
            },
        ),
        "events": (
            {
                "service_name": "api",
                "stack_name": "apps",
                "image": "ghcr.io/example/api:2.8.0",
                "target_image": "ghcr.io/example/api:2.9.0",
                "status": "failed",
                "old_digest": "sha256:api-old",
                "new_digest": "sha256:api-new",
            },
        ),
        "log_content": """[2026-05-28T10:04:00+00:00] docker-update-from-wud-v2
[2026-05-28T10:04:06+00:00] [apps/api] Pull complete.
[2026-05-28T10:04:32+00:00] [apps/api] Container recreated.
[2026-05-28T10:05:09+00:00] [apps/api] Health check timed out; leaving WUD line pending.
""",
    },
    {
        "started_at": "2026-05-27T22:45:00+00:00",
        "finished_at": "2026-05-27T22:45:12+00:00",
        "status": "success",
        "dry_run": True,
        "mode": "live",
        "log": "demo-dry-run.log",
        "metadata": {"source": "demo", "summary": "dry-run plan"},
        "pending": (
            {
                "line_no": 1,
                "raw": "nginx:1.25 tag=1.27",
                "image": "nginx:1.25",
                "desired_tag": "1.27",
                "service_key": "edge/nginx",
                "stack_name": "edge",
                "service_name": "nginx",
                "status": "planned",
                "status_reason": "dry-run only",
            },
        ),
        "events": (),
        "log_content": """[2026-05-27T22:45:00+00:00] docker-update-from-wud-v2
[2026-05-27T22:45:01+00:00] Dry-run: would update edge/nginx from nginx:1.25 to nginx:1.27.
[2026-05-27T22:45:12+00:00] Dry-run completed without mutation.
""",
    },
    {
        "started_at": "2026-05-30T19:20:00+00:00",
        "finished_at": "2026-05-30T19:20:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-auth",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "reset_admin_password",
            "actor_type": "reset_claim",
            "resource_type": "web_user",
            "resource_id": "admin",
            "target": {"username": "admin"},
        },
        "pending": (),
        "events": (
            {
                "service_name": "admin",
                "stack_name": "webui",
                "image": "web_user",
                "target_image": "admin",
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
    {
        "started_at": "2026-05-30T19:50:00+00:00",
        "finished_at": "2026-05-30T19:50:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-state",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "upsert_service_policy",
            "actor_type": "browser",
            "resource_type": "service_policy",
            "resource_id": DEMO_RADARR_SERVICE_KEY,
            "service_key": DEMO_RADARR_SERVICE_KEY,
            "target": {"service_key": DEMO_RADARR_SERVICE_KEY},
        },
        "pending": (),
        "events": (
            {
                "service_name": "radarr",
                "stack_name": "media",
                "image": "service-policy",
                "target_image": DEMO_RADARR_SERVICE_KEY,
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
    {
        "started_at": "2026-05-30T20:20:00+00:00",
        "finished_at": "2026-05-30T20:20:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-settings",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "update_managed_settings",
            "actor_type": "browser",
            "resource_type": "managed_settings",
            "resource_id": "webui_preferences",
            "target": {"keys": ["theme_preference"]},
        },
        "pending": (),
        "events": (
            {
                "service_name": "settings",
                "stack_name": "webui",
                "image": "managed-settings",
                "target_image": "webui-preferences",
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
)


def generate_static_demo_fixtures() -> dict[str, Any]:
    """Generate static demo fixtures from backend WebUI response builders."""

    _ensure_web_fixture_imports()
    with _preserved_wud_api_snapshot_cache():
        with tempfile.TemporaryDirectory(prefix="wud-static-demo.") as tmpdir:
            context = _demo_context(Path(tmpdir) / "state")
            try:
                with _static_demo_default_static_dir(context.paths["static_dir"]):
                    data = _fixture_payload(context)
                return _sanitize_payload(data, context.paths)
            finally:
                web_jobs.shutdown_apply_job_state(context.state)


@contextlib.contextmanager
def _preserved_wud_api_snapshot_cache():
    with web_wud_api._cache_lock:
        original_cache = dict(web_wud_api._snapshot_cache)
    try:
        yield
    finally:
        with web_wud_api._cache_lock:
            web_wud_api._snapshot_cache.clear()
            web_wud_api._snapshot_cache.update(original_cache)


def render_static_demo_fixtures_ts(data: dict[str, Any]) -> str:
    payload = json.dumps(data, indent=2, sort_keys=True)
    return (
        'import type { DemoGeneratedFixtures } from "./types";\n\n'
        f"export const generatedFixtures = {payload} satisfies DemoGeneratedFixtures;\n"
    )


def write_static_demo_fixtures(path: Path = GENERATED_FIXTURE_PATH) -> None:
    fixture_path = _resolve_repo_output_path(path)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        render_static_demo_fixtures_ts(generate_static_demo_fixtures()),
        encoding="utf-8",
    )


def _resolve_repo_output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"--fixtures-out must stay inside the repository: {path}"
        ) from exc
    return resolved


def _non_empty_subsets(values: list[int]) -> list[list[int]]:
    return [
        list(group)
        for size in range(1, len(values) + 1)
        for group in itertools.combinations(values, size)
    ]


def _line_set_key(line_numbers: list[int]) -> str:
    return "lines-" + "-".join(str(line_no) for line_no in line_numbers)


def _tag_token(line_no: int) -> str:
    return f"{DEMO_TAG_OVERRIDE_PREFIX}{line_no}"


def _tag_tokens(
    line_numbers: list[int],
    taggable_lines: dict[int, str],
) -> list[dict[str, Any]]:
    return [
        {
            "line_no": line_no,
            "token": _tag_token(line_no),
            "default_tag": taggable_lines[line_no],
        }
        for line_no in line_numbers
        if line_no in taggable_lines
    ]


def _plan_case_key(
    line_numbers: list[int],
    allow_tag_updates: bool,
    tag_tokens: list[dict[str, Any]],
) -> str:
    parts = [
        _line_set_key(line_numbers),
        "allow-tags" if allow_tag_updates else "block-tags",
    ]
    if tag_tokens:
        parts.append(
            "overrides-" + "-".join(token["token"] for token in tag_tokens)
        )
    else:
        parts.append("default-tags")
    return "__".join(parts)


def _safe_case_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower() or "item"


def _fixture_payload(context: SimpleNamespace) -> dict[str, Any]:
    request = context.request
    settings = context.settings
    parsed = web_pending.parse_pending_file(settings)[1]
    retag_targets = _dump(web_retags.retag_targets_response(settings))
    runs = [_normalize_run_record(_dump(run)) for run in web_runs.api_runs(request)]
    cached_doctor = web_diagnostics.web_doctor_result(settings, request)
    original_web_doctor_result = web_diagnostics.web_doctor_result
    web_diagnostics.web_doctor_result = lambda *_args, **_kwargs: cached_doctor
    try:
        return {
            "auth": {
                "session": _dump(web_auth.api_auth_session(request)),
                "setupStatus": _dump(web_auth.api_setup_status(request)),
            },
            "status": _dump(web_app.api_status(request)),
            "settings": _dump(web_settings.settings_response(settings, request)),
            "doctor": _dump(web_health.api_doctor(request)),
            "onboarding": _dump(web_onboarding.api_onboarding_checklist(request)),
            "pending": _dump(web_pending.pending_response(settings)),
            "updateTargets": _dump(web_pending.update_targets_response(settings)),
            "planCases": _plan_cases(context, parsed),
            "removalCases": _removal_cases(settings, parsed),
            "retagTargets": retag_targets,
            "retagCases": _retag_cases(settings, retag_targets),
            "releaseNotes": _dump(web_release_notes.api_release_notes(request)),
            "selfUpdate": _dump(web_self_update.api_self_update(request)),
            "selfUpdatePlan": _normalize_self_update_plan(
                _demo_self_update_plan(settings, request)
            ),
            "diagnostics": _dump(web_diagnostics.api_diagnostics_support_bundle(request)),
            "servicePolicies": _dump(web_state.api_service_policies(request)),
            "snoozes": {
                "active": _dump(web_state.api_snoozes(request, state="active")),
                "expired": _dump(web_state.api_snoozes(request, state="expired")),
                "all": _dump(web_state.api_snoozes(request, state="all")),
            },
            "tagExclusions": {
                "active": _dump(web_state.api_tag_exclusions(request, status="active")),
                "disabled": _dump(web_state.api_tag_exclusions(request, status="disabled")),
                "all": _dump(web_state.api_tag_exclusions(request, status="all")),
            },
            "runs": {
                "summaries": runs,
                "details": {
                    str(run["id"]): _normalize_run_record(
                        _dump(web_runs.api_run_detail(run["id"], request))
                    )
                    for run in runs
                },
                "logs": {
                    str(run["id"]): _dump(
                        web_runs.api_run_log(run["id"], request, tail_bytes=262_144)
                    )
                    for run in runs
                },
            },
        }
    finally:
        web_diagnostics.web_doctor_result = original_web_doctor_result


def _plan_cases(context: SimpleNamespace, parsed: Any) -> list[dict[str, Any]]:
    with _cached_command_capture():
        cases: list[dict[str, Any]] = []
        line_numbers = sorted(target.line_no for target in parsed.targets)
        taggable_lines = {
            target.line_no: target.desired_tag
            for target in parsed.targets
            if target.desired_tag
        }
        for selected in _non_empty_subsets(line_numbers):
            cases.append(
                _plan_case(
                    context,
                    selected,
                    allow_tag_updates=False,
                    tag_tokens=_tag_tokens(selected, taggable_lines),
                )
            )
            cases.append(
                _plan_case(
                    context,
                    selected,
                    allow_tag_updates=True,
                    tag_tokens=_tag_tokens(selected, taggable_lines),
                )
            )
        return cases


@contextlib.contextmanager
def _cached_command_capture():
    original_capture = command_module.CommandRunner.capture
    cache: dict[
        tuple[
            tuple[str, ...],
            str,
            tuple[tuple[str, str], ...],
            tuple[tuple[str, str], ...],
        ],
        command_module.CommandResult,
    ] = {}

    def cached_capture(
        runner,
        args,
        *,
        cwd=None,
        env=None,
        check=True,
    ):
        argv = command_module.normalize_args(args)
        cwd_key = str(Path(cwd).resolve()) if cwd is not None else ""
        base_env_key = tuple(sorted((getattr(runner, "_env", None) or {}).items()))
        env_key = tuple(sorted((env or {}).items()))
        key = (argv, cwd_key, base_env_key, env_key)
        if key not in cache:
            cache[key] = original_capture(
                runner,
                args,
                cwd=cwd,
                env=env,
                check=False,
            )
        result = cache[key]
        if check and not result.ok:
            raise command_module.CommandError(result)
        return result

    command_module.CommandRunner.capture = cached_capture
    try:
        yield
    finally:
        command_module.CommandRunner.capture = original_capture


def _plan_case(
    context: SimpleNamespace,
    line_numbers: list[int],
    *,
    allow_tag_updates: bool,
    tag_tokens: list[dict[str, Any]],
) -> dict[str, Any]:
    key = _plan_case_key(line_numbers, allow_tag_updates, [])
    payload = PlanRequest(
        line_numbers=line_numbers,
        allow_tag_updates=allow_tag_updates,
    )
    plan = web_plans.build_web_plan(context.settings, payload)
    response = web_plans.plan_response(
        plan,
        context.settings,
        context.request,
    )
    data = _dump(response)
    data["plan_id"] = f"demo-plan-{key}"
    if data.get("cleanup", {}).get("cleanup_id"):
        data["cleanup"]["cleanup_id"] = f"demo-plan-{key}-cleanup"
    case: dict[str, Any] = {
        "key": key,
        "request": {
            "line_numbers": line_numbers,
            "allow_tag_updates": allow_tag_updates,
            "tag_override_lines": [],
        },
        "tagTokens": tag_tokens,
        "response": data,
    }
    return case


def _removal_cases(settings: WebSettings, parsed: Any) -> list[dict[str, Any]]:
    line_numbers = sorted(target.line_no for target in parsed.targets)
    return [
        {
            "key": f"remove-{_line_set_key(selected)}",
            "request": {"line_numbers": selected},
            "response": _normalize_removal_plan(
                web_pending.pending_removal_plan(settings, selected, parsed=parsed),
                f"demo-removal-{_line_set_key(selected)}",
            ),
        }
        for selected in _non_empty_subsets(line_numbers)
    ]


def _tokenize_job_template(
    job_template: dict[str, Any],
    tag_tokens: list[dict[str, Any]],
) -> dict[str, Any]:
    replacements = {
        token["default_tag"]: token["token"]
        for token in tag_tokens
    }
    return _replace_many(job_template, replacements)


def _retag_plan_case(
    settings: WebSettings,
    plan_id: str,
    choices: list[RetagChoiceRequest],
) -> dict[str, Any]:
    plan = web_retags.build_retag_plan(
        settings,
        RetagPlanRequest(choices=choices),
    ).response
    data = _dump(plan)
    data["plan_id"] = plan_id
    return data


def _normalize_removal_plan(plan: Any, removal_id: str) -> dict[str, Any]:
    data = _dump(plan)
    data["removal_id"] = removal_id
    return data


def _retag_cases(
    settings: WebSettings,
    retag_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    targets = retag_targets.get("items", [])
    service_keys = [str(item["service_key"]) for item in targets]
    cases: list[dict[str, Any]] = []
    for choices_tuple in itertools.product(
        ("keep-current", "switch-to-concrete"),
        repeat=len(service_keys),
    ):
        choices = [
            RetagChoiceRequest(service_key=service_key, choice=choice)
            for service_key, choice in zip(service_keys, choices_tuple, strict=True)
        ]
        key = _retag_case_key(choices)
        response = _retag_plan_case(settings, f"demo-retag-plan-{key}", choices)
        case: dict[str, Any] = {
            "key": key,
            "request": {"choices": _dump(choices)},
            "response": response,
            "preview": _retag_preview_fixture(
                f"demo-retag-preview-{key}",
                response,
            ),
        }
        if response.get("can_apply"):
            case["jobTemplate"] = _generate_retag_job_fixture(key, choices)
        cases.append(case)
    return cases


def _retag_case_key(choices: list[Any]) -> str:
    selected = [
        _safe_case_part(choice.service_key)
        for choice in choices
        if choice.choice == "switch-to-concrete"
    ]
    if not selected:
        return "keep-all"
    return "switch-" + "-".join(selected)


def _retag_preview_fixture(
    preview_job_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    queued = RetagPreviewJobResponse(
        preview_job_id=preview_job_id,
        status="queued",
        plan=None,
        warnings=[],
        progress=[
            {
                "job_id": preview_job_id,
                "phase": "refresh",
                "status": "running",
                "message": "Refreshing demo retag candidates.",
                "created_at": DEMO_FIXTURE_STARTED_AT,
                "stack": "",
                "services": [],
                "line_numbers": [],
            }
        ],
    )
    complete = RetagPreviewJobResponse(
        preview_job_id=preview_job_id,
        status="success",
        plan=plan,
        warnings=plan.get("warnings", []),
        progress=[
            *queued.progress,
            {
                "job_id": preview_job_id,
                "phase": "preview",
                "status": "success",
                "message": "Demo retag preview is ready.",
                "created_at": DEMO_FIXTURE_FINISHED_AT,
                "stack": "",
                "services": [],
                "line_numbers": [],
            },
        ],
    )
    return {"queued": _dump(queued), "complete": _dump(complete)}


def _demo_self_update_plan(
    settings: WebSettings,
    request: Request,
) -> SelfUpdatePlanResponse:
    status = SelfUpdateResponse(
        status="available",
        strategy="prepare_tag_update",
        current_tag="v0.25.0",
        latest_tag="v0.26.0",
        current_image="ghcr.io/magrhino/wud-updater:v0.25.0",
        target_image="ghcr.io/magrhino/wud-updater:v0.26.0",
        restart_container=settings.restart_container,
        can_update=True,
        external_recreate_required=True,
    )
    plan, cached = web_self_update._build_self_update_tag_plan(settings, status)
    try:
        return SelfUpdatePlanResponse(
            strategy="prepare_tag_update",
            plan=web_plans.plan_response(plan, settings, request),
            current_tag=status.current_tag,
            latest_tag=status.latest_tag,
            current_image=status.current_image,
            target_image=status.target_image,
            restart_container=status.restart_container,
            external_recreate_required=True,
            warning=(
                "This updates the Compose image tag and pulls the image. "
                "Recreate the WUD-Updater container from outside the WebUI to run it."
            ),
        )
    finally:
        web_self_update._delete_self_update_plan_file(cached)


def _normalize_self_update_plan(plan: SelfUpdatePlanResponse) -> dict[str, Any]:
    data = _dump(plan)
    data["plan"]["plan_id"] = "demo-self-update-plan"
    data["plan"]["source_file"] = "demo/out/.self-update-plan.todo"
    cleanup = data["plan"].get("cleanup", {})
    if cleanup.get("cleanup_id"):
        cleanup["cleanup_id"] = "demo-self-update-plan-cleanup"
    return data


def _generate_apply_job_fixture(
    case_key: str,
    line_numbers: list[int],
    *,
    allow_tag_updates: bool,
    tag_tokens: list[dict[str, Any]],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"wud-static-demo-{case_key}.") as tmpdir:
        context = _demo_context(Path(tmpdir) / "state")
        try:
            payload = PlanRequest(
                line_numbers=line_numbers,
                allow_tag_updates=allow_tag_updates,
                tag_overrides=[
                    TagOverrideRequest(line_no=token["line_no"], tag=token["token"])
                    for token in tag_tokens
                ],
            )
            plan = web_plans.build_web_plan(context.settings, payload)
            wud_lock = web_jobs._acquire_apply_wud_lock(context.settings)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                queued = web_jobs._submit_apply_job_state(
                    context.state,
                    context.settings,
                    plan,
                    allow_tag_updates=allow_tag_updates,
                    tag_overrides=tuple(web_plans.tag_overrides_from_payload(payload)),
                    digest_pin_label_rewrite_approvals=(),
                    wud_lock=wud_lock,
                    effective_config_loader=web_settings._effective_config,
                    auto_update_schedule_run_updater=lambda *_args, **_kwargs: None,
                )
                terminal = _wait_for_job(context.state, queued.job_id)
            fixture = _job_fixture_from_terminal(
                context,
                queued,
                terminal,
                stable_job_id=f"demo-job-{case_key}",
                stable_log_file=f"demo/logs/demo-apply-{case_key}.log",
                remove_line_numbers=line_numbers,
            )
            return _sanitize_payload(fixture, context.paths)
        finally:
            web_jobs.shutdown_apply_job_state(context.state)


def _generate_retag_job_fixture(
    case_key: str,
    choices: list[RetagChoiceRequest],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"wud-static-demo-retag-{case_key}.") as tmpdir:
        context = _demo_context(Path(tmpdir) / "state")
        try:
            build = web_retags.build_retag_plan(
                context.settings,
                RetagPlanRequest(choices=choices),
            )
            wud_lock = web_jobs._acquire_apply_wud_lock(context.settings)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                queued = web_retags._submit_retag_apply_job(
                    context.request,
                    context.settings,
                    build,
                    wud_lock,
                )
                terminal = _wait_for_job(context.state, queued.job_id)
            fixture = _job_fixture_from_terminal(
                context,
                queued,
                terminal,
                stable_job_id=f"demo-retag-job-{case_key}",
                stable_log_file=f"demo/logs/demo-retag-{case_key}.log",
                remove_line_numbers=[],
            )
            return _sanitize_payload(fixture, context.paths)
        finally:
            web_jobs.shutdown_apply_job_state(context.state)


def _job_fixture_from_terminal(
    context: SimpleNamespace,
    queued: Any,
    terminal: Any,
    *,
    stable_job_id: str,
    stable_log_file: str,
    remove_line_numbers: list[int],
) -> dict[str, Any]:
    terminal_response = web_jobs._apply_job_response(terminal)
    log = web_jobs._apply_job_log_response(
        context.settings,
        terminal_response,
        max_bytes=65_536,
        safe_log_path=web_runs._safe_log_path,
        read_log_tail=web_runs._read_log_tail,
    ) or ApplyJobLogResponse(
        job_id=terminal_response.job_id,
        log_file="",
        exists=False,
        content="",
        truncated=False,
        max_bytes=65_536,
    )
    run = None
    if terminal_response.run_id is not None:
        run_id = terminal_response.run_id
        run = {
            "summary": _dump(
                next(
                    item
                    for item in web_runs.api_runs(context.request)
                    if item.id == run_id
                )
            ),
            "detail": _dump(web_runs.api_run_detail(run_id, context.request)),
            "log": _dump(
                web_runs.api_run_log(run_id, context.request, tail_bytes=262_144)
            ),
        }
    fixture = {
        "queued": _dump(queued),
        "terminal": _dump(terminal_response),
        "log": _dump(log),
        "run": run,
        "removeLineNumbers": remove_line_numbers,
    }
    return _normalize_job_fixture(
        fixture,
        original_job_id=terminal_response.job_id,
        stable_job_id=stable_job_id,
        stable_log_file=stable_log_file,
    )


def _wait_for_job(state: Any, job_id: str) -> Any:
    deadline = time.monotonic() + 15
    condition = state.web_apply_condition
    with condition:
        while True:
            job = state.web_apply_jobs[job_id]
            if job.status not in {"queued", "running"}:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"demo fixture job {job_id} did not finish")
            condition.wait(min(remaining, 0.05))


def _normalize_job_fixture(
    fixture: dict[str, Any],
    *,
    original_job_id: str,
    stable_job_id: str,
    stable_log_file: str,
) -> dict[str, Any]:
    normalized = _replace_string(fixture, original_job_id, stable_job_id)
    terminal = normalized["terminal"]
    queued = normalized["queued"]
    log = normalized["log"]
    queued["job_id"] = stable_job_id
    terminal["job_id"] = stable_job_id
    terminal["log_file"] = stable_log_file
    terminal["started_at"] = DEMO_FIXTURE_STARTED_AT
    terminal["finished_at"] = DEMO_FIXTURE_FINISHED_AT
    log["job_id"] = stable_job_id
    log["log_file"] = stable_log_file
    if "content" in log:
        log["content"] = _normalize_fixture_text(log["content"], stable_log_file)
    for index, event in enumerate(terminal.get("progress", [])):
        event["job_id"] = stable_job_id
        event["created_at"] = (
            DEMO_FIXTURE_STARTED_AT if index == 0 else DEMO_FIXTURE_FINISHED_AT
        )
    run = normalized.get("run")
    if run:
        for key in ("summary", "detail"):
            run[key]["started_at"] = DEMO_FIXTURE_STARTED_AT
            run[key]["finished_at"] = DEMO_FIXTURE_FINISHED_AT
            run[key]["log_file"] = stable_log_file
            metadata = run[key].get("metadata", {})
            if "plan_id" in metadata:
                metadata["plan_id"] = f"{stable_job_id}-plan"
            for event in run[key].get("events", []):
                event["created_at"] = DEMO_FIXTURE_FINISHED_AT
        run["log"]["log_file"] = stable_log_file
        run["log"]["content"] = _normalize_fixture_text(
            run["log"]["content"],
            stable_log_file,
        )
        _normalize_run_record(run["summary"])
        _normalize_run_record(run["detail"])
    return normalized


def _normalize_run_record(run: dict[str, Any]) -> dict[str, Any]:
    started_at = str(run.get("started_at") or DEMO_CREATED_AT)
    finished_at = str(run.get("finished_at") or started_at)
    for event in run.get("events", []):
        event["created_at"] = started_at
    for pending in run.get("pending_updates", []):
        pending["created_at"] = started_at
        pending["updated_at"] = finished_at
    return run


def _normalize_fixture_text(value: str, stable_log_file: str) -> str:
    value = DEMO_FIXTURE_TIMESTAMP_RE.sub(DEMO_FIXTURE_STARTED_AT, value)
    value = DEMO_FIXTURE_LOG_TIMESTAMP_RE.sub("[2026-05-30T20:12:26]", value)
    value = DEMO_TEMP_LOG_PATH_RE.sub(stable_log_file, value)
    value = re.sub(
        r"demo-[A-Za-z0-9._/-]*\.log",
        Path(stable_log_file).name,
        value,
    )
    return value


def _demo_context(root: Path) -> SimpleNamespace:
    paths = seed_demo_state(root)
    static_dir = paths["root"] / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    env = _demo_environ(paths, static_dir)
    settings = web_app.load_web_settings(env)
    _configure_backend_callbacks()
    _seed_wud_api_snapshot(settings)
    state = SimpleNamespace(web_settings=settings)
    web_jobs.initialize_apply_job_state(state)
    request = _demo_request(settings, state)
    _seed_release_note_cache(settings)
    return SimpleNamespace(
        paths={**paths, "static_dir": static_dir},
        env=env,
        settings=settings,
        state=state,
        request=request,
    )


def _demo_environ(paths: dict[str, Path], static_dir: Path) -> dict[str, str]:
    fake_bin = REPO_ROOT / "tests" / "fakes"
    command_path = os.pathsep.join(
        (str(fake_bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin")
    )
    return {
        "HOME": str(paths["root"]),
        "DOCKER_BASE": str(paths["docker_base"]),
        "HOST_DOCKER_BASE": str(paths["docker_base"]),
        "WUD_OUT_FILE": str(paths["wud_file"]),
        "WUD_LOG_DIR": str(paths["log_dir"]),
        "WUD_DB_PATH": str(paths["db_path"]),
        "WUD_WEB_STATIC_DIR": str(static_dir),
        "WUD_WEB_DEV_NO_AUTH": "true",
        "WUD_WEB_MUTATIONS_ENABLED": "true",
        "WUD_WEB_RESTART_CONTAINER": "demo-wud-updater",
        "WUD_WEB_DEMO_SELF_UPDATE": "true",
        "WUD_WEB_ALLOWED_HOSTS": "testserver, 127.0.0.1, localhost",
        "WUD_WEB_ALLOWED_ORIGINS": "http://testserver",
        "WUD_WEB_UPSTREAM_MAP": str(REPO_ROOT / "wud" / "upstreams.txt"),
        "WUD_SCRIPTS_DIR": str(REPO_ROOT / "wud"),
        "WUD_SYNC_SCRIPTS": "false",
        "WUD_UPDATER_USE_SUDO": "false",
        "DOCKER_HOST": "tcp://demo-docker:2375",
        "PATH": command_path,
        "FAKE_DOCKER_ROOT": str(paths["fake_docker_root"]),
    }


def _demo_request(settings: WebSettings, state: Any) -> Request:
    state.web_settings = settings
    app = SimpleNamespace(state=state)
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 49152),
            "headers": [(b"host", b"testserver")],
            "app": app,
        }
    )


@contextlib.contextmanager
def _static_demo_default_static_dir(static_dir: Path):
    original_resolve_static_dir = web_settings._resolve_static_dir

    def resolve_static_dir(configured: str | Path | None) -> Path | None:
        if configured is None:
            return static_dir
        return original_resolve_static_dir(configured)

    web_settings._resolve_static_dir = resolve_static_dir
    try:
        yield
    finally:
        web_settings._resolve_static_dir = original_resolve_static_dir


def _configure_backend_callbacks() -> None:
    web_health.configure(
        effective_config_loader=web_settings._effective_config,
        static_spa_available_checker=web_static.static_spa_available,
    )
    web_pending.configure(effective_config_loader=web_settings._effective_config)
    web_plans.configure(effective_config_loader=web_settings._effective_config)
    web_retags.configure(effective_config_loader=web_settings._effective_config)
    web_self_update.configure(
        effective_config_loader=web_settings._effective_config,
        plan_response_builder=web_plans.plan_response,
    )


def _seed_wud_api_snapshot(settings: WebSettings) -> None:
    containers = (
        web_wud_api.WudApiContainer(
            id="cid-home-assistant",
            name="home-assistant",
            display_name="home-assistant",
            status="running",
            watcher="docker",
            image="ghcr.io/home-assistant/home-assistant:2026.5.1",
            local_tag="2026.5.1",
            local_digest="",
            remote_tag="2026.5.3",
            remote_digest=(
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            update_kind="tag",
            semver_diff="patch",
            link=DEMO_HOME_ASSISTANT_CORE_URL,
            error="",
            labels={
                DEMO_OCI_SOURCE_LABEL: DEMO_HOME_ASSISTANT_CORE_URL
            },
        ),
        web_wud_api.WudApiContainer(
            id="cid-media-radarr",
            name="radarr",
            display_name="radarr",
            status="running",
            watcher="docker",
            image="lscr.io/linuxserver/radarr:5.21.1",
            local_tag="5.21.1",
            local_digest="",
            remote_tag="5.22.4",
            remote_digest=(
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            update_kind="tag",
            semver_diff="minor",
            link="https://github.com/radarr/radarr",
            error="",
            labels={
                "org.opencontainers.image.source": (
                    "https://github.com/linuxserver/docker-radarr"
                )
            },
        ),
        web_wud_api.WudApiContainer(
            id="cid-data-postgres",
            name="postgres",
            display_name="postgres",
            status="running",
            watcher="docker",
            image=DEMO_POSTGRES_IMAGE,
            local_tag="16",
            local_digest=DEMO_POSTGRES_DIGEST,
            remote_tag="",
            remote_digest=DEMO_POSTGRES_DIGEST,
            update_kind="digest",
            semver_diff="",
            link="",
            error="",
            labels={},
        ),
        web_wud_api.WudApiContainer(
            id="cid-media-wud-updater",
            name="demo-wud-updater",
            display_name="wud-updater",
            status="running",
            watcher="docker",
            image=DEMO_WUD_UPDATER_LATEST_IMAGE,
            local_tag="latest",
            local_digest="",
            remote_tag=DEMO_WUD_UPDATER_TARGET_TAG,
            remote_digest=DEMO_WUD_UPDATER_DIGEST,
            update_kind="tag",
            semver_diff="minor",
            link=DEMO_WUD_UPDATER_REPO_URL,
            error="",
            labels={
                DEMO_OCI_SOURCE_LABEL: DEMO_WUD_UPDATER_REPO_URL
            },
        ),
    )
    base_url = settings.wud_api_base_url or web_wud_api.DEFAULT_WUD_API_BASE_URL
    snapshot = web_wud_api.WudApiSnapshot(
        status=web_wud_api.WudApiStatus(
            state="ready",
            available=True,
            metadata_available=True,
            last_checked_at=DEMO_CREATED_AT,
            detail=f"{len(containers)} WUD update metadata item(s) available",
        ),
        containers=containers,
        metadata_checked=True,
        checked_monotonic=time.monotonic(),
    )
    with web_wud_api._cache_lock:
        web_wud_api._snapshot_cache[base_url] = snapshot


def _seed_release_note_cache(settings: WebSettings) -> None:
    exists, parsed = web_pending.parse_pending_file(settings)
    if not exists:
        return
    wud_snapshot = web_wud_api.get_snapshot(settings, include_containers=True)
    wud_metadata = web_wud_api.metadata_by_target(
        settings,
        parsed.targets,
        snapshot=wud_snapshot,
    )
    source_resolver = _demo_release_source_resolver(settings, wud_metadata)
    target_tag_resolver = web_wud_api.target_tag_resolver_from_metadata(wud_metadata)
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        refresh_release_notes(
            conn,
            parsed.targets,
            settings.command_env or {},
            client=GitHubClient(fetch_json=_demo_github_json),
            now=DEMO_CREATED_AT,
            source_resolver=source_resolver,
            target_tag_resolver=target_tag_resolver,
            force=True,
        )


def _demo_release_source_resolver(
    settings: WebSettings,
    wud_metadata: dict[int, Any],
):
    base_resolver = web_release_notes.release_note_source_resolver(
        settings,
        wud_metadata=wud_metadata,
    )

    def resolve(target: Any) -> str:
        if target.repo == "home-assistant/home-assistant":
            return DEMO_HOME_ASSISTANT_CORE_URL
        if target.repo == "magrhino/wud-updater":
            return DEMO_WUD_UPDATER_REPO_URL
        return base_resolver(target)

    return resolve


def _demo_github_json(url: str) -> object:
    marker = "https://api.github.com/repos/"
    if not url.startswith(marker):
        return {"message": "Not Found"}
    path = url.removeprefix(marker)
    if "/releases/tags/" in path:
        repo, tag = path.split("/releases/tags/", 1)
        return _demo_release_payload(repo, tag)
    if path.endswith("/releases/latest"):
        repo = path.removesuffix("/releases/latest")
        return _demo_release_payload(repo, "")
    return {"html_url": f"https://github.com/{path}"}


def _demo_release_payload(repo: str, tag: str) -> dict[str, object]:
    normalized_repo = repo.lower()
    requested = tag or "latest"
    releases = {
        ("home-assistant/core", "2026.5.3"): (
            "Home Assistant Core 2026.5.3",
            "Patch release for the demo fixture.",
        ),
        ("radarr/radarr", "v5.22.4"): (
            "Radarr v5.22.4",
            "Demo upstream Radarr release notes.",
        ),
        ("magrhino/wud-updater", DEMO_WUD_UPDATER_TARGET_TAG): (
            f"WUD-Updater {DEMO_WUD_UPDATER_TARGET_TAG}",
            "Demo WUD-Updater release notes.",
        ),
        ("linuxserver/docker-radarr", "latest"): (
            "linuxserver/radarr 5.22.4",
            "Remote changes:\n- Updating Radarr to v5.22.4",
        ),
    }
    candidates = [requested]
    if requested.startswith("v"):
        candidates.append(requested[1:])
    elif requested not in {"", "latest"}:
        candidates.append(f"v{requested}")
    for candidate in candidates:
        match = releases.get((normalized_repo, candidate))
        if match is None:
            continue
        title, body = match
        release_tag = "v5.22.4-ls1" if normalized_repo == "linuxserver/docker-radarr" else candidate
        return {
            "tag_name": release_tag,
            "name": title,
            "published_at": DEMO_CREATED_AT,
            "created_at": DEMO_CREATED_AT,
            "html_url": f"https://github.com/{repo}/releases/tag/{release_tag}",
            "body": body,
        }
    return {"message": "Not Found"}


def _sanitize_payload(value: Any, paths: dict[str, Path]) -> Any:
    replacements = {
        str(paths["wud_file"]): "demo/out/images.todo",
        str(paths["db_path"]): "demo/logs/wud-updater.sqlite",
        str(paths["log_dir"]): "demo/logs",
        str(paths["docker_base"]): "demo/docker",
        str(paths["fake_docker_root"]): "demo/fake-docker",
        str(paths.get("static_dir", "")): "demo/static",
        str(paths["root"]): "demo",
        str(REPO_ROOT): "demo/repo",
    }
    return _replace_many(value, replacements)


def _replace_many(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        result = value
        for old, new in sorted(
            ((old, new) for old, new in replacements.items() if old),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            result = result.replace(old, new)
        return _normalize_sanitized_string(result)
    if isinstance(value, list):
        return [_replace_many(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_many(item, replacements)
            for key, item in value.items()
        }
    return value


def _normalize_sanitized_string(value: str) -> str:
    value = DEMO_COMPOSE_CONFIG_CODE_RE.sub(
        r"compose-config-demo-docker-\1-docker-compose-yml",
        value,
    )
    return value


def _replace_string(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_string(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_string(item, old, new) for key, item in value.items()}
    return value


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, tuple):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "local-dev",
        help="demo state directory, default: local-dev",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--fixtures-out",
        type=Path,
        help="write generated static WebUI demo fixtures to this TypeScript file",
    )
    args = parser.parse_args()

    if args.fixtures_out is not None:
        write_static_demo_fixtures(args.fixtures_out)
        if not args.quiet:
            print(f"Wrote static WebUI demo fixtures: {args.fixtures_out}")
    else:
        paths = seed_demo_state(args.root)
        if not args.quiet:
            print("Created WebUI demo state:")
            print(f"  DOCKER_BASE={paths['docker_base']}")
            print(f"  FAKE_DOCKER_ROOT={paths['fake_docker_root']}")
            print(f"  WUD_OUT_FILE={paths['wud_file']}")
            print(f"  WUD_LOG_DIR={paths['log_dir']}")
            print(f"  WUD_DB_PATH={paths['db_path']}")
    return 0


def seed_demo_state(root: Path) -> dict[str, Path]:
    root = root.resolve()
    out_dir = root / "out"
    log_dir = root / "logs"
    docker_base = root / "docker"
    fake_docker_root = root / "fake-docker"
    wud_file = out_dir / "images.todo"
    db_path = log_dir / "wud-updater.sqlite"

    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    _reset_directory(docker_base)
    _reset_directory(fake_docker_root)

    wud_file.write_text("\n".join(PENDING_LINES) + "\n", encoding="utf-8")
    for path in log_dir.glob("demo-*.log"):
        path.unlink()
    _reset_sqlite(db_path)
    _write_demo_stacks(docker_base, fake_docker_root)

    with open_db(db_path) as conn:
        init_db(conn)
        _write_demo_management_state(conn)
        for entry in RUNS:
            log_name = str(entry["log"])
            if log_name:
                log_file = log_dir / log_name
                log_file.write_text(str(entry["log_content"]), encoding="utf-8")
                log_file_label = str(log_file)
            else:
                log_file_label = ""
            run_id = insert_update_run(
                conn,
                started_at=str(entry["started_at"]),
                status=str(entry["status"]),
                dry_run=bool(entry["dry_run"]),
                mode=str(entry["mode"]),
                wud_file=str(wud_file),
                log_file=log_file_label,
                metadata_json=json.dumps(entry["metadata"], sort_keys=True),
            )
            with conn:
                conn.execute(
                    "UPDATE update_runs SET finished_at = ? WHERE id = ?",
                    (entry["finished_at"], run_id),
                )
            for pending in entry["pending"]:
                insert_pending_update(
                    conn,
                    run_id=run_id,
                    line_no=int(pending["line_no"]),
                    raw=str(pending["raw"]),
                    image=str(pending["image"]),
                    desired_tag=str(pending["desired_tag"]),
                    service_key=str(pending["service_key"]),
                    stack_name=str(pending["stack_name"]),
                    service_name=str(pending["service_name"]),
                    status=str(pending["status"]),
                    status_reason=str(pending["status_reason"]),
                    metadata_json=DEMO_SOURCE_METADATA_JSON,
                )
                upsert_known_image(
                    conn,
                    service_key=str(pending["service_key"]),
                    image=str(pending["image"]),
                    digest="sha256:demo",
                    metadata_json=DEMO_SOURCE_METADATA_JSON,
                )
            for event in entry["events"]:
                insert_update_event(
                    conn,
                    run_id=run_id,
                    service_name=str(event["service_name"]),
                    stack_name=str(event["stack_name"]),
                    image=str(event["image"]),
                    target_image=str(event["target_image"]),
                    status=str(event["status"]),
                    old_digest=str(event["old_digest"]),
                    new_digest=str(event["new_digest"]),
                    metadata_json=json.dumps(
                        event.get("metadata", {"source": "demo"}),
                        sort_keys=True,
                    ),
                )

    return {
        "root": root,
        "out_dir": out_dir,
        "log_dir": log_dir,
        "docker_base": docker_base,
        "fake_docker_root": fake_docker_root,
        "wud_file": wud_file,
        "db_path": db_path,
    }


def _write_demo_management_state(conn) -> None:
    created_at = DEMO_CREATED_AT
    for policy in DEMO_SERVICE_POLICIES:
        with conn:
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    snooze_default_seconds,
                    auto_update_time,
                    auto_update_days_json,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(policy["service_key"]),
                    str(policy["update_mode"]),
                    1 if bool(policy["auto_update"]) else 0,
                    policy["snooze_default_seconds"],
                    policy["auto_update_time"],
                    policy["auto_update_days_json"],
                    created_at,
                    created_at,
                    DEMO_SOURCE_METADATA_JSON,
                ),
            )

    for snooze in DEMO_SNOOZES:
        insert_snooze(
            conn,
            service_key=str(snooze["service_key"]),
            snoozed_until=str(snooze["snoozed_until"]),
            reason=str(snooze["reason"]),
            created_at=str(snooze["created_at"]),
            metadata_json=DEMO_SOURCE_METADATA_JSON,
        )

    for snooze in DEMO_DEPENDENCY_SNOOZES:
        insert_dependency_snooze(
            conn,
            service_key=str(snooze["service_key"]),
            wait_for_service_key=str(snooze["wait_for_service_key"]),
            reason=str(snooze["reason"]),
            created_at=str(snooze["created_at"]),
            metadata_json=DEMO_SOURCE_METADATA_JSON,
        )

    for rule in DEMO_TAG_EXCLUSIONS:
        tag = str(rule["tag"])
        upsert_tag_exclusion_rule(
            conn,
            scope=str(rule["scope"]),
            image_repo=str(rule["image_repo"]),
            service_key=str(rule["service_key"]),
            tag=tag,
            regex_fragment=re.escape(tag),
            status=str(rule["status"]),
            created_at=created_at,
            updated_at=created_at,
            metadata_json=DEMO_SOURCE_METADATA_JSON,
        )

    for known in DEMO_KNOWN_IMAGES:
        upsert_known_image(
            conn,
            service_key=str(known["service_key"]),
            image=str(known["image"]),
            image_id=str(known["image_id"]),
            digest=str(known["digest"]),
            metadata_json=DEMO_SOURCE_METADATA_JSON,
            digest_provenance=known["digest_provenance"],
        )


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _reset_sqlite(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(f"{db_path}{suffix}")
        if path.exists():
            path.unlink()


def _write_demo_stacks(docker_base: Path, fake_docker_root: Path) -> None:
    for directory in (
        fake_docker_root / "stacks",
        fake_docker_root / "images",
        fake_docker_root / "manifests",
        fake_docker_root / "containers",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    containers: list[str] = []
    for stack in DEMO_STACKS:
        stack_name = str(stack["name"])
        services = tuple(stack["services"])
        stack_dir = docker_base / stack_name
        stack_dir.mkdir(parents=True, exist_ok=True)
        (stack_dir / ".fake-docker-id").write_text(f"{stack_name}\n", encoding="utf-8")
        _write_compose_file(stack_dir / "docker-compose.yml", stack_name, services)
        _write_fake_stack_state(fake_docker_root, stack_name, services, containers)

    for container_id, labels in DEMO_CONTAINER_LABELS.items():
        _write_fake_container_labels(fake_docker_root, container_id, labels)

    (fake_docker_root / "containers" / "demo-wud-updater.summary").write_text(
        "/demo-wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    for container_name, image in DEMO_UNMATCHED_CONTAINERS:
        (fake_docker_root / "containers" / f"{container_name}.summary").write_text(
            f"/{container_name}|running|healthy|0|0\n",
            encoding="utf-8",
        )
        containers.append(f"{container_name}\t{image}\n")
        _write_fake_image_state(fake_docker_root, image)

    for image, image_id, digest in DEMO_PULL_TARGETS:
        _write_fake_image_after_pull(
            fake_docker_root,
            image,
            image_id=image_id,
            digest=digest,
        )

    (fake_docker_root / "containers.tsv").write_text(
        "".join(containers),
        encoding="utf-8",
    )
    (fake_docker_root / "calls.log").write_text("", encoding="utf-8")


def _write_compose_file(
    path: Path,
    stack_name: str,
    services: tuple[tuple[str, str], ...],
) -> None:
    lines = ["services:\n"]
    for service, image in services:
        lines.extend(
            [
                f"  {service}:\n",
                f"    image: {image}\n",
                "    restart: unless-stopped\n",
            ]
        )
        labels = DEMO_COMPOSE_LABELS.get((stack_name, service), {})
        if labels:
            lines.append("    labels:\n")
            lines.extend(
                f"      - {key}={value}\n" for key, value in labels.items()
            )
    path.write_text("".join(lines), encoding="utf-8")


def _write_fake_stack_state(
    fake_docker_root: Path,
    stack_name: str,
    services: tuple[tuple[str, str], ...],
    containers: list[str],
) -> None:
    stack_state = fake_docker_root / "stacks" / stack_name
    stack_state.mkdir(parents=True, exist_ok=True)
    service_lines: list[str] = []
    image_lines: list[str] = []
    cid_lines: list[str] = []
    service_image_rows: list[str] = []
    for service, image in services:
        cid = f"cid-{stack_name}-{service}"
        service_lines.append(f"{service}\n")
        image_lines.append(f"{image}\n")
        cid_lines.append(f"{cid}\n")
        service_image_rows.append(f"{service}\t{image}\n")
        (stack_state / f"cids-{service}.txt").write_text(f"{cid}\n", encoding="utf-8")
        (fake_docker_root / "containers" / f"{cid}.summary").write_text(
            f"/{cid}|running|healthy|0|0\n",
            encoding="utf-8",
        )
        containers.append(f"{stack_name}-{service}\t{image}\n")
        _write_fake_image_state(fake_docker_root, image)

    (stack_state / "services.txt").write_text("".join(service_lines), encoding="utf-8")
    (stack_state / "images.txt").write_text("".join(image_lines), encoding="utf-8")
    (stack_state / "cids.txt").write_text("".join(cid_lines), encoding="utf-8")
    (stack_state / "service-images.tsv").write_text(
        "".join(service_image_rows),
        encoding="utf-8",
    )


def _write_fake_container_labels(
    fake_docker_root: Path,
    container_id: str,
    labels: dict[str, str],
) -> None:
    (fake_docker_root / "containers" / f"{container_id}.labels").write_text(
        "".join(f"{key}={value}\n" for key, value in labels.items()),
        encoding="utf-8",
    )


def _write_fake_image_state(fake_docker_root: Path, image: str) -> None:
    safe = _safe_fake_name(image)
    image_dir = fake_docker_root / "images"
    digest = f"{image}@sha256:{safe[:12].ljust(12, '0')}"
    (image_dir / f"{safe}.id").write_text(f"sha256:{safe}\n", encoding="utf-8")
    (image_dir / f"{safe}.digests").write_text(f"{digest}\n", encoding="utf-8")


def _write_fake_image_after_pull(
    fake_docker_root: Path,
    image: str,
    *,
    image_id: str,
    digest: str,
) -> None:
    safe = _safe_fake_name(image)
    image_dir = fake_docker_root / "images"
    (image_dir / f"{safe}.after_id").write_text(f"{image_id}\n", encoding="utf-8")
    (image_dir / f"{safe}.after_digests").write_text(
        f"{image}@{digest}\n",
        encoding="utf-8",
    )


def _safe_fake_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    raise SystemExit(main())
