import type {
  ApplyJobLogResponse,
  ApplyJobProgressEvent,
  ApplyJobResponse,
  AuthSessionResponse,
  CoreUpdateTourResponse,
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  DigestPinLabelRewriteApprovalRequest,
  DoctorResponse,
  ManagedSettingsUpdateResponse,
  OnboardingChecklistResponse,
  OnboardingDismissResponse,
  PendingCleanupLine,
  PendingCleanupResponse,
  PendingRemovalPlanResponse,
  PendingResponse,
  PlanResponse,
  PlanStatus,
  ReleaseNotesResponse,
  RetagChoiceRequest,
  RetagPlanIssue,
  RetagPlanResponse,
  RetagTargetItem,
  RetagTargetsResponse,
  RunDetail,
  RunLogResponse,
  RunSummary,
  ServicePolicyRecord,
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
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
  UpdateTargetsResponse,
} from "../types";
import {
  DEMO_DB_PATH,
  DEMO_DOCKER_BASE,
  DEMO_LATEST_VERSION,
  DEMO_LOG_DIR,
  DEMO_SOURCE_FILE,
  DEMO_VERSION,
} from "./constants";
import {
  DEMO_RETAG_TARGETS,
  DEMO_STACKS,
  DEMO_UPDATE_TARGETS,
  INITIAL_PENDING,
  INITIAL_POLICIES,
  INITIAL_RELEASE_NOTES,
  INITIAL_RUNS,
  INITIAL_SNOOZES,
  INITIAL_TAG_EXCLUSIONS,
} from "./fixtures";
import {
  applyTagOverride,
  cleanupLineKey,
  clone,
  demoApplyPreflight,
  doctorCheck,
  escapeRegex,
  isMatchedDemoItem,
  isUnmatchedDemoItem,
  normalizeDemoComposeIgnorePaths,
  nowIso,
  planCleanupItem,
  planStack,
  repoKey,
  runFromApply,
  runFromRetagApply,
  runFromCleanup,
  runFromRemoval,
  settingEntry,
  stripDemoFields,
  unmatchedIssue,
  upsertBy,
} from "./helpers";
import type { DemoJobRecord, DemoPendingItem, DemoRunFixture, DemoStackName } from "./types";

function planStatus(selectedCount: number, issueCount: number): PlanStatus {
  if (selectedCount === 0) {
    return "empty";
  }
  if (issueCount > 0) {
    return "blocked";
  }
  return "ready";
}

export class DemoApiState {
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
  digestPinUpdates = "false";
  digestPinUpdatesConfigured = false;
  coreUpdateTour: CoreUpdateTourResponse = {
    status: "not_started",
    step: "dashboard",
    updated_at: "",
  };
  nextJob = 1;
  nextRun = 7;
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
        settingEntry("WUD_DIGEST_PIN_UPDATES", "false", "false", false),
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
        {
          key: "digest_pin_updates",
          value: this.digestPinUpdates,
          default_value: "false",
          source: this.digestPinUpdatesConfigured ? "configured" : "default",
          editable: true,
          allowed_values: ["false", "true"],
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
      this.updateManagedSetting(key, value);
    }
    return {
      managed: this.settings().managed,
      audit_run_id: this.nextAudit++,
    };
  }

  private updateManagedSetting(key: string, value: string): void {
    switch (key) {
      case "theme_preference":
        this.updateThemePreference(value);
        return;
      case "onboarding_checklist":
        this.updateOnboardingChecklist(value);
        return;
      case "compose_ignore_paths":
        this.updateComposeIgnorePaths(value);
        return;
      case "digest_pin_updates":
        this.updateDigestPinUpdates(value);
        return;
      default:
        throw new Error(`managed setting is not editable: ${key}`);
    }
  }

  private updateThemePreference(value: string): void {
    if (!["system", "light", "dark"].includes(value)) {
      throw new Error("theme_preference must be system, light, or dark");
    }
    this.themePreference = value;
    this.themePreferenceConfigured = true;
  }

  private updateOnboardingChecklist(value: string): void {
    if (!["visible", "dismissed"].includes(value)) {
      throw new Error("onboarding_checklist must be visible or dismissed");
    }
    if (value === "visible") {
      this.onboardingDismissedAt = "";
      return;
    }
    if (!this.onboardingDismissedAt) {
      this.onboardingDismissedAt = new Date("2026-05-31T00:00:00.000Z").toISOString();
    }
  }

  private updateComposeIgnorePaths(value: string): void {
    this.composeIgnorePaths = normalizeDemoComposeIgnorePaths(value);
    this.composeIgnorePathsConfigured = true;
  }

  private updateDigestPinUpdates(value: string): void {
    if (!["false", "true"].includes(value)) {
      throw new Error("digest_pin_updates must be false or true");
    }
    this.digestPinUpdates = value;
    this.digestPinUpdatesConfigured = true;
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

  retagTargets(): RetagTargetsResponse {
    return {
      status: "ready",
      count: DEMO_RETAG_TARGETS.length,
      items: clone(DEMO_RETAG_TARGETS),
      warnings: [
        "Demo retag data is fixture-backed and does not inspect local Compose files.",
      ],
    };
  }

  createRetagPlan(choices: RetagChoiceRequest[]): RetagPlanResponse {
    const targetsByKey = new Map(
      DEMO_RETAG_TARGETS.map((item) => [item.service_key, item]),
    );
    const selected: RetagTargetItem[] = [];
    const issues: RetagPlanIssue[] = [];
    let keepCurrentCount = 0;
    const choicesByServiceKey = new Map<string, RetagChoiceRequest>();
    for (const choice of choices) {
      if (!choicesByServiceKey.has(choice.service_key)) {
        choicesByServiceKey.set(choice.service_key, choice);
      }
    }
    for (const choice of choicesByServiceKey.values()) {
      const target = targetsByKey.get(choice.service_key);
      if (!target) {
        issues.push({
          severity: "error",
          code: "retag-choice-unknown",
          message: `${choice.service_key} is not present in demo retag fixtures.`,
          service_key: choice.service_key,
          stack: "",
          service: "",
          hint: "",
          details: {},
        });
        continue;
      }
      if (choice.choice === "keep-current") {
        keepCurrentCount += 1;
        continue;
      }
      if (!target.retag_available) {
        issues.push({
          severity: "error",
          code: "retag-target-not-eligible",
          message: `${choice.service_key} cannot switch to concrete tracking: ${target.retag_reason}`,
          service_key: target.service_key,
          stack: target.stack,
          service: target.service,
          hint: "",
          details: {},
        });
        continue;
      }
      selected.push(target);
    }
    let status: RetagPlanResponse["status"] = "empty";
    if (issues.length) {
      status = "blocked";
    } else if (selected.length) {
      status = "ready";
    }
    const stacks = Array.from(new Set(selected.map((item) => item.stack))).map(
      (stackName) => {
        const stackItems = selected.filter((item) => item.stack === stackName);
        const first = stackItems[0];
        return {
          stack: stackName,
          directory: first?.directory ?? "",
          compose_file: first?.compose_file ?? "",
          project_directory: first?.project_directory ?? "",
          services: stackItems
            .map((item) => item.service)
            .sort((left, right) => left.localeCompare(right)),
          digest_pin_updates: stackItems
            .map((item) => ({
              service_key: item.service_key,
              stack: item.stack,
              service: item.service,
              source_image: item.image,
              resolved_tag: item.proposed_tag,
              planned_digest: item.final_image.split("@", 2)[1] ?? "",
              final_image: item.final_image,
              watch_tag: item.tracking_tag,
              marker: `wud-updater.resolved-tag=${item.proposed_tag}`,
              label_key: item.label_key,
              label_value: item.label_value,
              label_rewrites: [],
              digest_provenance: item.digest_provenance ?? null,
            }))
            .sort((left, right) =>
              left.service_key.localeCompare(right.service_key),
            ),
        };
      },
    );

    return {
      plan_id: `demo-retag-plan-${status}-${selected
        .map((item) => item.service_key)
        .sort((left, right) => left.localeCompare(right))
        .join("-")}`,
      status,
      can_apply: status === "ready" && selected.length > 0,
      external_recreate_required: false,
      selected_count: selected.length,
      keep_current_count: keepCurrentCount,
      stacks,
      issues,
      warnings: [
        "Demo retag preview is fixture-backed and does not inspect local Compose files.",
      ],
    };
  }

  createRetagJob(
    planId: string,
    choices: RetagChoiceRequest[],
  ): ApplyJobResponse {
    const plan = this.createRetagPlan(choices);
    if (plan.plan_id !== planId) {
      throw new Error("Demo retag plan is stale.");
    }
    const jobId = `demo-retag-job-${this.nextJob++}`;
    const job: ApplyJobResponse = {
      job_id: jobId,
      status: plan.can_apply ? "queued" : "failure",
      run_id: null,
      log_file: "",
      started_at: null,
      finished_at: null,
      error: plan.can_apply ? "" : "Demo retag plan is not applyable.",
      selected_line_numbers: [],
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
      lineNumbers: [],
      plan: null,
      retagPlan: plan,
      completed: false,
    });
    return clone(job);
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

  selfUpdate(): SelfUpdateResponse {
    return {
      status: "available",
      strategy: "pull_image",
      current_tag: `v${DEMO_VERSION}`,
      latest_tag: DEMO_LATEST_VERSION,
      current_image: "ghcr.io/magrhino/wud-updater:latest",
      target_image: "ghcr.io/magrhino/wud-updater:latest",
      restart_container: "demo-wud-updater",
      release_notes: Array.from({ length: 10 }, (_, index) => {
        const patch = 26 - index;
        const tag = `v0.${patch}.0`;
        return {
          tag,
          title: `${tag} demo release`,
          published_at: `2026-05-${String(28 - index).padStart(2, "0")}T12:00:00Z`,
          url: `https://github.com/magrhino/WUD-Updater/releases/tag/${tag}`,
          body:
            index === 0
              ? "Adds the WebUI self-update banner, release-note review, and image pull flow."
              : "Demo release note for the capped self-update history list.",
          body_truncated: false,
          breaking: index === 0,
          breaking_reasons: index === 0 ? ["Review external container recreate steps."] : [],
        };
      }),
      release_notes_truncated: true,
      release_notes_cap: 10,
      can_update: true,
      disabled_reason: "",
      external_recreate_required: false,
      warnings: [],
    };
  }

  selfUpdatePlan(): SelfUpdatePlanResponse {
    const item: DemoPendingItem = {
      line_no: 1,
      raw: "ghcr.io/magrhino/wud-updater:v0.25.0 tag=v0.26.0",
      image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      key: "ghcr.io/magrhino/wud-updater",
      repo: "ghcr.io/magrhino/wud-updater",
      current_tag: "v0.25.0",
      has_tag: true,
      allow_repo: false,
      digest: "",
      desired_tag: "v0.26.0",
      resolved_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      target_image: "ghcr.io/magrhino/wud-updater:v0.26.0",
      compose_images: ["ghcr.io/magrhino/wud-updater:v0.25.0"],
      services: ["wud-updater"],
      service: "wud-updater",
      stack: "media",
      action: "tag-update",
      diagnostic: null,
    };
    const plan: PlanResponse = {
      plan_id: "demo-self-update-plan",
      dry_run: true,
      can_apply: true,
      status: "ready",
      source_file: DEMO_SOURCE_FILE,
      mode: "stop",
      max_wait: 180,
      digest_pin_updates: false,
      selected_line_numbers: [1],
      summary: {
        target_count: 1,
        matched_target_count: 1,
        stack_count: 1,
        service_count: 1,
        skipped_count: 0,
        issue_count: 0,
      },
      targets: [
        {
          line_no: item.line_no,
          raw: item.raw,
          image: item.image,
          resolved_image: item.resolved_image,
          digest: item.digest,
          desired_tag: item.desired_tag,
          matched: true,
          action: item.action,
        },
      ],
      stacks: [planStack("media", [item])],
      skipped: [],
      issues: [],
      cleanup: {
        cleanup_id: "",
        can_remove_unmatched: false,
        items: [],
      },
      apply_preflight: demoApplyPreflight(),
    };
    return {
      strategy: "prepare_tag_update",
      plan,
      current_tag: "v0.25.0",
      latest_tag: "v0.26.0",
      current_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      target_image: "ghcr.io/magrhino/wud-updater:v0.26.0",
      restart_container: "demo-wud-updater",
      external_recreate_required: true,
      warning:
        "This updates the Compose image tag and pulls the image. Recreate the WUD-Updater container from outside the WebUI to run it.",
    };
  }

  createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
    _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
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

    const canApply = matchedSelected.length > 0 && issues.length === 0;
    const status = planStatus(selected.length, issues.length);

    return {
      plan_id: `demo-plan-${Date.now()}`,
      dry_run: true,
      can_apply: canApply,
      status,
      source_file: DEMO_SOURCE_FILE,
      mode: "stop",
      max_wait: 180,
      digest_pin_updates: false,
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
      apply_preflight: demoApplyPreflight({
        selectedReady: canApply,
        selectedDetail:
          status === "empty"
            ? "No selected services need changes."
            : issues[0]?.message || "",
      }),
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
    digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): ApplyJobResponse {
    const plan = this.createPlan(
      lineNumbers,
      allowTagUpdates,
      tagOverrides,
      digestPinLabelRewriteApprovals,
    );
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
      retagPlan: null,
      completed: false,
    });
    return clone(job);
  }

  completeJob(jobId: string): DemoJobRecord | null {
    const record = this.jobs.get(jobId);
    if (!record || record.completed) {
      return record ?? null;
    }
    if (record.retagPlan) {
      return this.completeRetagJob(record);
    }
    if (!record.plan) {
      return record;
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

  private completeRetagJob(record: DemoJobRecord): DemoJobRecord {
    const plan = record.retagPlan;
    if (!plan) {
      return record;
    }
    if (!plan.can_apply) {
      record.completed = true;
      return record;
    }

    const startedAt = "2026-05-30T20:12:26+00:00";
    const finishedAt = "2026-05-30T20:12:28+00:00";
    const logFile = `${DEMO_LOG_DIR}/retag-demo-${record.job.job_id}.log`;
    const runId = this.nextRun++;
    const logContent = this.retagApplyLog(plan, startedAt, finishedAt, logFile);

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
      runFromRetagApply(runId, plan, startedAt, finishedAt, logFile, logContent),
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

  private retagApplyLog(
    plan: RetagPlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
  ): string {
    const lines = [
      `[${startedAt}] [INFO] demo retag apply`,
      `[${startedAt}] [INFO] Log file: ${logFile}`,
      `[${startedAt}] [INFO] Selected retags: ${plan.selected_count}`,
    ];
    for (const stack of plan.stacks) {
      lines.push(
        `[${startedAt}] [INFO] [${stack.stack}] Writing retag Compose metadata.`,
        `[${startedAt}] [INFO] [${stack.stack}] Pulling retagged service image(s): ${stack.services.join(", ")}`,
      );
      for (const update of stack.digest_pin_updates) {
        lines.push(
          `[${startedAt}] [INFO] [${stack.stack}] ${update.service}: ${update.source_image} -> ${update.final_image}`,
        );
      }
      lines.push(
        `[${finishedAt}] [INFO] [${stack.stack}] Retagged service container(s) recreated.`,
      );
    }
    lines.push(
      `[${finishedAt}] [INFO] Retag changes applied.`,
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
