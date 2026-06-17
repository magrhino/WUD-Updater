// webui/src/stores/runs.ts
import { ref } from "vue";
import { defineStore } from "pinia";
import {
  type RunDetail,
  type RunLogResponse,
  type RunSummary,
  webApi,
} from "../api/client";
import { runWithStoreState } from "./storeState";

export const useRunsStore = defineStore("runs", () => {
  const runs = ref<RunSummary[]>([]);
  const runDetails = ref<Record<number, RunDetail>>({});
  const runLogs = ref<Record<number, RunLogResponse>>({});
  const loading = ref(false);
  const error = ref("");

  async function loadWithState(work: () => Promise<void>): Promise<void> {
    await runWithStoreState(loading, error, work);
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

  return {
    runs,
    runDetails,
    runLogs,
    loading,
    error,
    loadRuns,
    loadRunDetail,
    loadRunLog,
  };
});
