import type {
  ApplyJobLogResponse,
  ApplyJobResponse,
  AuthSessionResponse,
  DoctorResponse,
  OnboardingChecklistResponse,
  OnboardingDismissResponse,
  PendingGroupedItem,
  PendingGrouping,
  PendingItem,
  PendingResponse,
  PlanResponse,
  ReleaseNoteInfo,
  ReleaseNotesResponse,
  RunSummary,
  ServicePolicyRecord,
  SettingsResponse,
  SnoozeRecord,
  StatusResponse,
  StateOperationResponse,
  TagExclusionRuleRecord,
} from "../../src/api/client";

export function authSession(
  overrides: Partial<AuthSessionResponse> = {},
): AuthSessionResponse {
  return {
    authenticated: true,
    setup_required: false,
    auth_required: true,
    dev_auth_bypass: false,
    mutations_enabled: false,
    username: "admin",
    ...overrides,
  };
}

export function statusResponse(
  overrides: Partial<StatusResponse> = {},
): StatusResponse {
  return {
    ok: true,
    version: "0.24.2",
    wud_file: "/out/images.todo",
    wud_file_exists: true,
    pending_count: 1,
    db_path: "/out/wud.sqlite",
    db_ready: true,
    auth_required: true,
    dev_auth_bypass: false,
    setup_required: false,
    mutations_enabled: false,
    timezone: "UTC",
    auto_update_scheduler_enabled: false,
    static_spa_available: true,
    warnings: [],
    ...overrides,
  };
}

export function settingsResponse(
  overrides: Partial<SettingsResponse> = {},
): SettingsResponse {
  return {
    updater: [
      {
        name: "DOCKER_BASE",
        value: "/srv/docker",
        default_value: "/srv/docker",
        configured: true,
        source: "configured",
      },
      {
        name: "HOST_DOCKER_BASE",
        value: "/srv/docker",
        default_value: "",
        configured: true,
        source: "configured",
      },
      {
        name: "WUD_OUT_FILE",
        value: "/out/images.todo",
        default_value: "/srv/docker/wud/out/images.todo",
        configured: true,
        source: "configured",
      },
      {
        name: "WUD_LOG_DIR",
        value: "/logs",
        default_value: "./logs",
        configured: true,
        source: "configured",
      },
      {
        name: "WUD_DB_PATH",
        value: "/logs/wud-updater.sqlite",
        default_value: "/logs/wud-updater.sqlite",
        configured: true,
        source: "configured",
      },
      {
        name: "WUD_UPDATE_MODE",
        value: "stop",
        default_value: "stop",
        configured: false,
        source: "default",
      },
      {
        name: "WUD_MAX_WAIT",
        value: "180",
        default_value: "180",
        configured: false,
        source: "default",
      },
      {
        name: "WUD_LOCK_TIMEOUT",
        value: "30",
        default_value: "30",
        configured: false,
        source: "default",
      },
      {
        name: "WUD_TIMEZONE",
        value: "UTC",
        default_value: "UTC",
        configured: false,
        source: "default",
      },
    ],
    webui: [
      {
        name: "WUD_WEB_AUTH_REQUIRED",
        value: "true",
        default_value: "true",
        configured: false,
        source: "derived",
      },
      {
        name: "WUD_WEB_DEV_NO_AUTH",
        value: "false",
        default_value: "false",
        configured: false,
        source: "default",
      },
      {
        name: "WUD_WEB_PUBLIC_ORIGIN",
        value: "https://wud.example.test",
        default_value: "",
        configured: true,
        source: "configured",
      },
      {
        name: "WUD_WEB_ALLOWED_HOSTS",
        value: "127.0.0.1, localhost, wud.example.test",
        default_value: "127.0.0.1, localhost, wud.example.test",
        configured: false,
        source: "derived",
      },
      {
        name: "WUD_WEB_SECURE_COOKIES_EFFECTIVE",
        value: "true",
        default_value: "true",
        configured: false,
        source: "request",
      },
      {
        name: "WUD_WEB_MUTATIONS_ENABLED",
        value: "false",
        default_value: "false",
        configured: false,
        source: "default",
      },
      {
        name: "WUD_WEB_RESTART_CONTAINER",
        value: "wud-updater",
        default_value: "",
        configured: false,
        source: "derived",
      },
    ],
    secrets: [
      { name: "WUD_WEB_TOKEN", configured: false },
      { name: "GITHUB_TOKEN", configured: true },
      { name: "DISCORD_RELEASES_WEBHOOK", configured: false },
    ],
    ...overrides,
  };
}

export function doctorResponse(
  overrides: Partial<DoctorResponse> = {},
): DoctorResponse {
  return {
    ok: false,
    failures: 1,
    warnings: 1,
    checks: [
      {
        status: "FAIL",
        code: "docker-daemon-info",
        category: "docker",
        name: "Docker daemon info",
        detail: "exit 17: permission denied",
        target: "",
        suggestions: [
          {
            label: "Wire Docker access",
            description: "Mount the Docker socket or configure DOCKER_HOST.",
            snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
          },
        ],
      },
      {
        status: "WARN",
        code: "webui-public-origin",
        category: "webui",
        name: "WebUI public origin",
        detail: "derived from request as http://testserver",
        target: "",
        suggestions: [],
      },
      {
        status: "PASS",
        code: "webui-database",
        category: "webui",
        name: "WebUI database",
        detail: "/logs/wud-updater.sqlite",
        target: "",
        suggestions: [],
      },
    ],
    ...overrides,
  };
}

export function onboardingChecklistResponse(
  overrides: Partial<OnboardingChecklistResponse> = {},
): OnboardingChecklistResponse {
  return {
    dismissed: false,
    dismissed_at: "",
    all_passed: false,
    visible: true,
    items: [
      {
        key: "admin-setup",
        title: "Admin setup",
        status: "PASS",
        detail: "The first admin account exists.",
        check_codes: ["webui-authentication"],
        suggestions: [],
        docs: [
          {
            label: "First login",
            url: "https://github.com/magrhino/WUD-Updater/blob/main/docs/wiki/webui-container.md#first-login",
          },
        ],
      },
      {
        key: "docker-access",
        title: "Docker daemon access",
        status: "FAIL",
        detail: "Docker daemon info: permission denied",
        check_codes: ["docker-daemon-info"],
        suggestions: [
          {
            label: "Wire Docker access",
            description: "Mount the Docker socket or configure DOCKER_HOST.",
            snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
          },
        ],
        docs: [],
      },
      {
        key: "mutation-mode",
        title: "Browser mutation mode",
        status: "PASS",
        detail: "Browser apply controls are disabled server-side.",
        check_codes: ["webui-mutation-gate"],
        suggestions: [],
        docs: [],
      },
    ],
    ...overrides,
  };
}

export function onboardingDismissResponse(
  overrides: Partial<OnboardingDismissResponse> = {},
): OnboardingDismissResponse {
  return {
    dismissed: true,
    dismissed_at: "2026-05-31T00:00:00+00:00",
    ...overrides,
  };
}

export function pendingItem(overrides: Partial<PendingItem> = {}): PendingItem {
  return {
    line_no: 1,
    raw: "repo/app:1.0 sha256=abc",
    image: "repo/app:1.0",
    key: "repo/app",
    repo: "repo/app",
    current_tag: "1.0",
    has_tag: true,
    allow_repo: false,
    digest: "sha256:abc",
    desired_tag: "1.1",
    ...overrides,
  };
}

export function pendingGroupedItem(
  overrides: Partial<PendingGroupedItem> = {},
): PendingGroupedItem {
  const item = pendingItem(overrides);
  return {
    ...item,
    resolved_image: item.image,
    target_image: item.desired_tag ? `${item.repo}:${item.desired_tag}` : item.image,
    compose_images: [item.image],
    services: ["app"],
    action: item.desired_tag ? "tag-update" : "update",
    diagnostic: null,
    ...overrides,
  };
}

export function pendingGrouping(
  items = [pendingGroupedItem()],
): PendingGrouping {
  return {
    status: "ready",
    groups:
      items.length > 0
        ? [
            {
              name: "media",
              directory: "/docker/media",
              compose_file: "docker-compose.yml",
              project_directory: "/docker/media",
              services_label: "app",
              services: ["app"],
              line_numbers: items.map((item) => item.line_no),
              items,
            },
          ]
        : [],
    unmatched: [],
    warnings: [],
  };
}

export function pendingResponse(items = [pendingItem()]): PendingResponse {
  const groupedItems = items.map((item) => pendingGroupedItem(item));
  return {
    source_file: "/out/images.todo",
    exists: true,
    count: items.length,
    items,
    grouping: pendingGrouping(groupedItems),
    warnings: [],
  };
}

export function releaseNoteInfo(
  overrides: Partial<ReleaseNoteInfo> = {},
): ReleaseNoteInfo {
  return {
    line_no: 1,
    status: "ready",
    provider: "github",
    image_repo: "acme/app",
    upstream_repo: "acme/app",
    release_tag: "v2.0.0",
    title: "v2.0.0",
    published_at: "2026-01-02T00:00:00Z",
    breaking: false,
    breaking_reasons: [],
    links: [
      {
        label: "GitHub release",
        url: "https://github.com/acme/app/releases/tag/v2.0.0",
        kind: "github_release",
      },
    ],
    refreshed_at: "2026-01-02T00:00:00Z",
    error: "",
    ...overrides,
  };
}

export function releaseNotesResponse(
  items = [releaseNoteInfo()],
): ReleaseNotesResponse {
  return {
    source_file: "/out/images.todo",
    count: items.length,
    items,
    warnings: [],
  };
}

export function planResponse(overrides: Partial<PlanResponse> = {}): PlanResponse {
  return {
    plan_id: "plan-test",
    dry_run: true,
    can_apply: true,
    status: "ready",
    source_file: "/out/images.todo",
    mode: "stop",
    max_wait: 120,
    selected_line_numbers: [1],
    summary: {
      target_count: 1,
      matched_target_count: 1,
      stack_count: 1,
      service_count: 1,
      skipped_count: 0,
      issue_count: 0,
    },
    targets: [],
    stacks: [
      {
        name: "media",
        directory: "/docker/media",
        compose_file: "docker-compose.yml",
        project_directory: "/docker/media",
        services_label: "app",
        services: ["app"],
        pull_services: ["app"],
        stop_services: ["app"],
        force_recreate: false,
        up_no_deps: true,
        tag_updates: [],
        actions: [{ kind: "pull", description: "pull app", cwd: "/docker/media", args: ["docker", "compose", "pull", "app"] }],
        lines: [
          {
            line_no: 1,
            raw: "repo/app:1.0",
            image: "repo/app:1.0",
            resolved_image: "repo/app:1.0",
            compose_image: "repo/app:1.0",
            target_image: "repo/app:1.1",
            service: "app",
            digest: "",
            desired_tag: "1.1",
            action: "update",
          },
        ],
      },
    ],
    skipped: [],
    issues: [],
    cleanup: {
      cleanup_id: "",
      can_remove_unmatched: false,
      items: [],
    },
    ...overrides,
  };
}

export function applyJobResponse(
  overrides: Partial<ApplyJobResponse> = {},
): ApplyJobResponse {
  return {
    job_id: "job-test",
    status: "queued",
    run_id: null,
    log_file: "",
    started_at: null,
    finished_at: null,
    error: "",
    selected_line_numbers: [1],
    ...overrides,
  };
}

export function applyJobLogResponse(
  overrides: Partial<ApplyJobLogResponse> = {},
): ApplyJobLogResponse {
  return {
    job_id: "job-test",
    log_file: "/out/logs/job-test.log",
    exists: true,
    content: "[2026-05-28T12:00:00+00:00] [INFO] docker-update-from-wud-v2\n",
    truncated: false,
    max_bytes: 65_536,
    error: "",
    ...overrides,
  };
}

export function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 1,
    started_at: "2026-05-28T12:00:00+00:00",
    finished_at: null,
    status: "success",
    dry_run: true,
    mode: "stop",
    wud_file: "/out/images.todo",
    log_file: "",
    metadata: {},
    ...overrides,
  };
}

export function servicePolicy(
  overrides: Partial<ServicePolicyRecord> = {},
): ServicePolicyRecord {
  return {
    service_key: "media/app",
    update_mode: "stop",
    auto_update: true,
    snooze_default_seconds: null,
    auto_update_time: "09:30",
    auto_update_days: ["mon", "wed"],
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: {},
    ...overrides,
  };
}

export function snooze(overrides: Partial<SnoozeRecord> = {}): SnoozeRecord {
  return {
    id: 1,
    service_key: "media/app",
    snoozed_until: "2026-05-29T12:00:00+00:00",
    reason: "maintenance",
    created_at: "2026-05-28T12:00:00+00:00",
    active: true,
    metadata: {},
    ...overrides,
  };
}

export function tagExclusion(
  overrides: Partial<TagExclusionRuleRecord> = {},
): TagExclusionRuleRecord {
  return {
    id: 1,
    scope: "image_repo",
    image_repo: "repo/app",
    service_key: "",
    match_type: "exact",
    tag: "2.0",
    regex_fragment: "",
    status: "active",
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: {},
    ...overrides,
  };
}

export function stateOperationResponse(
  overrides: Partial<StateOperationResponse> = {},
): StateOperationResponse {
  return {
    operation: "upsert_service_policy",
    status: "success",
    audit_run_id: 10,
    resource_type: "service_policy",
    resource_id: "media/app",
    resource: servicePolicy(),
    ...overrides,
  };
}
