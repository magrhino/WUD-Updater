import type { WebApi } from "../client";
import type {
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  CsrfResponse,
  DigestPinLabelRewriteApprovalRequest,
  PendingCleanupLine,
  PendingMetadataRefreshRequest,
  PendingRescanLine,
  PendingRescanScope,
  PlanMutationOptions,
  RetagChoiceRequest,
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
  SnoozeState,
  StateOperation,
  TagExclusionStatusFilter,
  TagOverrideRequest,
} from "../types";
import {
  DEMO_CSRF_TOKEN,
  STATIC_DEMO_READ_ONLY_MESSAGE,
} from "./constants";
import { DemoApiState } from "./state";

function rejectStaticDemoMutation(): never {
  throw new Error(STATIC_DEMO_READ_ONLY_MESSAGE);
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
      _values: Record<string, string>,
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
    doctor: async (_csrfToken: string) => state.doctor(),
    onboardingChecklist: async (_csrfToken: string) => state.onboardingChecklist(),
    dismissOnboarding: async (_csrfToken: string) => rejectStaticDemoMutation(),
    coreUpdateTour: async () => state.coreUpdateTour,
    updateCoreUpdateTour: async (
      _status: CoreUpdateTourStatus,
      _step: CoreUpdateTourStep,
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
    pending: async () => state.pendingResponse(),
    pendingMetadata: async (
      request: PendingMetadataRefreshRequest,
      _csrfToken: string,
    ) =>
      state.pendingMetadata(request),
    updateTargets: async () => state.updateTargets(),
    retagTargets: async () => state.retagTargets(),
    refreshRetagGithubLatest: async (_csrfToken: string) =>
      rejectStaticDemoMutation(),
    startRetagPreview: async (
      choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => state.createRetagPreviewJob(choices),
    retagPreviewJob: async (previewJobId: string) =>
      state.retagPreviewJob(previewJobId),
    createRetagPlan: async (
      choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => state.createRetagPlan(choices),
    applyRetagPlan: async (
      _planId: string,
      _choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => rejectStaticDemoMutation(),
    diagnosticsSupportBundle: async () => state.diagnosticsSupportBundle(),
    cleanupPending: async (
      _cleanupId: string,
      _lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
    createRemovalPlan: async (_lineNumbers: number[], _csrfToken: string) =>
      rejectStaticDemoMutation(),
    removeSelectedPending: async (
      _removalId: string,
      _lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
    rescanPending: async (
      scope: PendingRescanScope,
      lines: PendingRescanLine[],
      _csrfToken: string,
    ) => state.rescanPending(scope, lines),
    releaseNotes: async () => state.releaseNotes(),
    refreshReleaseNotes: async (_csrfToken: string) => state.releaseNotes(),
    previewReleaseNotifications: async (_source, _csrfToken: string) =>
      rejectStaticDemoMutation(),
    sendReleaseNotifications: async (_source, _csrfToken: string) =>
      rejectStaticDemoMutation(),
    testReleaseNotificationWebhook: async (_csrfToken: string) =>
      rejectStaticDemoMutation(),
    securityScans: async () => state.securityScans(),
    refreshSecurityScans: async (_csrfToken: string) =>
      rejectStaticDemoMutation(),
    securityScanJob: async (jobId: string) => state.securityScanJob(jobId),
    selfUpdate: async () => state.selfUpdate(),
    planSelfUpdate: async (_csrfToken: string) => state.selfUpdatePlan(),
    applySelfUpdate: async (
      _csrfToken: string,
      _update: SelfUpdateResponse,
    ) => rejectStaticDemoMutation(),
    prepareSelfUpdate: async (
      _csrfToken: string,
      _update: SelfUpdateResponse,
      _plan: SelfUpdatePlanResponse,
    ) => rejectStaticDemoMutation(),
    servicePolicies: async () => state.servicePolicies(),
    snoozes: async (snoozeState: SnoozeState = "active") =>
      state.snoozeRecords(snoozeState),
    tagExclusions: async (status: TagExclusionStatusFilter = "active") =>
      state.tagExclusionRecords(status),
    stateOperation: async (_operation: StateOperation, _csrfToken: string) =>
      rejectStaticDemoMutation(),
    restartContainer: async (_csrfToken: string) => rejectStaticDemoMutation(),
    createPlan: async (
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
      options: PlanMutationOptions = {},
    ) =>
      state.createPlan(
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
        options.selections ?? [],
      ),
    createJob: async (
      _planId: string,
      _lineNumbers: number[],
      _allowTagUpdates: boolean,
      _tagOverrides: TagOverrideRequest[],
      _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
      _options: PlanMutationOptions = {},
    ) => rejectStaticDemoMutation(),
    applyPlan: async (
      _planId: string,
      _lineNumbers: number[],
      _allowTagUpdates: boolean,
      _tagOverrides: TagOverrideRequest[],
      _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
      _options: PlanMutationOptions = {},
    ) => rejectStaticDemoMutation(),
    job: async (_jobId: string) => rejectStaticDemoMutation(),
    applyJob: async (_jobId: string) => rejectStaticDemoMutation(),
    openJobStream: (_jobId: string) => rejectStaticDemoMutation(),
    runs: async () => state.runSummaries(),
    runDetail: async (runId: number) => state.runDetail(runId),
    rollbackPlan: async (runId: number) => state.rollbackPlan(runId),
    runLog: async (runId: number, _tailBytes = 262_144) => state.runLog(runId),
  };
}
