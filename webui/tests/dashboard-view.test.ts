import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  snooze,
  statusResponse,
  tagExclusion,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

function setupDashboardStores() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ authenticated: true });
  const connection = useConnectionStore();
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  const settings = useSettingsStore();
  settings.coreUpdateTour = coreUpdateTourResponse();
  return { pinia, auth, connection, updates, runs, settings };
}

describe("DashboardView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders status metrics from connection store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.status = statusResponse({
      pending_count: 3,
      db_ready: true,
      ok: true,
      mutations_enabled: true,
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("Ready");
    expect(wrapper.text()).toContain("OK");
  });

  it("renders pending updates from updates store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    const item = pendingItem({ line_no: 1, image: "repo/app:1.0", desired_tag: "1.1" });
    updates.pending = pendingResponse([item]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("repo/app:1.0");
    expect(wrapper.text()).toContain("1.1");
  });

  it("shows empty queue state when no pending updates", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    updates.pending = pendingResponse([]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Queue clear");
    expect(wrapper.text()).toContain("No pending updates");
  });

  it("renders recent runs from runs store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.runs = [
      runSummary({ id: 42, status: "success", started_at: "2026-06-01T10:00:00+00:00" }),
    ];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("#42");
    expect(wrapper.text()).toContain("success");
  });

  it("shows no runs empty state when runs store is empty", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.runs = [];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("No runs recorded");
  });

  it("renders management shortcut counts from settings store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    settings.servicePolicies = [
      servicePolicy({ service_key: "media/app" }),
      servicePolicy({ service_key: "media/db" }),
    ];
    settings.snoozes = [snooze({ service_key: "media/app" })];
    settings.tagExclusions = [
      tagExclusion({ tag: "2.0" }),
      tagExclusion({ id: 2, tag: "3.0" }),
      tagExclusion({ id: 3, tag: "4.0" }),
    ];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Policies");
    expect(wrapper.text()).toContain("Active snoozes");
    expect(wrapper.text()).toContain("Active exclusions");
  });

  it("shows error from connection store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.error = "Connection error: status unavailable";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.find('[role="alert"]').text()).toContain("Connection error: status unavailable");
  });

  it("shows error from updates store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    updates.error = "Updates error: pending unavailable";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("Updates error: pending unavailable");
  });

  it("shows error from runs store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.error = "Runs error: history unavailable";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("Runs error: history unavailable");
  });

  it("shows error from settings store", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    settings.error = "Settings error: policies unavailable";
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("Settings error: policies unavailable");
  });

  it("does not show error alert when all stores are clean", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it("shows warnings from connection status", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.status = statusResponse({
      warnings: ["WUD file not found: /out/images.todo"],
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.find('[data-alert-type="warning"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("WUD file not found: /out/images.todo");
  });

  it("shows warnings from pending response", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    updates.pending = {
      ...pendingResponse([]),
      warnings: ["Source file is approaching size limit."],
    };
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Source file is approaching size limit.");
  });

  it("aggregates warnings from both connection status and pending response", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.status = statusResponse({
      warnings: ["Status warning message"],
    });
    updates.pending = {
      ...pendingResponse([]),
      warnings: ["Pending warning message"],
    };
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    const warningAlerts = wrapper.findAll('[data-alert-type="warning"]');
    expect(warningAlerts).toHaveLength(2);
    const text = wrapper.text();
    expect(text).toContain("Status warning message");
    expect(text).toContain("Pending warning message");
  });

  it("calls all six store methods on mount", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    const loadStatus = vi.spyOn(connection, "loadStatus").mockResolvedValue();
    const loadPending = vi.spyOn(updates, "loadPending").mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    const loadServicePolicies = vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    const loadSnoozes = vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    const loadTagExclusions = vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(loadStatus).toHaveBeenCalledTimes(1);
    expect(loadPending).toHaveBeenCalledTimes(1);
    expect(loadRuns).toHaveBeenCalledTimes(1);
    expect(loadServicePolicies).toHaveBeenCalledTimes(1);
    expect(loadSnoozes).toHaveBeenCalledTimes(1);
    expect(loadTagExclusions).toHaveBeenCalledTimes(1);
  });

  it("does not show warning section when both status and pending have no warnings", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.status = statusResponse({ warnings: [] });
    updates.pending = pendingResponse([]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.findAll('[data-alert-type="warning"]')).toHaveLength(0);
  });

  it("shows latest run id as last run metric", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.runs = [
      runSummary({ id: 99 }),
      runSummary({ id: 98 }),
    ];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("#99");
    expect(wrapper.text()).not.toContain("#98");
  });

  it("shows None for last run when runs are empty", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.runs = [];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("None");
  });

  it("limits pending items preview to 5 entries", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1 }),
      pendingItem({ line_no: 2 }),
      pendingItem({ line_no: 3 }),
      pendingItem({ line_no: 4 }),
      pendingItem({ line_no: 5 }),
      pendingItem({ line_no: 6, image: "extra/service:1.0" }),
    ]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).not.toContain("extra/service:1.0");
  });

  it("limits recent runs preview to 5 entries", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    runs.runs = [
      runSummary({ id: 10 }),
      runSummary({ id: 11 }),
      runSummary({ id: 12 }),
      runSummary({ id: 13 }),
      runSummary({ id: 14 }),
      runSummary({ id: 15 }),
    ];
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("#10");
    expect(wrapper.text()).not.toContain("#15");
  });

  it("shows pending count from updates store when connection status is not loaded", async () => {
    const { pinia, connection, updates, runs, settings } = setupDashboardStores();
    connection.status = null;
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1 }),
      pendingItem({ line_no: 2 }),
    ]);
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("2");
  });
});