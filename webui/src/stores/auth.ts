import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  type AuthSessionResponse,
  type SetupStatusResponse,
  webApi,
} from "../api/client";
import { runWithStoreState } from "./storeState";

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
    await runWithStoreState(
      loading,
      error,
      async () => {
        session.value = await webApi.session();
      },
      {
        onError: () => {
          session.value = null;
        },
        rethrow: false,
      },
    );
  }

  async function loadSetupStatus(): Promise<void> {
    await runWithStoreState(
      loading,
      error,
      async () => {
        setupStatus.value = await webApi.setupStatus();
      },
      {
        onError: () => {
          setupStatus.value = null;
        },
        rethrow: false,
      },
    );
  }

  async function claimSetup(
    claim: string,
    username: string,
    password: string,
  ): Promise<void> {
    await runWithStoreState(loading, error, async () => {
      session.value = await webApi.setupClaim(
        claim,
        username,
        password,
        await ensureCsrf(),
      );
      setupStatus.value = null;
    });
  }

  async function resetAdmin(
    claim: string,
    username: string,
    password: string,
  ): Promise<void> {
    await runWithStoreState(loading, error, async () => {
      session.value = await webApi.resetAdminClaim(
        claim,
        username,
        password,
        await ensureCsrf(),
      );
      setupStatus.value = null;
    });
  }

  async function login(username: string, password: string): Promise<void> {
    await runWithStoreState(loading, error, async () => {
      session.value = await webApi.login(username, password, await ensureCsrf());
    });
  }

  async function logout(): Promise<void> {
    await runWithStoreState(loading, error, async () => {
      session.value = await webApi.logout(await ensureCsrf());
      csrfToken.value = "";
    });
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
    resetAdmin,
    login,
    logout,
  };
});
