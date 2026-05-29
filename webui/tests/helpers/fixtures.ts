import type {
  ApplyJobResponse,
  AuthSessionResponse,
  PendingItem,
  PendingResponse,
  PlanResponse,
  ReleaseNoteInfo,
  ReleaseNotesResponse,
  RunSummary,
  ServicePolicyRecord,
  SnoozeRecord,
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

export function pendingResponse(items = [pendingItem()]): PendingResponse {
  return {
    source_file: "/out/images.todo",
    exists: true,
    count: items.length,
    items,
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
