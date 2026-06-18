import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, type RouteLocationRaw, type Router } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWudRouter } from "../src/router";
import CoreUpdateTourPanel from "../src/components/CoreUpdateTourPanel.vue";
import OnboardingChecklist from "../src/components/OnboardingChecklist.vue";
import DashboardView from "../src/views/DashboardView.vue";
import DoctorView from "../src/views/DoctorView.vue";
import LogView from "../src/views/LogView.vue";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useRunsStore } from "../src/stores/runs";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore } from "../src/stores/updates";
import {
  authSession,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  pendingItem,
  pendingResponse,
  runSummary,
  servicePolicy,
  snooze,
  statusResponse,
  tagExclusion,
} from "./helpers/fixtures";
import { mountWithApp, naiveStubs } from "./helpers/mount";

async function setupRoute(
  to?: RouteLocationRaw,
): Promise<{
  pinia: Pinia;
  router: Router;
  connection: ReturnType<typeof useConnectionStore>;
  settings: ReturnType<typeof useSettingsStore>;
  updates: ReturnType<typeof useUpdatesStore>;
  runs: ReturnType<typeof useRunsStore>;
}> {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ authenticated: true });
  const connection = useConnectionStore();
  const settings = useSettingsStore();
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  settings.coreUpdateTour = coreUpdateTourResponse();
  const router = createWudRouter(createMemoryHistory());
  await router.push(to ?? { name: "dashboard" });
  await router.isReady();
  return { pinia, router, connection, settings, updates, runs };
}

function stubDashboardLoaders(
  connection: ReturnType<typeof useConnectionStore>,
  settings: ReturnType<typeof useSettingsStore>,
  updates: ReturnType<typeof useUpdatesStore>,
  runs: ReturnType<typeof useRunsStore>,
) {
  return {
    loadStatus: vi.spyOn(connection, "loadStatus").mockResolvedValue(),
    loadPending: vi.spyOn(updates, "loadPending").mockResolvedValue(),
    loadRuns: vi.spyOn(runs, "loadRuns").mockResolvedValue(),
    loadServicePolicies: vi
      .spyOn(settings, "loadServicePolicies")
      .mockResolvedValue(),
    loadSnoozes: vi.spyOn(settings, "loadSnoozes").mockResolvedValue(),
    loadTagExclusions: vi
      .spyOn(settings, "loadTagExclusions")
      .mockResolvedValue(),
  };
}

function mountTourPanel(
  pinia: Pinia,
  router: Router,
  props: InstanceType<typeof CoreUpdateTourPanel>["$props"],
) {
  return mount(CoreUpdateTourPanel, {
    props,
    global: {
      plugins: [pinia, router],
      stubs: naiveStubs,
    },
  });
}

describe("DashboardView split-store coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads each split store slice on mount", async () => {
    const { pinia, router, connection, settings, updates, runs } =
      await setupRoute();
    const loaders = stubDashboardLoaders(connection, settings, updates, runs);

    mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(loaders.loadStatus).toHaveBeenCalledTimes(1);
    expect(loaders.loadPending).toHaveBeenCalledTimes(1);
    expect(loaders.loadRuns).toHaveBeenCalledTimes(1);
    expect(loaders.loadServicePolicies).toHaveBeenCalledTimes(1);
    expect(loaders.loadSnoozes).toHaveBeenCalledTimes(1);
    expect(loaders.loadTagExclusions).toHaveBeenCalledTimes(1);
  });

  it("renders metrics, warnings, and management counts from split stores", async () => {
    const { pinia, router, connection, settings, updates, runs } =
      await setupRoute();
    stubDashboardLoaders(connection, settings, updates, runs);
    connection.status = statusResponse({
      ok: false,
      pending_count: 3,
      db_ready: false,
      warnings: ["Database file is not ready"],
    });
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1, image: "repo/app:1.0" }),
      pendingItem({ line_no: 2, image: "repo/db:1.0", repo: "repo/db" }),
    ]);
    runs.runs = [runSummary({ id: 42 })];
    settings.servicePolicies = [
      servicePolicy(),
      servicePolicy({ service_key: "media/radarr" }),
    ];
    settings.snoozes = [snooze()];
    settings.tagExclusions = [tagExclusion()];

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Database file is not ready");
    expect(wrapper.text()).toContain("Pending");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("Missing");
    expect(wrapper.text()).toContain("#42");
    expect(wrapper.text()).toContain("Needs attention");
    expect(wrapper.text()).toContain("Metadata ready");
    expect(wrapper.text()).toContain("Policies");
    expect(wrapper.text()).toContain("Active snoozes");
    expect(wrapper.text()).toContain("Active exclusions");
  });

  it("falls back to pending count from updates when status is unavailable", async () => {
    const { pinia, router, connection, settings, updates, runs } =
      await setupRoute();
    stubDashboardLoaders(connection, settings, updates, runs);
    connection.status = null;
    updates.pending = {
      ...pendingResponse([]),
      count: 7,
    };

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("7");
    expect(wrapper.text()).toContain("Queue clear");
    expect(wrapper.text()).toContain("No runs recorded.");
  });
});

describe("DoctorView split-store coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads doctor results on mount only when missing", async () => {
    const { pinia, router, connection } = await setupRoute({ name: "doctor" });
    const loadDoctor = vi.spyOn(connection, "loadDoctor").mockResolvedValue();

    mountWithApp(DoctorView, { pinia, router });
    await flushPromises();

    expect(loadDoctor).toHaveBeenCalledTimes(1);
  });

  it("renders doctor checks and refreshes through the connection store", async () => {
    const { pinia, router, connection } = await setupRoute({ name: "doctor" });
    connection.doctor = doctorResponse();
    const loadDoctor = vi.spyOn(connection, "loadDoctor").mockResolvedValue();

    const wrapper = mountWithApp(DoctorView, { pinia, router });
    await flushPromises();

    expect(loadDoctor).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Docker daemon info");
    expect(wrapper.text()).toContain("Pass");
    expect(wrapper.text()).toContain("Warn");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Refresh"))
      ?.trigger("click");

    expect(loadDoctor).toHaveBeenCalledTimes(1);
  });
});

describe("LogView split-store coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads and displays logs from the runs store, then reacts to route changes", async () => {
    const { pinia, router, runs } = await setupRoute({
      name: "run-log",
      params: { id: "10" },
    });
    runs.runLogs = {
      10: {
        run_id: 10,
        log_file: "/out/logs/run-10.log",
        exists: true,
        content: "run 10 log\n",
        truncated: false,
        max_bytes: 262_144,
      },
    };
    const loadRunLog = vi.spyOn(runs, "loadRunLog").mockResolvedValue();

    const wrapper = mountWithApp(LogView, { pinia, router });
    await flushPromises();

    expect(loadRunLog).toHaveBeenCalledWith(10);
    expect(wrapper.text()).toContain("#10 log");
    expect(wrapper.text()).toContain("run 10 log");

    await router.push({ name: "run-log", params: { id: "11" } });
    await flushPromises();

    expect(loadRunLog).toHaveBeenCalledWith(11);
  });

  it("shows missing and truncated log states", async () => {
    const { pinia, router, runs } = await setupRoute({
      name: "run-log",
      params: { id: "12" },
    });
    runs.runLogs = {
      12: {
        run_id: 12,
        log_file: "/out/logs/run-12.log",
        exists: false,
        content: "",
        truncated: true,
        max_bytes: 4_096,
      },
    };
    vi.spyOn(runs, "loadRunLog").mockResolvedValue();

    const wrapper = mountWithApp(LogView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Showing the last 4096 bytes.");
    expect(wrapper.text()).toContain("Log file not found.");
  });
});

describe("CoreUpdateTourPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("advances the matching tour step and navigates to the next route", async () => {
    const { pinia, router, settings } = await setupRoute();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockImplementation(async (status, step) => {
        settings.coreUpdateTour = coreUpdateTourResponse({ status, step });
        return settings.coreUpdateTour;
      });
    const routerPush = vi.spyOn(router, "push");
    const wrapper = mountTourPanel(pinia, router, {
      step: "dashboard",
      title: "Start from current state",
      detail: "Review the dashboard before choosing updates.",
      nextLabel: "Open pending updates",
      nextStep: "pending_select",
      nextTo: "/pending",
    });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Open pending updates"))
      ?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith(
      "in_progress",
      "pending_select",
    );
    expect(routerPush).toHaveBeenCalledWith("/pending");
  });

  it("stays hidden when the tour is not active for the step", async () => {
    const { pinia, router, settings } = await setupRoute();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "pending_select",
    });

    const wrapper = mountTourPanel(pinia, router, {
      step: "dashboard",
      title: "Start from current state",
      detail: "Review the dashboard before choosing updates.",
    });

    expect(wrapper.text()).not.toContain("Start from current state");
  });
});

describe("OnboardingChecklist split-store coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads onboarding and tour state on mount when not cached", async () => {
    const { pinia, router, settings } = await setupRoute({ name: "settings" });
    settings.onboarding = null;
    settings.coreUpdateTour = null;
    const loadOnboarding = vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const ensureCoreUpdateTour = vi
      .spyOn(settings, "ensureCoreUpdateTour")
      .mockResolvedValue();

    mountWithApp(OnboardingChecklist, { pinia, router });
    await flushPromises();

    expect(loadOnboarding).toHaveBeenCalledTimes(1);
    expect(ensureCoreUpdateTour).toHaveBeenCalledTimes(1);
  });

  it("starts the update tour once setup has no failing checks", async () => {
    const { pinia, router, settings } = await setupRoute({ name: "settings" });
    const readyChecklist = onboardingChecklistResponse();
    settings.onboarding = {
      ...readyChecklist,
      all_passed: true,
      items: readyChecklist.items.map((item) => ({
        ...item,
        status: "PASS" as const,
        detail: "ok",
      })),
    };
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "not_started",
      step: "dashboard",
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(coreUpdateTourResponse({
        status: "in_progress",
        step: "dashboard",
      }));

    const wrapper = mountWithApp(OnboardingChecklist, { pinia, router });
    await flushPromises();

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Start update tour"))
      ?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith(
      "in_progress",
      "dashboard",
    );
    expect(router.currentRoute.value.name).toBe("dashboard");
  });
});
