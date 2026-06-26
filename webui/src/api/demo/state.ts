import type {
  ApplyJobProgressEvent,
  ApplyJobResponse,
  AuthSessionResponse,
  CoreUpdateTourResponse,
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  DiagnosticsSupportBundleResponse,
  DigestPinLabelRewriteApprovalRequest,
  DoctorResponse,
  ManagedSettingsUpdateResponse,
  OnboardingChecklistResponse,
  OnboardingDismissResponse,
  PendingCleanupLine,
  PendingCleanupResponse,
  PendingGroupedItem,
  PendingItem,
  PendingRescanLine,
  PendingRemovalPlanResponse,
  PendingResponse,
  PendingRescanResponse,
  PendingRescanScope,
  PlanResponse,
  ReleaseNotificationSource,
  ReleaseNotificationResponse,
  ReleaseNotesResponse,
  RetagChoiceRequest,
  RetagPreviewJobResponse,
  RetagPlanResponse,
  RetagTargetsResponse,
  RunDetail,
  RunEventRecord,
  RunLogResponse,
  RunSummary,
  SecurityScanInfo,
  SecurityScanJobResponse,
  SecurityScanSeverityCounts,
  SecurityScansResponse,
  ServicePolicyRecord,
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
  SettingsResponse,
  SetupStatusResponse,
  SnoozeRecord,
  SnoozeState,
  StateOperation,
  StateOperationResponse,
  StatusResponse,
  TagExclusionRuleRecord,
  TagExclusionStatusFilter,
  TagOverrideRequest,
  UpdateTargetsResponse,
} from "../types";
import { DEMO_VERSION } from "./constants";
import { generatedFixtures } from "./generatedFixtures";
import {
  cleanupLineKey,
  clone,
  escapeRegex,
  normalizeDemoComposeIgnorePaths,
  nowIso,
  repoKey,
  upsertBy,
} from "./helpers";
import type {
  DemoGeneratedFixtures,
  DemoGeneratedJobFixture,
  DemoJobRecord,
  DemoPlanCase,
  DemoRemovalCase,
  DemoRetagCase,
  DemoRunFixture,
  DemoTagToken,
} from "./types";

const STATIC_FIXTURE_ERROR =
  "This selection is not part of the static demo fixture set.";
const DEMO_NOW = "2026-05-31T00:00:00.000Z";
const fixtures: DemoGeneratedFixtures = generatedFixtures;
const EMPTY_SECURITY_COUNTS: SecurityScanSeverityCounts = {
  critical: 0,
  high: 0,
  medium: 0,
  low: 0,
  unknown: 0,
};

type PendingLineFixture = {
  line_no: number;
  raw: string;
  image: string;
  desired_tag: string;
  digest: string;
  repo: string;
  target_image: string;
  stack_name: string;
  service_name: string;
  digest_provenance?: PendingItem["digest_provenance"];
};

function activeLineNumbers(activeKeys: Set<string>): Set<number> {
  return new Set(
    fixtures.pending.items
      .filter((item) => activeKeys.has(cleanupLineKey(item)))
      .map((item) => item.line_no),
  );
}

function pendingItemPlatform(item: PendingItem): string {
  if (item.platform) {
    return item.platform;
  }
  if (!item.platform_os || !item.platform_architecture) {
    return "";
  }
  return [item.platform_os, item.platform_architecture, item.platform_variant]
    .filter(Boolean)
    .join("/");
}

function normalizeDemoDigest(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const digest = trimmed.includes("@sha256:")
    ? trimmed.slice(trimmed.lastIndexOf("@") + 1)
    : trimmed;
  return digest.startsWith("sha256:") ? digest : `sha256:${digest}`;
}

function uniqueSortedNumbers(values: number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

function sameNumbers(left: number[], right: number[]): boolean {
  const normalizedLeft = uniqueSortedNumbers(left);
  const normalizedRight = uniqueSortedNumbers(right);
  return (
    normalizedLeft.length === normalizedRight.length &&
    normalizedLeft.every((value, index) => value === normalizedRight[index])
  );
}

function sameRetagChoices(
  left: RetagChoiceRequest[],
  right: RetagChoiceRequest[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every(
    (choice, index) =>
      choice.service_key === right[index]?.service_key &&
      choice.choice === right[index]?.choice &&
      (choice.target_tag ?? "") === (right[index]?.target_tag ?? ""),
  );
}

function replaceString(value: unknown, oldValue: string, newValue: string): unknown {
  if (typeof value === "string") {
    return value.replaceAll(oldValue, newValue);
  }
  if (Array.isArray(value)) {
    return value.map((item) => replaceString(item, oldValue, newValue));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        replaceString(item, oldValue, newValue),
      ]),
    );
  }
  return value;
}

function replaceMany<T>(
  value: T,
  replacements: Array<[oldValue: string, newValue: string]>,
): T {
  let result: unknown = clone(value);
  const placeholders = replacements
    .filter(([oldValue]) => oldValue.length > 0)
    .map(([oldValue, newValue], index) => ({
      oldValue,
      newValue,
      placeholder: `\0demo-replacement-${index}\0`,
    }))
    .sort((left, right) => right.oldValue.length - left.oldValue.length);
  for (const { oldValue, placeholder } of placeholders) {
    result = replaceString(result, oldValue, placeholder);
  }
  for (const { newValue, placeholder } of placeholders) {
    result = replaceString(result, placeholder, newValue);
  }
  return result as T;
}

function overrideByLine(tagOverrides: TagOverrideRequest[]): Map<number, string> {
  const values = new Map<number, string>();
  for (const override of tagOverrides) {
    if (!values.has(override.line_no)) {
      values.set(override.line_no, override.tag);
    }
  }
  return values;
}

function tokenReplacements(
  tagTokens: DemoTagToken[],
  tagOverrides: TagOverrideRequest[],
): Array<[oldValue: string, newValue: string]> {
  const overrides = overrideByLine(tagOverrides);
  return tagTokens.map((token) => {
    const value = overrides.get(token.line_no) ?? token.default_tag;
    return [token.token, value] satisfies [string, string];
  });
}

function replaceTagReference(value: string, defaultTag: string, tag: string): string {
  return value
    .replaceAll(`tag=${defaultTag}`, `tag=${tag}`)
    .replaceAll(`:${defaultTag}`, `:${tag}`);
}

function updateDesiredTagFields(
  item: {
    desired_tag: string;
    raw: string;
    target_image?: string;
  },
  defaultTag: string,
  tag: string,
): void {
  item.desired_tag = tag;
  item.raw = replaceTagReference(item.raw, defaultTag, tag);
  item.target_image = item.target_image
    ? replaceTagReference(item.target_image, defaultTag, tag)
    : item.target_image;
}

function updatePlanLineTagFields(
  item: {
    desired_tag: string;
    raw: string;
    resolved_image: string;
    target_image: string;
  },
  defaultTag: string,
  tag: string,
): void {
  updateDesiredTagFields(item, defaultTag, tag);
  item.resolved_image = item.resolved_image
    ? replaceTagReference(item.resolved_image, defaultTag, tag)
    : item.resolved_image;
}

function applyPlanTagOverride(
  response: PlanResponse,
  token: DemoTagToken,
  tag: string,
): void {
  response.targets
    .filter((target) => target.line_no === token.line_no)
    .forEach((target) => updateDesiredTagFields(target, token.default_tag, tag));
  response.skipped
    .filter((skipped) => skipped.line_no === token.line_no)
    .forEach((skipped) => updateDesiredTagFields(skipped, token.default_tag, tag));
  response.cleanup.items
    .filter((item) => item.line_no === token.line_no)
    .forEach((item) => updateDesiredTagFields(item, token.default_tag, tag));
  for (const stack of response.stacks) {
    const line = stack.lines.find((item) => item.line_no === token.line_no);
    if (!line) {
      continue;
    }
    const service = line.service;
    updatePlanLineTagFields(line, token.default_tag, tag);
    for (const update of stack.tag_updates) {
      if (!update.services.includes(service)) {
        continue;
      }
      update.desired_tag = tag;
      update.new_image = replaceTagReference(update.new_image, token.default_tag, tag);
    }
    for (const action of stack.actions) {
      if (action.kind === "compose-tag-update" && action.description.includes(service)) {
        action.description = replaceTagReference(
          action.description,
          token.default_tag,
          tag,
        );
      }
    }
  }
}

function materializePlanResponse(
  response: PlanResponse,
  tagTokens: DemoTagToken[],
  tagOverrides: TagOverrideRequest[],
): PlanResponse {
  const materialized = replaceMany(
    response,
    tokenReplacements(tagTokens, tagOverrides),
  );
  const overrides = overrideByLine(tagOverrides);
  if (overrides.size === 0) {
    return materialized;
  }
  const tokensByLine = new Map(tagTokens.map((token) => [token.line_no, token]));
  for (const [lineNo, tag] of overrides) {
    const token = tokensByLine.get(lineNo);
    if (token) {
      applyPlanTagOverride(materialized, token, tag);
    }
  }
  return materialized;
}

function tagOverridePlanSuffix(tagOverrides: TagOverrideRequest[]): string {
  if (!tagOverrides.length) {
    return "";
  }
  const parts = [...overrideByLine(tagOverrides).entries()]
    .sort(([left], [right]) => left - right)
    .map(([lineNo, tag]) => `${lineNo}-${tag}`);
  return `__overrides-${parts.join("-")}`;
}

function materializePlanCase(
  planCase: DemoPlanCase,
  tagOverrides: TagOverrideRequest[],
): DemoPlanCase {
  const response = materializePlanResponse(
    planCase.response,
    planCase.tagTokens,
    tagOverrides,
  );
  response.plan_id = `${response.plan_id}${tagOverridePlanSuffix(tagOverrides)}`;
  return {
    ...planCase,
    response,
    jobTemplate: planCase.jobTemplate
      ? materializeJobTemplate(planCase.jobTemplate, planCase.tagTokens, tagOverrides)
      : undefined,
  };
}

function materializeRetagCase(retagCase: DemoRetagCase): DemoRetagCase {
  return clone(retagCase);
}

function materializeJobTemplate(
  fixture: DemoGeneratedJobFixture,
  tagTokens: DemoTagToken[],
  tagOverrides: TagOverrideRequest[],
): DemoGeneratedJobFixture {
  const materialized = replaceMany(
    fixture,
    tokenReplacements(tagTokens, tagOverrides),
  );
  const overrides = overrideByLine(tagOverrides);
  const noopTokens = tagTokens.filter((token) => !overrides.has(token.line_no));
  if (noopTokens.length === 0) {
    return materialized;
  }
  materialized.log.content = removeNoopTagOverrideLogLines(
    materialized.log.content,
    noopTokens,
  );
  if (materialized.run) {
    materialized.run.log.content = removeNoopTagOverrideLogLines(
      materialized.run.log.content,
      noopTokens,
    );
  }
  return materialized;
}

function removeNoopTagOverrideLogLines(
  content: string,
  noopTokens: DemoTagToken[],
): string {
  if (!content) {
    return content;
  }
  return content
    .split("\n")
    .filter((line) =>
      noopTokens.every(
        (token) =>
          !line.includes(`Tag override: line ${token.line_no} uses tag ${token.default_tag} instead of ${token.default_tag}`),
      ),
    )
    .join("\n");
}

function remapJobId<T>(value: T, sourceJobId: string, jobId: string): T {
  return replaceString(clone(value), sourceJobId, jobId) as T;
}

function materializeRunFixture(fixture: DemoRunFixture, runId: number): DemoRunFixture {
  const run = clone(fixture);
  const remapEvents = (events: RunEventRecord[]) =>
    events.map((event, index) => ({
      ...event,
      id: runId * 1000 + index,
      run_id: runId,
    }));

  run.summary.id = runId;
  run.summary.events = remapEvents(run.summary.events);
  run.detail.id = runId;
  run.detail.events = remapEvents(run.detail.events);
  run.detail.pending_updates = run.detail.pending_updates.map((pending, index) => ({
    ...pending,
    id: runId * 100 + index,
    run_id: runId,
  }));
  run.log.run_id = runId;
  return run;
}

function filterPendingResponse(activeKeys: Set<string>): PendingResponse {
  const response = clone(fixtures.pending);
  response.items = response.items.filter((item) => activeKeys.has(cleanupLineKey(item)));
  response.count = response.items.length;
  response.grouping.groups = response.grouping.groups
    .map((group) => {
      const items = group.items.filter((item) =>
        activeKeys.has(cleanupLineKey(item)),
      );
      return {
        ...group,
        line_numbers: items.map((item) => item.line_no),
        items,
      };
    })
    .filter((group) => group.items.length > 0);
  response.grouping.unmatched = response.grouping.unmatched.filter((item) =>
    activeKeys.has(cleanupLineKey(item)),
  );
  return response;
}

function findGroupedLine(line: PendingCleanupLine): PendingLineFixture | null {
  for (const group of fixtures.pending.grouping.groups) {
    const item = group.items.find((candidate) => cleanupLineKey(candidate) === cleanupLineKey(line));
    if (item) {
      return pendingLineFixture(item, group.name, item.services[0] ?? "");
    }
  }
  const unmatched = fixtures.pending.grouping.unmatched.find(
    (candidate) => cleanupLineKey(candidate) === cleanupLineKey(line),
  );
  if (unmatched) {
    return pendingLineFixture(unmatched, "", unmatched.repo);
  }
  const item = fixtures.pending.items.find(
    (candidate) => cleanupLineKey(candidate) === cleanupLineKey(line),
  );
  return item ? pendingLineFixture(item, "", item.repo) : null;
}

function pendingLineFixture(
  item: PendingItem | PendingGroupedItem,
  stackName: string,
  serviceName: string,
): PendingLineFixture {
  return {
    line_no: item.line_no,
    raw: item.raw,
    image: item.image,
    desired_tag: item.desired_tag,
    digest: item.digest,
    repo: item.repo,
    target_image: "target_image" in item ? item.target_image : "",
    stack_name: stackName,
    service_name: serviceName,
    digest_provenance: item.digest_provenance,
  };
}

export class DemoApiState {
  private readonly activePendingLineKeys = new Set(
    fixtures.pending.items.map((item) => cleanupLineKey(item)),
  );
  policies = clone(fixtures.servicePolicies);
  snoozes = clone(fixtures.snoozes.all);
  tagExclusions = clone(fixtures.tagExclusions.all);
  runs = clone(fixtures.runs.summaries);
  private readonly runDetails = new Map(
    Object.entries(fixtures.runs.details).map(([id, detail]) => [
      Number(id),
      clone(detail),
    ]),
  );
  private readonly runLogs = new Map(
    Object.entries(fixtures.runs.logs).map(([id, log]) => [
      Number(id),
      clone(log),
    ]),
  );
  jobs = new Map<string, DemoJobRecord>();
  private readonly retagPreviewJobs = new Map<string, RetagPreviewJobResponse>();
  themePreference = "system";
  themePreferenceConfigured = false;
  onboardingDismissedAt = "";
  composeIgnorePaths =
    fixtures.settings.managed.find(
      (entry) => entry.key === "compose_ignore_paths",
    )?.value ?? "old";
  composeIgnorePathsConfigured = false;
  digestPinUpdates =
    fixtures.settings.managed.find(
      (entry) => entry.key === "digest_pin_updates",
    )?.value ?? "false";
  digestPinUpdatesConfigured = false;
  releaseNotesEnabled =
    fixtures.settings.managed.find(
      (entry) => entry.key === "release_notes_enabled",
    )?.value ?? "false";
  releaseNotesEnabledConfigured = false;
  coreUpdateTour: CoreUpdateTourResponse = {
    status: "not_started",
    step: "dashboard",
    updated_at: "",
  };
  private nextJob = 1;
  private nextRetagPreview = 1;
  private nextRun =
    Math.max(0, ...fixtures.runs.summaries.map((run) => run.id)) + 1;
  private nextAudit = 100;
  private nextSnooze =
    Math.max(0, ...fixtures.snoozes.all.map((snooze) => snooze.id)) + 1;
  private nextTagExclusion =
    Math.max(0, ...fixtures.tagExclusions.all.map((rule) => rule.id)) +
    1;

  session(): AuthSessionResponse {
    return clone(fixtures.auth.session);
  }

  setupStatus(): SetupStatusResponse {
    return clone(fixtures.auth.setupStatus);
  }

  status(): StatusResponse {
    return {
      ...clone(fixtures.status),
      version: DEMO_VERSION,
      pending_count: this.activePendingLineKeys.size,
    };
  }

  settings(): SettingsResponse {
    const settings = clone(fixtures.settings);
    this.updateManagedEntry(settings, "theme_preference", this.themePreference, this.themePreferenceConfigured);
    this.updateManagedEntry(
      settings,
      "onboarding_checklist",
      this.onboardingDismissedAt ? "dismissed" : "visible",
      Boolean(this.onboardingDismissedAt),
    );
    this.updateManagedEntry(
      settings,
      "compose_ignore_paths",
      this.composeIgnorePaths,
      this.composeIgnorePathsConfigured,
    );
    this.updateManagedEntry(
      settings,
      "digest_pin_updates",
      this.digestPinUpdates,
      this.digestPinUpdatesConfigured,
    );
    this.updateManagedEntry(
      settings,
      "release_notes_enabled",
      this.releaseNotesEnabled,
      this.releaseNotesEnabledConfigured,
    );
    return settings;
  }

  private updateManagedEntry(
    settings: SettingsResponse,
    key: string,
    value: string,
    configured: boolean,
  ): void {
    const entry = settings.managed.find((item) => item.key === key);
    if (!entry) {
      return;
    }
    entry.value = value;
    entry.source = configured ? "configured" : "default";
  }

  doctor(): DoctorResponse {
    return clone(fixtures.doctor);
  }

  diagnosticsSupportBundle(): DiagnosticsSupportBundleResponse {
    return {
      ...clone(fixtures.diagnostics),
      wudup_version: DEMO_VERSION,
      settings: this.settings(),
      doctor_result: this.doctor(),
      pending_summary: this.pendingResponse(),
      last_run_status: this.runs[0] ? clone(this.runs[0]) : null,
    };
  }

  onboardingChecklist(): OnboardingChecklistResponse {
    if (!this.onboardingDismissedAt) {
      return clone(fixtures.onboarding);
    }
    return {
      dismissed: true,
      dismissed_at: this.onboardingDismissedAt,
      all_passed: false,
      visible: false,
      items: [],
    };
  }

  dismissOnboarding(): OnboardingDismissResponse {
    this.onboardingDismissedAt = DEMO_NOW;
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
      updated_at: DEMO_NOW,
    };
    return clone(this.coreUpdateTour);
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
        if (!["system", "light", "dark"].includes(value)) {
          throw new Error("theme_preference must be system, light, or dark");
        }
        this.themePreference = value;
        this.themePreferenceConfigured = true;
        return;
      case "onboarding_checklist":
        if (!["visible", "dismissed"].includes(value)) {
          throw new Error("onboarding_checklist must be visible or dismissed");
        }
        this.onboardingDismissedAt = value === "dismissed" ? this.onboardingDismissedAt || DEMO_NOW : "";
        return;
      case "compose_ignore_paths":
        this.composeIgnorePaths = normalizeDemoComposeIgnorePaths(value);
        this.composeIgnorePathsConfigured = true;
        return;
      case "digest_pin_updates":
        if (!["false", "true"].includes(value)) {
          throw new Error("digest_pin_updates must be false or true");
        }
        this.digestPinUpdates = value;
        this.digestPinUpdatesConfigured = true;
        return;
      case "release_notes_enabled":
        if (!["false", "true"].includes(value)) {
          throw new Error("release_notes_enabled must be false or true");
        }
        this.releaseNotesEnabled = value;
        this.releaseNotesEnabledConfigured = true;
        return;
      default:
        throw new Error(`managed setting is not editable: ${key}`);
    }
  }

  pendingResponse(): PendingResponse {
    return filterPendingResponse(this.activePendingLineKeys);
  }

  updateTargets(): UpdateTargetsResponse {
    return clone(fixtures.updateTargets);
  }

  retagTargets(): RetagTargetsResponse {
    return clone(fixtures.retagTargets);
  }

  createRetagPlan(choices: RetagChoiceRequest[]): RetagPlanResponse {
    return clone(this.retagCase(choices).response);
  }

  createRetagPreviewJob(choices: RetagChoiceRequest[]): RetagPreviewJobResponse {
    const fixture = this.retagCase(choices).preview;
    const previewJobId = `demo-retag-preview-${this.nextRetagPreview++}`;
    const queued = this.materializeRetagPreviewJob(fixture.queued, previewJobId);
    const complete = this.materializeRetagPreviewJob(fixture.complete, previewJobId);
    this.retagPreviewJobs.set(previewJobId, complete);
    return queued;
  }

  retagPreviewJob(previewJobId: string): RetagPreviewJobResponse {
    const job = this.retagPreviewJobs.get(previewJobId);
    if (!job) {
      throw new Error("Demo retag preview job was not found.");
    }
    return clone(job);
  }

  private materializeRetagPreviewJob(
    response: RetagPreviewJobResponse,
    previewJobId: string,
  ): RetagPreviewJobResponse {
    const result = clone(response);
    const sourceId = response.preview_job_id;
    result.preview_job_id = previewJobId;
    result.progress = result.progress.map((event) => ({
      ...event,
      job_id: event.job_id === sourceId ? previewJobId : event.job_id,
    }));
    return result;
  }

  releaseNotes(): ReleaseNotesResponse {
    const activeLines = activeLineNumbers(this.activePendingLineKeys);
    const response = clone(fixtures.releaseNotes);
    response.items = response.items.filter((item) => activeLines.has(item.line_no));
    response.count = response.items.length;
    return response;
  }

  releaseNotifications(
    source: ReleaseNotificationSource,
    sent: boolean,
  ): ReleaseNotificationResponse {
    const releaseNotes = this.releaseNotes();
    const selectedLines =
      "line_numbers" in source
        ? new Set(source.line_numbers)
        : new Set(releaseNotes.items.map((item) => item.line_no));
    const pendingByLine = new Map(
      this.pendingResponse().items.map((item) => [item.line_no, item]),
    );
    const items = releaseNotes.items
      .filter((item) => selectedLines.has(item.line_no))
      .map((item) => {
        const pending = pendingByLine.get(item.line_no);
        const serviceKey = pending?.key ?? "";
        return {
          line_no: item.line_no,
          image: pending?.image || item.image_repo,
          service_key: serviceKey,
          title: item.title || item.release_tag || item.image_repo,
          description: item.upstream_repo || item.image_repo,
          status: item.status,
          release_tag: item.release_tag,
          upstream_repo: item.upstream_repo,
          links: item.links,
          triggers: [
            {
              id: "discord.releases",
              type: "discord",
              name: "releases",
            },
          ],
          skipped_reason: item.status === "ready" ? "" : item.error || item.status,
        };
      });
    const sendableCount = items.filter((item) => !item.skipped_reason).length;
    const embeds = items
      .filter((item) => !item.skipped_reason)
      .map((item) => ({
        title: item.title,
        description: item.description,
      }));
    return {
      enabled: true,
      destination: {
        type: "discord",
        configured: true,
        source: "DISCORD_RELEASES_WEBHOOK",
      },
      source: releaseNotes.source,
      source_file: releaseNotes.source_file,
      count: items.length,
      sendable_count: sendableCount,
      skipped_count: items.length - sendableCount,
      batches: embeds.length ? [{ embeds }] : [],
      items,
      wud_api: releaseNotes.wud_api,
      warnings: releaseNotes.warnings,
      sent,
      audit_run_id: sent ? 9004 : 0,
      error: "",
    };
  }

  securityScans(): SecurityScansResponse {
    const pending = this.pendingResponse();
    const items = pending.items.map((item, index) =>
      this.securityScanInfo(item, index),
    );
    return {
      source_file: pending.source_file,
      source: clone(pending.source),
      source_hash: pending.source_hash ?? "",
      scanning_enabled: true,
      scanner: "trivy",
      scan_mode: "registry",
      count: items.length,
      items,
      warnings: [],
    };
  }

  securityScanJob(): SecurityScanJobResponse {
    const result = this.securityScans();
    return {
      job_id: "demo-security-scan",
      status: "success",
      total_count: result.count,
      completed_count: result.count,
      result,
      error: "",
    };
  }

  private securityScanInfo(
    item: PendingItem,
    index: number,
  ): SecurityScanInfo {
    const reportedDigest = normalizeDemoDigest(item.digest);
    const platform = item.platform || pendingItemPlatform(item);
    const exact = Boolean(reportedDigest && platform);
    const hasFindings = index === 0 && exact;
    const counts =
      hasFindings
        ? { critical: 0, high: 1, medium: 2, low: 0, unknown: 0 }
        : EMPTY_SECURITY_COUNTS;
    const [platformOs = "", platformArchitecture = "", platformVariant = ""] =
      platform.split("/");

    return {
      line_no: item.line_no,
      state: exact ? (hasFindings ? "complete" : "not_scanned") : "unsupported",
      verdict: hasFindings ? "findings" : "unknown",
      scanner: "trivy",
      scanner_version: hasFindings ? "demo" : "",
      scanner_schema: hasFindings ? "trivy-json" : "",
      scanned_at: hasFindings ? DEMO_NOW : "",
      db_revision: "",
      db_updated_at: "",
      severity_counts: { ...counts },
      fixable_counts:
        hasFindings
          ? { critical: 0, high: 1, medium: 1, low: 0, unknown: 0 }
          : { ...EMPTY_SECURITY_COUNTS },
      unfixed_count: hasFindings ? 1 : 0,
      warnings:
        hasFindings ? ["Demo finding for candidate-only advisory display."] : [],
      error_code: "",
      error_message: "",
      subject: {
        subject_id: reportedDigest ? `${item.image}@${reportedDigest}` : "",
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        candidate_image: item.digest
          ? `${item.image}@${reportedDigest}`
          : item.image,
        canonical_registry: "",
        canonical_repository: item.repo,
        requested_ref: item.desired_tag,
        reported_digest: reportedDigest,
        index_digest: reportedDigest,
        manifest_digest: reportedDigest,
        platform,
        platform_os: item.platform_os || platformOs,
        platform_architecture: item.platform_architecture || platformArchitecture,
        platform_variant: item.platform_variant || platformVariant,
        platform_source: item.platform ? "wud" : "demo",
        identity_status: exact ? "exact" : "unsupported",
        warnings: [],
      },
    };
  }

  selfUpdate(): SelfUpdateResponse {
    return clone(fixtures.selfUpdate);
  }

  selfUpdatePlan(): SelfUpdatePlanResponse {
    return clone(fixtures.selfUpdatePlan);
  }

  createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
    _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): PlanResponse {
    const planCase = this.planCase(lineNumbers, allowTagUpdates, tagOverrides);
    this.requireActiveLines(lineNumbers);
    return clone(planCase.response);
  }

  cleanupPending(
    _cleanupId: string,
    lines: PendingCleanupLine[],
  ): PendingCleanupResponse {
    const unmatchedKeys = new Set(
      fixtures.pending.grouping.unmatched.map((line) => cleanupLineKey(line)),
    );
    return this.removePendingLines(lines, {
      requiredKeys: unmatchedKeys,
      reason: "unmatched",
      mode: "web-pending-cleanup",
      operation: "remove_unmatched_pending",
      statusReason: "removed-unmatched",
      staleError: "cleanup is stale",
    });
  }

  createRemovalPlan(lineNumbers: number[]): PendingRemovalPlanResponse {
    const removalCase = this.removalCase(lineNumbers);
    this.requireActiveLines(lineNumbers);
    return clone(removalCase.response);
  }

  removeSelectedPending(
    removalId: string,
    lines: PendingCleanupLine[],
  ): PendingCleanupResponse {
    const removal = fixtures.removalCases.find(
      (item) => item.response.removal_id === removalId,
    );
    if (!removal) {
      throw new Error("removal is stale");
    }
    const removalKeys = new Set(
      removal.response.lines.map((line) =>
        cleanupLineKey({ line_no: line.line_no, raw: line.raw }),
      ),
    );
    return this.removePendingLines(lines, {
      requiredKeys: removalKeys,
      reason: "selected",
      mode: "web-pending-removal",
      operation: "remove_selected_pending",
      statusReason: "removed-selected",
      staleError: "removal is stale",
    });
  }

  rescanPending(
    scope: PendingRescanScope,
    lines: PendingRescanLine[],
  ): PendingRescanResponse {
    return {
      status: "blocked",
      audit_run_id: 0,
      scope,
      requested_count: scope === "selected" ? lines.length : 0,
      watched_count: 0,
      skipped: [],
      wud_api: {
        ...clone(fixtures.pending.wud_api),
        detail: "Static demo mode cannot trigger WUD rescans.",
      },
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
    if (plan.plan_id !== planId) {
      throw new Error("Demo plan is stale.");
    }
    if (!plan.can_apply) {
      return this.createFailureJob("Demo plan is not applyable.");
    }
    const planCase = this.planCase(lineNumbers, allowTagUpdates, tagOverrides);
    const jobId = `demo-job-${this.nextJob++}`;
    return this.createJobFromFixture(
      jobId,
      planCase.jobTemplate ?? this.jobTemplateFromPlan(plan, jobId),
    );
  }

  createRetagJob(
    planId: string,
    choices: RetagChoiceRequest[],
  ): ApplyJobResponse {
    const retagCase = this.retagCase(choices);
    const plan = clone(retagCase.response);
    if (plan.plan_id !== planId) {
      throw new Error("Demo retag plan is stale.");
    }
    if (!plan.can_apply) {
      return this.createFailureJob("Demo retag plan is not applicable.");
    }
    if (!retagCase.jobTemplate) {
      throw new Error(STATIC_FIXTURE_ERROR);
    }
    return this.createJobFromFixture(`demo-retag-job-${this.nextJob++}`, retagCase.jobTemplate);
  }

  private createJobFromFixture(
    jobId: string,
    fixture: DemoGeneratedJobFixture,
  ): ApplyJobResponse {
    const materialized = remapJobId(fixture, fixture.queued.job_id, jobId);
    const record: DemoJobRecord = {
      job: clone(materialized.queued),
      log: {
        job_id: jobId,
        log_file: "",
        exists: true,
        content: "",
        truncated: false,
        max_bytes: materialized.log.max_bytes,
        error: "",
      },
      fixture: materialized,
      completed: false,
    };
    this.jobs.set(jobId, record);
    return clone(record.job);
  }

  private createFailureJob(error: string): ApplyJobResponse {
    const jobId = `demo-job-${this.nextJob++}`;
    const job: ApplyJobResponse = {
      job_id: jobId,
      status: "failure",
      run_id: null,
      log_file: "",
      started_at: null,
      finished_at: null,
      error,
      selected_line_numbers: [],
      progress: [],
    };
    const fixture: DemoGeneratedJobFixture = {
      queued: job,
      terminal: job,
      log: {
        job_id: jobId,
        log_file: "",
        exists: true,
        content: "",
        truncated: false,
        max_bytes: 65_536,
        error: "",
      },
      run: null,
      removeLineNumbers: [],
    };
    this.jobs.set(jobId, {
      job: clone(job),
      log: clone(fixture.log),
      fixture,
      completed: true,
    });
    return clone(job);
  }

  private jobTemplateFromPlan(
    plan: PlanResponse,
    jobId: string,
  ): DemoGeneratedJobFixture {
    const startedAt = "2026-05-30T20:12:26+00:00";
    const finishedAt = "2026-05-30T20:12:28+00:00";
    const logFile = `demo/logs/demo-apply-${jobId}.log`;
    const lineNumbers = plan.selected_line_numbers;
    const logContent = this.applyLogFromPlan(plan, startedAt, finishedAt, logFile);
    const run = this.runFixtureFromPlan(plan, startedAt, finishedAt, logFile, logContent);
    const progress = this.progressFromPlan(plan, jobId, startedAt, finishedAt);
    return {
      queued: {
        job_id: jobId,
        status: "queued",
        run_id: null,
        log_file: "",
        started_at: null,
        finished_at: null,
        error: "",
        selected_line_numbers: lineNumbers,
        progress: [],
      },
      terminal: {
        job_id: jobId,
        status: "success",
        run_id: 0,
        log_file: logFile,
        started_at: startedAt,
        finished_at: finishedAt,
        error: "",
        selected_line_numbers: lineNumbers,
        progress,
      },
      log: {
        job_id: jobId,
        log_file: logFile,
        exists: true,
        content: logContent,
        truncated: false,
        max_bytes: 65_536,
        error: "",
      },
      run,
      removeLineNumbers: lineNumbers,
    };
  }

  private progressFromPlan(
    plan: PlanResponse,
    jobId: string,
    startedAt: string,
    finishedAt: string,
  ): ApplyJobProgressEvent[] {
    const stack = plan.stacks[0];
    const services = plan.stacks.flatMap((item) => item.services);
    const lineNumbers = plan.selected_line_numbers;
    const event = (
      phase: string,
      status: ApplyJobProgressEvent["status"],
      message: string,
      createdAt: string,
    ): ApplyJobProgressEvent => ({
      job_id: jobId,
      phase,
      status,
      message,
      created_at: createdAt,
      stack: stack?.name ?? "",
      services,
      line_numbers: lineNumbers,
    });
    return [
      event("preflight", "success", "Demo preflight checks passed.", startedAt),
      event("pull", "running", "Pulling selected demo images.", finishedAt),
      event("pull", "success", "Images pulled and verified.", finishedAt),
      event("recreate", "running", "Recreating selected services.", finishedAt),
      event("recreate", "success", "Services were recreated.", finishedAt),
      event("health", "success", "Demo services reported healthy.", finishedAt),
      event("cleanup", "success", "Pending entries were reconciled.", finishedAt),
      event("completion", "success", "Updater completed successfully.", finishedAt),
    ];
  }

  private applyLogFromPlan(
    plan: PlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
  ): string {
    const lines = [
      `[${startedAt}] [INFO] docker-update-from-wud-v2`,
      `[${startedAt}] [INFO] WUD file: ${plan.source_file}`,
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
        if (line.action !== "tag-update") {
          lines.push(
            `[${startedAt}] [INFO] [${stack.name}] ${line.service}: ${line.image} -> ${line.target_image || line.image}`,
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

  private runFixtureFromPlan(
    plan: PlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
    logContent: string,
  ): DemoRunFixture {
    const planLines = plan.stacks.flatMap((stack) =>
      stack.lines.map((line) => ({ stack, line })),
    );
    const pending_updates = planLines.map(({ stack, line }, index) => ({
      id: index,
      run_id: 0,
      line_no: line.line_no,
      raw: line.raw,
      image: line.image,
      target_digest: line.digest_provenance?.target_digest ?? line.digest,
      desired_tag: line.desired_tag,
      service_key: `${stack.name}/${line.service}`,
      stack_name: stack.name,
      service_name: line.service,
      status: "success",
      status_reason: "demo fixture",
      created_at: startedAt,
      updated_at: finishedAt,
      metadata: { source: "demo" },
      digest_provenance: line.digest_provenance ?? null,
    }));
    const events = planLines.map(({ stack, line }, index): RunEventRecord => ({
      id: index,
      run_id: 0,
      created_at: finishedAt,
      service_name: line.service,
      stack_name: stack.name,
      image: line.image,
      target_image: line.target_image,
      old_image_id: "sha256:demo-old",
      new_image_id: "sha256:demo-new",
      old_digest: line.digest ? line.digest : "sha256:demo-old",
      new_digest: line.digest_provenance?.target_digest ?? "sha256:demo-new",
      status: "success",
      metadata: { source: "demo" },
      digest_provenance: line.digest_provenance ?? null,
    }));
    const verificationItems = pending_updates.map((item, index) => ({
      line_no: item.line_no,
      service_key: item.service_key,
      stack_name: item.stack_name,
      service_name: item.service_name,
      image: item.image,
      target_image: events[index]?.target_image ?? item.image,
      image_status: "new_image_running" as const,
      container_status: "recreated" as const,
      health_status: "passed" as const,
      wud_status: "removed" as const,
      follow_up_needed: false,
      summary: "Demo update verified.",
    }));
    const summary: RunSummary = {
      id: 0,
      started_at: startedAt,
      finished_at: finishedAt,
      status: "success",
      dry_run: false,
      mode: plan.mode,
      wud_file: plan.source_file,
      log_file: logFile,
      metadata: {
        source: "demo",
        summary: `updated ${planLines.length} services`,
      },
      events,
    };
    const detail: RunDetail = {
      ...summary,
      pending_updates,
      events,
      verification: {
        status: "verified",
        total_count: verificationItems.length,
        verified_count: verificationItems.length,
        needs_review_count: 0,
        items: verificationItems,
      },
    };
    return {
      summary,
      detail,
      log: {
        run_id: 0,
        log_file: logFile,
        exists: true,
        content: logContent,
        truncated: false,
        max_bytes: 262_144,
      },
    };
  }

  recordJobProgress(
    jobId: string,
    event: ApplyJobProgressEvent,
  ): ApplyJobProgressEvent | null {
    const record = this.jobs.get(jobId);
    if (!record) {
      return null;
    }
    if (record.job.status === "queued") {
      record.job = {
        ...record.job,
        status: "running",
        started_at: event.created_at,
      };
    }
    record.job = {
      ...record.job,
      progress: [...record.job.progress, clone(event)],
    };
    return clone(event);
  }

  jobProgress(jobId: string): ApplyJobProgressEvent[] {
    const record = this.jobs.get(jobId);
    return clone(record?.fixture.terminal.progress ?? []);
  }

  completeJob(jobId: string): DemoJobRecord | null {
    const record = this.jobs.get(jobId);
    if (!record || record.completed) {
      return record ?? null;
    }
    const runId = record.fixture.run ? this.nextRun++ : record.fixture.terminal.run_id;
    record.completed = true;
    record.job = {
      ...clone(record.fixture.terminal),
      run_id: runId,
    };
    record.log = clone(record.fixture.log);
    for (const lineNo of record.fixture.removeLineNumbers) {
      const line = fixtures.pending.items.find(
        (item) => item.line_no === lineNo,
      );
      if (line) {
        this.activePendingLineKeys.delete(cleanupLineKey(line));
      }
    }
    if (record.fixture.run && typeof runId === "number") {
      this.prependRun(materializeRunFixture(record.fixture.run, runId));
    }
    return record;
  }

  servicePolicies(): ServicePolicyRecord[] {
    return clone(this.policies);
  }

  snoozeRecords(state: SnoozeState): SnoozeRecord[] {
    const records = this.snoozes.map((snooze) => {
      const active =
        snooze.kind === "dependency" && snooze.wait_for_service_key
          ? this.dependencySnoozeActive(snooze)
          : snooze.active;
      return { ...snooze, active };
    });
    return clone(
      records.filter((snooze) => {
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

  private dependencySnoozeActive(snooze: SnoozeRecord): boolean {
    const [stackName, serviceName] = snooze.wait_for_service_key.split("/", 2);
    if (!stackName || !serviceName) {
      return snooze.active;
    }
    const createdAt = Date.parse(snooze.created_at);
    if (Number.isNaN(createdAt)) {
      return snooze.active;
    }
    const satisfied = this.runs.some((run) =>
      run.events.some((event) => {
        const eventCreatedAt = Date.parse(event.created_at);
        return (
          event.status === "success" &&
          event.stack_name === stackName &&
          event.service_name === serviceName &&
          !Number.isNaN(eventCreatedAt) &&
          eventCreatedAt >= createdAt
        );
      }),
    );
    return !satisfied;
  }

  tagExclusionRecords(status: TagExclusionStatusFilter): TagExclusionRuleRecord[] {
    return clone(
      this.tagExclusions.filter((rule) =>
        status === "all" ? true : rule.status === status,
      ),
    );
  }

  private upsertServicePolicy(
    operation: Extract<StateOperation, { kind: "upsert_service_policy" }>,
  ): StateOperationResponse {
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
    return this.operationResponse(
      operation.kind,
      "service_policy",
      policy.service_key,
      policy,
    );
  }

  stateOperation(operation: StateOperation): StateOperationResponse {
    if (operation.kind === "upsert_service_policy") {
      return this.upsertServicePolicy(operation);
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
        kind: "time",
        wait_for_service_key: "",
        metadata: { source: "demo" },
      };
      this.snoozes.unshift(snooze);
      return this.operationResponse(operation.kind, "snooze", String(snooze.id), snooze);
    }
    if (operation.kind === "create_dependency_snooze") {
      if (operation.service_key === operation.wait_for_service_key) {
        throw new Error("wait_for_service_key must be different from service_key");
      }
      const snooze: SnoozeRecord = {
        id: this.nextSnooze++,
        service_key: operation.service_key,
        snoozed_until: null,
        reason: operation.reason ?? "",
        created_at: nowIso(),
        active: true,
        kind: "dependency",
        wait_for_service_key: operation.wait_for_service_key,
        metadata: { source: "demo" },
      };
      this.snoozes.unshift(snooze);
      return this.operationResponse(
        operation.kind,
        "dependency_snooze",
        String(snooze.id),
        snooze,
      );
    }
    if (operation.kind === "delete_snooze") {
      this.snoozes = this.snoozes.filter(
        (snooze) =>
          snooze.id !== operation.snooze_id || snooze.kind === "dependency",
      );
      return this.operationResponse(
        operation.kind,
        "snooze",
        String(operation.snooze_id),
        null,
      );
    }
    if (operation.kind === "delete_dependency_snooze") {
      this.snoozes = this.snoozes.filter(
        (snooze) =>
          snooze.id !== operation.snooze_id || snooze.kind !== "dependency",
      );
      return this.operationResponse(
        operation.kind,
        "dependency_snooze",
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
      return this.operationResponse(
        operation.kind,
        "tag_exclusion",
        String(rule.id),
        rule,
      );
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
    return clone(this.runs);
  }

  runDetail(runId: number): RunDetail {
    const detail = this.runDetails.get(runId);
    if (!detail) {
      throw new Error(`Demo run ${runId} was not found`);
    }
    return clone(detail);
  }

  runLog(runId: number): RunLogResponse {
    const log = this.runLogs.get(runId);
    if (!log) {
      throw new Error(`Demo run ${runId} was not found`);
    }
    return clone(log);
  }

  private planCase(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
  ): DemoPlanCase {
    const selected = uniqueSortedNumbers(lineNumbers);
    const overrideLines = uniqueSortedNumbers(
      tagOverrides.map((override) => override.line_no),
    );
    const planCase = fixtures.planCases.find((candidate) => {
      if (
        candidate.request.allow_tag_updates !== allowTagUpdates ||
        !sameNumbers(candidate.request.line_numbers, selected)
      ) {
        return false;
      }
      if (overrideLines.length === 0) {
        return candidate.request.tag_override_lines.length === 0;
      }
      return (
        allowTagUpdates &&
        overrideLines.every((lineNo) =>
          candidate.tagTokens.some((token) => token.line_no === lineNo),
        )
      );
    });
    if (planCase) {
      return materializePlanCase(planCase, tagOverrides);
    }
    throw new Error(STATIC_FIXTURE_ERROR);
  }

  private removalCase(lineNumbers: number[]): DemoRemovalCase {
    const selected = uniqueSortedNumbers(lineNumbers);
    const removalCase = fixtures.removalCases.find((candidate) =>
      sameNumbers(candidate.request.line_numbers, selected),
    );
    if (removalCase) {
      return removalCase;
    }
    throw new Error(STATIC_FIXTURE_ERROR);
  }

  private retagCase(choices: RetagChoiceRequest[]): DemoRetagCase {
    const normalized = this.normalizedRetagChoices(choices);
    const retagCase = fixtures.retagCases.find((candidate) =>
      sameRetagChoices(candidate.request.choices, normalized),
    );
    if (retagCase) {
      return materializeRetagCase(retagCase);
    }
    throw new Error(STATIC_FIXTURE_ERROR);
  }

  private normalizedRetagChoices(
    choices: RetagChoiceRequest[],
  ): RetagChoiceRequest[] {
    const firstByService = new Map<string, RetagChoiceRequest>();
    for (const choice of choices) {
      if (!firstByService.has(choice.service_key)) {
        firstByService.set(choice.service_key, choice);
      }
    }
    const knownServices = new Set(
      fixtures.retagTargets.items.map((item) => item.service_key),
    );
    for (const serviceKey of firstByService.keys()) {
      if (!knownServices.has(serviceKey)) {
        throw new Error(STATIC_FIXTURE_ERROR);
      }
    }
    return fixtures.retagTargets.items.map((item) => {
      const requested = firstByService.get(item.service_key);
      const choice = requested?.choice ?? "keep-current";
      const targetTag = requested?.target_tag?.trim() ?? "";
      const normalized: RetagChoiceRequest = {
        service_key: item.service_key,
        choice,
      };
      if (choice === "switch-to-concrete" && targetTag) {
        normalized.target_tag = targetTag;
      }
      return normalized;
    });
  }

  private requireActiveLines(lineNumbers: number[]): void {
    const active = activeLineNumbers(this.activePendingLineKeys);
    if (!lineNumbers.every((lineNo) => active.has(lineNo))) {
      throw new Error("Demo fixture line is no longer active.");
    }
  }

  private removePendingLines(
    lines: PendingCleanupLine[],
    options: {
      requiredKeys: Set<string>;
      reason: string;
      mode: string;
      operation: string;
      statusReason: string;
      staleError: string;
    },
  ): PendingCleanupResponse {
    const requested = new Set(lines.map((line) => cleanupLineKey(line)));
    const removed = lines.map((line) => findGroupedLine(line));
    if (
      requested.size === 0 ||
      requested.size !== lines.length ||
      removed.includes(null) ||
      [...requested].some(
        (key) => !this.activePendingLineKeys.has(key) || !options.requiredKeys.has(key),
      )
    ) {
      throw new Error(options.staleError);
    }
    for (const key of requested) {
      this.activePendingLineKeys.delete(key);
    }
    const removedLines = removed.filter((line): line is PendingLineFixture =>
      Boolean(line),
    );
    const runId = this.nextRun++;
    this.prependRun(
      this.pendingRemovalRun(
        runId,
        removedLines,
        options.mode,
        options.operation,
        options.statusReason,
      ),
    );
    return {
      status: "success",
      audit_run_id: runId,
      removed_count: removedLines.length,
      removed: removedLines.map((line) => ({
        line_no: line.line_no,
        raw: line.raw,
        image: line.image,
        reason: options.reason,
      })),
    };
  }

  private pendingRemovalRun(
    runId: number,
    removedLines: PendingLineFixture[],
    mode: string,
    operation: string,
    statusReason: string,
  ): DemoRunFixture {
    const startedAt = "2026-05-30T20:12:26+00:00";
    const events = removedLines.map((line, index): RunEventRecord => ({
      id: runId * 1000 + index,
      run_id: runId,
      created_at: startedAt,
      service_name: line.service_name,
      stack_name: line.stack_name,
      image: line.image,
      target_image: line.target_image,
      old_image_id: "",
      new_image_id: "",
      old_digest: "",
      new_digest: "",
      status: "success",
      metadata: { source: "demo" },
      digest_provenance: line.digest_provenance ?? null,
    }));
    const pending_updates = removedLines.map((line, index) => ({
      id: runId * 100 + index,
      run_id: runId,
      line_no: line.line_no,
      raw: line.raw,
      image: line.image,
      target_digest: line.digest,
      desired_tag: line.desired_tag,
      service_key: line.stack_name
        ? `${line.stack_name}/${line.service_name}`
        : line.repo,
      stack_name: line.stack_name,
      service_name: line.service_name,
      status: "resolved",
      status_reason: statusReason,
      created_at: startedAt,
      updated_at: startedAt,
      metadata: { source: "demo" },
      digest_provenance: line.digest_provenance ?? null,
    }));
    const summary: RunSummary = {
      id: runId,
      started_at: startedAt,
      finished_at: startedAt,
      status: "success",
      dry_run: false,
      mode,
      wud_file: fixtures.pending.source_file,
      log_file: "",
      metadata: {
        source: "demo",
        operation,
        line_numbers: removedLines.map((line) => line.line_no),
      },
      events,
    };
    const detail: RunDetail = {
      ...summary,
      pending_updates,
      verification: {
        status: "verified",
        total_count: pending_updates.length,
        verified_count: pending_updates.length,
        needs_review_count: 0,
        items: pending_updates.map((line) => ({
          line_no: line.line_no,
          service_key: line.service_key,
          stack_name: line.stack_name,
          service_name: line.service_name,
          image: line.image,
          target_image: "",
          image_status: "already_current",
          container_status: "skipped",
          health_status: "skipped",
          wud_status: "removed",
          follow_up_needed: false,
          summary: "Pending fixture line removed from the browser session.",
        })),
      },
    };
    return {
      summary,
      detail,
      log: {
        run_id: runId,
        log_file: "",
        exists: true,
        content: "Removed pending demo fixture entries.\n",
        truncated: false,
        max_bytes: 262_144,
      },
    };
  }

  private prependRun(run: DemoRunFixture): void {
    this.runs = [clone(run.summary), ...this.runs];
    this.runDetails.set(run.summary.id, clone(run.detail));
    this.runLogs.set(run.summary.id, clone(run.log));
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
}
