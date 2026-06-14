// ---------------------------------------------------------------------------
// Pending updates
// ---------------------------------------------------------------------------

export interface DigestTagProvenance {
  source_image: string;
  resolved_tag: string;
  watch_tag: string;
  target_digest: string;
  final_image: string;
  provenance_source: string;
  provenance_confidence: string;
}

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
  digest_provenance?: DigestTagProvenance | null;
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

export interface PendingRemovalPlanLine {
  line_no: number;
  raw: string;
  image: string;
  desired_tag: string;
  digest: string;
}

export interface PendingRemovalPlanResponse {
  removal_id: string;
  source_file: string;
  can_remove: boolean;
  selected_line_numbers: number[];
  lines: PendingRemovalPlanLine[];
}

// ---------------------------------------------------------------------------
// Update targets
// ---------------------------------------------------------------------------

export type UpdateTargetsStatus = "ready" | "unavailable";

export interface UpdateTargetItem {
  service_key: string;
  stack: string;
  service: string;
  image: string;
  image_repo: string;
  current_tag: string;
  directory: string;
  compose_file: string;
  project_directory: string;
}

export interface UpdateTargetsResponse {
  status: UpdateTargetsStatus;
  count: number;
  items: UpdateTargetItem[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Retag targets
// ---------------------------------------------------------------------------

export type RetagTargetsStatus = "ready" | "unavailable";
export type RetagTargetChoice = "keep-current" | "switch-to-concrete";

export interface RetagTargetItem {
  service_key: string;
  stack: string;
  service: string;
  image: string;
  image_repo: string;
  current_tag: string;
  tracking_tag: string;
  tracking_tag_source: string;
  proposed_tag: string;
  final_image: string;
  retag_available: boolean;
  retag_reason: string;
  choices: RetagTargetChoice[];
  label_key: string;
  label_value: string;
  directory: string;
  compose_file: string;
  project_directory: string;
  digest_provenance?: DigestTagProvenance | null;
}

export interface RetagTargetsResponse {
  status: RetagTargetsStatus;
  count: number;
  items: RetagTargetItem[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Release notes
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

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
  digest_provenance?: DigestTagProvenance | null;
}

export interface PlanTagUpdate {
  old_image: string;
  desired_tag: string;
  new_image: string;
  services: string[];
}

export interface DigestPinLabelRewriteApprovalRequest {
  stack: string;
  service: string;
  label_key: string;
  current_label_value: string;
  planned_tag: string;
  proposed_label_value: string;
}

export interface PlanDigestPinLabelRewrite {
  service: string;
  label_key: string;
  current_label_value: string;
  planned_tag: string;
  proposed_label_value: string;
  proposed_label_regex: string;
  approved: boolean;
  reason: string;
}

export interface PlanDigestPinUpdate {
  source_image: string;
  resolved_tag: string;
  planned_digest: string;
  final_image: string;
  watch_tag: string;
  marker: string;
  label_key: string;
  label_value: string;
  services: string[];
  label_rewrites: PlanDigestPinLabelRewrite[];
  digest_provenance?: DigestTagProvenance | null;
}

export interface PlanDigestUnpinUpdate {
  source_image: string;
  resolved_tag: string;
  tag_image: string;
  current_digest: string;
  target_digest: string;
  watch_tag: string;
  marker: string;
  label_key: string;
  label_value: string;
  services: string[];
  digest_provenance?: DigestTagProvenance | null;
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
  digest_pin_updates: PlanDigestPinUpdate[];
  digest_unpin_updates: PlanDigestUnpinUpdate[];
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

export type ApplyPreflightStatus = "PASS" | "WARN" | "FAIL";

export interface ApplyPreflightCheck {
  status: ApplyPreflightStatus;
  code: string;
  label: string;
  detail: string;
  source_check_codes: string[];
}

export interface ApplyPreflightResponse {
  ok: boolean;
  failures: number;
  warnings: number;
  checks: ApplyPreflightCheck[];
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
  digest_pin_updates: boolean;
  selected_line_numbers: number[];
  summary: PlanSummary;
  targets: PlanTarget[];
  stacks: PlanStack[];
  skipped: PlanSkipped[];
  issues: PlanIssue[];
  cleanup: PlanCleanup;
  apply_preflight: ApplyPreflightResponse;
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export type ApplyJobStatus = "queued" | "running" | "success" | "failure";
export type ApplyJobProgressStatus = "running" | "success" | "failure" | "skipped";

export interface ApplyJobProgressEvent {
  job_id: string;
  phase: string;
  status: ApplyJobProgressStatus;
  message: string;
  created_at: string;
  stack: string;
  services: string[];
  line_numbers: number[];
}

export interface ApplyJobResponse {
  job_id: string;
  status: ApplyJobStatus;
  run_id: number | null;
  log_file: string;
  started_at: string | null;
  finished_at: string | null;
  error: string;
  selected_line_numbers: number[];
  progress: ApplyJobProgressEvent[];
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

// ---------------------------------------------------------------------------
// Status and settings
// ---------------------------------------------------------------------------

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
  timezone: string;
  auto_update_scheduler_enabled: boolean;
  static_spa_available: boolean;
  warnings: string[];
}

export type SettingsEntrySource = "configured" | "default" | "derived" | "request";

export interface SettingsEntry {
  name: string;
  value: string;
  default_value: string;
  configured: boolean;
  source: SettingsEntrySource;
}

export interface SecretSettingStatus {
  name: string;
  configured: boolean;
}

export type ManagedSettingSource = "configured" | "default";

export interface ManagedSettingEntry {
  key: string;
  value: string;
  default_value: string;
  source: ManagedSettingSource;
  editable: boolean;
  allowed_values: string[];
  restart_required: boolean;
  disabled_reason: string;
}

export interface SettingsResponse {
  updater: SettingsEntry[];
  webui: SettingsEntry[];
  secrets: SecretSettingStatus[];
  managed: ManagedSettingEntry[];
}

export interface ManagedSettingsUpdateResponse {
  managed: ManagedSettingEntry[];
  audit_run_id: number;
}

// ---------------------------------------------------------------------------
// Doctor and onboarding
// ---------------------------------------------------------------------------

export type DoctorCheckStatus = "PASS" | "WARN" | "FAIL";

export interface DoctorSuggestion {
  label: string;
  description: string;
  snippet: string;
}

export interface DoctorCheck {
  status: DoctorCheckStatus;
  code: string;
  category: string;
  name: string;
  detail: string;
  target: string;
  suggestions: DoctorSuggestion[];
}

export interface DoctorResponse {
  ok: boolean;
  failures: number;
  warnings: number;
  checks: DoctorCheck[];
}

export interface OnboardingDocLink {
  label: string;
  url: string;
}

export interface OnboardingChecklistItem {
  key: string;
  title: string;
  status: DoctorCheckStatus;
  detail: string;
  check_codes: string[];
  suggestions: DoctorSuggestion[];
  docs: OnboardingDocLink[];
}

export interface OnboardingChecklistResponse {
  dismissed: boolean;
  dismissed_at: string;
  all_passed: boolean;
  visible: boolean;
  items: OnboardingChecklistItem[];
}

export interface OnboardingDismissResponse {
  dismissed: boolean;
  dismissed_at: string;
}

export type CoreUpdateTourStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "dismissed";

export type CoreUpdateTourStep =
  | "dashboard"
  | "pending_select"
  | "pending_preflight"
  | "pending_apply"
  | "runs_history";

export interface CoreUpdateTourResponse {
  status: CoreUpdateTourStatus;
  step: CoreUpdateTourStep;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Auth and setup
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Run history
// ---------------------------------------------------------------------------

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
  digest_provenance?: DigestTagProvenance | null;
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
  events: RunEventRecord[];
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
  digest_provenance?: DigestTagProvenance | null;
}

export interface RunDetail extends RunSummary {
  pending_updates: PendingUpdateRecord[];
}

export interface RunLogResponse {
  run_id: number;
  log_file: string;
  exists: boolean;
  content: string;
  truncated: boolean;
  max_bytes: number;
}

export interface LogTail {
  exists: boolean;
  content: string;
  truncated: boolean;
}

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

export interface DiagnosticsSupportBundleResponse {
  wud_updater_version: string;
  settings: SettingsResponse;
  doctor_result: DoctorResponse;
  pending_summary: PendingResponse;
  last_run_status: RunSummary | null;
  diagnostics_warnings: string[];
  discovery_warnings: string[];
  log_tail: LogTail | null;
}

// ---------------------------------------------------------------------------
// Service policies, snoozes, and tag exclusions
// ---------------------------------------------------------------------------

export type ServicePolicyUpdateMode = "" | "pause" | "stop" | "live";
export type AutoUpdateDay = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export type SnoozeState = "active" | "expired" | "all";
export type TagExclusionScope = "image_repo" | "service";
export type TagExclusionMatchType = "exact";
export type TagExclusionStatus = "active" | "disabled";
export type TagExclusionStatusFilter = TagExclusionStatus | "all";

export interface ServicePolicyRecord {
  service_key: string;
  update_mode: ServicePolicyUpdateMode;
  auto_update: boolean;
  snooze_default_seconds: number | null;
  auto_update_time: string | null;
  auto_update_days: AutoUpdateDay[];
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
  scope: TagExclusionScope;
  image_repo: string;
  service_key: string;
  match_type: TagExclusionMatchType;
  tag: string;
  regex_fragment: string;
  status: TagExclusionStatus;
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
      auto_update_time?: string | null;
      auto_update_days?: AutoUpdateDay[];
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

// ---------------------------------------------------------------------------
// Container restart
// ---------------------------------------------------------------------------

export interface ContainerRestartResponse {
  status: "scheduled";
  audit_run_id: number;
  container: string;
}

// ---------------------------------------------------------------------------
// Self-update
// ---------------------------------------------------------------------------

export type SelfUpdateStatus =
  | "available"
  | "up_to_date"
  | "disabled"
  | "unavailable";
export type SelfUpdateStrategy = "pull_image" | "prepare_tag_update";

export interface SelfUpdateReleaseNote {
  tag: string;
  title: string;
  published_at: string;
  url: string;
  body: string;
  body_truncated: boolean;
  breaking: boolean;
  breaking_reasons: string[];
}

export interface SelfUpdateResponse {
  status: SelfUpdateStatus;
  strategy: SelfUpdateStrategy;
  current_tag: string;
  latest_tag: string;
  current_image: string;
  target_image: string;
  restart_container: string;
  release_notes: SelfUpdateReleaseNote[];
  release_notes_truncated: boolean;
  release_notes_cap: number;
  can_update: boolean;
  disabled_reason: string;
  external_recreate_required: boolean;
  warnings: string[];
}

export interface SelfUpdateApplyResponse {
  status: "image_pulled";
  audit_run_id: number;
  current_tag: string;
  latest_tag: string;
  target_image: string;
  container: string;
}

export interface SelfUpdatePlanResponse {
  strategy: "prepare_tag_update";
  plan: PlanResponse;
  current_tag: string;
  latest_tag: string;
  current_image: string;
  target_image: string;
  restart_container: string;
  external_recreate_required: boolean;
  warning: string;
}

export interface SelfUpdatePrepareResponse {
  status: "tag_prepared";
  audit_run_id: number;
  current_tag: string;
  latest_tag: string;
  target_image: string;
  container: string;
  external_recreate_required: boolean;
}

export interface SelfUpdateRequest {
  confirmation: "pull_image";
  current_tag: string;
  latest_tag: string;
  target_image: string;
  restart_container: string;
}

export interface SelfUpdatePrepareRequest {
  confirmation: "prepare_tag_update";
  plan_id: string;
  current_tag: string;
  latest_tag: string;
  target_image: string;
  restart_container: string;
}
