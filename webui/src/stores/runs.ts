// webui/src/stores/runs.ts
import { ref } from "vue";
import { defineStore } from "pinia";
import {
  type RunDetail,
  type RunLogResponse,
  type RollbackPlanResponse,
  type RunSummary,
  webApi,
} from "../api/client";
import { runWithStoreState } from "./storeState";

export const useRunsStore = defineStore("runs", () => {
  const runs = ref<RunSummary[]>([]);
  const runDetails = ref<Record<number, RunDetail>>({});
  const runLogs = ref<Record<number, RunLogResponse>>({});
  const rollbackPlans = ref<Record<number, RollbackPlanResponse>>({});
  const rollbackPlanRequests = new Map<number, symbol>();
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

  async function loadRollbackPlan(runId: number): Promise<void> {
    const request = Symbol();
    rollbackPlanRequests.set(runId, request);
    await runWithStoreState(
      loading,
      error,
      async () => {
        try {
          const plan = await webApi.rollbackPlan(runId);
          if (rollbackPlanRequests.get(runId) !== request) return;
          rollbackPlans.value = { ...rollbackPlans.value, [runId]: plan };
          rollbackPlanRequests.delete(runId);
        } catch (exc) {
          if (rollbackPlanRequests.get(runId) !== request) return;
          throw exc;
        }
      },
      {
        onError: () => {
          const plans = { ...rollbackPlans.value };
          delete plans[runId];
          rollbackPlans.value = plans;
          rollbackPlanRequests.delete(runId);
        },
      },
    );
  }

  return {
    runs,
    runDetails,
    runLogs,
    rollbackPlans,
    loading,
    error,
    loadRuns,
    loadRunDetail,
    loadRunLog,
    loadRollbackPlan,
  };
});
