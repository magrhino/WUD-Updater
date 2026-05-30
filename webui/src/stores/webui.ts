import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  type ApplyJobLogResponse,
  type ApplyJobResponse,
  type PlanResponse,
  type PendingResponse,
  type ReleaseNotesResponse,
  type RunDetail,
  type RunLogResponse,
  type RunSummary,
  type ServicePolicyRecord,
  type ServicePolicyUpdateMode,
  type SnoozeRecord,
  type SnoozeState,
  type StatusResponse,
  type StateOperation,
  type StateOperationResponse,
  type TagOverrideRequest,
  type TagExclusionRuleRecord,
  type TagExclusionScope,
  type TagExclusionStatus,
  type TagExclusionStatusFilter,
  webApi,
} from "../api/client";
import { useAuthStore } from "./auth";

export const APPLY_JOB_RECOVERY_MESSAGE =
  "Last known apply job state is unavailable because the WebUI process restarted. Check Runs -> Latest run and the updater log before applying more updates.";

const APPLY_JOB_STORAGE_KEY = "applyJobId";
const TERMINAL_APPLY_JOB_STATUSES = new Set<ApplyJobResponse["status"]>([
  "success",
  "failure",
]);

export const useWebuiStore = defineStore("webui", () => {
  const status = ref<StatusResponse | null>(null);
  const pending = ref<PendingResponse | null>(null);
  const releaseNotes = ref<ReleaseNotesResponse | null>(null);
  const plan = ref<PlanResponse | null>(null);
  const applyJob = ref<ApplyJobResponse | null>(null);
  const applyJobLog = ref<ApplyJobLogResponse | null>(null);
  const rememberedApplyJobId = ref(readRememberedApplyJobId());
  const applyJobRecovery = ref("");
  const runs = ref<RunSummary[]>([]);
  const runDetails = ref<Record<number, RunDetail>>({});
  const runLogs = ref<Record<number, RunLogResponse>>({});
  const servicePolicies = ref<ServicePolicyRecord[]>([]);
  const snoozes = ref<SnoozeRecord[]>([]);
  const tagExclusions = ref<TagExclusionRuleRecord[]>([]);
  const snoozeStateFilter = ref<SnoozeState>("active");
  const tagExclusionStatusFilter = ref<TagExclusionStatusFilter>("active");
  const loading = ref(false);
  const releaseNotesLoading = ref(false);
  const releaseNotesError = ref("");
  const error = ref("");

  const warnings = computed(() => [
    ...(status.value?.warnings ?? []),
    ...(pending.value?.warnings ?? []),
  ]);

  async function loadDashboard(): Promise<void> {
    await loadWithState(async () => {
      const [
        nextStatus,
        nextPending,
        nextRuns,
        nextServicePolicies,
        nextSnoozes,
        nextTagExclusions,
      ] = await Promise.all([
        webApi.status(),
        webApi.pending(),
        webApi.runs(),
        webApi.servicePolicies(),
        webApi.snoozes("active"),
        webApi.tagExclusions("active"),
      ]);
      status.value = nextStatus;
      pending.value = nextPending;
      runs.value = nextRuns;
      servicePolicies.value = nextServicePolicies;
      snoozes.value = nextSnoozes;
      tagExclusions.value = nextTagExclusions;
    });
  }

  async function loadPending(): Promise<void> {
    await loadWithState(async () => {
      plan.value = null;
      pending.value = await webApi.pending();
    });
  }

  async function loadReleaseNotes(): Promise<void> {
    releaseNotesLoading.value = true;
    releaseNotesError.value = "";
    try {
      releaseNotes.value = await webApi.releaseNotes();
    } catch (exc) {
      releaseNotesError.value = errorMessage(exc);
      throw exc;
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
    } catch (exc) {
      releaseNotesError.value = errorMessage(exc);
      throw exc;
    } finally {
      releaseNotesLoading.value = false;
    }
  }

  async function createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[] = [],
  ): Promise<void> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      plan.value = null;
      applyJob.value = null;
      applyJobLog.value = null;
      plan.value = await webApi.createPlan(
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
        await auth.ensureCsrf(),
      );
    });
  }

  function clearPlan(): void {
    plan.value = null;
  }

  async function createJob(
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
    tagOverrides: TagOverrideRequest[] = [],
  ): Promise<ApplyJobResponse> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      applyJobLog.value = null;
      const job = await webApi.createJob(
        planId,
        lineNumbers,
        allowTagUpdates,
        tagOverrides,
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
  ): Promise<ApplyJobResponse> {
    return createJob(planId, lineNumbers, allowTagUpdates, tagOverrides);
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
    } catch (exc) {
      if (
        options.recoverMissing &&
        exc instanceof ApiError &&
        exc.status === 404
      ) {
        markApplyJobRecovery();
        return null;
      }
      error.value = errorMessage(exc);
      throw exc;
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

  async function loadRuns(): Promise<void> {
    await loadWithState(async () => {
      runs.value = await webApi.runs();
    });
  }

  async function loadRunDetail(runId: number): Promise<void> {
    await loadWithState(async () => {
      runDetails.value = {
        ...runDetails.value,
        [runId]: await webApi.runDetail(runId),
      };
    });
  }

  async function loadRunLog(runId: number, tailBytes = 262_144): Promise<void> {
    await loadWithState(async () => {
      runLogs.value = {
        ...runLogs.value,
        [runId]: await webApi.runLog(runId, tailBytes),
      };
    });
  }

  async function loadServicePolicies(): Promise<void> {
    await loadWithState(async () => {
      servicePolicies.value = await webApi.servicePolicies();
    });
  }

  async function loadSnoozes(state: SnoozeState = "active"): Promise<void> {
    await loadWithState(async () => {
      snoozeStateFilter.value = state;
      snoozes.value = await webApi.snoozes(state);
    });
  }

  async function loadTagExclusions(
    status: TagExclusionStatusFilter = "active",
  ): Promise<void> {
    await loadWithState(async () => {
      tagExclusionStatusFilter.value = status;
      tagExclusions.value = await webApi.tagExclusions(status);
    });
  }

  async function stateOperation(
    operation: StateOperation,
  ): Promise<StateOperationResponse> {
    const auth = useAuthStore();
    let response: StateOperationResponse | null = null;
    await loadWithState(async () => {
      response = await webApi.stateOperation(operation, await auth.ensureCsrf());
    });
    if (response === null) {
      throw new Error("State operation did not return a response");
    }
    return response;
  }

  async function upsertServicePolicy(
    serviceKey: string,
    updateMode: ServicePolicyUpdateMode,
    autoUpdate: boolean,
    snoozeDefaultSeconds: number | null,
  ): Promise<void> {
    await stateOperation({
      kind: "upsert_service_policy",
      service_key: serviceKey,
      update_mode: updateMode,
      auto_update: autoUpdate,
      snooze_default_seconds: snoozeDefaultSeconds,
    });
    await loadServicePolicies();
  }

  async function deleteServicePolicy(serviceKey: string): Promise<void> {
    await stateOperation({
      kind: "delete_service_policy",
      service_key: serviceKey,
    });
    await loadServicePolicies();
  }

  async function createSnooze(
    serviceKey: string,
    snoozedUntil: string,
    reason: string,
    state: SnoozeState,
  ): Promise<void> {
    await stateOperation({
      kind: "create_snooze",
      service_key: serviceKey,
      snoozed_until: snoozedUntil,
      reason,
    });
    await loadSnoozes(state);
  }

  async function deleteSnooze(
    snoozeId: number,
    state: SnoozeState,
  ): Promise<void> {
    await stateOperation({
      kind: "delete_snooze",
      snooze_id: snoozeId,
    });
    await loadSnoozes(state);
  }

  async function upsertTagExclusion(
    scope: TagExclusionScope,
    imageRepo: string,
    serviceKey: string,
    tag: string,
    status: TagExclusionStatus,
    statusFilter: TagExclusionStatusFilter,
  ): Promise<void> {
    await stateOperation({
      kind: "upsert_tag_exclusion",
      scope,
      image_repo: imageRepo,
      service_key: serviceKey,
      match_type: "exact",
      tag,
      status,
    });
    await loadTagExclusions(statusFilter);
  }

  async function setTagExclusionStatus(
    ruleId: number,
    status: TagExclusionStatus,
    statusFilter: TagExclusionStatusFilter,
  ): Promise<void> {
    await stateOperation({
      kind: "set_tag_exclusion_status",
      rule_id: ruleId,
      status,
    });
    await loadTagExclusions(statusFilter);
  }

  async function loadWithState(work: () => Promise<void>): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      await work();
    } catch (exc) {
      error.value = errorMessage(exc);
      throw exc;
    } finally {
      loading.value = false;
    }
  }

  return {
    status,
    pending,
    releaseNotes,
    plan,
    applyJob,
    applyJobLog,
    rememberedApplyJobId,
    applyJobRecovery,
    runs,
    runDetails,
    runLogs,
    servicePolicies,
    snoozes,
    tagExclusions,
    snoozeStateFilter,
    tagExclusionStatusFilter,
    loading,
    releaseNotesLoading,
    releaseNotesError,
    error,
    warnings,
    loadDashboard,
    loadPending,
    loadReleaseNotes,
    refreshReleaseNotes,
    createPlan,
    clearPlan,
    createJob,
    applyPlan,
    setApplyJob,
    setApplyJobLog,
    setError,
    loadApplyJob,
    loadRuns,
    loadRunDetail,
    loadRunLog,
    loadServicePolicies,
    loadSnoozes,
    loadTagExclusions,
    stateOperation,
    upsertServicePolicy,
    deleteServicePolicy,
    createSnooze,
    deleteSnooze,
    upsertTagExclusion,
    setTagExclusionStatus,
  };
});

function errorMessage(exc: unknown): string {
  if (exc instanceof ApiError || exc instanceof Error) {
    return exc.message;
  }
  return "Request failed";
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
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}
