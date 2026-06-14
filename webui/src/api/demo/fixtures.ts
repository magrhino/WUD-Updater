import type {
  DigestTagProvenance,
  PendingGroupedItem,
  PendingUpdateRecord,
  ReleaseNoteInfo,
  RetagTargetItem,
  RunEventRecord,
  RunSummary,
  ServicePolicyRecord,
  SnoozeRecord,
  TagExclusionRuleRecord,
  UpdateTargetItem,
} from "../types";
import {
  DEMO_DOCKER_BASE,
  DEMO_LOG_DIR,
  DEMO_POSTGRES_DIGEST,
  DEMO_SOURCE_FILE,
} from "./constants";
import type { DemoPendingItem, DemoRunFixture, DemoStack, DemoStackName } from "./types";

export const DEMO_STACKS: Record<DemoStackName, DemoStack> = {
  data: {
    name: "data",
    servicesLabel: "postgres",
    services: ["postgres"],
  },
  home: {
    name: "home",
    servicesLabel: "home-assistant",
    services: ["home-assistant"],
  },
  media: {
    name: "media",
    servicesLabel: "radarr, wud-updater",
    services: ["radarr", "wud-updater"],
  },
};

const STALE_PENDING_PREFLIGHT_FINDINGS = [
  "No discovered Compose service matched this pending line.",
  "No running Docker container matched this pending line.",
];
const STALE_PENDING_POSSIBLE_REASONS = [
  "The Compose service was removed or renamed.",
  "The Compose image name changed.",
  "The update tag was already applied and WUD left the old pending line behind.",
];
const STALE_PENDING_RECOMMENDED_ACTIONS = [
  "Remove the stale WUD line when the service is intentionally gone or already updated.",
  "If the service should still be managed, update the WUD line or stack image to the current service/image name.",
];

export const GENERIC_UNMATCHED_DIAGNOSTIC: NonNullable<PendingGroupedItem["diagnostic"]> = {
  code: "unmatched",
  message: "This pending update no longer matches any discovered Compose service.",
  hint: "Preflight did not find a matching Compose service or running Docker container. Likely causes are service removal, image rename, or a tag that was already applied.",
  stack: "",
  service: "",
  compose_file: "",
  found_files: [],
  details: {
    preflight_findings: STALE_PENDING_PREFLIGHT_FINDINGS,
    possible_reasons: STALE_PENDING_POSSIBLE_REASONS,
    recommended_actions: STALE_PENDING_RECOMMENDED_ACTIONS,
  },
};

export const DEMO_POSTGRES_DIGEST_PROVENANCE: DigestTagProvenance = {
  source_image: "postgres:16",
  resolved_tag: "16",
  watch_tag: "16",
  target_digest: DEMO_POSTGRES_DIGEST,
  final_image: `postgres@${DEMO_POSTGRES_DIGEST}`,
  provenance_source: "compose",
  provenance_confidence: "recovered",
};

export const INITIAL_PENDING: DemoPendingItem[] = [
  {
    line_no: 2,
    raw: "ghcr.io/home-assistant/home-assistant:2026.5.1 tag=2026.5.3",
    image: "ghcr.io/home-assistant/home-assistant:2026.5.1",
    key: "home-assistant/home-assistant:2026.5.1",
    repo: "home-assistant/home-assistant",
    current_tag: "2026.5.1",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "2026.5.3",
    resolved_image: "ghcr.io/home-assistant/home-assistant:2026.5.1",
    target_image: "ghcr.io/home-assistant/home-assistant:2026.5.3",
    compose_images: ["ghcr.io/home-assistant/home-assistant:2026.5.1"],
    services: ["home-assistant"],
    action: "tag-update",
    diagnostic: null,
    stack: "home",
    service: "home-assistant",
  },
  {
    line_no: 3,
    raw: "lscr.io/linuxserver/radarr:5.21.1 tag=5.22.4",
    image: "lscr.io/linuxserver/radarr:5.21.1",
    key: "linuxserver/radarr:5.21.1",
    repo: "linuxserver/radarr",
    current_tag: "5.21.1",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "5.22.4",
    resolved_image: "lscr.io/linuxserver/radarr:5.21.1",
    target_image: "lscr.io/linuxserver/radarr:5.22.4",
    compose_images: ["lscr.io/linuxserver/radarr:5.21.1"],
    services: ["radarr"],
    action: "tag-update",
    diagnostic: null,
    stack: "media",
    service: "radarr",
  },
  {
    line_no: 4,
    raw: `postgres:16@${DEMO_POSTGRES_DIGEST}`,
    image: `postgres:16@${DEMO_POSTGRES_DIGEST}`,
    key: "postgres:16",
    repo: "postgres",
    current_tag: "16",
    has_tag: true,
    allow_repo: false,
    digest: DEMO_POSTGRES_DIGEST,
    desired_tag: "",
    resolved_image: `postgres:16@${DEMO_POSTGRES_DIGEST}`,
    target_image: DEMO_POSTGRES_DIGEST_PROVENANCE.final_image,
    compose_images: ["postgres:16"],
    services: ["postgres"],
    action: "recreate_stack",
    diagnostic: null,
    digest_provenance: DEMO_POSTGRES_DIGEST_PROVENANCE,
    stack: "data",
    service: "postgres",
  },
  {
    line_no: 5,
    raw: "ghcr.io/magrhino/wud-updater:latest tag=v0.25.1",
    image: "ghcr.io/magrhino/wud-updater:latest",
    key: "magrhino/wud-updater:latest",
    repo: "magrhino/wud-updater",
    current_tag: "latest",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "v0.25.1",
    resolved_image: "ghcr.io/magrhino/wud-updater:latest",
    target_image: "ghcr.io/magrhino/wud-updater:v0.25.1",
    compose_images: ["ghcr.io/magrhino/wud-updater:latest"],
    services: ["wud-updater"],
    action: "tag-update",
    diagnostic: null,
    stack: "media",
    service: "wud-updater",
  },
  {
    line_no: 6,
    raw: "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
    image: "ghcr.io/gethomepage/homepage:v0.9.12",
    key: "gethomepage/homepage:v0.9.12",
    repo: "gethomepage/homepage",
    current_tag: "v0.9.12",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "v0.10.9",
    resolved_image: "ghcr.io/gethomepage/homepage:v0.9.12",
    target_image: "ghcr.io/gethomepage/homepage:v0.10.9",
    compose_images: [],
    services: [],
    action: "unmatched",
    diagnostic: { ...GENERIC_UNMATCHED_DIAGNOSTIC },
    stack: "",
    service: "homepage",
  },
  {
    line_no: 7,
    raw: "vaultwarden/server:1.31.0 tag=1.32.0",
    image: "vaultwarden/server:1.31.0",
    key: "vaultwarden/server:1.31.0",
    repo: "vaultwarden/server",
    current_tag: "1.31.0",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "1.32.0",
    resolved_image: "vaultwarden/server:1.31.0",
    target_image: "vaultwarden/server:1.32.0",
    compose_images: [],
    services: [],
    action: "unmatched",
    diagnostic: { ...GENERIC_UNMATCHED_DIAGNOSTIC },
    stack: "",
    service: "vaultwarden",
  },
  {
    line_no: 8,
    raw: "containrrr/watchtower:1.7.1 tag=1.7.2",
    image: "containrrr/watchtower:1.7.1",
    key: "containrrr/watchtower:1.7.1",
    repo: "containrrr/watchtower",
    current_tag: "1.7.1",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "1.7.2",
    resolved_image: "containrrr/watchtower:1.7.1",
    target_image: "containrrr/watchtower:1.7.2",
    compose_images: [],
    services: [],
    action: "unmatched",
    diagnostic: { ...GENERIC_UNMATCHED_DIAGNOSTIC },
    stack: "",
    service: "watchtower",
  },
];

export const INITIAL_POLICIES: ServicePolicyRecord[] = [
  {
    service_key: "home/home-assistant",
    update_mode: "live",
    auto_update: true,
    snooze_default_seconds: null,
    auto_update_time: "03:30",
    auto_update_days: ["mon", "wed", "fri"],
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: { source: "demo" },
  },
  {
    service_key: "media/radarr",
    update_mode: "stop",
    auto_update: false,
    snooze_default_seconds: 86_400,
    auto_update_time: null,
    auto_update_days: [],
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: { source: "demo" },
  },
];

export const INITIAL_SNOOZES: SnoozeRecord[] = [
  {
    id: 1,
    service_key: "media/radarr",
    snoozed_until: "2099-01-01T00:00:00+00:00",
    reason: "demo maintenance window",
    created_at: "2026-05-28T12:00:00+00:00",
    active: true,
    metadata: { source: "demo" },
  },
  {
    id: 2,
    service_key: "data/postgres",
    snoozed_until: "2020-01-01T00:00:00+00:00",
    reason: "expired demo snooze",
    created_at: "2020-01-01T00:00:00+00:00",
    active: false,
    metadata: { source: "demo" },
  },
];

export const INITIAL_TAG_EXCLUSIONS: TagExclusionRuleRecord[] = [
  {
    id: 1,
    scope: "image_repo",
    image_repo: "home-assistant/home-assistant",
    service_key: "",
    match_type: "exact",
    tag: "2026.5.3",
    regex_fragment: String.raw`2026\.5\.3`,
    status: "active",
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: { source: "demo" },
  },
  {
    id: 2,
    scope: "service",
    image_repo: "linuxserver/radarr",
    service_key: "media/radarr",
    match_type: "exact",
    tag: "5.22.4",
    regex_fragment: String.raw`5\.22\.4`,
    status: "disabled",
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: { source: "demo" },
  },
];

export const DEMO_UPDATE_TARGETS: UpdateTargetItem[] = [
  {
    service_key: "data/postgres",
    stack: "data",
    service: "postgres",
    image: "postgres:16",
    image_repo: "postgres",
    current_tag: "16",
    directory: `${DEMO_DOCKER_BASE}/data`,
    compose_file: "docker-compose.yml",
    project_directory: "",
  },
  {
    service_key: "home/home-assistant",
    stack: "home",
    service: "home-assistant",
    image: "ghcr.io/home-assistant/home-assistant:2026.5.1",
    image_repo: "home-assistant/home-assistant",
    current_tag: "2026.5.1",
    directory: `${DEMO_DOCKER_BASE}/home`,
    compose_file: "docker-compose.yml",
    project_directory: "",
  },
  {
    service_key: "media/radarr",
    stack: "media",
    service: "radarr",
    image: "lscr.io/linuxserver/radarr:5.21.1",
    image_repo: "linuxserver/radarr",
    current_tag: "5.21.1",
    directory: `${DEMO_DOCKER_BASE}/media`,
    compose_file: "docker-compose.yml",
    project_directory: "",
  },
  {
    service_key: "media/wud-updater",
    stack: "media",
    service: "wud-updater",
    image: "ghcr.io/magrhino/wud-updater:latest",
    image_repo: "magrhino/wud-updater",
    current_tag: "latest",
    directory: `${DEMO_DOCKER_BASE}/media`,
    compose_file: "docker-compose.yml",
    project_directory: "",
  },
];

export const DEMO_RETAG_TARGETS: RetagTargetItem[] = [
  {
    service_key: "media/wud-updater",
    stack: "media",
    service: "wud-updater",
    image: "ghcr.io/magrhino/wud-updater:latest",
    image_repo: "magrhino/wud-updater",
    current_tag: "latest",
    tracking_tag: "latest",
    tracking_tag_source: "label",
    proposed_tag: "v0.26.0",
    final_image: `ghcr.io/magrhino/wud-updater@${DEMO_POSTGRES_DIGEST}`,
    retag_available: true,
    retag_reason: "eligible",
    choices: ["keep-current", "switch-to-concrete"],
    label_key: "wud.tag.include",
    label_value: "^latest$$",
    directory: `${DEMO_DOCKER_BASE}/media`,
    compose_file: "docker-compose.yml",
    project_directory: "",
    digest_provenance: {
      source_image: "ghcr.io/magrhino/wud-updater:latest",
      resolved_tag: "v0.26.0",
      watch_tag: "latest",
      target_digest: DEMO_POSTGRES_DIGEST,
      final_image: `ghcr.io/magrhino/wud-updater@${DEMO_POSTGRES_DIGEST}`,
      provenance_source: "demo",
      provenance_confidence: "high",
    },
  },
  {
    service_key: "home/home-assistant",
    stack: "home",
    service: "home-assistant",
    image: "ghcr.io/home-assistant/home-assistant:latest",
    image_repo: "home-assistant/home-assistant",
    current_tag: "latest",
    tracking_tag: "latest",
    tracking_tag_source: "image",
    proposed_tag: "",
    final_image: "",
    retag_available: false,
    retag_reason: "missing-provenance",
    choices: ["keep-current"],
    label_key: "wud.tag.include",
    label_value: "",
    directory: `${DEMO_DOCKER_BASE}/home`,
    compose_file: "docker-compose.yml",
    project_directory: "",
    digest_provenance: null,
  },
  {
    service_key: "data/postgres",
    stack: "data",
    service: "postgres",
    image: "postgres:16",
    image_repo: "postgres",
    current_tag: "16",
    tracking_tag: "16",
    tracking_tag_source: "label",
    proposed_tag: "",
    final_image: "",
    retag_available: false,
    retag_reason: "not-latest-tracking",
    choices: ["keep-current"],
    label_key: "wud.tag.include",
    label_value: "16",
    directory: `${DEMO_DOCKER_BASE}/data`,
    compose_file: "docker-compose.yml",
    project_directory: "",
    digest_provenance: null,
  },
  {
    service_key: "media/radarr",
    stack: "media",
    service: "radarr",
    image: "lscr.io/linuxserver/radarr:latest",
    image_repo: "linuxserver/radarr",
    current_tag: "latest",
    tracking_tag: "latest",
    tracking_tag_source: "label",
    proposed_tag: "5.22.4",
    final_image: `lscr.io/linuxserver/radarr@${DEMO_POSTGRES_DIGEST}`,
    retag_available: false,
    retag_reason: "stale-provenance",
    choices: ["keep-current"],
    label_key: "wud.tag.include",
    label_value: "latest",
    directory: `${DEMO_DOCKER_BASE}/media`,
    compose_file: "docker-compose.yml",
    project_directory: "",
    digest_provenance: {
      source_image: "lscr.io/linuxserver/radarr:latest",
      resolved_tag: "5.22.4",
      watch_tag: "latest",
      target_digest: DEMO_POSTGRES_DIGEST,
      final_image: `lscr.io/linuxserver/radarr@${DEMO_POSTGRES_DIGEST}`,
      provenance_source: "demo",
      provenance_confidence: "stale",
    },
  },
];

export const INITIAL_RELEASE_NOTES: ReleaseNoteInfo[] = [
  releaseNote({
    line_no: 2,
    image_repo: "home-assistant/home-assistant",
    upstream_repo: "home-assistant/core",
    release_tag: "2026.5.3",
    title: "Home Assistant Core 2026.5.3",
    url: "https://github.com/home-assistant/core/releases/tag/2026.5.3",
  }),
  releaseNote({
    line_no: 3,
    image_repo: "linuxserver/radarr",
    upstream_repo: "Radarr/Radarr",
    release_tag: "v5.22.4",
    title: "Radarr v5.22.4",
    url: "https://github.com/Radarr/Radarr/releases/tag/v5.22.4",
  }),
  releaseNote({
    line_no: 5,
    image_repo: "magrhino/wud-updater",
    upstream_repo: "magrhino/wud-updater",
    release_tag: "v0.25.1",
    title: "WUD-Updater v0.25.1",
    url: "https://github.com/magrhino/wud-updater/releases/tag/v0.25.1",
  }),
];

export const INITIAL_RUNS: DemoRunFixture[] = [
  demoRun({
    id: 6,
    startedAt: "2026-05-30T20:20:00+00:00",
    finishedAt: "2026-05-30T20:20:00+00:00",
    status: "success",
    dryRun: false,
    mode: "web-settings",
    logFile: "",
    summary: "updated WebUI preferences",
    metadata: {
      source: "webui",
      operation: "update_managed_settings",
      actor_type: "browser",
      resource_type: "managed_settings",
      resource_id: "webui_preferences",
      target: { keys: ["theme_preference"] },
    },
    logContent: "",
    pending: [],
    events: [
      runEvent(60, 6, "settings", "webui", "managed-settings", "webui-preferences", "success"),
    ],
  }),
  demoRun({
    id: 5,
    startedAt: "2026-05-30T19:50:00+00:00",
    finishedAt: "2026-05-30T19:50:00+00:00",
    status: "success",
    dryRun: false,
    mode: "web-state",
    logFile: "",
    summary: "saved service policy",
    metadata: {
      source: "webui",
      operation: "upsert_service_policy",
      actor_type: "browser",
      resource_type: "service_policy",
      resource_id: "media/radarr",
      service_key: "media/radarr",
      target: { service_key: "media/radarr" },
    },
    logContent: "",
    pending: [],
    events: [
      runEvent(50, 5, "radarr", "media", "service-policy", "media/radarr", "success"),
    ],
  }),
  demoRun({
    id: 4,
    startedAt: "2026-05-30T19:20:00+00:00",
    finishedAt: "2026-05-30T19:20:00+00:00",
    status: "success",
    dryRun: false,
    mode: "web-auth",
    logFile: "",
    summary: "reset admin credentials",
    metadata: {
      source: "webui",
      operation: "reset_admin_password",
      actor_type: "reset_claim",
      resource_type: "web_user",
      resource_id: "admin",
      target: { username: "admin" },
    },
    logContent: "",
    pending: [],
    events: [
      runEvent(40, 4, "admin", "webui", "web_user", "admin", "success"),
    ],
  }),
  demoRun({
    id: 3,
    startedAt: "2026-05-27T22:45:00+00:00",
    finishedAt: "2026-05-27T22:45:12+00:00",
    status: "success",
    dryRun: true,
    mode: "live",
    logFile: `${DEMO_LOG_DIR}/demo-dry-run.log`,
    summary: "dry-run plan",
    logContent: `[2026-05-27T22:45:00+00:00] docker-update-from-wud-v2
[2026-05-27T22:45:01+00:00] Dry-run: would update edge/nginx from nginx:1.25 to nginx:1.27.
[2026-05-27T22:45:12+00:00] Dry-run completed without mutation.
`,
    pending: [
      pendingRecord(1, 3, "nginx:1.25 tag=1.27", "edge/nginx", "planned"),
    ],
    events: [],
  }),
  demoRun({
    id: 2,
    startedAt: "2026-05-28T10:04:00+00:00",
    finishedAt: "2026-05-28T10:05:09+00:00",
    status: "failed",
    dryRun: false,
    mode: "pause",
    logFile: `${DEMO_LOG_DIR}/demo-failed.log`,
    summary: "health check failed",
    logContent: `[2026-05-28T10:04:00+00:00] docker-update-from-wud-v2
[2026-05-28T10:04:06+00:00] [apps/api] Pull complete.
[2026-05-28T10:04:32+00:00] [apps/api] Container recreated.
[2026-05-28T10:05:09+00:00] [apps/api] Health check timed out; leaving WUD line pending.
`,
    pending: [
      pendingRecord(1, 2, "ghcr.io/example/api:2.8.0 tag=2.9.0", "apps/api", "failed"),
    ],
    events: [
      runEvent(20, 2, "api", "apps", "ghcr.io/example/api:2.8.0", "ghcr.io/example/api:2.9.0", "failed"),
    ],
  }),
  demoRun({
    id: 1,
    startedAt: "2026-05-28T12:12:00+00:00",
    finishedAt: "2026-05-28T12:13:41+00:00",
    status: "success",
    dryRun: false,
    mode: "stop",
    logFile: `${DEMO_LOG_DIR}/demo-success.log`,
    summary: "updated two services",
    logContent: `[2026-05-28T12:12:00+00:00] docker-update-from-wud-v2
[2026-05-28T12:12:02+00:00] Found 2 matching services.
[2026-05-28T12:12:38+00:00] [media/sonarr] Recreated container and health check passed.
[2026-05-28T12:13:40+00:00] [infra/redis] Recreated container and health check passed.
[2026-05-28T12:13:41+00:00] Done.
`,
    pending: [
      pendingRecord(1, 1, "lscr.io/linuxserver/sonarr:4.0.14 tag=4.0.15", "media/sonarr", "success"),
      pendingRecord(2, 1, "redis:7.2 tag=7.4", "infra/redis", "success"),
    ],
    events: [
      runEvent(10, 1, "sonarr", "media", "lscr.io/linuxserver/sonarr:4.0.14", "lscr.io/linuxserver/sonarr:4.0.15", "success"),
      runEvent(11, 1, "redis", "infra", "redis:7.2", "redis:7.4", "success"),
    ],
  }),
];

function demoRun(options: {
  id: number;
  startedAt: string;
  finishedAt: string;
  status: string;
  dryRun: boolean;
  mode: string;
  logFile: string;
  summary: string;
  logContent: string;
  pending: ReturnType<typeof pendingRecord>[];
  events: RunEventRecord[];
  metadata?: Record<string, unknown>;
}): DemoRunFixture {
  const summary: RunSummary = {
    id: options.id,
    started_at: options.startedAt,
    finished_at: options.finishedAt,
    status: options.status,
    dry_run: options.dryRun,
    mode: options.mode,
    wud_file: DEMO_SOURCE_FILE,
    log_file: options.logFile,
    metadata: options.metadata ?? { source: "demo", summary: options.summary },
    events: options.events,
  };
  return {
    summary,
    detail: {
      ...summary,
      pending_updates: options.pending,
      events: options.events,
    },
    log: {
      run_id: options.id,
      log_file: options.logFile,
      exists: true,
      content: options.logContent,
      truncated: false,
      max_bytes: 262_144,
    },
  };
}

export function pendingRecord(
  lineNo: number,
  runId: number,
  raw: string,
  serviceKey: string,
  status: string,
  id = lineNo + runId * 10,
  statusReason = status === "failed"
    ? "container health check timed out"
    : "demo fixture",
  digestProvenance: DigestTagProvenance | null | undefined = null,
): PendingUpdateRecord {
  const [stackName, serviceName] = serviceKey.split("/");
  const image = raw.split(" ")[0] ?? raw;
  const desiredTag = raw.includes(" tag=") ? raw.split(" tag=")[1] ?? "" : "";
  return {
    id,
    run_id: runId,
    line_no: lineNo,
    raw,
    image,
    target_digest: digestProvenance?.target_digest ?? "",
    desired_tag: desiredTag,
    service_key: serviceKey,
    stack_name: stackName ?? "",
    service_name: serviceName ?? "",
    status,
    status_reason: statusReason,
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:01+00:00",
    digest_provenance: digestProvenance ?? null,
    metadata: { source: "demo" },
  };
}

export function runEvent(
  id: number,
  runId: number,
  serviceName: string,
  stackName: string,
  image: string,
  targetImage: string,
  status: string,
  digestProvenance: DigestTagProvenance | null | undefined = null,
): RunEventRecord {
  const oldDigest = digestProvenance ? explicitDigestFromImage(image) : "sha256:demo-old";
  const newDigest = digestProvenance?.target_digest ?? "sha256:demo-new";
  return {
    id,
    run_id: runId,
    created_at: "2026-05-28T12:00:01+00:00",
    service_name: serviceName,
    stack_name: stackName,
    image,
    target_image: targetImage,
    old_image_id: "sha256:demo-old",
    new_image_id: "sha256:demo-new",
    old_digest: oldDigest,
    new_digest: newDigest,
    status,
    digest_provenance: digestProvenance ?? null,
    metadata: { source: "demo" },
  };
}

function explicitDigestFromImage(image: string): string {
  const marker = "@sha256:";
  const markerIndex = image.indexOf(marker);
  if (markerIndex === -1) {
    return "";
  }
  return `sha256:${image.slice(markerIndex + marker.length)}`;
}

function releaseNote(options: {
  line_no: number;
  image_repo: string;
  upstream_repo: string;
  release_tag: string;
  title: string;
  url: string;
}): ReleaseNoteInfo {
  return {
    line_no: options.line_no,
    status: "ready",
    provider: "github",
    image_repo: options.image_repo,
    upstream_repo: options.upstream_repo,
    release_tag: options.release_tag,
    title: options.title,
    published_at: "2026-05-28T12:00:00+00:00",
    breaking: false,
    breaking_reasons: [],
    links: [
      {
        label: "GitHub release",
        url: options.url,
        kind: "github_release",
      },
    ],
    refreshed_at: "2026-05-28T12:00:00+00:00",
    error: "",
  };
}
