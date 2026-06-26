
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { vi } from "vitest";

import { createWudRouter } from "../../src/router";
import { useAuthStore } from "../../src/stores/auth";
import { useConnectionStore } from "../../src/stores/connection";
import { useSettingsStore } from "../../src/stores/settings";
import { useUpdatesStore } from "../../src/stores/updates";
import { useRunsStore } from "../../src/stores/runs";
import PendingView from "../../src/views/PendingView.vue";
import {
  applyPreflightResponse,
  authSession,
  coreUpdateTourResponse,
  pendingGroupedItem,
  pendingGrouping,
  pendingResponse,
  statusResponse,
} from "./fixtures";
import { mountWithApp, naiveStubs } from "./mount";

export { mockApplyJobStream } from "./applyJobStream";

export function setupStores(mutationsEnabled: boolean) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ mutations_enabled: mutationsEnabled });
  const connection = useConnectionStore();
  const settings = useSettingsStore();
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  connection.status = statusResponse({ mutations_enabled: mutationsEnabled });
  settings.coreUpdateTour = coreUpdateTourResponse();
  return { pinia, auth, connection, settings, updates, runs };
}

export function failedApplyPreflight(code: string, detail: string) {
  const base = applyPreflightResponse();
  return applyPreflightResponse({
    ok: false,
    failures: 1,
    checks: base.checks.map((check) =>
      check.code === code
        ? {
            ...check,
            status: "FAIL" as const,
            detail,
          }
        : check,
    ),
  });
}

export function buttonByText(wrapperText: string, text: string) {
  return wrapperText.includes(text);
}

export function emitSelectValue(
  wrapper: ReturnType<typeof mountWithApp>,
  index: number,
  value: string | number | null,
): void {
  const select = wrapper.findAllComponents(naiveStubs.NSelect)[index];
  if (!select) {
    throw new Error(`Missing select at index ${index}`);
  }
  select.vm.$emit("update:value", value);
}

export function mockMobileViewport(): () => void {
  const originalMatchMedia = window.matchMedia;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches:
      !query.includes("prefers-") &&
      (query.includes("max-width") || query.includes("width <")),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  return () => {
    window.matchMedia = originalMatchMedia;
  };
}

export function mockPendingLifecycle(
  settings: ReturnType<typeof useSettingsStore>,
  updates: ReturnType<typeof useUpdatesStore>,
) {
  vi.spyOn(updates, "loadPending").mockResolvedValue();
  vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
  vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
  vi.spyOn(updates, "loadSecurityScans").mockResolvedValue();
  vi.spyOn(settings, "loadPendingSafetyCues").mockResolvedValue();
}

export function mountPendingView(pinia: ReturnType<typeof createPinia>) {
  const router = createWudRouter(createMemoryHistory());
  return mountWithApp(PendingView, { pinia, router });
}

export const stalePendingPreflightFindings = [
  "Running container old still matches this pending line.",
  "Docker labels reference docker-compose.yml.",
  "The referenced Compose file was not found, but archived/nonstandard file(s) were found: docker-compose.archive.yml.",
];
export const stalePendingPossibleReasons = [
  "The active Compose file was renamed to an archived or nonstandard filename.",
  "The stack was moved or the Compose file path changed after the container was created.",
];
export const stalePendingRecommendedActions = [
  "Restore or rename the active Compose file to a supported Compose filename.",
  "Update Docker base or ignore paths if the stack moved.",
  "Remove the stale WUD line if the stack is intentionally gone.",
];

export function unmatchedPendingItem() {
  return pendingGroupedItem({
    line_no: 1,
    raw: "repo/old:latest",
    image: "repo/old:latest",
    repo: "repo/old",
    current_tag: "latest",
    desired_tag: "",
    services: [],
    diagnostic: {
      code: "compose-label-active-file-missing",
      message:
        "Container old was created from stack media, but docker-compose.yml is missing.",
      hint: "Only docker-compose.archive.yml was found; restore an active Compose file or remove the stale pending line.",
      stack: "media",
      service: "old",
      compose_file: "docker-compose.yml",
      found_files: ["docker-compose.archive.yml"],
      details: {
        preflight_findings: stalePendingPreflightFindings,
        possible_reasons: stalePendingPossibleReasons,
        recommended_actions: stalePendingRecommendedActions,
      },
    },
  });
}

export function pendingWithUnmatched(item = unmatchedPendingItem()) {
  return {
    ...pendingResponse([item]),
    grouping: {
      ...pendingGrouping([]),
      groups: [],
      unmatched: [item],
    },
  };
}
