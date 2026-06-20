// webui/src/stores/updates.ts
import { ref } from "vue";
import { defineStore } from "pinia";
import {
  ApiError,
  LIVE_JOB_LOG_TAIL_BYTES,
  type ApplyJobLogResponse,
  type ApplyJobResponse,
  type DigestPinLabelRewriteApprovalRequest,
  type PendingCleanupLine,
  type PendingCleanupResponse,
  type PendingRemovalPlanResponse,
  type PlanResponse,
  type PendingResponse,
  type ReleaseNotesResponse,
  type RetagChoiceRequest,
  type RetagPlanResponse,
  type RetagPreviewJobResponse,
  type RetagTargetChoice,
  type RetagTargetsResponse,
  type SelfUpdateApplyResponse,
  type SelfUpdatePlanResponse,
  type SelfUpdatePrepareResponse,
  type SelfUpdateResponse,
  type TagOverrideRequest,
  type UpdateTargetsResponse,
  webApi,
} from "../api/client";
import { usePolledJob } from "../composables/usePolledJob";
import { useAuthStore } from "./auth";
import { errorMessage, runWithStoreState } from "./storeState";
import {
  normalizeRetagChoice,
  retagChoice as selectedRetagChoice,
} from "../utils/retagChoices";

export const APPLY_JOB_RECOVERY_MESSAGE =
  "Last known apply job state is unavailable because the WebUI process restarted. Check Runs -> Latest run and the updater log before applying more updates.";

const APPLY_JOB_STORAGE_KEY = "applyJobId";
const TERMINAL_APPLY_JOB_STATUSES = new Set<ApplyJobResponse["status"]>([
  "success",
  "failure",
]);

const TERMINAL_RETAG_PREVIEW_STATUSES = new Set<RetagPreviewJobResponse["status"]>([
  "success",
  "failure",
]);

export const useUpdatesStore = defineStore("updates", () => {
  const pending = ref<PendingResponse | null>(null);
  const updateTargets = ref<UpdateTargetsResponse | null>(null);
  const retagTargets = ref<RetagTargetsResponse | null>(null);
  const retagChoices = ref<Record<string, RetagTargetChoice>>({});
  const retagPlan = ref<RetagPlanResponse | null>(null);
  const retagGithubLatestFallback = ref(false);
  let retagPreviewStart: (() => Promise<RetagPreviewJobResponse>) | null = null;
  const retagPreviewPoller = usePolledJob<RetagPreviewJobResponse>(
    () => {
      if (retagPreviewStart === null) {
        throw new Error("Retag preview was not started");
      }
      return retagPreviewStart();
    },
    (job) => webApi.retagPreviewJob(job.preview_job_id),
    (job) => TERMINAL_RETAG_PREVIEW_STATUSES.has(job.status),
    { intervalMs: 400 },
  );
  const releaseNotes = ref<ReleaseNotesResponse | null>(null);
  const selfUpdate = ref<SelfUpdateResponse | null>(null);
  const selfUpdatePlan = ref<SelfUpdatePlanResponse | null>(null);
  const selfUpdateMessage = ref("");
  const selfUpdateError = ref("");
  const plan = ref<PlanResponse | null>(null);
  const pendingCleanup = ref<PendingCleanupResponse | null>(null);
  const pendingRemovalPlan = ref<PendingRemovalPlanResponse | null>(null);
  const applyJob = ref<ApplyJobResponse | null>(null);
  const applyJobLog = ref<ApplyJobLogResponse | null>(null);
  const rememberedApplyJobId = ref(readRememberedApplyJobId());
  const applyJobRecovery = ref("");
  const loading = ref(false);
  const releaseNotesLoading = ref(false);
  const releaseNotesError = ref("");
  const error = ref("");

  async function loadWithState(work: () => Promise<void>): Promise<void> {
    await runWithStoreState(loading, error, work);
  }

  async function loadPending(
    options: { preserveCleanup?: boolean } = {},
  ): Promise<void> {
    await loadWithState(async () => {
      plan.value = null;
      pendingRemovalPlan.value = null;
      if (!options.preserveCleanup) {
        pendingCleanup.value = null;
      }
      pending.value = await webApi.pending();
    });
  }

  async function loadUpdateTargets(): Promise<void> {
    await loadWithState(async () => {
      updateTargets.value = await webApi.updateTargets();
    });
  }

  async function loadRetagTargets(
    options: { githubLatestFallback?: boolean } = {},
  ): Promise<void> {
    const githubLatestFallback =
      options.githubLatestFallback ?? retagGithubLatestFallback.value;
    retagGithubLatestFallback.value = githubLatestFallback;
    await loadWithState(async () => {
      retagTargets.value = await webApi.retagTargets({
        github_latest_fallback: githubLatestFallback,
      });
      resetRetagChoices();
      retagPlan.value = null;
      retagPreviewPoller.reset();
    });
  }

  async function setRetagGithubLatestFallback(enabled: boolean): Promise<void> {
    retagGithubLatestFallback.value = enabled;
    if (enabled) {
      await refreshRetagGithubLatest();
      return;
    }
    await loadRetagTargets({ githubLatestFallback: false });
  }

  async function refreshRetagGithubLatest(): Promise<void> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      retagTargets.value = await webApi.refreshRetagGithubLatest(
        await auth.ensureCsrf(),
      );
      retagGithubLatestFallback.value = true;
      resetRetagChoices();
      retagPlan.value = null;
      retagPreviewPoller.reset();
    });
  }

  function resetRetagChoices(): void {
    retagChoices.value = Object.fromEntries(
      (retagTargets.value?.items ?? []).map((item) => [
        item.service_key,
        "keep-current" satisfies RetagTargetChoice,
      ]),
    );
  }

  function setRetagChoice(
    serviceKey: string,
    choice: RetagTargetChoice,
  ): void {
    const item = retagTargets.value?.items.find(
      (target) => target.service_key === serviceKey,
    );
    retagChoices.value = {
      ...retagChoices.value,
      [serviceKey]: item ? normalizeRetagChoice(item, choice) : choice,
    };
    retagPlan.value = null;
    retagPreviewPoller.reset();
  }

  function retagChoiceRequests(): RetagChoiceRequest[] {
    const items = retagTargets.value?.items ?? [];
    return items
      .map((item) => ({
        service_key: item.service_key,
        choice: selectedRetagChoice(item, retagChoices.value),
      }))
      .sort((left, right) => left.service_key.localeCompare(right.service_key));
  }

  async function createRetagPlan(): Promise<RetagPlanResponse> {
    const auth = useAuthStore();
    let response: RetagPlanResponse | null = null;
    await loadWithState(async () => {
      retagPlan.value = null;
      applyJob.value = null;
      applyJobLog.value = null;
      const choices = retagChoiceRequests();
      const csrfToken = await auth.ensureCsrf();
      const options = { github_latest_fallback: retagGithubLatestFallback.value };
      retagPreviewStart = () =>
        webApi.startRetagPreview(choices, csrfToken, options);
      const job = await retagPreviewPoller.run();
      if (job.status === "failure") {
        throw new Error(job.error || "Retag preview failed");
      }
      if (job.plan === null) {
        throw new Error("Retag preview did not return a plan");
      }
      response = job.plan;
      retagPlan.value = job.plan;
    });
    if (response === null) {
      throw new Error("Retag plan did not return a response");
    }
    return response;
  }

  async function applyRetagPlan(): Promise<ApplyJobResponse> {
    const auth = useAuthStore();
    const planToApply = retagPlan.value;
    if (planToApply === null) {
      throw new Error("Retag preview must be loaded before applying");
    }
    await loadWithState(async () => {
      applyJobLog.value = null;
      const job = await webApi.applyRetagPlan(
        planToApply.plan_id,
        retagChoiceRequests(),
        await auth.ensureCsrf(),
        { github_latest_fallback: retagGithubLatestFallback.value },
      );
      setApplyJob(job);
    });
    if (applyJob.value === null) {
      throw new Error("Apply job was not created");
    }
    return applyJob.value;
  }

  async function loadReleaseNotes(): Promise<void> {
    releaseNotesLoading.value = true;
    releaseNotesError.value = "";
    try {
      releaseNotes.value = await webApi.releaseNotes();
    } catch (caughtError) {
      releaseNotesError.value = errorMessage(caughtError);
      throw caughtError;
    } finally {
      releaseNotesLoading.value = false;
    }
  }

  async function refreshReleaseNotes(): Promise<void> {
    const auth = useAuthStore();
    releaseNotesLoading.value = true;
    releaseNotesError.value = "";
    try {
      releaseNotes.value = await webApi.refreshReleaseNotes(await auth.ensureCsrf());
    } catch (caughtError) {
      releaseNotesError.value = errorMessage(caughtError);
      throw caughtError;
    } finally {
      releaseNotesLoading.value = false;
    }
  }

  async function loadSelfUpdate(): Promise<void> {
    selfUpdateError.value = "";
    try {
      selfUpdate.value = await webApi.selfUpdate();
      selfUpdatePlan.value = null;
    } catch (caughtError) {
      selfUpdateError.value = errorMessage(caughtError);
      throw caughtError;
    }
  }

  async function planSelfUpdate(): Promise<SelfUpdatePlanResponse> {
    const auth = useAuthStore();
    selfUpdateError.value = "";
    let response: SelfUpdatePlanResponse | null = null;
    try {
      await loadWithState(async () => {
        response = await webApi.planSelfUpdate(await auth.ensureCsrf());
        selfUpdatePlan.value = response;
      });
    } catch (caughtError) {
      selfUpdateError.value = errorMessage(caughtError);
      throw caughtError;
    }
    if (response === null) {
      throw new Error("Self-update plan did not return a response");
    }
    return response;
  }

  async function applySelfUpdate(): Promise<
    SelfUpdateApplyResponse | SelfUpdatePrepareResponse
  > {
    const auth = useAuthStore();
    selfUpdateMessage.value = "";
    selfUpdateError.value = "";
    let response: SelfUpdateApplyResponse | SelfUpdatePrepareResponse | null = null;
    try {
      await loadWithState(async () => {
        if (selfUpdate.value === null) {
          throw new Error("Self-update status has not been loaded");
        }
        if (selfUpdate.value.strategy === "prepare_tag_update") {
          const planLocal = selfUpdatePlan.value;
          if (planLocal === null) {
            throw new Error(
              "Self-update tag update preview must be loaded before applying",
            );
          }
          const csrfToken = await auth.ensureCsrf();
          response = await webApi.prepareSelfUpdate(
            csrfToken,
            selfUpdate.value,
            planLocal,
          );
          selfUpdateMessage.value =
            "Tag updated and image pulled. Recreate the WUDup container from outside the WebUI to run the new version. Tagged deployments are recommended for predictable updates.";
        } else {
          const csrfToken = await auth.ensureCsrf();
          response = await webApi.applySelfUpdate(csrfToken, selfUpdate.value);
          selfUpdateMessage.value =
            "Image pulled. Recreate the WUDup container to run the new version. Tagged deployments are recommended for predictable updates.";
        }
        try {
          selfUpdate.value = await webApi.selfUpdate();
          selfUpdatePlan.value = null;
        } catch {
          // Keep the success visible even if the follow-up status check fails.
        }
      });
    } catch (caughtError) {
      selfUpdateError.value = errorMessage(caughtError);
      throw caughtError;
    }
    if (response === null) {
      throw new Error("Self-update did not return a response");
    }
    return response;
  }

  async function createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[] = [],
    digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): Promise<void> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      plan.value = null;
      pendingCleanup.value = null;
      pendingRemovalPlan.value = null;
      applyJob.value = null;
      applyJobLog.value = null;
      plan.value = await webApi.createPlan(
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
        await auth.ensureCsrf(),
      );
    });
  }

  async function cleanupPending(
    cleanupId: string,
    lines: PendingCleanupLine[],
  ): Promise<PendingCleanupResponse> {
    const auth = useAuthStore();
    let response: PendingCleanupResponse | null = null;
    await loadWithState(async () => {
      response = await webApi.cleanupPending(
        cleanupId,
        lines,
        await auth.ensureCsrf(),
      );
      pendingCleanup.value = response;
      plan.value = null;
      pendingRemovalPlan.value = null;
    });
    if (response === null) {
      throw new Error("Pending cleanup did not return a response");
    }
    return response;
  }

  async function createRemovalPlan(
    lineNumbers: number[],
  ): Promise<PendingRemovalPlanResponse> {
    const auth = useAuthStore();
    let response: PendingRemovalPlanResponse | null = null;
    await loadWithState(async () => {
      plan.value = null;
      pendingCleanup.value = null;
      pendingRemovalPlan.value = await webApi.createRemovalPlan(
        lineNumbers,
        await auth.ensureCsrf(),
      );
      response = pendingRemovalPlan.value;
    });
    if (response === null) {
      throw new Error("Pending removal plan did not return a response");
    }
    return response;
  }

  async function removeSelectedPending(
    removalId: string,
    lines: PendingCleanupLine[],
  ): Promise<PendingCleanupResponse> {
    const auth = useAuthStore();
    let response: PendingCleanupResponse | null = null;
    await loadWithState(async () => {
      response = await webApi.removeSelectedPending(
        removalId,
        lines,
        await auth.ensureCsrf(),
      );
      pendingCleanup.value = response;
      pendingRemovalPlan.value = null;
      plan.value = null;
    });
    if (response === null) {
      throw new Error("Pending removal did not return a response");
    }
    return response;
  }

  function clearPlan(): void {
    plan.value = null;
    pendingRemovalPlan.value = null;
  }

  async function createJob(
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[] = [],
    digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): Promise<ApplyJobResponse> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      applyJobLog.value = null;
      const job = await webApi.createJob(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
        await auth.ensureCsrf(),
      );
      setApplyJob(job);
    });
    if (applyJob.value === null) {
      throw new Error("Apply job was not created");
    }
    return applyJob.value;
  }

  async function applyPlan(
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[] = [],
    digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[] = [],
  ): Promise<ApplyJobResponse> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      applyJobLog.value = null;
      const job = await webApi.applyPlan(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        digestPinLabelRewriteApprovals,
        await auth.ensureCsrf(),
      );
      setApplyJob(job);
    });
    if (applyJob.value === null) {
      throw new Error("Apply job was not created");
    }
    return applyJob.value;
  }

  function setApplyJob(job: ApplyJobResponse): void {
    applyJob.value = job;
    applyJobRecovery.value = "";
    rememberApplyJob(job);
  }

  function setApplyJobLog(log: ApplyJobLogResponse): void {
    applyJobLog.value = log;
  }

  function setError(message: string): void {
    error.value = message;
  }

  async function loadApplyJob(
    jobId: string,
    options: { recoverMissing?: boolean } = {},
  ): Promise<ApplyJobResponse | null> {
    try {
      const job = await webApi.job(jobId);
      setApplyJob(job);
      return job;
    } catch (caughtError) {
      if (
        options.recoverMissing &&
        caughtError instanceof ApiError &&
        caughtError.status === 404
      ) {
        markApplyJobRecovery();
        return null;
      }
      error.value = errorMessage(caughtError);
      throw caughtError;
    }
  }

  async function loadApplyJobLogFromRun(
    job: ApplyJobResponse | null = applyJob.value,
  ): Promise<ApplyJobLogResponse | null> {
    if (!job?.run_id) {
      return null;
    }
    try {
      const runLog = await webApi.runLog(job.run_id, LIVE_JOB_LOG_TAIL_BYTES);
      const log: ApplyJobLogResponse = {
        job_id: job.job_id,
        log_file: runLog.log_file || job.log_file,
        exists: runLog.exists,
        content: runLog.content,
        truncated: runLog.truncated,
        max_bytes: runLog.max_bytes,
        error: "",
      };
      setApplyJobLog(log);
      return log;
    } catch (caughtError) {
      error.value = errorMessage(caughtError);
      return null;
    }
  }

  function markApplyJobRecovery(): void {
    applyJob.value = null;
    applyJobLog.value = null;
    applyJobRecovery.value = APPLY_JOB_RECOVERY_MESSAGE;
    clearRememberedApplyJobId();
  }

  function rememberApplyJob(job: ApplyJobResponse): void {
    if (TERMINAL_APPLY_JOB_STATUSES.has(job.status)) {
      clearRememberedApplyJobId();
      return;
    }
    rememberedApplyJobId.value = job.job_id;
    writeRememberedApplyJobId(job.job_id);
  }

  function clearRememberedApplyJobId(): void {
    rememberedApplyJobId.value = "";
    removeRememberedApplyJobId();
  }

  return {
    pending,
    updateTargets,
    retagTargets,
    retagChoices,
    retagPlan,
    retagPreviewJob: retagPreviewPoller.job,
    retagPreviewPolling: retagPreviewPoller.polling,
    retagPreviewError: retagPreviewPoller.error,
    retagGithubLatestFallback,
    releaseNotes,
    selfUpdate,
    selfUpdatePlan,
    selfUpdateMessage,
    selfUpdateError,
    plan,
    pendingCleanup,
    pendingRemovalPlan,
    applyJob,
    applyJobLog,
    rememberedApplyJobId,
    applyJobRecovery,
    loading,
    releaseNotesLoading,
    releaseNotesError,
    error,
    loadPending,
    loadUpdateTargets,
    loadRetagTargets,
    setRetagGithubLatestFallback,
    refreshRetagGithubLatest,
    resetRetagChoices,
    setRetagChoice,
    retagChoiceRequests,
    createRetagPlan,
    applyRetagPlan,
    loadReleaseNotes,
    refreshReleaseNotes,
    loadSelfUpdate,
    planSelfUpdate,
    applySelfUpdate,
    createPlan,
    cleanupPending,
    createRemovalPlan,
    removeSelectedPending,
    clearPlan,
    createJob,
    applyPlan,
    setApplyJob,
    setApplyJobLog,
    setError,
    loadApplyJob,
    loadApplyJobLogFromRun,
    markApplyJobRecovery,
    rememberApplyJob,
    clearRememberedApplyJobId,
  };
});

function readRememberedApplyJobId(): string {
  const storage = sessionStorageAvailable();
  try {
    return storage?.getItem(APPLY_JOB_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeRememberedApplyJobId(jobId: string): void {
  const storage = sessionStorageAvailable();
  try {
    storage?.setItem(APPLY_JOB_STORAGE_KEY, jobId);
  } catch {
    // Remembering a transient job id is best-effort.
  }
}

function removeRememberedApplyJobId(): void {
  const storage = sessionStorageAvailable();
  try {
    storage?.removeItem(APPLY_JOB_STORAGE_KEY);
  } catch {
    // Remembering a transient job id is best-effort.
  }
}

function sessionStorageAvailable(): Storage | null {
  try {
    return "sessionStorage" in globalThis ? globalThis.sessionStorage : null;
  } catch {
    return null;
  }
}
