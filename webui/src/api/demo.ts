import type {
  ApplyJobLogResponse,
  ApplyJobProgressEvent,
  ApplyJobResponse,
  AuthSessionResponse,
  ContainerRestartResponse,
  CoreUpdateTourResponse,
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  CsrfResponse,
  DoctorResponse,
  ManagedSettingsUpdateResponse,
  OnboardingChecklistResponse,
  OnboardingDismissResponse,
  PendingGroupedItem,
  PendingCleanupLine,
  PendingCleanupResponse,
  PendingRemovalPlanResponse,
  PendingUpdateRecord,
  PendingResponse,
  PlanCleanupItem,
  PlanLine,
  PlanResponse,
  PlanStack,
  ReleaseNoteInfo,
  ReleaseNotesResponse,
  RunDetail,
  RunEventRecord,
  RunLogResponse,
  RunSummary,
  ServicePolicyRecord,
  SettingsEntrySource,
  SettingsResponse,
  SetupStatusResponse,
  SnoozeRecord,
  SnoozeState,
  StatusResponse,
  StateOperation,
  StateOperationResponse,
  TagExclusionRuleRecord,
  TagExclusionStatusFilter,
  TagOverrideRequest,
  UpdateTargetItem,
  UpdateTargetsResponse,
  WebApi,
} from "./client";

const DEMO_VERSION = "0.25.0";
const DEMO_SOURCE_FILE = "demo/out/images.todo";
const DEMO_DB_PATH = "demo/logs/wud-updater.sqlite";
const DEMO_LOG_DIR = "demo/logs";
const DEMO_DOCKER_BASE = "demo/docker";
const DEMO_CSRF_TOKEN = "demo-csrf-token";

type DemoStackName = "data" | "home" | "media";

type DemoStack = {
  name: DemoStackName;
  servicesLabel: string;
  services: string[];
};

type DemoJobRecord = {
  job: ApplyJobResponse;
  log: ApplyJobLogResponse;
  lineNumbers: number[];
  plan: PlanResponse | null;
  completed: boolean;
};

type DemoRunFixture = {
  summary: RunSummary;
  detail: RunDetail;
  log: RunLogResponse;
};

const DEMO_STACKS: Record<DemoStackName, DemoStack> = {
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

type DemoPendingItem = PendingGroupedItem & {
  stack: DemoStackName | "";
  service: string;
};

const GENERIC_UNMATCHED_DIAGNOSTIC: NonNullable<PendingGroupedItem["diagnostic"]> = {
  code: "unmatched",
  message: "No Compose stack matched this WUD entry.",
  hint: "Confirm this image is still managed by an active Compose stack, or remove the stale WUD entry.",
  stack: "",
  service: "",
  compose_file: "",
  found_files: [],
  details: {},
};

const INITIAL_PENDING: DemoPendingItem[] = [
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
    raw: "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    image:
      "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    key: "postgres:16",
    repo: "postgres",
    current_tag: "16",
    has_tag: true,
    allow_repo: false,
    digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    desired_tag: "",
    resolved_image:
      "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    target_image:
      "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    compose_images: ["postgres:16"],
    services: ["postgres"],
    action: "update",
    diagnostic: null,
    stack: "data",
    service: "postgres",
  },
  {
    line_no: 5,
    raw: "ghcr.io/magrhino/wud-updater:v0.25.0 tag=v0.25.1",
    image: "ghcr.io/magrhino/wud-updater:v0.25.0",
    key: "magrhino/wud-updater:v0.25.0",
    repo: "magrhino/wud-updater",
    current_tag: "v0.25.0",
    has_tag: true,
    allow_repo: false,
    digest: "",
    desired_tag: "v0.25.1",
    resolved_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
    target_image: "ghcr.io/magrhino/wud-updater:v0.25.1",
    compose_images: ["ghcr.io/magrhino/wud-updater:v0.25.0"],
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

const INITIAL_POLICIES: ServicePolicyRecord[] = [
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

const INITIAL_SNOOZES: SnoozeRecord[] = [
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

const INITIAL_TAG_EXCLUSIONS: TagExclusionRuleRecord[] = [
  {
    id: 1,
    scope: "image_repo",
    image_repo: "home-assistant/home-assistant",
    service_key: "",
    match_type: "exact",
    tag: "2026.5.3",
    regex_fragment: "2026\\.5\\.3",
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
    regex_fragment: "5\\.22\\.4",
    status: "disabled",
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: { source: "demo" },
  },
];

const DEMO_UPDATE_TARGETS: UpdateTargetItem[] = [
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
    image: "ghcr.io/magrhino/wud-updater:v0.25.0",
    image_repo: "magrhino/wud-updater",
    current_tag: "v0.25.0",
    directory: `${DEMO_DOCKER_BASE}/media`,
    compose_file: "docker-compose.yml",
    project_directory: "",
  },
];

const INITIAL_RELEASE_NOTES: ReleaseNoteInfo[] = [
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

const INITIAL_RUNS: DemoRunFixture[] = [
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

class DemoApiState {
  pending = clone(INITIAL_PENDING);
  policies = clone(INITIAL_POLICIES);
  snoozes = clone(INITIAL_SNOOZES);
  tagExclusions = clone(INITIAL_TAG_EXCLUSIONS);
  runs = clone(INITIAL_RUNS);
  jobs = new Map<string, DemoJobRecord>();
  themePreference = "system";
  themePreferenceConfigured = false;
  onboardingDismissedAt = "";
  composeIgnorePaths = "old";
  composeIgnorePathsConfigured = false;
  coreUpdateTour: CoreUpdateTourResponse = {
    status: "not_started",
    step: "dashboard",
    updated_at: "",
  };
  nextJob = 1;
  nextRun = 4;
  nextAudit = 100;
  nextSnooze = 3;
  nextTagExclusion = 3;

  session(): AuthSessionResponse {
    return {
      authenticated: true,
      setup_required: false,
      auth_required: false,
      dev_auth_bypass: true,
      mutations_enabled: true,
      username: null,
    };
  }

  setupStatus(): SetupStatusResponse {
    return {
      setup_required: false,
      claim_required: false,
      authenticated: true,
      auth_required: false,
      dev_auth_bypass: true,
      mutations_enabled: true,
      password_min_length: 12,
    };
  }

  status(): StatusResponse {
    return {
      ok: true,
      version: DEMO_VERSION,
      wud_file: DEMO_SOURCE_FILE,
      wud_file_exists: true,
      pending_count: this.pending.length,
      db_path: DEMO_DB_PATH,
      db_ready: true,
      auth_required: false,
      dev_auth_bypass: true,
      setup_required: false,
      mutations_enabled: true,
      timezone: "UTC",
      auto_update_scheduler_enabled: true,
      static_spa_available: true,
      warnings: ["Static demo mode uses in-browser fixture data only."],
    };
  }

  settings(): SettingsResponse {
    return {
      updater: [
        settingEntry("DOCKER_BASE", DEMO_DOCKER_BASE, DEMO_DOCKER_BASE, false),
        settingEntry("HOST_DOCKER_BASE", DEMO_DOCKER_BASE, "", true),
        settingEntry("WUD_OUT_FILE", DEMO_SOURCE_FILE, DEMO_SOURCE_FILE, false),
        settingEntry("WUD_LOG_DIR", DEMO_LOG_DIR, DEMO_LOG_DIR, false),
        settingEntry("WUD_DB_PATH", DEMO_DB_PATH, DEMO_DB_PATH, false),
        settingEntry("WUD_UPDATE_MODE", "stop", "stop", false),
        settingEntry("WUD_MAX_WAIT", "180", "180", false),
        settingEntry("WUD_LOCK_TIMEOUT", "30", "30", false),
        settingEntry("WUD_TIMEZONE", "UTC", "UTC", false),
        settingEntry("WUD_COMPOSE_IGNORE_PATHS", "old", "old", false),
      ],
      webui: [
        settingEntry("WUD_WEB_AUTH_REQUIRED", "false", "true", false, "derived"),
        settingEntry("WUD_WEB_DEV_NO_AUTH", "true", "false", true),
        settingEntry("WUD_WEB_PUBLIC_ORIGIN", "", "", false),
        settingEntry("WUD_WEB_ALLOWED_ORIGINS", "", "", false),
        settingEntry(
          "WUD_WEB_ALLOWED_HOSTS",
          "127.0.0.1, localhost",
          "127.0.0.1, localhost",
          false,
          "derived",
        ),
        settingEntry("WUD_WEB_TRUSTED_PROXIES", "", "", false),
        settingEntry("WUD_WEB_SECURE_COOKIES", "auto", "auto", false),
        settingEntry(
          "WUD_WEB_SECURE_COOKIES_EFFECTIVE",
          "false",
          "false",
          false,
          "request",
        ),
        settingEntry(
          "WUD_WEB_STATIC_SPA_AVAILABLE",
          "true",
          "true",
          false,
          "derived",
        ),
        settingEntry("WUD_WEB_MUTATIONS_ENABLED", "true", "false", true),
        settingEntry(
          "WUD_WEB_RESTART_CONTAINER",
          "demo-wud-updater",
          "",
          false,
          "derived",
        ),
        settingEntry(
          "WUD_WEB_AUTO_UPDATE_SCHEDULER_ENABLED",
          "true",
          "false",
          false,
          "derived",
        ),
      ],
      secrets: [
        { name: "WUD_WEB_TOKEN", configured: false },
        { name: "GITHUB_TOKEN", configured: false },
        { name: "DISCORD_RELEASES_WEBHOOK", configured: false },
        { name: "DISCORD_WEBHOOK", configured: false },
        { name: "ADMIN_WEBHOOK", configured: false },
      ],
      managed: [
        {
          key: "theme_preference",
          value: this.themePreference,
          default_value: "system",
          source: this.themePreferenceConfigured ? "configured" : "default",
          editable: true,
          allowed_values: ["system", "light", "dark"],
          restart_required: false,
          disabled_reason: "",
        },
        {
          key: "onboarding_checklist",
          value: this.onboardingDismissedAt ? "dismissed" : "visible",
          default_value: "visible",
          source: this.onboardingDismissedAt ? "configured" : "default",
          editable: true,
          allowed_values: ["visible", "dismissed"],
          restart_required: false,
          disabled_reason: "",
        },
        {
          key: "compose_ignore_paths",
          value: this.composeIgnorePaths,
          default_value: "old",
          source: this.composeIgnorePathsConfigured ? "configured" : "default",
          editable: true,
          allowed_values: [],
          restart_required: false,
          disabled_reason: "",
        },
      ],
    };
  }

  doctor(): DoctorResponse {
    return {
      ok: true,
      failures: 0,
      warnings: 4,
      checks: [
        doctorCheck("PASS", "docker-cli", "docker", "Docker CLI", "Docker version 28.0.0"),
        doctorCheck(
          "PASS",
          "docker-daemon-info",
          "docker",
          "Docker daemon info",
          "Docker Root Dir: /var/lib/docker",
        ),
        doctorCheck(
          "PASS",
          "compose-discovery",
          "compose",
          "Compose discovery",
          "3 stack(s) rendered",
        ),
        doctorCheck(
          "WARN",
          "webui-authentication",
          "webui",
          "WebUI authentication",
          "static demo mode bypasses authentication",
        ),
        doctorCheck(
          "WARN",
          "webui-public-origin",
          "webui",
          "WebUI public origin",
          "not configured in demo mode",
          {
            label: "Set reverse proxy origin",
            description: "Set this in real reverse-proxy deployments.",
            snippet: "WUD_WEB_PUBLIC_ORIGIN=https://wud.example.test",
          },
        ),
        doctorCheck(
          "WARN",
          "webui-mutation-gate",
          "webui",
          "WebUI mutation gate",
          "demo mode enables in-browser apply fixtures",
        ),
        doctorCheck(
          "WARN",
          "truenas-status-helper",
          "truenas",
          "TrueNAS status helper",
          "TRUENAS_STATUS_CHECK is disabled",
        ),
      ],
    };
  }

  onboardingChecklist(): OnboardingChecklistResponse {
    if (this.onboardingDismissedAt) {
      return {
        dismissed: true,
        dismissed_at: this.onboardingDismissedAt,
        all_passed: false,
        visible: false,
        items: [],
      };
    }
    return {
      dismissed: false,
      dismissed_at: "",
      all_passed: false,
      visible: true,
      items: [
        {
          key: "admin-setup",
          title: "Admin setup",
          status: "WARN",
          detail:
            "Static demo mode bypasses authentication; real deployments create an admin during first run.",
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
          key: "wud-output",
          title: "Shared WUD output file",
          status: "PASS",
          detail:
            "Demo fixture data includes a shared pending-update file path.",
          check_codes: ["wud-out-file"],
          suggestions: [],
          docs: [],
        },
        {
          key: "docker-access",
          title: "Docker daemon access",
          status: "PASS",
          detail: "Demo mode uses sanitized fixture Docker state.",
          check_codes: ["docker-daemon-info"],
          suggestions: [],
          docs: [],
        },
        {
          key: "mutation-mode",
          title: "Browser mutation mode",
          status: "WARN",
          detail:
            "Demo mode enables in-browser apply fixtures; real deployments require server-side enablement.",
          check_codes: ["webui-mutation-gate"],
          suggestions: [
            {
              label: "Return to read-only mode",
              description:
                "Leave browser mutations disabled unless this deployment is intentionally allowed to apply updates.",
              snippet: "WUD_WEB_MUTATIONS_ENABLED=false",
            },
          ],
          docs: [
            {
              label: "Read-only and mutations",
              url: "https://github.com/magrhino/WUD-Updater/blob/main/docs/wiki/webui-container.md#read-only-and-mutations",
            },
          ],
        },
      ],
    };
  }

  dismissOnboarding(): OnboardingDismissResponse {
    this.onboardingDismissedAt = new Date("2026-05-31T00:00:00.000Z").toISOString();
    return {
      dismissed: true,
      dismissed_at: this.onboardingDismissedAt,
    };
  }

  updateCoreUpdateTour(
    status: CoreUpdateTourStatus,
    step: CoreUpdateTourStep,
  ): CoreUpdateTourResponse {
    this.coreUpdateTour = {
      status,
      step,
      updated_at: new Date("2026-05-31T00:00:00.000Z").toISOString(),
    };
    return this.coreUpdateTour;
  }

  updateManagedSettings(
    values: Record<string, string>,
  ): ManagedSettingsUpdateResponse {
    for (const [key, value] of Object.entries(values)) {
      if (key === "theme_preference") {
        if (!["system", "light", "dark"].includes(value)) {
          throw new Error("theme_preference must be system, light, or dark");
        }
        this.themePreference = value;
        this.themePreferenceConfigured = true;
      } else if (key === "onboarding_checklist") {
        if (!["visible", "dismissed"].includes(value)) {
          throw new Error("onboarding_checklist must be visible or dismissed");
        }
        this.onboardingDismissedAt =
          value === "dismissed"
            ? this.onboardingDismissedAt ||
              new Date("2026-05-31T00:00:00.000Z").toISOString()
            : "";
      } else if (key === "compose_ignore_paths") {
        this.composeIgnorePaths = normalizeDemoComposeIgnorePaths(value);
        this.composeIgnorePathsConfigured = true;
      } else {
        throw new Error(`managed setting is not editable: ${key}`);
      }
    }
    return {
      managed: this.settings().managed,
      audit_run_id: this.nextAudit++,
    };
  }

  pendingResponse(): PendingResponse {
    return {
      source_file: DEMO_SOURCE_FILE,
      exists: true,
      count: this.pending.length,
      items: this.pending.map(stripDemoFields),
      grouping: {
        status: "ready",
        groups: (Object.keys(DEMO_STACKS) as DemoStackName[])
          .map((name) => this.stackGroup(name))
          .filter((group) => group.items.length > 0),
        unmatched: this.pending
          .filter(isUnmatchedDemoItem)
          .map(stripDemoFields),
        warnings: [],
      },
      warnings: [],
    };
  }

  updateTargets(): UpdateTargetsResponse {
    return {
      status: "ready",
      count: DEMO_UPDATE_TARGETS.length,
      items: clone(DEMO_UPDATE_TARGETS),
      warnings: [],
    };
  }

  releaseNotes(): ReleaseNotesResponse {
    const activeLines = new Set(this.pending.map((item) => item.line_no));
    const items = INITIAL_RELEASE_NOTES.filter((item) => activeLines.has(item.line_no));
    return {
      source_file: DEMO_SOURCE_FILE,
      count: items.length,
      items: clone(items),
      warnings: [],
    };
  }

  createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
  ): PlanResponse {
    const requested = new Set(lineNumbers);
    const selected = this.pending
      .filter((item) => requested.has(item.line_no))
      .map((item) => applyTagOverride(item, tagOverrides));
    const matchedSelected = selected.filter(isMatchedDemoItem);
    const unmatchedSelected = selected.filter(isUnmatchedDemoItem);
    const tagUpdateCount = matchedSelected.filter(
      (item) => item.action === "tag-update",
    ).length;
    const blockedTagUpdates = tagUpdateCount > 0 && !allowTagUpdates;
    const unmatchedIssues = unmatchedSelected.map((item) => unmatchedIssue(item));
    const stacks = (Object.keys(DEMO_STACKS) as DemoStackName[])
      .map((name) => planStack(name, matchedSelected))
      .filter((stack) => stack.lines.length > 0);
    const issues = [
      ...unmatchedIssues,
      ...(blockedTagUpdates
        ? [
            {
              severity: "error",
              code: "tag_updates_disabled",
              message: "Tag rewrites must be confirmed before applying this demo plan.",
              line_no: null,
              stack: "",
              service: "",
              hint: "",
              details: {},
            },
          ]
        : []),
    ];
    const cleanupItems = unmatchedSelected.map(planCleanupItem);

    return {
      plan_id: `demo-plan-${Date.now()}`,
      dry_run: true,
      can_apply: matchedSelected.length > 0 && issues.length === 0,
      status: selected.length === 0 ? "empty" : issues.length > 0 ? "blocked" : "ready",
      source_file: DEMO_SOURCE_FILE,
      mode: "stop",
      max_wait: 180,
      selected_line_numbers: selected.map((item) => item.line_no),
      summary: {
        target_count: selected.length,
        matched_target_count: matchedSelected.length,
        stack_count: stacks.length,
        service_count: matchedSelected.length,
        skipped_count: unmatchedSelected.length,
        issue_count: issues.length,
      },
      targets: selected.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        resolved_image: item.resolved_image,
        digest: item.digest,
        desired_tag: item.desired_tag,
        matched: isMatchedDemoItem(item),
        action: item.action,
      })),
      stacks,
      skipped: unmatchedSelected.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        desired_tag: item.desired_tag,
        reason: "unmatched",
      })),
      issues,
      cleanup: {
        cleanup_id: cleanupItems.length > 0 ? "demo-cleanup" : "",
        can_remove_unmatched: cleanupItems.length > 0,
        items: cleanupItems,
      },
    };
  }

  cleanupPending(
    _cleanupId: string,
    lines: PendingCleanupLine[],
  ): PendingCleanupResponse {
    const requested = new Set(lines.map((line) => cleanupLineKey(line)));
    const removed = this.pending.filter(
      (item) => isUnmatchedDemoItem(item) && requested.has(cleanupLineKey(item)),
    );
    if (removed.length === 0 || removed.length !== requested.size) {
      throw new Error("cleanup is stale");
    }

    this.pending = this.pending.filter(
      (item) => !requested.has(cleanupLineKey(item)),
    );
    const runId = this.nextRun++;
    this.runs.unshift(runFromCleanup(runId, removed));
    return {
      status: "success",
      audit_run_id: runId,
      removed_count: removed.length,
      removed: removed.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        reason: "unmatched",
      })),
    };
  }

  createRemovalPlan(lineNumbers: number[]): PendingRemovalPlanResponse {
    const requested = new Set(lineNumbers);
    const lines = this.pending
      .filter((item) => requested.has(item.line_no))
      .sort((left, right) => left.line_no - right.line_no)
      .map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        desired_tag: item.desired_tag,
        digest: item.digest,
      }));
    if (lines.length === 0 || lines.length !== requested.size) {
      throw new Error("removal is stale");
    }
    return {
      removal_id: "demo-removal",
      source_file: DEMO_SOURCE_FILE,
      can_remove: true,
      selected_line_numbers: lines.map((item) => item.line_no),
      lines,
    };
  }

  removeSelectedPending(
    removalId: string,
    lines: PendingCleanupLine[],
  ): PendingCleanupResponse {
    if (removalId !== "demo-removal") {
      throw new Error("removal is stale");
    }
    const requested = new Set(lines.map((line) => cleanupLineKey(line)));
    const removed = this.pending.filter((item) =>
      requested.has(cleanupLineKey(item)),
    );
    if (removed.length === 0 || removed.length !== requested.size) {
      throw new Error("removal is stale");
    }

    this.pending = this.pending.filter(
      (item) => !requested.has(cleanupLineKey(item)),
    );
    const runId = this.nextRun++;
    this.runs.unshift(runFromRemoval(runId, removed));
    return {
      status: "success",
      audit_run_id: runId,
      removed_count: removed.length,
      removed: removed.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        reason: "selected",
      })),
    };
  }

  createJob(
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
  ): ApplyJobResponse {
    const plan = this.createPlan(lineNumbers, allowTagUpdates, tagOverrides);
    const jobId = `demo-job-${this.nextJob++}`;
    const job: ApplyJobResponse = {
      job_id: jobId,
      status: planId && plan.can_apply ? "queued" : "failure",
      run_id: null,
      log_file: "",
      started_at: null,
      finished_at: null,
      error: plan.can_apply ? "" : "Demo plan is not applyable.",
      selected_line_numbers: plan.selected_line_numbers,
      progress: [],
    };
    const log: ApplyJobLogResponse = {
      job_id: jobId,
      log_file: "",
      exists: true,
      content: "",
      truncated: false,
      max_bytes: 65_536,
      error: "",
    };
    this.jobs.set(jobId, {
      job,
      log,
      lineNumbers: plan.selected_line_numbers,
      plan,
      completed: false,
    });
    return clone(job);
  }

  completeJob(jobId: string): DemoJobRecord | null {
    const record = this.jobs.get(jobId);
    if (!record || record.completed || !record.plan) {
      return record ?? null;
    }
    if (!record.plan.can_apply) {
      record.completed = true;
      return record;
    }

    const startedAt = "2026-05-30T20:12:26+00:00";
    const finishedAt = "2026-05-30T20:12:28+00:00";
    const logFile = `${DEMO_LOG_DIR}/update-from-wud-v2-demo-${record.job.job_id}.log`;
    const selectedItems = this.pending.filter(
      (item) => isMatchedDemoItem(item) && record.lineNumbers.includes(item.line_no),
    );
    const runId = this.nextRun++;
    const logContent = this.applyLog(record.plan, startedAt, finishedAt, logFile);
    const selectedKeys = new Set(selectedItems.map((item) => cleanupLineKey(item)));

    this.pending = this.pending.filter(
      (item) => !selectedKeys.has(cleanupLineKey(item)),
    );
    record.completed = true;
    record.job = {
      ...record.job,
      status: "success",
      run_id: runId,
      log_file: logFile,
      started_at: startedAt,
      finished_at: finishedAt,
      error: "",
    };
    record.log = {
      ...record.log,
      log_file: logFile,
      content: logContent,
    };
    this.runs.unshift(
      runFromApply(runId, selectedItems, record.plan, startedAt, finishedAt, logFile, logContent),
    );
    return record;
  }

  appendJobProgress(
    jobId: string,
    phase: string,
    status: ApplyJobProgressEvent["status"],
    message: string,
    options: {
      stack?: string;
      services?: string[];
      lineNumbers?: number[];
    } = {},
  ): ApplyJobProgressEvent | null {
    const record = this.jobs.get(jobId);
    if (!record) {
      return null;
    }
    const event: ApplyJobProgressEvent = {
      job_id: jobId,
      phase,
      status,
      message,
      created_at: nowIso(),
      stack: options.stack ?? "",
      services: options.services ?? [],
      line_numbers: options.lineNumbers ?? record.lineNumbers,
    };
    record.job = {
      ...record.job,
      progress: [...record.job.progress, event],
    };
    return clone(event);
  }

  servicePolicies(): ServicePolicyRecord[] {
    return clone(this.policies);
  }

  snoozeRecords(state: SnoozeState): SnoozeRecord[] {
    return clone(
      this.snoozes.filter((snooze) => {
        if (state === "active") {
          return snooze.active;
        }
        if (state === "expired") {
          return !snooze.active;
        }
        return true;
      }),
    );
  }

  tagExclusionRecords(status: TagExclusionStatusFilter): TagExclusionRuleRecord[] {
    return clone(
      this.tagExclusions.filter((rule) =>
        status === "all" ? true : rule.status === status,
      ),
    );
  }

  stateOperation(operation: StateOperation): StateOperationResponse {
    if (operation.kind === "upsert_service_policy") {
      const existing = this.policies.find(
        (policy) => policy.service_key === operation.service_key,
      );
      const policy: ServicePolicyRecord = {
        service_key: operation.service_key,
        update_mode: operation.update_mode ?? existing?.update_mode ?? "",
        auto_update: operation.auto_update ?? existing?.auto_update ?? false,
        snooze_default_seconds:
          "snooze_default_seconds" in operation
            ? (operation.snooze_default_seconds ?? null)
            : (existing?.snooze_default_seconds ?? null),
        auto_update_time:
          "auto_update_time" in operation
            ? (operation.auto_update_time ?? null)
            : (existing?.auto_update_time ?? null),
        auto_update_days:
          "auto_update_days" in operation
            ? (operation.auto_update_days ?? [])
            : (existing?.auto_update_days ?? []),
        created_at: existing?.created_at ?? nowIso(),
        updated_at: nowIso(),
        metadata: { source: "demo" },
      };
      this.policies = upsertBy(
        this.policies,
        policy,
        (item) => item.service_key === policy.service_key,
      );
      return this.operationResponse(operation.kind, "service_policy", policy.service_key, policy);
    }

    if (operation.kind === "delete_service_policy") {
      this.policies = this.policies.filter(
        (policy) => policy.service_key !== operation.service_key,
      );
      return this.operationResponse(
        operation.kind,
        "service_policy",
        operation.service_key,
        null,
      );
    }

    if (operation.kind === "create_snooze") {
      const snooze: SnoozeRecord = {
        id: this.nextSnooze++,
        service_key: operation.service_key,
        snoozed_until: operation.snoozed_until,
        reason: operation.reason ?? "",
        created_at: nowIso(),
        active: new Date(operation.snoozed_until).getTime() > Date.now(),
        metadata: { source: "demo" },
      };
      this.snoozes.unshift(snooze);
      return this.operationResponse(operation.kind, "snooze", String(snooze.id), snooze);
    }

    if (operation.kind === "delete_snooze") {
      this.snoozes = this.snoozes.filter(
        (snooze) => snooze.id !== operation.snooze_id,
      );
      return this.operationResponse(
        operation.kind,
        "snooze",
        String(operation.snooze_id),
        null,
      );
    }

    if (operation.kind === "upsert_tag_exclusion") {
      const imageRepo = repoKey(operation.image_repo);
      const key = (rule: TagExclusionRuleRecord) =>
        rule.scope === operation.scope &&
        rule.image_repo === imageRepo &&
        rule.service_key === (operation.service_key ?? "") &&
        rule.tag === operation.tag;
      const existing = this.tagExclusions.find(key);
      const rule: TagExclusionRuleRecord = {
        id: existing?.id ?? this.nextTagExclusion++,
        scope: operation.scope,
        image_repo: imageRepo,
        service_key: operation.service_key ?? "",
        match_type: operation.match_type ?? "exact",
        tag: operation.tag,
        regex_fragment: escapeRegex(operation.tag),
        status: operation.status ?? existing?.status ?? "active",
        created_at: existing?.created_at ?? nowIso(),
        updated_at: nowIso(),
        metadata: { source: "demo" },
      };
      this.tagExclusions = upsertBy(this.tagExclusions, rule, key);
      return this.operationResponse(operation.kind, "tag_exclusion", String(rule.id), rule);
    }

    const rule = this.tagExclusions.find((item) => item.id === operation.rule_id);
    if (rule) {
      rule.status = operation.status;
      rule.updated_at = nowIso();
    }
    return this.operationResponse(
      operation.kind,
      "tag_exclusion",
      String(operation.rule_id),
      rule ?? null,
    );
  }

  runSummaries(): RunSummary[] {
    return clone(this.runs.map((run) => run.summary));
  }

  runDetail(runId: number): RunDetail {
    return clone(this.findRun(runId).detail);
  }

  runLog(runId: number): RunLogResponse {
    return clone(this.findRun(runId).log);
  }

  private stackGroup(name: DemoStackName) {
    const stack = DEMO_STACKS[name];
    const items = this.pending.filter((item) => item.stack === name);
    return {
      name,
      directory: `${DEMO_DOCKER_BASE}/${name}`,
      compose_file: "docker-compose.yml",
      project_directory: "",
      services_label: stack.servicesLabel,
      services: stack.services,
      line_numbers: items.map((item) => item.line_no),
      items: clone(items.map(stripDemoFields)),
    };
  }

  private applyLog(
    plan: PlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
  ): string {
    const lines = [
      `[${startedAt}] [INFO] docker-update-from-wud-v2`,
      `[${startedAt}] [INFO] Base    : ${DEMO_DOCKER_BASE}`,
      `[${startedAt}] [INFO] WUD file: ${DEMO_SOURCE_FILE}`,
      `[${startedAt}] [INFO] Log file: ${logFile}`,
      `[${startedAt}] [INFO] Mode    : ${plan.mode}`,
      `[${startedAt}] [INFO] Dry-run : false`,
      `[${startedAt}] [INFO] Confirm : true`,
      `[${startedAt}] [INFO] TagEdit : true`,
      `[${startedAt}] [INFO] MaxWait : ${plan.max_wait}s`,
      `[${startedAt}] [INFO] Removed in-flight WUD entries before update.`,
    ];
    for (const stack of plan.stacks) {
      lines.push(
        `[${startedAt}] [INFO] [${stack.name}] Checking for updates (mode=${plan.mode})`,
        `[${startedAt}] [INFO] [${stack.name}] Matched compose service(s): ${stack.services.join(", ")}`,
      );
      for (const line of stack.lines) {
        if (line.action === "tag-update") {
          lines.push(
            `[${startedAt}] [INFO] [${stack.name}] Compose tag updated: ${line.compose_image} -> ${line.target_image}`,
          );
        }
      }
      lines.push(
        `[${startedAt}] [INFO] [${stack.name}] Stopping affected service(s): ${stack.services.join(", ")}`,
        `[${startedAt}] [INFO] [${stack.name}] Bringing affected service(s) up: ${stack.services.join(", ")}`,
        `[${finishedAt}] [INFO] [${stack.name}] Healthy`,
      );
    }
    lines.push(
      `[${finishedAt}] [INFO] Successful WUD entries were removed before update.`,
      `[${finishedAt}] [INFO] Done. See log: ${logFile}`,
      "",
    );
    return lines.join("\n");
  }

  private operationResponse(
    operation: StateOperation["kind"],
    resourceType: string,
    resourceId: string,
    resource: StateOperationResponse["resource"],
  ): StateOperationResponse {
    return {
      operation,
      status: "success",
      audit_run_id: this.nextAudit++,
      resource_type: resourceType,
      resource_id: resourceId,
      resource: clone(resource),
    };
  }

  private findRun(runId: number): DemoRunFixture {
    const run = this.runs.find((item) => item.summary.id === runId);
    if (!run) {
      throw new Error(`Demo run ${runId} was not found`);
    }
    return run;
  }
}

export function createDemoWebApi(): WebApi {
  const state = new DemoApiState();

  return {
    csrf: async (): Promise<CsrfResponse> => ({ csrf_token: DEMO_CSRF_TOKEN }),
    setupStatus: async () => state.setupStatus(),
    setupClaim: async (
      _claim: string,
      _username: string,
      _password: string,
      _csrfToken: string,
    ) => state.session(),
    resetAdminClaim: async (
      _claim: string,
      _username: string,
      _password: string,
      _csrfToken: string,
    ) => state.session(),
    session: async () => state.session(),
    login: async (_username: string, _password: string, _csrfToken: string) =>
      state.session(),
    logout: async (_csrfToken: string) => state.session(),
    status: async () => state.status(),
    settings: async () => state.settings(),
    updateManagedSettings: async (
      values: Record<string, string>,
      _csrfToken: string,
    ) => state.updateManagedSettings(values),
    doctor: async (_csrfToken: string) => state.doctor(),
    onboardingChecklist: async (_csrfToken: string) => state.onboardingChecklist(),
    dismissOnboarding: async (_csrfToken: string) => state.dismissOnboarding(),
    coreUpdateTour: async () => state.coreUpdateTour,
    updateCoreUpdateTour: async (
      status: CoreUpdateTourStatus,
      step: CoreUpdateTourStep,
      _csrfToken: string,
    ) => state.updateCoreUpdateTour(status, step),
    pending: async () => state.pendingResponse(),
    updateTargets: async () => state.updateTargets(),
    cleanupPending: async (
      cleanupId: string,
      lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => state.cleanupPending(cleanupId, lines),
    createRemovalPlan: async (lineNumbers: number[], _csrfToken: string) =>
      state.createRemovalPlan(lineNumbers),
    removeSelectedPending: async (
      removalId: string,
      lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => state.removeSelectedPending(removalId, lines),
    releaseNotes: async () => state.releaseNotes(),
    refreshReleaseNotes: async (_csrfToken: string) => state.releaseNotes(),
    servicePolicies: async () => state.servicePolicies(),
    snoozes: async (snoozeState: SnoozeState = "active") =>
      state.snoozeRecords(snoozeState),
    tagExclusions: async (status: TagExclusionStatusFilter = "active") =>
      state.tagExclusionRecords(status),
    stateOperation: async (operation: StateOperation, _csrfToken: string) =>
      state.stateOperation(operation),
    restartContainer: async (_csrfToken: string): Promise<ContainerRestartResponse> => ({
      status: "scheduled",
      audit_run_id: 9001,
      container: "demo-wud-updater",
    }),
    createPlan: async (
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      _csrfToken: string,
    ) => state.createPlan(lineNumbers, allowTagUpdates, tagOverrides),
    createJob: async (
      planId: string,
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      _csrfToken: string,
    ) => state.createJob(planId, lineNumbers, allowTagUpdates, tagOverrides),
    applyPlan: async (
      planId: string,
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      _csrfToken: string,
    ) =>
      state.createJob(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
      ),
    job: async (jobId: string) => clone(requireJob(state, jobId).job),
    applyJob: async (jobId: string) => clone(requireJob(state, jobId).job),
    openJobStream: (jobId: string) =>
      new DemoJobStream(state, jobId) as unknown as EventSource,
    runs: async () => state.runSummaries(),
    runDetail: async (runId: number) => state.runDetail(runId),
    runLog: async (runId: number, _tailBytes = 262_144) => state.runLog(runId),
  };
}

class DemoJobStream extends EventTarget {
  onerror: ((event: Event) => void) | null = null;
  private timers: number[] = [];

  constructor(
    private readonly state: DemoApiState,
    private readonly jobId: string,
  ) {
    super();
    this.schedule();
  }

  close(): void {
    for (const timer of this.timers) {
      window.clearTimeout(timer);
    }
    this.timers = [];
  }

  private schedule(): void {
    const record = this.state.jobs.get(this.jobId);
    if (!record) {
      this.queue(() => this.onerror?.(new Event("error")), 0);
      return;
    }
    if (record.job.status === "failure" || record.plan?.can_apply === false) {
      this.queue(() => {
        this.emit("job", record.job);
        this.close();
      }, 0);
      return;
    }
    this.queue(() => {
      this.emitProgress(
        "preflight",
        "success",
        "Demo preflight checks passed.",
      );
      record.job = {
        ...record.job,
        status: "running",
        started_at: "2026-05-30T20:12:26+00:00",
      };
      record.log = {
        ...record.log,
        content:
          "[2026-05-30T20:12:26+00:00] [INFO] docker-update-from-wud-v2\n",
      };
      this.emit("job", record.job);
      this.emitProgress(
        "pull",
        "running",
        "Pulling selected demo images.",
      );
      this.emit("log", record.log);
    }, 40);
    this.queue(() => {
      this.emitProgress("pull", "success", "Images pulled and verified.");
      this.emitProgress("recreate", "running", "Recreating selected services.");
      this.emitProgress("recreate", "success", "Services were recreated.");
      this.emitProgress("health", "success", "Demo services reported healthy.");
      this.emitProgress("cleanup", "success", "Pending entries were reconciled.");
      this.emitProgress("completion", "success", "Updater completed successfully.");
      const completed = this.state.completeJob(this.jobId);
      if (!completed) {
        this.onerror?.(new Event("error"));
        return;
      }
      this.emit("log", completed.log);
      this.emit("job", completed.job);
      this.close();
    }, 140);
  }

  private queue(callback: () => void, delay: number): void {
    this.timers.push(window.setTimeout(callback, delay));
  }

  private emit(type: string, data: unknown): void {
    this.dispatchEvent(
      new MessageEvent(type, {
        data: JSON.stringify(data),
      }),
    );
  }

  private emitProgress(
    phase: string,
    status: ApplyJobProgressEvent["status"],
    message: string,
  ): void {
    const record = this.state.jobs.get(this.jobId);
    const stack = record?.plan?.stacks[0];
    const event = this.state.appendJobProgress(this.jobId, phase, status, message, {
      stack: stack?.name,
      services: stack?.services,
      lineNumbers: record?.lineNumbers,
    });
    if (event) {
      this.emit("progress", event);
    }
  }
}

function requireJob(state: DemoApiState, jobId: string): DemoJobRecord {
  const job = state.jobs.get(jobId);
  if (!job) {
    throw new Error(`Demo job ${jobId} was not found`);
  }
  return job;
}

function stripDemoFields(item: DemoPendingItem): PendingGroupedItem {
  const { stack: _stack, service: _service, ...pending } = item;
  return pending;
}

function cleanupLineKey(line: PendingCleanupLine): string {
  return `${line.line_no}\u0000${line.raw}`;
}

function isMatchedDemoItem(
  item: DemoPendingItem,
): item is DemoPendingItem & { stack: DemoStackName } {
  return item.stack !== "";
}

function isUnmatchedDemoItem(
  item: DemoPendingItem,
): item is DemoPendingItem & { stack: "" } {
  return item.stack === "";
}

function unmatchedIssue(item: DemoPendingItem) {
  const diagnostic = item.diagnostic ?? GENERIC_UNMATCHED_DIAGNOSTIC;
  return {
    severity: "error",
    code: diagnostic.code,
    message: diagnostic.message,
    line_no: item.line_no,
    stack: diagnostic.stack,
    service: diagnostic.service,
    hint: diagnostic.hint,
    details: diagnostic.details,
  };
}

function planCleanupItem(item: DemoPendingItem): PlanCleanupItem {
  return {
    line_no: item.line_no,
    raw: item.raw,
    image: item.image,
    desired_tag: item.desired_tag,
    digest: item.digest,
    reason: "unmatched",
    diagnostic: item.diagnostic,
  };
}

function demoServiceKey(item: DemoPendingItem): string {
  return item.stack ? `${item.stack}/${item.service}` : item.service;
}

function applyTagOverride(
  item: DemoPendingItem,
  tagOverrides: TagOverrideRequest[],
): DemoPendingItem {
  const override = tagOverrides.find((entry) => entry.line_no === item.line_no);
  if (!override) {
    return clone(item);
  }
  const targetImage = rewriteTag(item.resolved_image, override.tag);
  const action = isUnmatchedDemoItem(item) ? "unmatched" : "tag-update";
  return {
    ...clone(item),
    desired_tag: override.tag,
    target_image: targetImage,
    action,
  };
}

function planStack(name: DemoStackName, items: DemoPendingItem[]): PlanStack {
  const stack = DEMO_STACKS[name];
  const lines = items
    .filter((item) => item.stack === name)
    .map<PlanLine>((item) => ({
      line_no: item.line_no,
      raw: item.raw,
      image: item.image,
      resolved_image: item.resolved_image,
      compose_image: item.compose_images[0] ?? item.image,
      target_image: item.target_image,
      service: item.service,
      digest: item.digest,
      desired_tag: item.desired_tag,
      action: item.action,
    }));
  return {
    name,
    directory: `${DEMO_DOCKER_BASE}/${name}`,
    compose_file: "docker-compose.yml",
    project_directory: "",
    services_label: stack.servicesLabel,
    services: lines.map((line) => line.service),
    pull_services: lines.map((line) => line.service),
    stop_services: lines.map((line) => line.service),
    force_recreate: true,
    up_no_deps: true,
    tag_updates: lines
      .filter((line) => line.action === "tag-update")
      .map((line) => ({
        old_image: line.compose_image,
        desired_tag: line.desired_tag,
        new_image: line.target_image,
        services: [line.service],
      })),
    actions:
      lines.length > 0
        ? [
            {
              kind: "pull",
              description: `pull ${stack.servicesLabel}`,
              cwd: `${DEMO_DOCKER_BASE}/${name}`,
              args: ["docker", "compose", "pull", ...lines.map((line) => line.service)],
            },
            {
              kind: "up",
              description: `recreate ${stack.servicesLabel}`,
              cwd: `${DEMO_DOCKER_BASE}/${name}`,
              args: [
                "docker",
                "compose",
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                ...lines.map((line) => line.service),
              ],
            },
          ]
        : [],
    lines,
  };
}

function runFromApply(
  runId: number,
  selectedItems: DemoPendingItem[],
  plan: PlanResponse,
  startedAt: string,
  finishedAt: string,
  logFile: string,
  logContent: string,
): DemoRunFixture {
  const summary: RunSummary = {
    id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    status: "success",
    dry_run: false,
    mode: plan.mode,
    wud_file: DEMO_SOURCE_FILE,
    log_file: logFile,
    metadata: { source: "demo", summary: `updated ${selectedItems.length} services` },
  };
  const pending_updates = selectedItems.map((item, index) =>
    pendingRecord(
      item.line_no,
      runId,
      item.raw,
      demoServiceKey(item),
      "success",
      index + runId * 100,
    ),
  );
  const events = selectedItems.map((item, index) =>
    runEvent(
      index + runId * 1000,
      runId,
      item.service,
      item.stack,
      item.image,
      item.target_image,
      "success",
    ),
  );
  return {
    summary,
    detail: {
      ...summary,
      pending_updates,
      events,
    },
    log: {
      run_id: runId,
      log_file: logFile,
      exists: true,
      content: logContent,
      truncated: false,
      max_bytes: 262_144,
    },
  };
}

function runFromCleanup(
  runId: number,
  removedItems: DemoPendingItem[],
): DemoRunFixture {
  const startedAt = "2026-05-30T20:12:26+00:00";
  const finishedAt = "2026-05-30T20:12:26+00:00";
  const logFile = "";
  const summary: RunSummary = {
    id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    status: "success",
    dry_run: false,
    mode: "web-pending-cleanup",
    wud_file: DEMO_SOURCE_FILE,
    log_file: logFile,
    metadata: {
      source: "demo",
      operation: "remove_unmatched_pending",
      line_numbers: removedItems.map((item) => item.line_no),
    },
  };
  const pending_updates = removedItems.map((item, index) =>
    pendingRecord(
      item.line_no,
      runId,
      item.raw,
      demoServiceKey(item),
      "resolved",
      index + runId * 100,
      "removed-unmatched",
    ),
  );
  const events = removedItems.map((item, index) =>
    runEvent(
      index + runId * 1000,
      runId,
      item.service,
      item.stack,
      item.image,
      "",
      "success",
    ),
  );
  return {
    summary,
    detail: {
      ...summary,
      pending_updates,
      events,
    },
    log: {
      run_id: runId,
      log_file: logFile,
      exists: true,
      content: "Removed unmatched pending demo entries.\n",
      truncated: false,
      max_bytes: 262_144,
    },
  };
}

function runFromRemoval(
  runId: number,
  removedItems: DemoPendingItem[],
): DemoRunFixture {
  const startedAt = "2026-05-30T20:12:26+00:00";
  const finishedAt = "2026-05-30T20:12:26+00:00";
  const logFile = "";
  const summary: RunSummary = {
    id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    status: "success",
    dry_run: false,
    mode: "web-pending-removal",
    wud_file: DEMO_SOURCE_FILE,
    log_file: logFile,
    metadata: {
      source: "demo",
      operation: "remove_selected_pending",
      line_numbers: removedItems.map((item) => item.line_no),
    },
  };
  const pending_updates = removedItems.map((item, index) =>
    pendingRecord(
      item.line_no,
      runId,
      item.raw,
      demoServiceKey(item),
      "resolved",
      index + runId * 100,
      "removed-selected",
    ),
  );
  const events = removedItems.map((item, index) =>
    runEvent(
      index + runId * 1000,
      runId,
      item.service,
      item.stack,
      item.image,
      "",
      "success",
    ),
  );
  return {
    summary,
    detail: {
      ...summary,
      pending_updates,
      events,
    },
    log: {
      run_id: runId,
      log_file: logFile,
      exists: true,
      content: "Removed selected pending demo entries.\n",
      truncated: false,
      max_bytes: 262_144,
    },
  };
}

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
    metadata: { source: "demo", summary: options.summary },
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

function pendingRecord(
  lineNo: number,
  runId: number,
  raw: string,
  serviceKey: string,
  status: string,
  id = lineNo + runId * 10,
  statusReason = status === "failed"
    ? "container health check timed out"
    : "demo fixture",
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
    target_digest: "",
    desired_tag: desiredTag,
    service_key: serviceKey,
    stack_name: stackName ?? "",
    service_name: serviceName ?? "",
    status,
    status_reason: statusReason,
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:01+00:00",
    metadata: { source: "demo" },
  };
}

function runEvent(
  id: number,
  runId: number,
  serviceName: string,
  stackName: string,
  image: string,
  targetImage: string,
  status: string,
): RunEventRecord {
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
    old_digest: "sha256:demo-old",
    new_digest: "sha256:demo-new",
    status,
    metadata: { source: "demo" },
  };
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

function settingEntry(
  name: string,
  value: string,
  defaultValue: string,
  configured: boolean,
  source: SettingsEntrySource = configured ? "configured" : "default",
): SettingsResponse["updater"][number] {
  return {
    name,
    value,
    default_value: defaultValue,
    configured,
    source,
  };
}

function normalizeDemoComposeIgnorePaths(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const rawItem of trimmed.split(",")) {
    const item = rawItem.trim();
    const parts = item.split("/");
    if (
      !item ||
      item.startsWith("/") ||
      parts.some((part) => part === "" || part === "." || part === "..")
    ) {
      throw new Error(
        "compose_ignore_paths entries must be non-empty relative paths",
      );
    }
    if (!seen.has(item)) {
      seen.add(item);
      paths.push(item);
    }
  }
  return paths.join(", ");
}

function doctorCheck(
  status: DoctorResponse["checks"][number]["status"],
  code: string,
  category: string,
  name: string,
  detail: string,
  suggestion?: DoctorResponse["checks"][number]["suggestions"][number],
): DoctorResponse["checks"][number] {
  return {
    status,
    code,
    category,
    name,
    detail,
    target: "",
    suggestions: suggestion ? [suggestion] : [],
  };
}

function rewriteTag(image: string, tag: string): string {
  const digestless = image.split("@sha256:")[0] ?? image;
  const slash = digestless.lastIndexOf("/");
  const colon = digestless.lastIndexOf(":");
  if (colon > slash) {
    return `${digestless.slice(0, colon)}:${tag}`;
  }
  return `${digestless}:${tag}`;
}

function repoKey(image: string): string {
  const digestless = image.trim().split("@sha256:")[0] ?? image.trim();
  const firstSlash = digestless.indexOf("/");
  const withoutRegistry =
    firstSlash === -1 || !isRegistryPrefix(digestless.slice(0, firstSlash))
      ? digestless
      : digestless.slice(firstSlash + 1);
  const lastSlash = withoutRegistry.lastIndexOf("/");
  const lastSegment = withoutRegistry.slice(lastSlash + 1);
  const tagSeparator = lastSegment.lastIndexOf(":");
  if (tagSeparator === -1) {
    return withoutRegistry;
  }
  return `${withoutRegistry.slice(0, lastSlash + 1)}${lastSegment.slice(0, tagSeparator)}`;
}

function isRegistryPrefix(value: string): boolean {
  return value.includes(".") || value.includes(":") || value === "localhost";
}

function upsertBy<T>(items: T[], next: T, matches: (item: T) => boolean): T[] {
  const index = items.findIndex(matches);
  if (index === -1) {
    return [next, ...items];
  }
  const updated = [...items];
  updated[index] = next;
  return updated;
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function nowIso(): string {
  return new Date().toISOString();
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
