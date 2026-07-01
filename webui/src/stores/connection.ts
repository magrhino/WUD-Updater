// webui/src/stores/connection.ts
import { ref } from "vue";
import { defineStore } from "pinia";
import {
  type ContainerRestartResponse,
  type DiagnosticsSupportBundleResponse,
  type DoctorResponse,
  type StateOperation,
  type StateOperationResponse,
  type StatusResponse,
  webApi,
} from "../api/client";
import { useAuthStore } from "./auth";
import { runWithStoreState } from "./storeState";

export { errorMessage } from "./storeState";

export const useConnectionStore = defineStore("connection", () => {
  const status = ref<StatusResponse | null>(null);
  const doctor = ref<DoctorResponse | null>(null);
  const loading = ref(false);
  const error = ref("");

  async function loadWithState(work: () => Promise<void>): Promise<void> {
    await runWithStoreState(loading, error, work);
  }

  async function loadStatus(options: { silent?: boolean } = {}): Promise<void> {
    if (options.silent) {
      status.value = await webApi.status();
      return;
    }
    await loadWithState(async () => {
      status.value = await webApi.status();
    });
  }

  async function loadDoctor(): Promise<void> {
    const auth = useAuthStore();
    await loadWithState(async () => {
      doctor.value = await webApi.doctor(await auth.ensureCsrf());
    });
  }

  async function restartContainer(): Promise<ContainerRestartResponse> {
    const auth = useAuthStore();
    let response: ContainerRestartResponse | null = null;
    await loadWithState(async () => {
      response = await webApi.restartContainer(await auth.ensureCsrf());
    });
    if (response === null) {
      throw new Error("Container restart did not return a response");
    }
    return response;
  }

  async function diagnosticsSupportBundle(): Promise<DiagnosticsSupportBundleResponse> {
    let response: DiagnosticsSupportBundleResponse | null = null;
    await loadWithState(async () => {
      response = await webApi.diagnosticsSupportBundle();
    });
    if (response === null) {
      throw new Error("Diagnostics support bundle did not return a response");
    }
    return response;
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

  function setError(message: string): void {
    error.value = message;
  }

  return {
    status,
    doctor,
    loading,
    error,
    loadWithState,
    loadStatus,
    loadDoctor,
    restartContainer,
    diagnosticsSupportBundle,
    stateOperation,
    setError,
  };
});
