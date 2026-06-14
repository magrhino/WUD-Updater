import type {
  ApplyPreflightCheck,
  ApplyPreflightResponse,
  DoctorResponse,
  PendingCleanupLine,
  PendingGroupedItem,
  PlanCleanupItem,
  PlanLine,
  PlanResponse,
  PlanStack,
  RunSummary,
  SettingsEntrySource,
  SettingsResponse,
  TagOverrideRequest,
} from "../types";
import { DEMO_DOCKER_BASE, DEMO_SOURCE_FILE } from "./constants";
import {
  DEMO_STACKS,
  GENERIC_UNMATCHED_DIAGNOSTIC,
  demoRunVerification,
  pendingRecord,
  runEvent,
} from "./fixtures";
import type { DemoPendingItem, DemoRunFixture, DemoStackName } from "./types";

export function stripDemoFields(item: DemoPendingItem): PendingGroupedItem {
  const { stack: _stack, service: _service, ...pending } = item;
  return pending;
}

export function cleanupLineKey(line: PendingCleanupLine): string {
  return `${line.line_no}\u0000${line.raw}`;
}

export function isMatchedDemoItem(
  item: DemoPendingItem,
): item is DemoPendingItem & { stack: DemoStackName } {
  return item.stack !== "";
}

export function isUnmatchedDemoItem(
  item: DemoPendingItem,
): item is DemoPendingItem & { stack: "" } {
  return item.stack === "";
}

export function unmatchedIssue(item: DemoPendingItem) {
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

export function planCleanupItem(item: DemoPendingItem): PlanCleanupItem {
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

export function applyTagOverride(
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

export function planStack(name: DemoStackName, items: DemoPendingItem[]): PlanStack {
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
      digest_provenance: item.digest_provenance ?? null,
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
    digest_pin_updates: [],
    digest_unpin_updates: [],
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

export function runFromApply(
  runId: number,
  selectedItems: DemoPendingItem[],
  plan: PlanResponse,
  startedAt: string,
  finishedAt: string,
  logFile: string,
  logContent: string,
): DemoRunFixture {
  const pending_updates = selectedItems.map((item, index) =>
    pendingRecord(
      item.line_no,
      runId,
      item.raw,
      demoServiceKey(item),
      "success",
      index + runId * 100,
      undefined,
      item.digest_provenance,
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
      item.digest_provenance,
    ),
  );
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
    events,
  };
  return {
    summary,
    detail: {
      ...summary,
      pending_updates,
      events,
      verification: demoRunVerification(pending_updates, events),
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

export function runFromCleanup(
  runId: number,
  removedItems: DemoPendingItem[],
): DemoRunFixture {
  return runFromPendingRemoval(runId, removedItems, {
    mode: "web-pending-cleanup",
    operation: "remove_unmatched_pending",
    statusReason: "removed-unmatched",
    logContent: "Removed unmatched pending demo entries.\n",
  });
}

export function runFromRemoval(
  runId: number,
  removedItems: DemoPendingItem[],
): DemoRunFixture {
  return runFromPendingRemoval(runId, removedItems, {
    mode: "web-pending-removal",
    operation: "remove_selected_pending",
    statusReason: "removed-selected",
    logContent: "Removed selected pending demo entries.\n",
  });
}

function runFromPendingRemoval(
  runId: number,
  removedItems: DemoPendingItem[],
  options: {
    mode: string;
    operation: string;
    statusReason: string;
    logContent: string;
  },
): DemoRunFixture {
  const startedAt = "2026-05-30T20:12:26+00:00";
  const finishedAt = "2026-05-30T20:12:26+00:00";
  const logFile = "";
  const pending_updates = removedItems.map((item, index) =>
    pendingRecord(
      item.line_no,
      runId,
      item.raw,
      demoServiceKey(item),
      "resolved",
      index + runId * 100,
      options.statusReason,
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
  const summary: RunSummary = {
    id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    status: "success",
    dry_run: false,
    mode: options.mode,
    wud_file: DEMO_SOURCE_FILE,
    log_file: logFile,
    metadata: {
      source: "demo",
      operation: options.operation,
      line_numbers: removedItems.map((item) => item.line_no),
    },
    events,
  };
  return {
    summary,
    detail: {
      ...summary,
      pending_updates,
      events,
      verification: demoRunVerification(pending_updates, events),
    },
    log: {
      run_id: runId,
      log_file: logFile,
      exists: true,
      content: options.logContent,
      truncated: false,
      max_bytes: 262_144,
    },
  };
}

export function settingEntry(
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

export function normalizeDemoComposeIgnorePaths(value: string): string {
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

export function doctorCheck(
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

export function demoApplyPreflight(
  options: { selectedReady?: boolean; selectedDetail?: string } = {},
): ApplyPreflightResponse {
  const selectedReady = options.selectedReady ?? true;
  const checks: ApplyPreflightResponse["checks"] = [
    preflightCheck("PASS", "docker-reachable", "Docker reachable", ["docker-daemon-info"]),
    preflightCheck("PASS", "compose-renders", "Compose renders", ["compose-discovery"]),
    preflightCheck("PASS", "wud-file-writable", "WUD file writable", ["wud-out-file"]),
    preflightCheck("PASS", "database-ready", "Database ready", ["webui-database"]),
    preflightCheck("PASS", "logs-writable", "Logs writable", ["wud-log-dir"]),
    preflightCheck("PASS", "mutations-enabled", "Mutations enabled", ["webui-mutation-gate"]),
    preflightCheck("PASS", "bind-mounts-safe", "Bind mounts safe", [
      "bind-mount-path-invalid",
    ]),
    preflightCheck(
      selectedReady ? "PASS" : "FAIL",
      "selected-services-matched",
      "Selected services matched",
      ["selected-services"],
      selectedReady
        ? ""
        : options.selectedDetail || "Selected updates are not ready to apply.",
    ),
  ];
  const failures = checks.filter((check) => check.status === "FAIL").length;
  const warnings = checks.filter((check) => check.status === "WARN").length;
  return {
    ok: failures === 0,
    failures,
    warnings,
    checks,
  };
}

function preflightCheck(
  status: ApplyPreflightCheck["status"],
  code: string,
  label: string,
  sourceCheckCodes: string[],
  detail = "",
): ApplyPreflightCheck {
  return {
    status,
    code,
    label,
    detail,
    source_check_codes: sourceCheckCodes,
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

export function repoKey(image: string): string {
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

export function upsertBy<T>(items: T[], next: T, matches: (item: T) => boolean): T[] {
  const index = items.findIndex(matches);
  if (index === -1) {
    return [next, ...items];
  }
  const updated = [...items];
  updated[index] = next;
  return updated;
}

export function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function clone<T>(value: T): T {
  return structuredClone(value);
}
