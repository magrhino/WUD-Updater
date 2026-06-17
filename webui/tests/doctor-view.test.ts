import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { nextTick } from "vue";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, webApi } from "../src/api/client";
import { createWudRouter } from "../src/router";
import DashboardView from "../src/views/DashboardView.vue";
import DoctorView from "../src/views/DoctorView.vue";
import PendingView from "../src/views/PendingView.vue";
import PoliciesView from "../src/views/PoliciesView.vue";
import SettingsView from "../src/views/SettingsView.vue";
import SnoozesView from "../src/views/SnoozesView.vue";
import TagExclusionsView from "../src/views/TagExclusionsView.vue";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import {
  applyPreflightResponse,
  applyJobLogResponse,
  applyJobResponse,
  authSession,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  pendingGroupedItem,
  pendingGrouping,
  pendingItem,
  pendingResponse,
  planResponse,
  releaseNoteInfo,
  releaseNotesResponse,
  runVerification,
  runSummary,
  servicePolicy,
  settingsResponse,
  snooze,
  statusResponse,
  tagExclusion,
  updateTarget,
  updateTargetsResponse,
} from "./helpers/fixtures";
import { mountWithApp, naiveStubs } from "./helpers/mount";


import {
  buttonByText,
  emitSelectValue,
  failedApplyPreflight,
  mockApplyJobStream,
  mockMobileViewport,
  mockPendingLifecycle,
  mountPendingView,
  pendingWithUnmatched,
  setupStores,
  stalePendingPreflightFindings,
  stalePendingPossibleReasons,
  stalePendingRecommendedActions,
  unmatchedPendingItem,
} from "./helpers/viewSecurity";

describe("doctor view", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders doctor results with redacted details and copyable suggestions", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    connection.doctor = doctorResponse({
      checks: [
        {
          status: "FAIL",
          code: "docker-daemon-info",
          category: "docker",
          name: "Docker daemon info",
          detail: "exit 17: info failed: <redacted>",
          target: "",
          suggestions: [
            {
              label: "Wire Docker access",
              description: "Mount the Docker socket or configure DOCKER_HOST.",
              snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
            },
          ],
        },
      ],
    });
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();

    const wrapper = mountWithApp(DoctorView, { pinia });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain("Doctor results");
    expect(text).toContain("Docker daemon info");
    expect(text).toContain("exit 17: info failed: <redacted>");
    expect(text).toContain("Wire Docker access");
    expect(text).toContain("Copy");
    expect(text).not.toContain("github-token-secret");
  });
});
