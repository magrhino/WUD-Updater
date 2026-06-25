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
  type PendingRescanLine,
  type PendingRescanResponse,
  type PendingRescanScope,
  type PlanResponse,
  type PendingResponse,
  type ReleaseNoteInfo,
  type ReleaseNotesResponse,
  type RetagChoiceRequest,
  type RetagPlanResponse,
  type RetagPreviewJobResponse,
  type RetagTargetChoice,
  type RetagTargetItem,
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
  canEnableRetagTargetChoice,
  normalizeRetagChoice,
  retagChoice as selectedRetagChoice,
  retagTargetIdentity,
  retagTargetTagValue,
} from "../utils/retagChoices";
import {
  fetchReleaseChangelog,
  IDLE_RELEASE_CHANGELOG,
  releaseChangelogKey,
  type ReleaseChangelogState,
} from "../utils/releaseChangelog";
import { useRunsStore } from "./runs";

export const APPLY_JOB_RECOVERY_MESSAGE =
  "Last known apply job state is unavailable because the WebUI process restarted. Check Runs -> Latest run and the updater log before applying more updates.";
const PENDING_RESCAN_SELECTION_REQUIRED_MESSAGE =
  "Select at least one pending update to rescan.";

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
  const retagTargetTags = ref<Record<string, string>>({});
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
  const releaseChangelogs = ref<Record<string, ReleaseChangelogState>>({});
  const releaseChangelogRequests = new Map<string, Promise<void>>();
  const selfUpdate = ref<SelfUpdateResponse | null>(null);
  const selfUpdatePlan = ref<SelfUpdatePlanResponse | null>(null);
  const selfUpdateMessage = ref("");
  const selfUpdateError = ref("");
  const plan = ref<PlanResponse | null>(null);
  const pendingCleanup = ref<PendingCleanupResponse | null>(null);
  const pendingRemovalPlan = ref<PendingRemovalPlanResponse | null>(null);
  const pendingRescan = ref<PendingRescanResponse | null>(null);
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
      pendingRescan.value = null;
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
    const items = retagTargets.value?.items ?? [];
    retagChoices.value = Object.fromEntries(
      items.map((item) => [
        retagTargetIdentity(item),
        "keep-current" satisfies RetagTargetChoice,
      ]),
    );
    retagTargetTags.value = Object.fromEntries(
      items.map((item) => [
        retagTargetIdentity(item),
        item.retag_available ? item.proposed_tag : "",
      ]),
    );
  }

  function findRetagTarget(targetKey: string): RetagTargetItem | undefined {
    return retagTargets.value?.items.find(
      (target) =>
        retagTargetIdentity(target) === targetKey ||
        target.service_key === targetKey,
    );
  }

  function setRetagChoice(
    targetKey: string,
    choice: RetagTargetChoice,
  ): void {
    const item = findRetagTarget(targetKey);
    const choiceKey = item ? retagTargetIdentity(item) : targetKey;
    retagChoices.value = {
      ...retagChoices.value,
      [choiceKey]: item
        ? normalizeRetagChoice(item, choice, retagTargetTags.value)
        : choice,
    };
    retagPlan.value = null;
    retagPreviewPoller.reset();
  }

  function setRetagChoicesForItems(
    items: RetagTargetItem[],
    choice: RetagTargetChoice,
  ): void {
    const currentItems = new Map(
      (retagTargets.value?.items ?? []).map((item) => [
        retagTargetIdentity(item),
        item,
      ]),
    );
    const nextChoices = { ...retagChoices.value };
    for (const requestedItem of items) {
      const item = currentItems.get(retagTargetIdentity(requestedItem));
      if (!item) {
        continue;
      }
      nextChoices[retagTargetIdentity(item)] =
        choice === "switch-to-concrete" &&
        canEnableRetagTargetChoice(item, retagTargetTags.value)
          ? "switch-to-concrete"
          : "keep-current";
    }
    retagChoices.value = nextChoices;
    retagPlan.value = null;
    retagPreviewPoller.reset();
  }

  function setRetagTargetTag(targetKey: string, tag: string): void {
    const item = findRetagTarget(targetKey);
    const choiceKey = item ? retagTargetIdentity(item) : targetKey;
    retagTargetTags.value = {
      ...retagTargetTags.value,
      [choiceKey]: tag,
    };
    if (item && tag.trim()) {
      retagChoices.value = {
        ...retagChoices.value,
        [choiceKey]: "switch-to-concrete",
      };
    }
    retagPlan.value = null;
    retagPreviewPoller.reset();
  }

  function retagChoiceRequests(): RetagChoiceRequest[] {
    const items = retagTargets.value?.items ?? [];
    return items
      .map((item) => {
        const choice = selectedRetagChoice(
          item,
          retagChoices.value,
          retagTargetTags.value,
        );
        const request: RetagChoiceRequest = {
          service_key: item.service_key,
          choice,
        };
        const targetId = retagTargetIdentity(item);
        if (targetId !== item.service_key) {
          request.target_id = targetId;
        }
        if (choice === "switch-to-concrete") {
          const tag = retagTargetTagValue(item, retagTargetTags.value).trim();
          if (tag && (!item.retag_available || tag !== item.proposed_tag)) {
            request.target_tag = tag;
          }
        }
        return request;
      })
      .sort(
        (left, right) =>
          left.service_key.localeCompare(right.service_key) ||
          (left.target_id ?? "").localeCompare(right.target_id ?? ""),
      );
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

  function releaseChangelogStateFor(
    note: ReleaseNoteInfo | null,
  ): ReleaseChangelogState {
    const key = releaseChangelogKeyFor(note);
    return key
      ? releaseChangelogs.value[key] ?? IDLE_RELEASE_CHANGELOG
      : IDLE_RELEASE_CHANGELOG;
  }

  async function loadReleaseChangelog(note: ReleaseNoteInfo | null): Promise<void> {
    const link = releaseChangelogLinkFor(note);
    if (link === "") {
      return;
    }
    const key = releaseChangelogKey(link);
    if (key === "") {
      return;
    }
    const currentState = releaseChangelogs.value[key];
    if (currentState?.status === "ready") {
      return;
    }
    const pendingRequest = releaseChangelogRequests.get(key);
    if (pendingRequest) {
      await pendingRequest;
      return;
    }
    setReleaseChangelogState(key, {
      status: "loading",
      body: "",
      sourceUrl: "",
      error: "",
    });
    const request = fetchReleaseChangelog(link, note?.release_tag ?? "")
      .then((result) => {
        if (result.status === "ready") {
          setReleaseChangelogState(key, {
            status: "ready",
            body: result.body,
            sourceUrl: result.sourceUrl,
            error: "",
          });
          return;
        }
        setReleaseChangelogState(key, {
          status: "unavailable",
          body: "",
          sourceUrl: "",
          error: result.error,
        });
      })
      .catch((caughtError: unknown) => {
        setReleaseChangelogState(key, {
          status: "error",
          body: "",
          sourceUrl: "",
          error: errorMessage(caughtError),
        });
      })
      .finally(() => {
        releaseChangelogRequests.delete(key);
      });
    releaseChangelogRequests.set(key, request);
    await request;
  }

  function setReleaseChangelogState(
    key: string,
    state: ReleaseChangelogState,
  ): void {
    releaseChangelogs.value = {
      ...releaseChangelogs.value,
      [key]: state,
    };
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

  async function rescanPending(
    scope: PendingRescanScope,
    lineNumbers: number[] = [],
  ): Promise<PendingRescanResponse> {
    if (scope === "selected" && lineNumbers.length === 0) {
      pendingRescan.value = null;
      error.value = PENDING_RESCAN_SELECTION_REQUIRED_MESSAGE;
      throw new Error(PENDING_RESCAN_SELECTION_REQUIRED_MESSAGE);
    }
    const auth = useAuthStore();
    const runs = useRunsStore();
    let response: PendingRescanResponse | null = null;
    await loadWithState(async () => {
      plan.value = null;
      pendingCleanup.value = null;
      pendingRemovalPlan.value = null;
      pendingRescan.value = null;
      response = await webApi.rescanPending(
        scope,
        rescanLinesFor(scope, lineNumbers),
        await auth.ensureCsrf(),
      );
      pendingRescan.value = response;
      pending.value = await webApi.pending();
    });
    await loadReleaseNotes().catch(() => undefined);
    refreshReleaseNotes().catch(() => undefined);
    await runs.loadRuns().catch(() => undefined);
    if (response === null) {
      throw new Error("Pending rescan did not return a response");
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

  function rescanLinesFor(
    scope: PendingRescanScope,
    lineNumbers: number[],
  ): PendingRescanLine[] {
    if (scope !== "selected") {
      return [];
    }
    const byLine = new Map(
      (pending.value?.items ?? []).map((item) => [item.line_no, item]),
    );
    const sourceHash = pending.value?.source_hash ?? "";
    return lineNumbers.map((lineNo) => {
      const item = byLine.get(lineNo);
      return {
        line_no: lineNo,
        raw: item?.raw ?? "",
        source_id: item?.source_id ?? "",
        source_hash: sourceHash,
        container_id: item?.wud_metadata?.id ?? "",
      };
    });
  }

  return {
    pending,
    updateTargets,
    retagTargets,
    retagChoices,
    retagTargetTags,
    retagPlan,
    retagPreviewJob: retagPreviewPoller.job,
    retagPreviewPolling: retagPreviewPoller.polling,
    retagPreviewError: retagPreviewPoller.error,
    retagGithubLatestFallback,
    releaseNotes,
    releaseChangelogs,
    selfUpdate,
    selfUpdatePlan,
    selfUpdateMessage,
    selfUpdateError,
    plan,
    pendingCleanup,
    pendingRemovalPlan,
    pendingRescan,
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
    setRetagChoicesForItems,
    setRetagTargetTag,
    retagChoiceRequests,
    createRetagPlan,
    applyRetagPlan,
    loadReleaseNotes,
    refreshReleaseNotes,
    releaseChangelogStateFor,
    releaseChangelogCanLoad,
    loadReleaseChangelog,
    loadSelfUpdate,
    planSelfUpdate,
    applySelfUpdate,
    createPlan,
    cleanupPending,
    createRemovalPlan,
    removeSelectedPending,
    rescanPending,
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

function releaseChangelogKeyFor(note: ReleaseNoteInfo | null): string {
  const link = releaseChangelogLinkFor(note);
  return link ? releaseChangelogKey(link) : "";
}

function releaseChangelogCanLoad(note: ReleaseNoteInfo | null): boolean {
  const link = releaseChangelogLinkFor(note);
  return Boolean(link && releaseChangelogKey(link));
}

function releaseChangelogLinkFor(note: ReleaseNoteInfo | null): string {
  return note?.links.find((link) => link.kind === "github_release")?.url ?? "";
}

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
