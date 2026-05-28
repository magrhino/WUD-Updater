import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  type PendingResponse,
  type RunDetail,
  type RunLogResponse,
  type RunSummary,
  type StatusResponse,
  webApi,
} from "../api/client";

export const useWebuiStore = defineStore("webui", () => {
  const status = ref<StatusResponse | null>(null);
  const pending = ref<PendingResponse | null>(null);
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
      pending.value = await webApi.pending();
    });
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
    runs,
    runDetails,
    runLogs,
    loading,
    error,
    warnings,
    loadDashboard,
    loadPending,
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
