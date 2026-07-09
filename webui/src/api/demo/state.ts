import type {
  ApplyJobProgressEvent,
  ApplyJobResponse,
  AuthSessionResponse,
  CoreUpdateTourResponse,
  DiagnosticsSupportBundleResponse,
  DigestPinLabelRewriteApprovalRequest,
  DoctorResponse,
  OnboardingChecklistResponse,
  PendingItem,
  PendingMetadataRefreshRequest,
  PendingMetadataRefreshResponse,
  PendingRescanLine,
  PendingResponse,
  PendingRescanResponse,
  PendingRescanScope,
  PlanResponse,
  ReleaseNotesResponse,
  RetagChoiceRequest,
  RetagPreviewJobResponse,
  RetagPlanResponse,
  RetagTargetItem,
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
} from "./helpers";
import type {
  DemoGeneratedFixtures,
  DemoGeneratedJobFixture,
  DemoJobRecord,
  DemoRunFixture,
} from "./types";
import {
  normalizeSecurityDigest,
  pendingItemPlatform,
} from "../../utils/securityScans";

const fixtures: DemoGeneratedFixtures = generatedFixtures;
const DEMO_NOW = "2026-05-31T00:00:00.000Z";
const TAG_VALUE_PATTERN = /^\w[\w.-]{0,127}$/;
const EMPTY_SECURITY_COUNTS: SecurityScanSeverityCounts = {
  critical: 0,
  high: 0,
  medium: 0,
  low: 0,
  unknown: 0,
};
const DEMO_FINDING_SECURITY_COUNTS: SecurityScanSeverityCounts = {
  critical: 0,
  high: 1,
  medium: 0,
  low: 0,
  unknown: 0,
};
type DemoSecurityScanDecision = {
  hasFindings: boolean;
  state: SecurityScanInfo["state"];
  verdict: SecurityScanInfo["verdict"];
};

function activeLineNumbers(activeKeys: Set<string>): Set<number> {
  return new Set(
    fixtures.pending.items
      .filter((item) => activeKeys.has(cleanupLineKey(item)))
      .map((item) => item.line_no),
  );
}

function uniqueSortedNumbers(values: number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

function demoNotificationKey(lineNo: number): string {
  return `demo-release-notification-${lineNo}`;
}

function retagTargetKey(item: RetagTargetItem): string {
  return item.target_id || item.service_key;
}

function retagChoiceKey(choice: RetagChoiceRequest): string {
  return choice.target_id || choice.service_key;
}

function lookupRetagChoiceTarget(
  choice: RetagChoiceRequest,
  targetById: Map<string, RetagTargetItem>,
  targetByUniqueService: Map<string, RetagTargetItem>,
): RetagTargetItem | undefined {
  if (choice.target_id) {
    return targetById.get(choice.target_id);
  }
  return targetByUniqueService.get(choice.service_key);
}

function demoIdPart(value: string): string {
  let result = "";
  let needsSeparator = false;
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    const isAllowed =
      (code >= 48 && code <= 57)
      || (code >= 65 && code <= 90)
      || (code >= 97 && code <= 122)
      || char === "_"
      || char === "."
      || char === "-";
    if (isAllowed) {
      if (needsSeparator && result !== "") {
        result += "-";
      }
      result += char;
      needsSeparator = false;
    } else if (result !== "") {
      needsSeparator = true;
    }
  }
  let start = 0;
  let end = result.length;
  while (start < end && result[start] === "-") {
    start += 1;
  }
  while (end > start && result[end - 1] === "-") {
    end -= 1;
  }
  return result.slice(start, end) || "item";
}

function replaceTagReference(value: string, defaultTag: string, tag: string): string {
  return value
    .replaceAll(`tag=${defaultTag}`, `tag=${tag}`)
    .replaceAll(`:${defaultTag}`, `:${tag}`);
}

function materializeTagOverride<T extends PendingResponse["grouping"]["unmatched"][number]>(
  item: T,
  tagOverrides: Map<number, string>,
): T {
  const tag = tagOverrides.get(item.line_no);
  if (!tag) {
    return item;
  }
  return {
    ...item,
    raw: replaceTagReference(item.raw, item.desired_tag, tag),
    desired_tag: tag,
    target_image: replaceTagReference(item.target_image, item.desired_tag, tag),
  };
}

function tagOverridesByLine(
  pending: PendingResponse,
  selectedLineNumbers: number[],
  allowTagUpdates: boolean,
  tagOverrides: TagOverrideRequest[],
): Map<number, string> {
  const overrides = new Map<number, string>();
  for (const item of tagOverrides) {
    if (overrides.has(item.line_no)) {
      throw new Error(`tag_overrides line ${item.line_no} was provided more than once`);
    }
    if (!TAG_VALUE_PATTERN.test(item.tag)) {
      throw new Error(`tag_overrides line ${item.line_no} has invalid tag: ${item.tag}`);
    }
    overrides.set(item.line_no, item.tag);
  }
  if (overrides.size === 0) {
    return overrides;
  }
  if (!allowTagUpdates) {
    throw new Error("tag_overrides require allow_tag_updates=true");
  }
  const selected = new Set(selectedLineNumbers);
  const pendingByLine = new Map(pending.items.map((item) => [item.line_no, item]));
  const missing = [...overrides.keys()].filter((lineNo) => !selected.has(lineNo));
  if (missing.length) {
    throw new Error(
      `tag_overrides must reference selected WUD tag update lines: ${missing.join(", ")}`,
    );
  }
  for (const lineNo of overrides.keys()) {
    if (!pendingByLine.get(lineNo)?.desired_tag) {
      throw new Error(`tag_overrides line ${lineNo} does not target a tag update`);
    }
  }
  return overrides;
}

function validateDigestPinLabelRewriteApprovals(
  approvals: DigestPinLabelRewriteApprovalRequest[],
): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const item of approvals) {
    const key = [
      item.stack,
      item.service,
      item.label_key,
      item.current_label_value,
      item.planned_tag,
      item.proposed_label_value,
    ].join("\0");
    if (seen.has(key)) {
      throw new Error("digest_pin_label_rewrite_approvals contains a duplicate approval");
    }
    if (item.label_key !== "wud.tag.include") {
      throw new Error("digest_pin_label_rewrite_approvals can only approve wud.tag.include");
    }
    if (!TAG_VALUE_PATTERN.test(item.planned_tag)) {
      throw new Error("digest_pin_label_rewrite_approvals has an invalid planned tag");
    }
    seen.add(key);
    parts.push(`${item.stack}-${item.service}-${item.planned_tag}`);
  }
  return parts.map(demoIdPart).join("-");
}

function planIdFor(
  selectedLineNumbers: number[],
  allowTagUpdates: boolean,
  tagOverrides: Map<number, string>,
  digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
): string {
  const parts = [
    `demo-session-${selectedLineNumbers.join("-") || "empty"}`,
    allowTagUpdates ? "allow-tags" : "block-tags",
  ];
  if (tagOverrides.size) {
    parts.push(
      [...tagOverrides.entries()]
        .sort(([left], [right]) => left - right)
        .map(([lineNo, tag]) => `${lineNo}-${demoIdPart(tag)}`)
        .join("-"),
    );
  }
  const approvalPart = validateDigestPinLabelRewriteApprovals(
    digestPinLabelRewriteApprovals,
  );
  if (approvalPart) {
    parts.push(approvalPart);
  }
  return parts.join("-");
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
  const response: PendingResponse = clone(fixtures.pending);
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

function readOnlyPlanFromPending(
  pending: PendingResponse,
  selectedLineNumbers: number[],
  allowTagUpdates: boolean,
  tagOverrides: TagOverrideRequest[],
  digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
): PlanResponse {
  const selected = new Set(selectedLineNumbers);
  const overrides = tagOverridesByLine(
    pending,
    selectedLineNumbers,
    allowTagUpdates,
    tagOverrides,
  );
  const selectedGroups = pending.grouping.groups
    .map((group) => ({
      ...group,
      items: group.items
        .filter((item) => selected.has(item.line_no))
        .map((item) => materializeTagOverride(item, overrides)),
    }))
    .filter((group) => group.items.length > 0);
  const selectedUnmatchedItems = pending.grouping.unmatched
    .filter((item) => selected.has(item.line_no))
    .map((item) => materializeTagOverride(item, overrides));
  const tagUpdatesDisabled = [
    ...selectedGroups.flatMap((group) => group.items),
    ...selectedUnmatchedItems,
  ].filter((item) => item.desired_tag && !allowTagUpdates);
  const matchedGroups = selectedGroups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => allowTagUpdates || !item.desired_tag,
      ),
    }))
    .filter((group) => group.items.length > 0);
  const selectedUnmatched = selectedUnmatchedItems.filter(
    (item) => allowTagUpdates || !item.desired_tag,
  );
  const stacks = matchedGroups.map((group) => readOnlyPlanStack(group));
  const matchedTargets = stacks.flatMap((stack) =>
    stack.lines.map((line) => ({
      line_no: line.line_no,
      raw: line.raw,
      image: line.image,
      resolved_image: line.resolved_image,
      digest: line.digest,
      desired_tag: line.desired_tag,
      matched: true,
      action: line.action,
    })),
  );
  const skipped = [
    ...tagUpdatesDisabled.map((item) => ({
      line_no: item.line_no,
      raw: item.raw,
      image: item.image,
      desired_tag: item.desired_tag,
      reason: "tag-updates-disabled",
    })),
    ...selectedUnmatched.map((item) => ({
      line_no: item.line_no,
      raw: item.raw,
      image: item.image,
      desired_tag: item.desired_tag,
      reason: item.diagnostic?.code ?? "unmatched",
    })),
  ];
  const issues = selectedUnmatched.map((item) => ({
    severity: "error",
    code: item.diagnostic?.code ?? "unmatched",
    message:
      item.diagnostic?.message ??
      "This pending update is not matched to a discovered Compose service.",
    line_no: item.line_no,
    stack: item.diagnostic?.stack ?? "",
    service: item.diagnostic?.service ?? "",
    hint: item.diagnostic?.hint ?? "",
    details: item.diagnostic?.details ?? {},
  }));
  const serviceCount = new Set(
    stacks.flatMap((stack) =>
      stack.lines.map((line) => `${stack.name}/${line.service}`),
    ),
  ).size;

  let status: PlanResponse["status"] = "empty";
  if (issues.length > 0 || (stacks.length > 0 && skipped.length > 0)) {
    status = "blocked";
  } else if (stacks.length > 0) {
    status = "ready";
  }
  const applyable = status === "ready";

  return {
    plan_id: planIdFor(
      selectedLineNumbers,
      allowTagUpdates,
      overrides,
      digestPinLabelRewriteApprovals,
    ),
    dry_run: true,
    can_apply: applyable,
    status,
    source_file: pending.source_file,
    source: clone(pending.source),
    mode: "stop",
    max_wait: 180,
    digest_pin_updates: false,
    selected_line_numbers: selectedLineNumbers,
    summary: {
      target_count: selectedLineNumbers.length,
      matched_target_count: matchedTargets.length,
      stack_count: stacks.length,
      service_count: serviceCount,
      skipped_count: skipped.length,
      issue_count: issues.length,
    },
    targets: [
      ...matchedTargets,
      ...selectedUnmatched.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        resolved_image: item.resolved_image,
        digest: item.digest,
        desired_tag: item.desired_tag,
        matched: false,
        action: item.action,
      })),
      ...tagUpdatesDisabled.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        resolved_image: item.resolved_image,
        digest: item.digest,
        desired_tag: item.desired_tag,
        matched: false,
        action: "tag-updates-disabled",
      })),
    ],
    stacks,
    skipped,
    issues,
    cleanup: {
      cleanup_id: "demo-session-cleanup",
      can_remove_unmatched: false,
      items: selectedUnmatched.map((item) => ({
        line_no: item.line_no,
        raw: item.raw,
        image: item.image,
        desired_tag: item.desired_tag,
        digest: item.digest,
        reason: item.diagnostic?.code ?? "unmatched",
        diagnostic: item.diagnostic,
      })),
    },
    apply_preflight: {
      ok: applyable,
      failures: applyable ? 0 : 1,
      warnings: 0,
      checks: [
        {
          status: applyable ? "PASS" : "FAIL",
          code: "static-demo-session-job",
          label: "Static demo session job",
          detail: applyable
            ? "Apply runs as a browser-only demo job and resets on reload."
            : "Only matched demo pending updates can be applied in the static demo.",
          source_check_codes: [],
        },
      ],
    },
  };
}

function readOnlyPlanStack(
  group: PendingResponse["grouping"]["groups"][number],
): PlanResponse["stacks"][number] {
  const lines = group.items.map((item) => {
    const composeImage = item.compose_images[0] ?? item.resolved_image;
    return {
      line_no: item.line_no,
      raw: item.raw,
      image: item.image,
      resolved_image: item.resolved_image,
      compose_image: composeImage,
      target_image: item.target_image || item.resolved_image,
      service: item.services[0] ?? item.repo,
      digest: item.digest,
      desired_tag: item.desired_tag,
      action: item.action,
      digest_provenance: item.digest_provenance ?? null,
    };
  });
  const services = [...new Set(lines.map((line) => line.service))];
  return {
    name: group.name,
    directory: group.directory,
    compose_file: group.compose_file,
    project_directory: group.project_directory,
    services_label: group.services_label,
    services,
    pull_services: services,
    stop_services: services,
    force_recreate: lines.some((line) => line.action !== "tag-update"),
    up_no_deps: true,
    tag_updates: lines
      .filter((line) => line.action === "tag-update")
      .map((line) => ({
        old_image: line.compose_image,
        desired_tag: line.desired_tag,
        new_image: line.target_image,
        services: [line.service],
      })),
    digest_pin_updates: [],
    digest_unpin_updates: [],
    actions: [],
    lines,
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
  coreUpdateTour: CoreUpdateTourResponse = {
    status: "not_started",
    step: "dashboard",
    updated_at: "",
  };
  private nextJob = 1;
  private nextRetagPreview = 1;
  private nextRun =
    Math.max(0, ...fixtures.runs.summaries.map((run) => run.id)) + 1;

  session(): AuthSessionResponse {
    return {
      ...clone(fixtures.auth.session),
      dev_auth_bypass: false,
      mutations_enabled: false,
    };
  }

  setupStatus(): SetupStatusResponse {
    return {
      ...clone(fixtures.auth.setupStatus),
      dev_auth_bypass: false,
      mutations_enabled: false,
    };
  }

  status(): StatusResponse {
    return {
      ...clone(fixtures.status),
      version: DEMO_VERSION,
      dev_auth_bypass: false,
      mutations_enabled: false,
      auto_update_scheduler_enabled: false,
      pending_count: this.pendingResponse().count,
      source_hash: this.pendingResponse().source_hash ?? "",
    };
  }

  settings(): SettingsResponse {
    const settings = clone(fixtures.settings);
    this.updateSettingsEntry(settings.webui, "WUD_WEB_DEV_NO_AUTH", "false", false, "default");
    this.updateSettingsEntry(
      settings.webui,
      "WUD_WEB_MUTATIONS_ENABLED",
      "false",
      false,
      "default",
    );
    this.updateSettingsEntry(
      settings.webui,
      "WUD_WEB_AUTO_UPDATE_SCHEDULER_ENABLED",
      "false",
      false,
      "derived",
    );
    return settings;
  }

  private updateSettingsEntry(
    entries: SettingsResponse["webui"],
    name: string,
    value: string,
    configured: boolean,
    source: SettingsResponse["webui"][number]["source"],
  ): void {
    const entry = entries.find((item) => item.name === name);
    if (!entry) {
      return;
    }
    entry.value = value;
    entry.configured = configured;
    entry.source = source;
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
    return clone(fixtures.onboarding);
  }

  pendingResponse(): PendingResponse {
    return filterPendingResponse(this.activePendingLineKeys);
  }

  pendingMetadata(
    request: PendingMetadataRefreshRequest,
  ): PendingMetadataRefreshResponse {
    const pending = this.pendingResponse();
    if ((pending.source_hash ?? "") !== request.source_hash) {
      return this.stalePendingMetadata(pending);
    }
    const byLine = new Map(pending.items.map((item) => [item.line_no, item]));
    const items: PendingMetadataRefreshResponse["items"] = [];
    for (const line of request.lines) {
      const item = byLine.get(line.line_no);
      if (item?.raw !== line.raw || item?.source_id !== line.source_id) {
        return this.stalePendingMetadata(pending);
      }
      items.push({
        line_no: item.line_no,
        raw: item.raw,
        source_id: item.source_id,
        wud_metadata: item.wud_metadata ?? null,
      });
    }
    return {
      status: "ready",
      requires_pending_reload: false,
      source_hash: pending.source_hash ?? "",
      wud_api: pending.wud_api,
      items,
    };
  }

  private stalePendingMetadata(
    pending: PendingResponse,
  ): PendingMetadataRefreshResponse {
    return {
      status: "stale",
      requires_pending_reload: true,
      source_hash: pending.source_hash ?? "",
      wud_api: pending.wud_api,
      items: [],
    };
  }

  updateTargets(): UpdateTargetsResponse {
    return clone(fixtures.updateTargets);
  }

  retagTargets(): RetagTargetsResponse {
    return clone(fixtures.retagTargets);
  }

  createRetagPlan(choices: RetagChoiceRequest[]): RetagPlanResponse {
    return this.retagPlanFromChoices(choices);
  }

  createRetagPreviewJob(choices: RetagChoiceRequest[]): RetagPreviewJobResponse {
    const previewJobId = `demo-retag-preview-${this.nextRetagPreview++}`;
    const plan = this.createRetagPlan(choices);
    const complete: RetagPreviewJobResponse = {
      preview_job_id: previewJobId,
      status: plan.issues.length ? "failure" : "success",
      plan,
      warnings: plan.warnings,
      error: plan.issues[0]?.message ?? "",
      progress: [
        {
          job_id: previewJobId,
          phase: "compose-digest-pin",
          status: plan.issues.length ? "failure" : "success",
          message: plan.issues.length
            ? "Demo retag preview found an invalid selection."
            : "Demo retag preview generated from current fixture data.",
          created_at: "2026-05-30T20:12:26+00:00",
          stack: plan.stacks[0]?.stack ?? "",
          services: plan.stacks.flatMap((stack) => stack.services),
          line_numbers: [],
        },
      ],
    };
    this.retagPreviewJobs.set(previewJobId, complete);
    return clone(complete);
  }

  retagPreviewJob(previewJobId: string): RetagPreviewJobResponse {
    const job = this.retagPreviewJobs.get(previewJobId);
    if (!job) {
      throw new Error("Demo retag preview job was not found.");
    }
    return clone(job);
  }

  private retagPlanFromChoices(choices: RetagChoiceRequest[]): RetagPlanResponse {
    const normalized = this.normalizedRetagChoices(choices);
    const selected = normalized
      .map((choice) => ({
        choice,
        item: fixtures.retagTargets.items.find(
          (item) => retagTargetKey(item) === retagChoiceKey(choice),
        ),
      }))
      .filter(
        (
          entry,
        ): entry is { choice: RetagChoiceRequest; item: RetagTargetItem } =>
          Boolean(entry.item) && entry.choice.choice === "switch-to-concrete",
      );
    const issues = selected
      .filter(({ item, choice }) => !this.retagTargetTag(item, choice))
      .map(({ item }) => ({
        severity: "error",
        code: "missing-target-tag",
        message: `${item.service_key} needs a concrete target tag.`,
        service_key: item.service_key,
        stack: item.stack,
        service: item.service,
        hint: "Choose a concrete tag before applying the retag plan.",
        details: {},
      }));
    const updates = selected
      .filter(({ item, choice }) => this.retagTargetTag(item, choice))
      .map(({ item, choice }) => this.retagPlanUpdate(item, choice));
    const stacks = fixtures.retagTargets.items
      .map((item) => ({
        stack: item.stack,
        directory: item.directory,
        compose_file: item.compose_file,
        project_directory: item.project_directory,
      }))
      .filter(
        (stack, index, stacks) =>
          stacks.findIndex(
            (candidate) =>
              candidate.stack === stack.stack &&
              candidate.directory === stack.directory &&
              candidate.compose_file === stack.compose_file &&
              candidate.project_directory === stack.project_directory,
          ) === index,
      )
      .map((stack) => ({
        ...stack,
        services: updates
          .filter((update) => update.stack === stack.stack)
          .map((update) => update.service),
        digest_pin_updates: updates.filter(
          (update) =>
            update.stack === stack.stack &&
            fixtures.retagTargets.items.some(
              (item) =>
                item.service_key === update.service_key &&
                item.directory === stack.directory &&
                item.compose_file === stack.compose_file &&
                item.project_directory === stack.project_directory,
            ),
        ),
      }))
      .filter((stack) => stack.digest_pin_updates.length > 0);
    const selectedCount = updates.length;
    let status: RetagPlanResponse["status"] = "empty";
    if (selectedCount > 0) {
      status = issues.length > 0 ? "blocked" : "ready";
    }
    return {
      plan_id:
        selectedCount === 0
          ? "demo-retag-empty"
          : `demo-retag-${updates
              .map((update) => `${demoIdPart(update.service_key)}-${demoIdPart(update.resolved_tag)}`)
              .join("-")}`,
      status,
      can_apply: selectedCount > 0 && issues.length === 0,
      external_recreate_required: true,
      selected_count: selectedCount,
      keep_current_count: normalized.length - selectedCount,
      stacks,
      issues,
      warnings: [
        "Static demo retag apply is session-local and does not edit Compose files.",
      ],
    };
  }

  private retagPlanUpdate(
    item: RetagTargetItem,
    choice: RetagChoiceRequest,
  ): RetagPlanResponse["stacks"][number]["digest_pin_updates"][number] {
    const tag = this.retagTargetTag(item, choice);
    const finalImage = this.retagFinalImage(item, tag);
    return {
      target_id: retagTargetKey(item),
      service_key: item.service_key,
      stack: item.stack,
      service: item.service,
      source_image: item.image,
      resolved_tag: tag,
      planned_digest: item.digest_provenance?.target_digest ?? "",
      final_image: finalImage,
      watch_tag: item.tracking_tag,
      marker: item.target_id || item.service_key,
      label_key: item.label_key,
      label_value: item.label_value,
      label_rewrites: item.label_key
        ? [
            {
              service: item.service,
              label_key: item.label_key,
              current_label_value: item.label_value,
              planned_tag: tag,
              proposed_label_value: item.label_value
                ? item.label_value.replace(item.tracking_tag, tag)
                : tag,
              proposed_label_regex: "",
              approved: true,
              reason: "demo",
            },
          ]
        : [],
      digest_provenance: item.digest_provenance ?? null,
    };
  }

  private retagTargetTag(
    item: RetagTargetItem,
    choice: RetagChoiceRequest,
  ): string {
    const tag = choice.target_tag?.trim() || item.proposed_tag;
    return tag && tag !== "latest" ? tag : "";
  }

  private retagFinalImage(item: RetagTargetItem, tag: string): string {
    if (!tag) {
      return item.final_image;
    }
    if (item.final_image.includes(`:${item.proposed_tag}`)) {
      return item.final_image.replace(`:${item.proposed_tag}`, `:${tag}`);
    }
    return `${item.image_repo}:${tag}`;
  }

  releaseNotes(): ReleaseNotesResponse {
    const activeLines = activeLineNumbers(this.activePendingLineKeys);
    const fixture = clone(fixtures.releaseNotes);
    const response: ReleaseNotesResponse = {
      ...fixture,
      items: [],
    };
    response.items = fixture.items
      .filter((item) => activeLines.has(item.line_no))
      .map((item) => {
        const notificationKey =
          item.notification_key || demoNotificationKey(item.line_no);
        return {
          ...item,
          notification_key: notificationKey,
          notification_status: item.notification_status || "new",
          notification_last_sent_at: item.notification_last_sent_at || "",
          notification_send_count: item.notification_send_count || 0,
          notification_skipped_reason:
            item.notification_skipped_reason || "",
        };
      });
    response.count = response.items.length;
    return response;
  }

  securityScans(): SecurityScansResponse {
    const pending = this.pendingResponse();
    let seenReviewCandidate = false;
    const items = pending.items.map((item) => {
      const exactCandidate = Boolean(
        normalizeSecurityDigest(item.digest) && pendingItemPlatform(item),
      );
      const reviewCandidate =
        exactCandidate && !seenReviewCandidate;
      seenReviewCandidate ||= reviewCandidate;
      return this.securityScanInfo(item, reviewCandidate);
    });
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

  securityScanJob(jobId = "demo-security-scan"): SecurityScanJobResponse {
    const result = this.securityScans();
    return {
      job_id: jobId,
      status: "success",
      total_count: result.count,
      completed_count: result.count,
      result,
      error: "",
    };
  }

  private securityScanInfo(
    item: PendingItem,
    firstExact: boolean,
  ): SecurityScanInfo {
    const reportedDigest = normalizeSecurityDigest(item.digest);
    const platform = pendingItemPlatform(item);
    const decision = this.securityScanDecision(reportedDigest, platform, firstExact);
    const severityCounts = this.securityScanSeverityCounts(decision.hasFindings);
    const fixableCounts = this.securityScanSeverityCounts(decision.hasFindings);
    const findings = decision.hasFindings
      ? [
          {
            vulnerability_id: "CVE-2026-0001",
            package_name: "demo-package",
            installed_version: "1.0.0",
            fixed_version: "1.0.1",
            severity: "high" as const,
            title: "Demo vulnerability for candidate advisory review",
            primary_url: "https://avd.aquasec.com/nvd/cve-2026-0001",
          },
        ]
      : [];
    const subject = {
      requested_ref: item.image,
      reported_digest: reportedDigest,
      manifest_digest: reportedDigest,
      platform,
    };
    const currentDigest = normalizeSecurityDigest(item.wud_metadata?.local_digest ?? "");
    const currentSubject = {
      requested_ref: item.image,
      reported_digest: currentDigest,
      manifest_digest: currentDigest,
      platform,
    };
    const canCompare = Boolean(currentDigest && reportedDigest && platform);
    const comparisonReady = decision.state === "complete" && canCompare;
    let comparisonMessage = "";
    if (comparisonReady) {
      comparisonMessage =
        "Demo comparison: installed and candidate findings are unchanged.";
    } else if (decision.state === "complete") {
      comparisonMessage = "Installed digest is unavailable in the demo fixture.";
    }

    return {
      line_no: item.line_no,
      state: decision.state,
      verdict: decision.verdict,
      scanner: "trivy",
      scanner_version: decision.hasFindings ? "demo" : "",
      scanner_schema: decision.hasFindings ? "trivy-json" : "",
      scanned_at: decision.hasFindings ? DEMO_NOW : "",
      db_revision: "",
      db_updated_at: "",
      severity_counts: severityCounts,
      fixable_counts: fixableCounts,
      unfixed_count: 0,
      findings,
      subject,
      comparison: {
        status: comparisonReady ? "unchanged" : "unknown",
        current_subject: comparisonReady
          ? currentSubject
          : { requested_ref: "", reported_digest: "", manifest_digest: "", platform: "" },
        fixed_findings: [],
        remaining_findings: comparisonReady ? findings : [],
        introduced_findings: [],
        message: comparisonMessage,
      },
      warnings:
        decision.hasFindings
          ? ["Demo finding for candidate and installed-digest comparison display."]
          : [],
      error_code: "",
      error_message: "",
    };
  }

  private securityScanDecision(
    reportedDigest: string,
    platform: string,
    reviewCandidate: boolean,
  ): DemoSecurityScanDecision {
    const exact = Boolean(reportedDigest && platform);
    const hasFindings = reviewCandidate && exact;

    if (hasFindings) {
      return {
        hasFindings,
        state: "complete",
        verdict: "findings",
      };
    }

    if (!exact) {
      return {
        hasFindings,
        state: "unsupported",
        verdict: "unknown",
      };
    }
    return {
      hasFindings,
      state: "not_scanned",
      verdict: "unknown",
    };
  }

  private securityScanSeverityCounts(
    hasFindings: boolean,
  ): SecurityScanSeverityCounts {
    if (hasFindings) {
      return { ...DEMO_FINDING_SECURITY_COUNTS };
    }
    return { ...EMPTY_SECURITY_COUNTS };
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
    digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): PlanResponse {
    const selectedLineNumbers = uniqueSortedNumbers(lineNumbers);
    this.requireActiveLines(selectedLineNumbers);
    return readOnlyPlanFromPending(
      this.pendingResponse(),
      selectedLineNumbers,
      allowTagUpdates,
      tagOverrides,
      digestPinLabelRewriteApprovals,
    );
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
    const jobId = `demo-job-${this.nextJob++}`;
    return this.createJobFromFixture(jobId, this.jobTemplateFromPlan(plan, jobId));
  }

  createRetagJob(
    planId: string,
    choices: RetagChoiceRequest[],
  ): ApplyJobResponse {
    const plan = this.createRetagPlan(choices);
    if (plan.plan_id !== planId) {
      throw new Error("Demo retag plan is stale.");
    }
    if (!plan.can_apply) {
      return this.createFailureJob("Demo retag plan is not applicable.");
    }
    const jobId = `demo-retag-job-${this.nextJob++}`;
    return this.createJobFromFixture(
      jobId,
      this.jobTemplateFromRetagPlan(plan, jobId),
    );
  }

  private createJobFromFixture(
    jobId: string,
    fixture: DemoGeneratedJobFixture,
  ): ApplyJobResponse {
    const record: DemoJobRecord = {
      job: clone(fixture.queued),
      log: {
        job_id: jobId,
        log_file: "",
        exists: true,
        content: "",
        truncated: false,
        max_bytes: fixture.log.max_bytes,
        error: "",
      },
      fixture: clone(fixture),
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

  private jobTemplateFromRetagPlan(
    plan: RetagPlanResponse,
    jobId: string,
  ): DemoGeneratedJobFixture {
    const startedAt = "2026-05-30T20:12:26+00:00";
    const finishedAt = "2026-05-30T20:12:28+00:00";
    const logFile = `demo/logs/demo-retag-${jobId}.log`;
    const logContent = this.applyLogFromRetagPlan(plan, startedAt, finishedAt, logFile);
    const progress = this.progressFromRetagPlan(plan, jobId, startedAt, finishedAt);
    return {
      queued: {
        job_id: jobId,
        status: "queued",
        run_id: null,
        log_file: "",
        started_at: null,
        finished_at: null,
        error: "",
        selected_line_numbers: [],
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
        selected_line_numbers: [],
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
      run: this.runFixtureFromRetagPlan(
        plan,
        startedAt,
        finishedAt,
        logFile,
        logContent,
      ),
      removeLineNumbers: [],
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

  private progressFromRetagPlan(
    plan: RetagPlanResponse,
    jobId: string,
    startedAt: string,
    finishedAt: string,
  ): ApplyJobProgressEvent[] {
    const services = plan.stacks.flatMap((item) => item.services);
    const stack = plan.stacks[0];
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
      stack: stack?.stack ?? "",
      services,
      line_numbers: [],
    });
    return [
      event("compose-digest-pin", "success", "Compose digest-pin metadata prepared.", startedAt),
      event("pull", "running", "Pulling retagged demo images.", finishedAt),
      event("pull", "success", "Retagged images pulled.", finishedAt),
      event("recreate", "running", "Recreating retagged demo services.", finishedAt),
      event("recreate", "success", "Retagged services were recreated.", finishedAt),
      event("health", "success", "Retagged demo services reported healthy.", finishedAt),
      event("completion", "success", "Retag apply completed successfully.", finishedAt),
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

  private applyLogFromRetagPlan(
    plan: RetagPlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
  ): string {
    const lines = [
      `[${startedAt}] [INFO] wudup static demo retag apply`,
      `[${startedAt}] [INFO] Log file: ${logFile}`,
      `[${startedAt}] [INFO] Dry-run : false`,
      `[${startedAt}] [INFO] Static demo: no Compose files were changed.`,
    ];
    for (const stack of plan.stacks) {
      lines.push(
        `[${startedAt}] [INFO] [${stack.stack}] Preparing retagged service(s): ${stack.services.join(", ")}`,
      );
      for (const update of stack.digest_pin_updates) {
        lines.push(
          `[${startedAt}] [INFO] [${stack.stack}] ${update.service}: ${update.source_image} -> ${update.final_image}`,
        );
      }
      lines.push(
        `[${startedAt}] [INFO] [${stack.stack}] Recreating retagged service(s): ${stack.services.join(", ")}`,
        `[${finishedAt}] [INFO] [${stack.stack}] Healthy`,
      );
    }
    lines.push(
      `[${finishedAt}] [INFO] Demo retag apply finished. No files were written.`,
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

  private runFixtureFromRetagPlan(
    plan: RetagPlanResponse,
    startedAt: string,
    finishedAt: string,
    logFile: string,
    logContent: string,
  ): DemoRunFixture {
    const updates = plan.stacks.flatMap((stack) =>
      stack.digest_pin_updates.map((update) => ({ stack, update })),
    );
    const events = updates.map(({ stack, update }, index): RunEventRecord => ({
      id: index,
      run_id: 0,
      created_at: finishedAt,
      service_name: update.service,
      stack_name: stack.stack,
      image: update.source_image,
      target_image: update.final_image,
      old_image_id: "sha256:demo-old",
      new_image_id: "sha256:demo-new",
      old_digest: update.digest_provenance?.target_digest ?? "sha256:demo-old",
      new_digest: update.planned_digest || "sha256:demo-new",
      status: "success",
      metadata: { source: "demo", operation: "retag_apply" },
      digest_provenance: update.digest_provenance ?? null,
    }));
    const verificationItems = updates.map(({ stack, update }) => ({
      line_no: 0,
      service_key: update.service_key,
      stack_name: stack.stack,
      service_name: update.service,
      image: update.source_image,
      target_image: update.final_image,
      image_status: "new_image_running" as const,
      container_status: "recreated" as const,
      health_status: "passed" as const,
      wud_status: "unknown" as const,
      follow_up_needed: false,
      summary: "Demo retag verified.",
    }));
    const summary: RunSummary = {
      id: 0,
      started_at: startedAt,
      finished_at: finishedAt,
      status: "success",
      dry_run: false,
      mode: "web-retag",
      wud_file: "",
      log_file: logFile,
      metadata: {
        source: "demo",
        operation: "retag_apply",
        summary: `retagged ${updates.length} services`,
      },
      events,
    };
    const detail: RunDetail = {
      ...summary,
      pending_updates: [],
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

  private normalizedRetagChoices(
    choices: RetagChoiceRequest[],
  ): RetagChoiceRequest[] {
    const serviceCounts = new Map<string, number>();
    for (const item of fixtures.retagTargets.items) {
      serviceCounts.set(item.service_key, (serviceCounts.get(item.service_key) ?? 0) + 1);
    }
    const targetById = new Map(
      fixtures.retagTargets.items.map((item) => [retagTargetKey(item), item]),
    );
    const targetByUniqueService = new Map(
      fixtures.retagTargets.items
        .filter((item) => serviceCounts.get(item.service_key) === 1)
        .map((item) => [item.service_key, item]),
    );
    const byTarget = new Map<string, RetagChoiceRequest>();
    for (const choice of choices) {
      const targetId = choice.target_id ?? "";
      if (!targetId && serviceCounts.get(choice.service_key) !== 1) {
        throw new Error(
          "retag choices for duplicate service(s) must include target_id: "
            + choice.service_key,
        );
      }
      const target = lookupRetagChoiceTarget(choice, targetById, targetByUniqueService);
      if (!target) {
        throw new Error(
          targetId
            ? "Static demo retag target was not found."
            : "Static demo retag service was not found.",
        );
      }
      if (target.service_key !== choice.service_key) {
        throw new Error("Static demo retag target does not match service_key.");
      }
      const key = retagTargetKey(target);
      if (byTarget.has(key)) {
        throw new Error("retag choices contain duplicate target(s): " + choice.service_key);
      }
      byTarget.set(key, choice);
    }
    return fixtures.retagTargets.items.map((item) => {
      const requested = byTarget.get(retagTargetKey(item));
      const choice = requested?.choice ?? "keep-current";
      const targetTag = requested?.target_tag?.trim() ?? "";
      const normalized: RetagChoiceRequest = {
        service_key: item.service_key,
        choice,
      };
      if (item.target_id) {
        normalized.target_id = item.target_id;
      }
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

  private prependRun(run: DemoRunFixture): void {
    this.runs = [clone(run.summary), ...this.runs];
    this.runDetails.set(run.summary.id, clone(run.detail));
    this.runLogs.set(run.summary.id, clone(run.log));
  }
}
