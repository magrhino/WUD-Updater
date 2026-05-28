import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  type ApplyJobResponse,
  type PlanResponse,
  type PendingResponse,
  type RunDetail,
  type RunLogResponse,
  type RunSummary,
  type StatusResponse,
  webApi,
} from "../api/client";
import { useAuthStore } from "./auth";

export const useWebuiStore = defineStore("webui", () => {
  const status = ref<StatusResponse | null>(null);
  const pending = ref<PendingResponse | null>(null);
  const plan = ref<PlanResponse | null>(null);
  const applyJob = ref<ApplyJobResponse | null>(null);
  const runs = ref<RunSummary[]>([]);
  const runDetails = ref<Record<number, RunDetail>>({});
  const runLogs = ref<Record<number, RunLogResponse>>({});
  const loading = ref(false);
  const error = ref("");

  const warnings = computed(() => [
    ...(status.value?.warnings ?? []),
    ...(pending.value?.warnings ?? []),
  ]);

  async function loadDashboard(): Promise<void> {
    await loadWithState(async () => {
      const [nextStatus, nextPending, nextRuns] = await Promise.all([
        webApi.status(),
        webApi.pending(),
        webApi.runs(),
      ]);
      status.value = nextStatus;
      pending.value = nextPending;
      runs.value = nextRuns;
    });
  }

  async function loadPending(): Promise<void> {
    await loadWithState(async () => {
      plan.value = null;
      pending.value = await webApi.pending();
    });
  }

  async function createPlan(
    lineNumbers: number[],
    allowTagUpdates: boolean,
  ): Promise<void> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      plan.value = null;
      applyJob.value = null;
      plan.value = await webApi.createPlan(
        lineNumbers,
        allowTagUpdates,
        await auth.ensureCsrf(),
      );
    });
  }

  function clearPlan(): void {
    plan.value = null;
  }

  async function applyPlan(
    planId: string,
    lineNumbers: number[],
    allowTagUpdates: boolean,
  ): Promise<ApplyJobResponse> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      applyJob.value = await webApi.applyPlan(
        planId,
        lineNumbers,
        allowTagUpdates,
        await auth.ensureCsrf(),
      );
    });
    if (applyJob.value === null) {
      throw new Error("Apply job was not created");
    }
    return applyJob.value;
  }

  async function loadApplyJob(jobId: string): Promise<void> {
    try {
      applyJob.value = await webApi.applyJob(jobId);
    } catch (exc) {
      error.value = errorMessage(exc);
      throw exc;
    }
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
    plan,
    applyJob,
    runs,
    runDetails,
    runLogs,
    loading,
    error,
    warnings,
    loadDashboard,
    loadPending,
    createPlan,
    clearPlan,
    applyPlan,
    loadApplyJob,
    loadRuns,
    loadRunDetail,
    loadRunLog,
  };
});

function errorMessage(exc: unknown): string {
  if (exc instanceof ApiError || exc instanceof Error) {
    return exc.message;
  }
  return "Request failed";
}
