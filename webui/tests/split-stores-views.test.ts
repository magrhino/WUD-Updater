import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useUpdatesStore } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdateTargetOptions } from "../src/composables/useUpdateTargetOptions";
import DashboardView from "../src/views/DashboardView.vue";
import DoctorView from "../src/views/DoctorView.vue";
import LogView from "../src/views/LogView.vue";
import CoreUpdateTourPanel from "../src/components/CoreUpdateTourPanel.vue";
import OnboardingChecklist from "../src/components/OnboardingChecklist.vue";
import {
  authSession,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  onboardingDismissResponse,
  pendingResponse,
  runSummary,
  servicePolicy,
  snooze,
  statusResponse,
  updateTarget,
  updateTargetsResponse,
} from "./helpers/fixtures";
import { mountWithApp, naiveStubs } from "./helpers/mount";

function mockMediaQueries(matches: (query: string) => boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function mockDesktopViewport(): void {
  mockMediaQueries((query) => query.includes("min-width"));
}

describe("DashboardView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mockDesktopViewport();
  });

  it("renders pending count from connection status", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    connection.status = statusResponse({ pending_count: 3 });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("3");
  });

  it("falls back to pending count from updates store when status is unavailable", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    connection.status = null;
    updates.pending = { ...pendingResponse(), count: 7 };
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("7");
  });

  it("shows error from connection store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    connection.error = "connection failed";
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.find('[role="alert"]').text()).toContain("connection failed");
  });

  it("shows error from runs store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    runs.error = "runs fetch failed";
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.find('[role="alert"]').text()).toContain("runs fetch failed");
  });

  it("shows error from settings store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    settings.error = "settings load failed";
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.find('[role="alert"]').text()).toContain("settings load failed");
  });

  it("displays status warnings from connection store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    connection.status = statusResponse({ warnings: ["WUD file missing"] });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("WUD file missing");
  });

  it("shows service policy and snooze counts from settings store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    settings.servicePolicies = [servicePolicy(), servicePolicy({ service_key: "media/radarr" })];
    settings.snoozes = [snooze()];
    settings.tagExclusions = [];
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("Active snoozes");
    expect(wrapper.text()).toContain("1");
  });

  it("shows latest run from runs store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    runs.runs = [runSummary({ id: 42 }), runSummary({ id: 41 })];
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("#42");
  });

  it("calls all 6 store loaders on mount", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse();
    const loadStatus = vi.spyOn(connection, "loadStatus").mockResolvedValue();
    const loadPending = vi.spyOn(updates, "loadPending").mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    const loadServicePolicies = vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    const loadSnoozes = vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    const loadTagExclusions = vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(loadStatus).toHaveBeenCalledTimes(1);
    expect(loadPending).toHaveBeenCalledTimes(1);
    expect(loadRuns).toHaveBeenCalledTimes(1);
    expect(loadServicePolicies).toHaveBeenCalledTimes(1);
    expect(loadSnoozes).toHaveBeenCalledTimes(1);
    expect(loadTagExclusions).toHaveBeenCalledTimes(1);
  });

  it("shows empty state when no runs recorded", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    runs.runs = [];
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("No runs recorded.");
  });

  it("shows OK status metric from connection store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    const settings = useSettingsStore();
    connection.status = statusResponse({ ok: true });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(DashboardView, { pinia, router });

    expect(wrapper.text()).toContain("OK");
  });
});

describe("DoctorView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mockDesktopViewport();
  });

  it("loads doctor results on mount when not yet loaded", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    const loadDoctor = vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    mountWithApp(DoctorView, { pinia, router });
    await flushPromises();

    expect(loadDoctor).toHaveBeenCalledTimes(1);
  });

  it("skips loading doctor results when already loaded", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    connection.doctor = doctorResponse();
    const loadDoctor = vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    mountWithApp(DoctorView, { pinia, router });
    await flushPromises();

    expect(loadDoctor).not.toHaveBeenCalled();
  });

  it("displays doctor check results from connection store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    connection.doctor = doctorResponse();
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    const wrapper = mountWithApp(DoctorView, { pinia, router });

    expect(wrapper.text()).toContain("Docker daemon info");
    expect(wrapper.text()).toContain("exit 17: permission denied");
  });

  it("shows error from connection store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    connection.error = "doctor check failed";
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    const wrapper = mountWithApp(DoctorView, { pinia, router });

    expect(wrapper.find('[role="alert"]').text()).toContain("doctor check failed");
  });

  it("calls loadDoctor on refresh button click", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    connection.doctor = doctorResponse();
    const loadDoctor = vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    const wrapper = mountWithApp(DoctorView, { pinia, router });
    loadDoctor.mockClear();
    const refreshButton = wrapper
      .findAll("button")
      .find((btn) => btn.attributes("title")?.includes("Refresh"));
    await refreshButton?.trigger("click");
    await flushPromises();

    expect(loadDoctor).toHaveBeenCalledTimes(1);
  });

  it("shows loading skeleton while doctor results are being fetched", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const connection = useConnectionStore();
    connection.loading = true;
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/doctor");
    await router.isReady();

    const wrapper = mountWithApp(DoctorView, { pinia, router });

    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true);
  });
});

describe("LogView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads run log on mount", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    const loadRunLog = vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/5/log");
    await router.isReady();

    mountWithApp(LogView, { pinia, router });
    await flushPromises();

    expect(loadRunLog).toHaveBeenCalledWith(5);
  });

  it("displays log content from runs store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    runs.runLogs = {
      5: {
        run_id: 5,
        log_file: "/out/logs/run-5.log",
        exists: true,
        content: "run 5 log output",
        truncated: false,
        max_bytes: 262_144,
      },
    };
    vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/5/log");
    await router.isReady();

    const wrapper = mountWithApp(LogView, { pinia, router });

    expect(wrapper.text()).toContain("run 5 log output");
    expect(wrapper.text()).toContain("#5 log");
  });

  it("shows error from runs store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    runs.error = "log file not found";
    vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/5/log");
    await router.isReady();

    const wrapper = mountWithApp(LogView, { pinia, router });

    expect(wrapper.find('[role="alert"]').text()).toContain("log file not found");
  });

  it("shows truncation warning when log is truncated", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    runs.runLogs = {
      7: {
        run_id: 7,
        log_file: "/out/logs/run-7.log",
        exists: true,
        content: "partial content",
        truncated: true,
        max_bytes: 4_096,
      },
    };
    vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/7/log");
    await router.isReady();

    const wrapper = mountWithApp(LogView, { pinia, router });

    expect(wrapper.find('[data-alert-type="warning"]').text()).toContain("4096 bytes");
  });

  it("shows empty state when log file does not exist", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    runs.runLogs = {
      3: {
        run_id: 3,
        log_file: "/out/logs/run-3.log",
        exists: false,
        content: "",
        truncated: false,
        max_bytes: 262_144,
      },
    };
    vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/3/log");
    await router.isReady();

    const wrapper = mountWithApp(LogView, { pinia, router });

    expect(wrapper.text()).toContain("Log file not found.");
  });

  it("reloads log when run id route param changes", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const runs = useRunsStore();
    const loadRunLog = vi.spyOn(runs, "loadRunLog").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/runs/5/log");
    await router.isReady();

    mountWithApp(LogView, { pinia, router });
    await flushPromises();
    loadRunLog.mockClear();

    await router.push("/runs/6/log");
    await nextTick();
    await flushPromises();

    expect(loadRunLog).toHaveBeenCalledWith(6);
  });
});

describe("CoreUpdateTourPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("is hidden when tour status is not in_progress", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({ status: "not_started" });
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour step detail",
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.find('[aria-label="Core update tour"]').exists()).toBe(false);
  });

  it("is visible when tour is in_progress at the matching step", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail text",
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.find('[aria-label="Core update tour"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Dashboard Tour");
    expect(wrapper.text()).toContain("Tour detail text");
  });

  it("is hidden when tour is in_progress but at a different step", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "pending_select",
    });
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail text",
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.find('[aria-label="Core update tour"]').exists()).toBe(false);
  });

  it("is hidden when show prop is false even if tour step matches", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail text",
        show: false,
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.find('[aria-label="Core update tour"]').exists()).toBe(false);
  });

  it("calls settings.updateCoreUpdateTour when advancing with in_progress status", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(coreUpdateTourResponse({ status: "in_progress", step: "pending_select" }));
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail",
        nextStep: "pending_select" as const,
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    const advanceButton = wrapper
      .findAll("button")
      .find((btn) => btn.text().includes("Continue tour"));
    await advanceButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("in_progress", "pending_select");
  });

  it("calls settings.updateCoreUpdateTour with completed status when complete prop is true", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "runs_history",
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(coreUpdateTourResponse({ status: "completed", step: "runs_history" }));
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "runs_history" as const,
        title: "History Tour",
        detail: "Final step",
        complete: true,
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.text()).toContain("Finish tour");

    const finishButton = wrapper
      .findAll("button")
      .find((btn) => btn.text().includes("Finish tour"));
    await finishButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("completed", "runs_history");
  });

  it("calls settings.updateCoreUpdateTour with dismissed when dismissing", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(coreUpdateTourResponse({ status: "dismissed", step: "dashboard" }));
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail",
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    const dismissButton = wrapper
      .findAll("button")
      .find((btn) => btn.text().includes("Dismiss tour"));
    await dismissButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("dismissed", "dashboard");
  });

  it("shows custom next label when nextLabel prop is provided", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(CoreUpdateTourPanel, {
      props: {
        step: "dashboard" as const,
        title: "Dashboard Tour",
        detail: "Tour detail",
        nextLabel: "Go to Pending",
      },
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.text()).toContain("Go to Pending");
    expect(wrapper.text()).not.toContain("Continue tour");
  });
});

describe("OnboardingChecklist", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads onboarding and core update tour on mount when not yet loaded", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const settings = useSettingsStore();
    const loadOnboarding = vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const loadCoreUpdateTour = vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });
    await flushPromises();

    expect(loadOnboarding).toHaveBeenCalledTimes(1);
    expect(loadCoreUpdateTour).toHaveBeenCalledTimes(1);
  });

  it("skips loading when onboarding and tour are already loaded", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const settings = useSettingsStore();
    settings.onboarding = onboardingChecklistResponse();
    settings.coreUpdateTour = coreUpdateTourResponse();
    const loadOnboarding = vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const loadCoreUpdateTour = vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });
    await flushPromises();

    expect(loadOnboarding).not.toHaveBeenCalled();
    expect(loadCoreUpdateTour).not.toHaveBeenCalled();
  });

  it("renders checklist items from settings store onboarding", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.onboarding = onboardingChecklistResponse({ visible: true });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.text()).toContain("Admin setup");
    expect(wrapper.text()).toContain("Docker daemon access");
  });

  it("shows 'Resume update tour' label when tour is in progress", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.onboarding = onboardingChecklistResponse({
      visible: true,
      all_passed: true,
      items: [
        {
          key: "admin-setup",
          title: "Admin setup",
          status: "PASS",
          detail: "Admin exists.",
          check_codes: [],
          suggestions: [],
          docs: [],
        },
      ],
    });
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "pending_select",
    });
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    vi.spyOn(settings, "updateCoreUpdateTour").mockResolvedValue(
      coreUpdateTourResponse({ status: "in_progress", step: "pending_select" }),
    );
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.text()).toContain("Resume update tour");
  });

  it("shows 'Start update tour' when tour is not started and all items pass", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const settings = useSettingsStore();
    settings.onboarding = onboardingChecklistResponse({
      visible: true,
      all_passed: true,
      items: [
        {
          key: "admin-setup",
          title: "Admin setup",
          status: "PASS",
          detail: "Admin exists.",
          check_codes: [],
          suggestions: [],
          docs: [],
        },
      ],
    });
    settings.coreUpdateTour = coreUpdateTourResponse({ status: "not_started" });
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    vi.spyOn(settings, "updateCoreUpdateTour").mockResolvedValue(
      coreUpdateTourResponse({ status: "in_progress", step: "dashboard" }),
    );
    const router = createWudRouter(createMemoryHistory());

    const wrapper = mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });

    expect(wrapper.text()).toContain("Start update tour");
  });

  it("calls settings.dismissOnboarding when dismiss button clicked", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const settings = useSettingsStore();
    settings.onboarding = onboardingChecklistResponse({ visible: true });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    const dismissOnboarding = vi
      .spyOn(settings, "dismissOnboarding")
      .mockResolvedValue(onboardingDismissResponse());
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mount(OnboardingChecklist, {
      global: {
        plugins: [pinia, router],
        stubs: naiveStubs,
      },
    });
    const dismissButton = wrapper
      .findAll("button")
      .find((btn) => btn.text().toLowerCase().includes("dismiss"));
    await dismissButton?.trigger("click");
    await flushPromises();

    expect(dismissOnboarding).toHaveBeenCalledTimes(1);
  });
});

describe("useUpdateTargetOptions composable", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("returns empty options when updateTargets is null", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = null;

    const { serviceKeyOptions, imageRepoOptions, targets } = useUpdateTargetOptions();

    expect(targets.value).toEqual([]);
    expect(serviceKeyOptions.value).toEqual([]);
    expect(imageRepoOptions.value).toEqual([]);
  });

  it("returns service key and image repo options from updates store", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse();

    const { serviceKeyOptions, imageRepoOptions } = useUpdateTargetOptions();

    expect(serviceKeyOptions.value).toHaveLength(1);
    expect(serviceKeyOptions.value[0]?.value).toBe("media/app");
    expect(imageRepoOptions.value[0]?.value).toBe("repo/app");
  });

  it("deduplicates options with the same value", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = {
      status: "ready",
      count: 2,
      items: [
        updateTarget({ service_key: "media/app", image_repo: "repo/app" }),
        updateTarget({ service_key: "media/app", image_repo: "repo/app" }),
      ],
      warnings: [],
    };

    const { serviceKeyOptions, imageRepoOptions } = useUpdateTargetOptions();

    expect(serviceKeyOptions.value).toHaveLength(1);
    expect(imageRepoOptions.value).toHaveLength(1);
  });

  it("returns sorted options alphabetically", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = {
      status: "ready",
      count: 3,
      items: [
        updateTarget({ service_key: "media/sonarr", image_repo: "linuxserver/sonarr" }),
        updateTarget({ service_key: "media/app", image_repo: "repo/app" }),
        updateTarget({ service_key: "media/radarr", image_repo: "linuxserver/radarr" }),
      ],
      warnings: [],
    };

    const { serviceKeyOptions } = useUpdateTargetOptions();

    const keys = serviceKeyOptions.value.map((o) => o.value);
    expect(keys).toEqual(["media/app", "media/radarr", "media/sonarr"]);
  });

  it("returns target for given service key", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse();

    const { targetForServiceKey } = useUpdateTargetOptions();

    const found = targetForServiceKey("media/app");
    expect(found?.service_key).toBe("media/app");
    expect(targetForServiceKey("nonexistent/service")).toBeUndefined();
  });

  it("returns target for given image repo", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse();

    const { targetForImageRepo } = useUpdateTargetOptions();

    const found = targetForImageRepo("repo/app");
    expect(found?.image_repo).toBe("repo/app");
    expect(targetForImageRepo("nonexistent/repo")).toBeUndefined();
  });

  it("returns tag options for image repo filtered by non-empty current_tag", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = {
      status: "ready",
      count: 3,
      items: [
        updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "1.0" }),
        updateTarget({ service_key: "media/app2", image_repo: "repo/app", current_tag: "1.1" }),
        updateTarget({ service_key: "other/service", image_repo: "other/repo", current_tag: "2.0" }),
      ],
      warnings: [],
    };

    const { tagOptionsForImageRepo } = useUpdateTargetOptions();

    const tags = tagOptionsForImageRepo("repo/app");
    expect(tags).toHaveLength(2);
    expect(tags.map((t) => t.value)).toContain("1.0");
    expect(tags.map((t) => t.value)).toContain("1.1");
    expect(tags.map((t) => t.value)).not.toContain("2.0");
  });

  it("excludes targets with blank current_tag from tag options", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.updateTargets = {
      status: "ready",
      count: 2,
      items: [
        updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "1.0" }),
        updateTarget({ service_key: "media/app2", image_repo: "repo/app", current_tag: "   " }),
      ],
      warnings: [],
    };

    const { tagOptionsForImageRepo } = useUpdateTargetOptions();

    const tags = tagOptionsForImageRepo("repo/app");
    expect(tags).toHaveLength(1);
    expect(tags[0]?.value).toBe("1.0");
  });
});