import type { Ref } from "vue";

import { ApiError } from "../api/client";

export function errorMessage(exc: unknown): string {
  if (exc instanceof ApiError || exc instanceof Error) {
    return exc.message;
  }
  return "Request failed";
}

export async function runWithStoreState(
  loading: Ref<boolean>,
  error: Ref<string>,
  work: () => Promise<void>,
  options: {
    onError?: (exc: unknown) => void;
    rethrow?: boolean;
  } = {},
): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    await work();
  } catch (exc) {
    options.onError?.(exc);
    error.value = errorMessage(exc);
    if (options.rethrow !== false) {
      throw exc;
    }
  } finally {
    loading.value = false;
  }
}
