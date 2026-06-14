import type { WebApi } from "../client";
import type {
  ApplyJobProgressEvent,
  ContainerRestartResponse,
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  CsrfResponse,
  DigestPinLabelRewriteApprovalRequest,
  PendingCleanupLine,
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
    createRetagPlan: async (
      choices: RetagChoiceRequest[],
      _csrfToken: string,
    ) => state.createRetagPlan(choices),
    applyRetagPlan: async (
      _planId: string,
      _choices: RetagChoiceRequest[],
      _csrfToken: string,
    ) => {
      throw new Error("Demo mode does not apply retag changes.");
    },
    diagnosticsSupportBundle: async () => ({
      wud_updater_version: "demo-v0.0.0",
      settings: state.settings(),
      doctor_result: state.doctor(),
      pending_summary: state.pendingResponse(),
      last_run_status: null,
      diagnostics_warnings: [],
      discovery_warnings: [],
      log_tail: null,
    }),
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
      target_image: "ghcr.io/magrhino/wud-updater:latest",
      container: "demo-wud-updater",
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
      target_image: "ghcr.io/magrhino/wud-updater:v0.26.0",
      container: "demo-wud-updater",
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
      container: "demo-wud-updater",
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
    if (record.job.status === "failure" || record.plan?.can_apply === false) {
      this.queue(() => {
        this.emit("job", record.job);
        this.close();
      }, 0);
      return;
    }
    this.queue(() => {
      this.emitProgress(
        "preflight",
        "success",
        "Demo preflight checks passed.",
      );
      record.job = {
        ...record.job,
        status: "running",
        started_at: "2026-05-30T20:12:26+00:00",
      };
      record.log = {
        ...record.log,
        content:
          "[2026-05-30T20:12:26+00:00] [INFO] docker-update-from-wud-v2\n",
      };
      this.emit("job", record.job);
      this.emitProgress(
        "pull",
        "running",
        "Pulling selected demo images.",
      );
      this.emit("log", record.log);
    }, 40);
    this.queue(() => {
      this.emitProgress("pull", "success", "Images pulled and verified.");
      this.emitProgress("recreate", "running", "Recreating selected services.");
      this.emitProgress("recreate", "success", "Services were recreated.");
      this.emitProgress("health", "success", "Demo services reported healthy.");
      this.emitProgress("cleanup", "success", "Pending entries were reconciled.");
      this.emitProgress("completion", "success", "Updater completed successfully.");
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

  private emitProgress(
    phase: string,
    status: ApplyJobProgressEvent["status"],
    message: string,
  ): void {
    const record = this.state.jobs.get(this.jobId);
    const stack = record?.plan?.stacks[0];
    const event = this.state.appendJobProgress(this.jobId, phase, status, message, {
      stack: stack?.name,
      services: stack?.services,
      lineNumbers: record?.lineNumbers,
    });
    if (event) {
      this.emit("progress", event);
    }
  }
}

function requireJob(state: DemoApiState, jobId: string): DemoJobRecord {
  const job = state.jobs.get(jobId);
  if (!job) {
    throw new Error(`Demo job ${jobId} was not found`);
  }
  return job;
}
