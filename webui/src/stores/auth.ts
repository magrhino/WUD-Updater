import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { ApiError, type AuthSessionResponse, webApi } from "../api/client";

export const useAuthStore = defineStore("auth", () => {
  const session = ref<AuthSessionResponse | null>(null);
  const csrfToken = ref("");
  const loading = ref(false);
  const error = ref("");

  const authenticated = computed(() => session.value?.authenticated === true);
  const authRequired = computed(() => session.value?.auth_required !== false);

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

  async function login(token: string): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      session.value = await webApi.login(token, await ensureCsrf());
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
    loading,
    error,
    authenticated,
    authRequired,
    ensureCsrf,
    loadSession,
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
