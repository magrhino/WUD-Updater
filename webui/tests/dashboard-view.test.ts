import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useUpdatesStore } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import { useSettingsStore } from "../src/stores/settings";
import DashboardView from "../src/views/DashboardView.vue";
import {
  authSession,
  coreUpdateTourResponse,
  pendingItem,
  pendingResponse,
  runSummary,
  servicePolicy,
  settingsResponse,
  snooze,
  statusResponse,
  tagExclusion,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

async function setupDashboard(mutationsEnabled = false) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({
    authenticated: true,
    mutations_enabled: mutationsEnabled,
  });
  const connection = useConnectionStore();
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  const settings = useSettingsStore();
  settings.coreUpdateTour = coreUpdateTourResponse();
  const router = createWudRouter(createMemoryHistory());
  await router.push("/");
  await router.isReady();
  return { pinia, router, connection, updates, runs, settings };
}

describe("DashboardView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("triggers all six parallel store loads on mount", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    const loadStatus = vi.spyOn(connection, "loadStatus").mockResolvedValue();
    const loadPending = vi.spyOn(updates, "loadPending").mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    const loadServicePolicies = vi
      .spyOn(settings, "loadServicePolicies")
      .mockResolvedValue();
    const loadSnoozes = vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    const loadTagExclusions = vi
      .spyOn(settings, "loadTagExclusions")
      .mockResolvedValue();

    mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(loadStatus).toHaveBeenCalledTimes(1);
    expect(loadPending).toHaveBeenCalledTimes(1);
    expect(loadRuns).toHaveBeenCalledTimes(1);
    expect(loadServicePolicies).toHaveBeenCalledTimes(1);
    expect(loadSnoozes).toHaveBeenCalledTimes(1);
    expect(loadTagExclusions).toHaveBeenCalledTimes(1);
  });

  it("renders metric cards from connection.status and updates.pending", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.status = statusResponse({
      ok: true,
      pending_count: 3,
      db_ready: true,
      mutations_enabled: false,
    });
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1 }),
      pendingItem({ line_no: 2 }),
      pendingItem({ line_no: 3 }),
    ]);
    runs.runs = [runSummary({ id: 7 })];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Pending");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("Database");
    expect(wrapper.text()).toContain("Ready");
    expect(wrapper.text()).toContain("Status");
    expect(wrapper.text()).toContain("OK");
    expect(wrapper.text()).toContain("Last run");
    expect(wrapper.text()).toContain("#7");
  });

  it("shows 'None' for last run when runs list is empty", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    runs.runs = [];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("None");
  });

  it("shows empty state when there are no pending items", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    updates.pending = pendingResponse([]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Queue clear");
    expect(wrapper.text()).toContain("No pending updates are waiting for review");
  });

  it("renders pending items up to the 5-item limit", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    const items = Array.from({ length: 7 }, (_, i) =>
      pendingItem({ line_no: i + 1, image: `repo/app:${i + 1}.0` }),
    );
    updates.pending = pendingResponse(items);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("repo/app:1.0");
    expect(wrapper.text()).toContain("repo/app:5.0");
    expect(wrapper.text()).not.toContain("repo/app:6.0");
    expect(wrapper.text()).not.toContain("repo/app:7.0");
  });

  it("renders runs up to the 5-run limit", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    runs.runs = Array.from({ length: 7 }, (_, i) =>
      runSummary({ id: i + 1, status: "success" }),
    );
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("#1");
    expect(wrapper.text()).toContain("#5");
    expect(wrapper.text()).not.toContain("#6");
    expect(wrapper.text()).not.toContain("#7");
  });

  it("shows management shortcut counts from settings store", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    settings.servicePolicies = [
      servicePolicy({ service_key: "media/app" }),
      servicePolicy({ service_key: "media/sonarr" }),
    ];
    settings.snoozes = [snooze({ service_key: "media/radarr" })];
    settings.tagExclusions = [
      tagExclusion({ tag: "2.0" }),
      tagExclusion({ tag: "3.0" }),
      tagExclusion({ tag: "4.0" }),
    ];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Policies");
    expect(wrapper.text()).toContain("Active snoozes");
    expect(wrapper.text()).toContain("Active exclusions");
    const strongText = wrapper
      .findAll("strong")
      .map((el) => el.text());
    expect(strongText).toContain("2");
    expect(strongText).toContain("1");
    expect(strongText).toContain("3");
  });

  it("surfaces an error from any one of the split stores", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    runs.error = "runs database offline";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("runs database offline");
  });

  it("surfaces an error from the connection store", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.error = "status endpoint unreachable";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain(
      "status endpoint unreachable",
    );
  });

  it("shows warnings from connection.status and updates.pending combined", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.status = statusResponse({
      warnings: ["Docker socket not mounted"],
    });
    updates.pending = pendingResponse([]);
    Object.assign(updates.pending, {
      warnings: ["Pending file is stale"],
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Docker socket not mounted");
    expect(wrapper.text()).toContain("Pending file is stale");
  });

  it("shows pending count from updates.pending when connection.status is null", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.status = null;
    updates.pending = pendingResponse(
      Array.from({ length: 4 }, (_, i) => pendingItem({ line_no: i + 1 })),
    );
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    const metricStrong = wrapper
      .findAll("strong")
      .map((el) => el.text());
    expect(metricStrong).toContain("4");
  });

  it("shows 'Needs attention' when connection.status.ok is false", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.status = statusResponse({ ok: false });
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Needs attention");
  });

  it("shows 'Missing' database state when db_ready is false", async () => {
    const { pinia, router, connection, updates, runs, settings } =
      await setupDashboard();
    connection.status = statusResponse({ db_ready: false });
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia, router });
    await flushPromises();

    expect(wrapper.text()).toContain("Missing");
  });
});