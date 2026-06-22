import type { WebApi } from "../client";
import type {
  ContainerRestartResponse,
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  CsrfResponse,
  DigestPinLabelRewriteApprovalRequest,
  PendingCleanupLine,
  PendingRescanLine,
  PendingRescanScope,
  RetagChoiceRequest,
  SelfUpdateApplyResponse,
  SelfUpdatePlanResponse,
  SelfUpdatePrepareResponse,
  SelfUpdateResponse,
  SnoozeState,
  StateOperation,
  TagExclusionStatusFilter,
  TagOverrideRequest,
} from "../types";
import { DEMO_CSRF_TOKEN, DEMO_LATEST_VERSION, DEMO_VERSION } from "./constants";
import { clone } from "./helpers";
import { DemoApiState } from "./state";
import type { DemoJobRecord } from "./types";

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
      values: Record<string, string>,
      _csrfToken: string,
    ) => state.updateManagedSettings(values),
    doctor: async (_csrfToken: string) => state.doctor(),
    onboardingChecklist: async (_csrfToken: string) => state.onboardingChecklist(),
    dismissOnboarding: async (_csrfToken: string) => state.dismissOnboarding(),
    coreUpdateTour: async () => state.coreUpdateTour,
    updateCoreUpdateTour: async (
      status: CoreUpdateTourStatus,
      step: CoreUpdateTourStep,
      _csrfToken: string,
    ) => state.updateCoreUpdateTour(status, step),
    pending: async () => state.pendingResponse(),
    updateTargets: async () => state.updateTargets(),
    retagTargets: async () => state.retagTargets(),
    refreshRetagGithubLatest: async (_csrfToken: string) => state.retagTargets(),
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
      planId: string,
      choices: RetagChoiceRequest[],
      _csrfToken: string,
      _options = {},
    ) => state.createRetagJob(planId, choices),
    diagnosticsSupportBundle: async () => state.diagnosticsSupportBundle(),
    cleanupPending: async (
      cleanupId: string,
      lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => state.cleanupPending(cleanupId, lines),
    createRemovalPlan: async (lineNumbers: number[], _csrfToken: string) =>
      state.createRemovalPlan(lineNumbers),
    removeSelectedPending: async (
      removalId: string,
      lines: PendingCleanupLine[],
      _csrfToken: string,
    ) => state.removeSelectedPending(removalId, lines),
    rescanPending: async (
      scope: PendingRescanScope,
      lines: PendingRescanLine[],
      _csrfToken: string,
    ) => state.rescanPending(scope, lines),
    releaseNotes: async () => state.releaseNotes(),
    refreshReleaseNotes: async (_csrfToken: string) => state.releaseNotes(),
    selfUpdate: async () => state.selfUpdate(),
    planSelfUpdate: async (_csrfToken: string) => state.selfUpdatePlan(),
    applySelfUpdate: async (
      _csrfToken: string,
      _update: SelfUpdateResponse,
    ): Promise<SelfUpdateApplyResponse> => ({
      status: "image_pulled",
      audit_run_id: 9002,
      current_tag: `v${DEMO_VERSION}`,
      latest_tag: DEMO_LATEST_VERSION,
      target_image: "ghcr.io/magrhino/wudup:latest",
      container: "demo-wudup",
    }),
    prepareSelfUpdate: async (
      _csrfToken: string,
      _update: SelfUpdateResponse,
      _plan: SelfUpdatePlanResponse,
    ): Promise<SelfUpdatePrepareResponse> => ({
      status: "tag_prepared",
      audit_run_id: 9003,
      current_tag: "v0.25.0",
      latest_tag: "v0.26.0",
      target_image: "ghcr.io/magrhino/wudup:v0.26.0",
      container: "demo-wudup",
      external_recreate_required: true,
    }),
    servicePolicies: async () => state.servicePolicies(),
    snoozes: async (snoozeState: SnoozeState = "active") =>
      state.snoozeRecords(snoozeState),
    tagExclusions: async (status: TagExclusionStatusFilter = "active") =>
      state.tagExclusionRecords(status),
    stateOperation: async (operation: StateOperation, _csrfToken: string) =>
      state.stateOperation(operation),
    restartContainer: async (_csrfToken: string): Promise<ContainerRestartResponse> => ({
      status: "scheduled",
      audit_run_id: 9001,
      container: "demo-wudup",
    }),
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
      planId: string,
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
    ) =>
      state.createJob(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
      ),
    applyPlan: async (
      planId: string,
      lineNumbers: number[],
      allowTagUpdates: boolean,
      tagOverrides: TagOverrideRequest[],
      digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[],
      _csrfToken: string,
    ) =>
      state.createJob(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
      ),
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
