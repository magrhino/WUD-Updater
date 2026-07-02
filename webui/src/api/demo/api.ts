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
  RetagChoiceRequest,
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
  SnoozeState,
  StateOperation,
  TagExclusionStatusFilter,
  TagOverrideRequest,
} from "../types";
import { DEMO_CSRF_TOKEN } from "./constants";
import { clone } from "./helpers";
import { DemoApiState } from "./state";
import type { DemoJobRecord } from "./types";

const STATIC_DEMO_READ_ONLY =
  "The public static demo is read-only. Run WUDup locally to apply changes.";

function rejectStaticDemoMutation(): never {
  throw new Error(STATIC_DEMO_READ_ONLY);
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
      _choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => rejectStaticDemoMutation(),
    retagPreviewJob: async (previewJobId: string) =>
      state.retagPreviewJob(previewJobId),
    createRetagPlan: async (
      _choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => rejectStaticDemoMutation(),
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
    ) =>
      state.createPlan(
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
      ),
    createJob: async (
      _planId: string,
      _lineNumbers: number[],
      _allowTagUpdates: boolean,
      _tagOverrides: TagOverrideRequest[],
      _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
    applyPlan: async (
      _planId: string,
      _lineNumbers: number[],
      _allowTagUpdates: boolean,
      _tagOverrides: TagOverrideRequest[],
      _digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
    ) => rejectStaticDemoMutation(),
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
      globalThis.clearTimeout(timer);
    }
    this.timers = [];
  }

  private schedule(): void {
    const record = this.state.jobs.get(this.jobId);
    if (!record) {
      this.queue(() => this.onerror?.(new Event("error")), 0);
      return;
    }
    if (record.job.status === "failure") {
      this.queue(() => {
        this.emit("job", record.job);
        this.close();
      }, 0);
      return;
    }
    this.queue(() => {
      const [first] = this.state.jobProgress(this.jobId);
      if (first) {
        const progress = this.state.recordJobProgress(this.jobId, first);
        if (progress) {
          this.emit("progress", progress);
        }
      }
      const running = this.state.jobs.get(this.jobId);
      if (running) {
        this.emit("job", running.job);
      }
    }, 40);
    this.queue(() => {
      for (const progress of this.state.jobProgress(this.jobId).slice(1)) {
        const event = this.state.recordJobProgress(this.jobId, progress);
        if (event) {
          this.emit("progress", event);
        }
      }
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
    this.timers.push(globalThis.setTimeout(callback, delay));
  }

  private emit(type: string, data: unknown): void {
    this.dispatchEvent(
      new MessageEvent(type, {
        data: JSON.stringify(data),
      }),
    );
  }
}

function requireJob(state: DemoApiState, jobId: string): DemoJobRecord {
  const job = state.jobs.get(jobId);
  if (!job) {
    throw new Error(`Demo job ${jobId} was not found`);
  }
  return job;
}
