import type {
  ApplyJobLogResponse,
  ApplyJobResponse,
  AuthSessionResponse,
  DiagnosticsSupportBundleResponse,
  DoctorResponse,
  OnboardingChecklistResponse,
  PendingGroupedItem,
  PendingRemovalPlanResponse,
  PendingResponse,
  PlanResponse,
  ReleaseNotesResponse,
  RetagChoiceRequest,
  RetagPreviewJobResponse,
  RetagPlanResponse,
  RetagTargetsResponse,
  RunDetail,
  RunLogResponse,
  RunSummary,
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
  ServicePolicyRecord,
  SettingsResponse,
  SetupStatusResponse,
  SnoozeRecord,
  StatusResponse,
  TagExclusionRuleRecord,
  TagOverrideRequest,
  UpdateTargetsResponse,
} from "../types";

export type DemoStackName = "data" | "home" | "media";

export type DemoStack = {
  name: DemoStackName;
  servicesLabel: string;
  services: string[];
};

export type DemoPendingItem = PendingGroupedItem & {
  stack: DemoStackName | "";
  service: string;
};

export type DemoRunFixture = {
  summary: RunSummary;
  detail: RunDetail;
  log: RunLogResponse;
};

export type DemoGeneratedJobFixture = {
  queued: ApplyJobResponse;
  terminal: ApplyJobResponse;
  log: ApplyJobLogResponse;
  run: DemoRunFixture | null;
  removeLineNumbers: number[];
};

export type DemoRetagPreviewFixture = {
  queued: RetagPreviewJobResponse;
  complete: RetagPreviewJobResponse;
};

export type DemoTagToken = {
  line_no: number;
  token: string;
  default_tag: string;
};

export type DemoPlanCase = {
  key: string;
  request: {
    line_numbers: number[];
    allow_tag_updates: boolean;
    tag_override_lines: number[];
  };
  tagTokens: DemoTagToken[];
  response: PlanResponse;
  jobTemplate?: DemoGeneratedJobFixture;
};

export type DemoRemovalCase = {
  key: string;
  request: {
    line_numbers: number[];
  };
  response: PendingRemovalPlanResponse;
};

export type DemoRetagCase = {
  key: string;
  request: {
    choices: RetagChoiceRequest[];
  };
  response: RetagPlanResponse;
  preview: DemoRetagPreviewFixture;
  jobTemplate?: DemoGeneratedJobFixture;
};

export type DemoGeneratedFixtures = {
  auth: {
    session: AuthSessionResponse;
    setupStatus: SetupStatusResponse;
  };
  status: StatusResponse;
  settings: SettingsResponse;
  doctor: DoctorResponse;
  onboarding: OnboardingChecklistResponse;
  pending: PendingResponse;
  updateTargets: UpdateTargetsResponse;
  planCases: DemoPlanCase[];
  removalCases: DemoRemovalCase[];
  retagTargets: RetagTargetsResponse;
  retagCases: DemoRetagCase[];
  releaseNotes: ReleaseNotesResponse;
  selfUpdate: SelfUpdateResponse;
  selfUpdatePlan: SelfUpdatePlanResponse;
  diagnostics: DiagnosticsSupportBundleResponse;
  servicePolicies: ServicePolicyRecord[];
  snoozes: {
    active: SnoozeRecord[];
    expired: SnoozeRecord[];
    all: SnoozeRecord[];
  };
  tagExclusions: {
    active: TagExclusionRuleRecord[];
    disabled: TagExclusionRuleRecord[];
    all: TagExclusionRuleRecord[];
  };
  runs: {
    summaries: RunSummary[];
    details: Record<string, RunDetail>;
    logs: Record<string, RunLogResponse>;
  };
};

export type DemoMaterializedPlanCase = Omit<DemoPlanCase, "response" | "jobTemplate"> & {
  response: PlanResponse;
  jobTemplate?: DemoGeneratedJobFixture;
};

export type DemoMaterializedRetagCase = Omit<DemoRetagCase, "response" | "preview" | "jobTemplate"> & {
  response: RetagPlanResponse;
  preview: DemoRetagPreviewFixture;
  jobTemplate?: DemoGeneratedJobFixture;
};

export type DemoJobRecord = {
  job: ApplyJobResponse;
  log: ApplyJobLogResponse;
  fixture: DemoGeneratedJobFixture;
  completed: boolean;
};

export type DemoTagOverrideRequest = TagOverrideRequest;
