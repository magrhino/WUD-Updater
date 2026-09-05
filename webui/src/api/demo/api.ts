import type { WebApi } from "../client";
import type {
  CsrfResponse,
  DigestPinLabelRewriteApprovalRequest,
  PendingMetadataRefreshRequest,
  PendingRescanLine,
  PendingRescanScope,
  PlanMutationOptions,
  RetagChoiceRequest,
  SnoozeState,
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

async function rejectStaticDemoMutationAsync(): Promise<never> {
  return rejectStaticDemoMutation();
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
    updateManagedSettings: rejectStaticDemoMutationAsync,
    doctor: async (_csrfToken: string) => state.doctor(),
    onboardingChecklist: async (_csrfToken: string) => state.onboardingChecklist(),
    dismissOnboarding: rejectStaticDemoMutationAsync,
    coreUpdateTour: async () => state.coreUpdateTour,
    updateCoreUpdateTour: rejectStaticDemoMutationAsync,
    pending: async () => state.pendingResponse(),
    pendingMetadata: async (
      request: PendingMetadataRefreshRequest,
      _csrfToken: string,
    ) =>
      state.pendingMetadata(request),
    updateTargets: async () => state.updateTargets(),
    retagTargets: async () => state.retagTargets(),
    refreshRetagGithubLatest: rejectStaticDemoMutationAsync,
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
    applyRetagPlan: rejectStaticDemoMutationAsync,
    diagnosticsSupportBundle: async () => state.diagnosticsSupportBundle(),
    cleanupPending: rejectStaticDemoMutationAsync,
    createRemovalPlan: rejectStaticDemoMutationAsync,
    removeSelectedPending: rejectStaticDemoMutationAsync,
    rescanPending: async (
      scope: PendingRescanScope,
      lines: PendingRescanLine[],
      _csrfToken: string,
    ) => state.rescanPending(scope, lines),
    releaseNotes: async () => state.releaseNotes(),
    refreshReleaseNotes: async (_csrfToken: string) => state.releaseNotes(),
    previewReleaseNotifications: rejectStaticDemoMutationAsync,
    sendReleaseNotifications: rejectStaticDemoMutationAsync,
    testReleaseNotificationWebhook: rejectStaticDemoMutationAsync,
    securityScans: async () => state.securityScans(),
    refreshSecurityScans: rejectStaticDemoMutationAsync,
    securityScanJob: async (jobId: string) => state.securityScanJob(jobId),
    selfUpdate: async () => state.selfUpdate(),
    planSelfUpdate: async (_csrfToken: string) => state.selfUpdatePlan(),
    applySelfUpdate: rejectStaticDemoMutationAsync,
    prepareSelfUpdate: rejectStaticDemoMutationAsync,
    servicePolicies: async () => state.servicePolicies(),
    snoozes: async (snoozeState: SnoozeState = "active") =>
      state.snoozeRecords(snoozeState),
    tagExclusions: async (status: TagExclusionStatusFilter = "active") =>
      state.tagExclusionRecords(status),
    stateOperation: rejectStaticDemoMutationAsync,
    restartContainer: rejectStaticDemoMutationAsync,
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
        options,
      ),
    createJob: rejectStaticDemoMutationAsync,
    applyPlan: rejectStaticDemoMutationAsync,
    job: rejectStaticDemoMutationAsync,
    applyJob: rejectStaticDemoMutationAsync,
    openJobStream: (_jobId: string) => rejectStaticDemoMutation(),
    runs: async () => state.runSummaries(),
    runDetail: async (runId: number) => state.runDetail(runId),
    rollbackPlan: async (runId: number) => state.rollbackPlan(runId),
    runLog: async (runId: number, _tailBytes = 262_144) => state.runLog(runId),
  };
}
