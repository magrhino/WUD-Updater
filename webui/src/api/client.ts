import { createDemoWebApi } from "./demo";

export interface PendingItem {
  line_no: number;
  raw: string;
  image: string;
  key: string;
  repo: string;
  current_tag: string;
  has_tag: boolean;
  allow_repo: boolean;
  digest: string;
  desired_tag: string;
}

export interface PendingDiagnostic {
  code: string;
  message: string;
  hint: string;
  stack: string;
  service: string;
  compose_file: string;
  found_files: string[];
  details: Record<string, unknown>;
}

export type PendingGroupingStatus = "ready" | "unavailable";

export interface PendingGroupedItem extends PendingItem {
  resolved_image: string;
  target_image: string;
  compose_images: string[];
  services: string[];
  action: string;
  diagnostic: PendingDiagnostic | null;
}

export interface PendingStackGroup {
  name: string;
  directory: string;
  compose_file: string;
  project_directory: string;
  services_label: string;
  services: string[];
  line_numbers: number[];
  items: PendingGroupedItem[];
}

export interface PendingGrouping {
  status: PendingGroupingStatus;
  groups: PendingStackGroup[];
  unmatched: PendingGroupedItem[];
  warnings: string[];
}

export interface PendingResponse {
  source_file: string;
  exists: boolean;
  count: number;
  items: PendingItem[];
  grouping: PendingGrouping;
  warnings: string[];
}

export interface ReleaseNoteLink {
  label: string;
  url: string;
  kind: string;
}

export interface ReleaseNoteInfo {
  line_no: number;
  status: string;
  provider: string;
  image_repo: string;
  upstream_repo: string;
  release_tag: string;
  title: string;
  published_at: string;
  breaking: boolean;
  breaking_reasons: string[];
  links: ReleaseNoteLink[];
  refreshed_at: string;
  error: string;
}

export interface ReleaseNotesResponse {
  source_file: string;
  count: number;
  items: ReleaseNoteInfo[];
  warnings: string[];
}

export type PlanStatus = "ready" | "empty" | "blocked";

export interface PlanSummary {
  target_count: number;
  matched_target_count: number;
  stack_count: number;
  service_count: number;
  skipped_count: number;
  issue_count: number;
}

export interface PlanIssue {
  severity: string;
  code: string;
  message: string;
  line_no: number | null;
  stack: string;
  service: string;
  hint: string;
  details: Record<string, unknown>;
}

export interface PlanTarget {
  line_no: number;
  raw: string;
  image: string;
  resolved_image: string;
  digest: string;
  desired_tag: string;
  matched: boolean;
  action: string;
}

export interface PlanLine {
  line_no: number;
  raw: string;
  image: string;
  resolved_image: string;
  compose_image: string;
  target_image: string;
  service: string;
  digest: string;
  desired_tag: string;
  action: string;
}

export interface PlanTagUpdate {
  old_image: string;
  desired_tag: string;
  new_image: string;
  services: string[];
}

export interface PlanAction {
  kind: string;
  description: string;
  cwd: string;
  args: string[];
}

export interface PlanStack {
  name: string;
  directory: string;
  compose_file: string;
  project_directory: string;
  services_label: string;
  services: string[];
  pull_services: string[];
  stop_services: string[];
  force_recreate: boolean;
  up_no_deps: boolean;
  tag_updates: PlanTagUpdate[];
  actions: PlanAction[];
  lines: PlanLine[];
}

export interface PlanSkipped {
  line_no: number;
  raw: string;
  image: string;
  desired_tag: string;
  reason: string;
}

export interface PlanCleanupItem {
  line_no: number;
  raw: string;
  image: string;
  desired_tag: string;
  digest: string;
  reason: string;
  diagnostic: PendingDiagnostic | null;
}

export interface PlanCleanup {
  cleanup_id: string;
  can_remove_unmatched: boolean;
  items: PlanCleanupItem[];
}

export interface TagOverrideRequest {
  line_no: number;
  tag: string;
}

export interface PlanResponse {
  plan_id: string;
  dry_run: boolean;
  can_apply: boolean;
  status: PlanStatus;
  source_file: string;
  mode: string;
  max_wait: number;
  selected_line_numbers: number[];
  summary: PlanSummary;
  targets: PlanTarget[];
  stacks: PlanStack[];
  skipped: PlanSkipped[];
  issues: PlanIssue[];
  cleanup: PlanCleanup;
}

export interface PendingCleanupLine {
  line_no: number;
  raw: string;
}

export interface PendingCleanupRemovedLine extends PendingCleanupLine {
  image: string;
  reason: string;
}

export interface PendingCleanupResponse {
  status: "success";
  audit_run_id: number;
  removed_count: number;
  removed: PendingCleanupRemovedLine[];
}

export type ApplyJobStatus = "queued" | "running" | "success" | "failure";

export interface ApplyJobResponse {
  job_id: string;
  status: ApplyJobStatus;
  run_id: number | null;
  log_file: string;
  started_at: string | null;
  finished_at: string | null;
  error: string;
  selected_line_numbers: number[];
}

export interface ApplyJobLogResponse {
  job_id: string;
  log_file: string;
  exists: boolean;
  content: string;
  truncated: boolean;
  max_bytes: number;
  error: string;
}

export interface StatusResponse {
  ok: boolean;
  version: string;
  wud_file: string;
  wud_file_exists: boolean;
  pending_count: number;
  db_path: string;
  db_ready: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  setup_required: boolean;
  mutations_enabled: boolean;
  static_spa_available: boolean;
  warnings: string[];
}

export interface AuthSessionResponse {
  authenticated: boolean;
  setup_required: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  mutations_enabled: boolean;
  username: string | null;
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface SetupStatusResponse {
  setup_required: boolean;
  claim_required: boolean;
  authenticated: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  mutations_enabled: boolean;
  password_min_length: number;
}

export interface RunSummary {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  dry_run: boolean;
  mode: string;
  wud_file: string;
  log_file: string;
  metadata: Record<string, unknown>;
}

export interface PendingUpdateRecord {
  id: number;
  run_id: number;
  line_no: number;
  raw: string;
  image: string;
  target_digest: string;
  desired_tag: string;
  service_key: string;
  stack_name: string;
  service_name: string;
  status: string;
  status_reason: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface RunEventRecord {
  id: number;
  run_id: number;
  created_at: string;
  service_name: string;
  stack_name: string;
  image: string;
  target_image: string;
  old_image_id: string;
  new_image_id: string;
  old_digest: string;
  new_digest: string;
  status: string;
  metadata: Record<string, unknown>;
}

export interface RunDetail extends RunSummary {
  pending_updates: PendingUpdateRecord[];
  events: RunEventRecord[];
}

export interface RunLogResponse {
  run_id: number;
  log_file: string;
  exists: boolean;
  content: string;
  truncated: boolean;
  max_bytes: number;
}

export type ServicePolicyUpdateMode = "" | "pause" | "stop" | "live";
export type SnoozeState = "active" | "expired" | "all";
export type TagExclusionScope = "image_repo" | "service";
export type TagExclusionMatchType = "exact";
export type TagExclusionStatus = "active" | "disabled";
export type TagExclusionStatusFilter = TagExclusionStatus | "all";

export interface ServicePolicyRecord {
  service_key: string;
  update_mode: string;
  auto_update: boolean;
  snooze_default_seconds: number | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface SnoozeRecord {
  id: number;
  service_key: string;
  snoozed_until: string;
  reason: string;
  created_at: string;
  active: boolean;
  metadata: Record<string, unknown>;
}

export interface TagExclusionRuleRecord {
  id: number;
  scope: string;
  image_repo: string;
  service_key: string;
  match_type: string;
  tag: string;
  regex_fragment: string;
  status: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export type StateOperation =
  | {
      kind: "upsert_service_policy";
      service_key: string;
      update_mode?: ServicePolicyUpdateMode;
      auto_update?: boolean;
      snooze_default_seconds?: number | null;
    }
  | {
      kind: "delete_service_policy";
      service_key: string;
    }
  | {
      kind: "create_snooze";
      service_key: string;
      snoozed_until: string;
      reason?: string;
    }
  | {
      kind: "delete_snooze";
      snooze_id: number;
    }
  | {
      kind: "upsert_tag_exclusion";
      scope: TagExclusionScope;
      image_repo: string;
      service_key?: string;
      match_type?: TagExclusionMatchType;
      tag: string;
      status?: TagExclusionStatus;
    }
  | {
      kind: "set_tag_exclusion_status";
      rule_id: number;
      status: TagExclusionStatus;
    };

export interface StateOperationResponse {
  operation: StateOperation["kind"];
  status: "success";
  audit_run_id: number;
  resource_type: string;
  resource_id: string;
  resource: ServicePolicyRecord | SnoozeRecord | TagExclusionRuleRecord | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const API_PREFIX = "/api/v1";
export const LIVE_JOB_LOG_TAIL_BYTES = 65_536;

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, detail);
  }

  return body as T;
}

const liveWebApi = {
  csrf: () => apiRequest<CsrfResponse>("/auth/csrf"),
  setupStatus: () => apiRequest<SetupStatusResponse>("/setup/status"),
  setupClaim: (
    claim: string,
    username: string,
    password: string,
    csrfToken: string,
  ) =>
    apiRequest<AuthSessionResponse>("/setup/claim", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({ claim, username, password }),
    }),
  resetAdminClaim: (
    claim: string,
    username: string,
    password: string,
    csrfToken: string,
  ) =>
    apiRequest<AuthSessionResponse>("/auth/reset-admin/claim", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({ claim, username, password }),
    }),
  session: () => apiRequest<AuthSessionResponse>("/auth/session"),
  login: (username: string, password: string, csrfToken: string) =>
    apiRequest<AuthSessionResponse>("/auth/login", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({ username, password }),
    }),
  logout: (csrfToken: string) =>
    apiRequest<AuthSessionResponse>("/auth/logout", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
    }),
  status: () => apiRequest<StatusResponse>("/status"),
  pending: () => apiRequest<PendingResponse>("/pending"),
  cleanupPending: (
    cleanupId: string,
    lines: PendingCleanupLine[],
    csrfToken: string,
  ) =>
    apiRequest<PendingCleanupResponse>("/pending/cleanup", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({
        cleanup_id: cleanupId,
        lines,
        confirmation: "remove_unmatched",
      }),
    }),
  releaseNotes: () => apiRequest<ReleaseNotesResponse>("/release-notes"),
  refreshReleaseNotes: (csrfToken: string) =>
    apiRequest<ReleaseNotesResponse>("/release-notes/refresh", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
    }),
  servicePolicies: () => apiRequest<ServicePolicyRecord[]>("/service-policies"),
  snoozes: (state: SnoozeState = "active") =>
    apiRequest<SnoozeRecord[]>(`/snoozes?state=${encodeURIComponent(state)}`),
  tagExclusions: (status: TagExclusionStatusFilter = "active") =>
    apiRequest<TagExclusionRuleRecord[]>(
      `/tag-exclusions?status=${encodeURIComponent(status)}`,
    ),
  stateOperation: (operation: StateOperation, csrfToken: string) =>
    apiRequest<StateOperationResponse>("/state/operations", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify(operation),
    }),
  createPlan: (
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
    csrfToken: string,
  ) =>
    apiRequest<PlanResponse>("/plans", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({
        line_numbers: lineNumbers,
        allow_tag_updates: allowTagUpdates,
        tag_overrides: tagOverrides,
      }),
    }),
  createJob: (
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
    csrfToken: string,
  ) =>
    apiRequest<ApplyJobResponse>("/jobs", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({
        plan_id: planId,
        line_numbers: lineNumbers,
        allow_tag_updates: allowTagUpdates,
        tag_overrides: tagOverrides,
        confirmation: "apply",
      }),
    }),
  applyPlan: (
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[],
    csrfToken: string,
  ) =>
    apiRequest<ApplyJobResponse>("/plans/apply", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({
        plan_id: planId,
        line_numbers: lineNumbers,
        allow_tag_updates: allowTagUpdates,
        tag_overrides: tagOverrides,
        confirmation: "apply",
      }),
    }),
  job: (jobId: string) =>
    apiRequest<ApplyJobResponse>(`/jobs/${encodeURIComponent(jobId)}`),
  applyJob: (jobId: string) => apiRequest<ApplyJobResponse>(`/apply-jobs/${jobId}`),
  openJobStream: (jobId: string) =>
    new EventSource(
      `${API_PREFIX}/jobs/${encodeURIComponent(jobId)}/stream?log_tail_bytes=${LIVE_JOB_LOG_TAIL_BYTES}`,
      { withCredentials: true },
    ),
  runs: () => apiRequest<RunSummary[]>("/runs"),
  runDetail: (runId: number) => apiRequest<RunDetail>(`/runs/${runId}`),
  runLog: (runId: number, tailBytes = 262_144) =>
    apiRequest<RunLogResponse>(`/runs/${runId}/log?tail_bytes=${tailBytes}`),
};

export type WebApi = typeof liveWebApi;

export const webApi: WebApi =
  import.meta.env.MODE === "demo" || import.meta.env.VITE_WUD_DEMO_MODE === "true"
    ? createDemoWebApi()
    : liveWebApi;
