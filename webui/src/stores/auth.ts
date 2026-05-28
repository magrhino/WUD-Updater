import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  type AuthSessionResponse,
  type SetupStatusResponse,
  webApi,
} from "../api/client";

export const useAuthStore = defineStore("auth", () => {
  const session = ref<AuthSessionResponse | null>(null);
  const setupStatus = ref<SetupStatusResponse | null>(null);
  const csrfToken = ref("");
  const loading = ref(false);
  const error = ref("");

  const authenticated = computed(() => session.value?.authenticated === true);
  const authRequired = computed(() => session.value?.auth_required !== false);
  const setupRequired = computed(
    () =>
      session.value?.setup_required === true ||
      setupStatus.value?.setup_required === true,
  );

  async function ensureCsrf(): Promise<string> {
    if (!csrfToken.value) {
      csrfToken.value = (await webApi.csrf()).csrf_token;
    }
    return csrfToken.value;
  }

  async function loadSession(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      session.value = await webApi.session();
    } catch (exc) {
      session.value = null;
      error.value = errorMessage(exc);
    } finally {
      loading.value = false;
    }
  }

  async function loadSetupStatus(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      setupStatus.value = await webApi.setupStatus();
    } catch (exc) {
      setupStatus.value = null;
      error.value = errorMessage(exc);
    } finally {
      loading.value = false;
    }
  }

  async function claimSetup(
    claim: string,
    username: string,
    password: string,
  ): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      session.value = await webApi.setupClaim(
        claim,
        username,
        password,
        await ensureCsrf(),
      );
      setupStatus.value = null;
    } catch (exc) {
      error.value = errorMessage(exc);
      throw exc;
    } finally {
      loading.value = false;
    }
  }

  async function login(username: string, password: string): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      session.value = await webApi.login(username, password, await ensureCsrf());
    } catch (exc) {
      error.value = errorMessage(exc);
      throw exc;
    } finally {
      loading.value = false;
    }
  }

  async function logout(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      session.value = await webApi.logout(await ensureCsrf());
      csrfToken.value = "";
    } catch (exc) {
      error.value = errorMessage(exc);
      throw exc;
    } finally {
      loading.value = false;
    }
  }

  return {
    session,
    setupStatus,
    loading,
    error,
    authenticated,
    authRequired,
    setupRequired,
    ensureCsrf,
    loadSession,
    loadSetupStatus,
    claimSetup,
    login,
    logout,
  };
});

function errorMessage(exc: unknown): string {
  if (exc instanceof ApiError || exc instanceof Error) {
    return exc.message;
  }
  return "Request failed";
}
