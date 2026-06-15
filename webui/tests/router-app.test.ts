import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import App from "../src/App.vue";
import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import SetupView from "../src/views/SetupView.vue";
import { themeStorageKey } from "../src/theme";
import {
  authSession,
  coreUpdateTourResponse,
  retagTargetsResponse,
  selfUpdateApplyResponse,
  selfUpdatePlanResponse,
  selfUpdatePrepareResponse,
  selfUpdateResponse,
  settingsResponse,
  statusResponse,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

describe("router auth guard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("routes setup-required users to setup", async () => {
    const auth = useAuthStore();
    auth.session = authSession({
      authenticated: false,
      setup_required: true,
      username: null,
    });
    const router = createWudRouter(createMemoryHistory());

    await router.push("/pending");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("setup");
  });

  it("routes unauthenticated users to login with redirect", async () => {
    const auth = useAuthStore();
    auth.session = authSession({
      authenticated: false,
      setup_required: false,
      username: null,
    });
    const router = createWudRouter(createMemoryHistory());

    await router.push("/pending");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/pending");
  });

  it("routes authenticated users away from login and setup", async () => {
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const router = createWudRouter(createMemoryHistory());

    await router.push("/login");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("dashboard");

    await router.push("/setup");

    expect(router.currentRoute.value.name).toBe("dashboard");
  });

  it("allows unauthenticated users to open admin recovery", async () => {
    const auth = useAuthStore();
    auth.session = authSession({
      authenticated: false,
      setup_required: false,
      username: null,
    });
    const router = createWudRouter(createMemoryHistory());

    await router.push("/reset-admin?claim=recovery&user=admin");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("reset-admin");
    expect(router.currentRoute.value.query.claim).toBe("recovery");
  });

  it("routes first admin setup success to Settings onboarding", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({
      authenticated: false,
      setup_required: true,
      username: null,
    });
    auth.setupStatus = {
      setup_required: true,
      claim_required: true,
      authenticated: false,
      auth_required: true,
      dev_auth_bypass: false,
      mutations_enabled: false,
      password_min_length: 12,
    };
    vi.spyOn(auth, "loadSetupStatus").mockResolvedValue();
    vi.spyOn(auth, "claimSetup").mockImplementation(async () => {
      auth.session = authSession({ authenticated: true, setup_required: false });
      auth.setupStatus = null;
    });
    const router = createWudRouter(createMemoryHistory());
    await router.push("/setup?claim=claim");
    await router.isReady();
    const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
    const wrapper = mountWithApp(SetupView, { pinia, router });

    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("admin");
    await inputs[1].setValue("correct horse battery staple");
    await inputs[2].setValue("correct horse battery staple");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(auth.claimSetup).toHaveBeenCalledWith(
      "claim",
      "admin",
      "correct horse battery staple",
    );
    expect(replace).toHaveBeenCalledWith({
      name: "settings",
      query: { onboarding: "1" },
    });
  });
});

describe("app shell", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows a linked release tag in the shell footer", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    connection.status = statusResponse({ version: "0.24.2" });
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    const versionLink = wrapper.find(
      'a[href="https://github.com/magrhino/WUD-Updater/releases/tag/v0.24.2"]',
    );

    expect(versionLink.exists()).toBe(true);
    expect(versionLink.text()).toBe("v0.24.2");
    expect(wrapper.text()).not.toContain("Mutations enabled");

    connection.status = statusResponse({ version: "dev-build" });
    await nextTick();

    const buildLink = wrapper.find(
      'a[href="https://github.com/magrhino/WUD-Updater/releases"]',
    );
    expect(buildLink.exists()).toBe(true);
    expect(buildLink.text()).toBe("dev-build");
  });

  it("cycles theme preference from system to light to dark", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.coreUpdateTour = coreUpdateTourResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    const themeButton = () => {
      const button = wrapper
        .findAll("button")
        .find((candidate) =>
          candidate.attributes("aria-label")?.includes("theme"),
        );
      if (!button) {
        throw new Error("theme button was not rendered");
      }
      return button;
    };

    expect(themeButton().attributes("aria-label")).toContain("System theme");
    expect(themeButton().attributes("title")).toBe("Theme: System theme (light)");

    await themeButton().trigger("click");
    await nextTick();

    expect(window.localStorage.getItem(themeStorageKey)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(themeButton().attributes("aria-label")).toContain("Light theme");

    await themeButton().trigger("click");
    await nextTick();

    expect(window.localStorage.getItem(themeStorageKey)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeButton().attributes("aria-label")).toContain("Dark theme");

    await themeButton().trigger("click");
    await nextTick();

    expect(window.localStorage.getItem(themeStorageKey)).toBe("auto");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(themeButton().attributes("aria-label")).toContain("System theme");
  });

  it("hydrates configured managed theme preference after authentication", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.coreUpdateTour = coreUpdateTourResponse();
    settings.settings = settingsResponse({
      managed: [
        {
          key: "theme_preference",
          value: "dark",
          default_value: "system",
          source: "configured",
          editable: true,
          allowed_values: ["system", "light", "dark"],
          restart_required: false,
        },
        settingsResponse().managed[1]!,
      ],
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await nextTick();

    expect(window.localStorage.getItem(themeStorageKey)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(
      wrapper.findAll("button").some((button) =>
        button.attributes("aria-label")?.includes("Dark theme"),
      ),
    ).toBe(true);
  });

  it("shows self-update banner and confirms release notes before applying", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    connection.status = statusResponse({ version: "0.24.2" });
    settings.coreUpdateTour = coreUpdateTourResponse();
    updates.selfUpdate = selfUpdateResponse({
      release_notes_truncated: true,
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const applySelfUpdate = vi
      .spyOn(updates, "applySelfUpdate")
      .mockResolvedValue(selfUpdateApplyResponse());
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("Update available: v0.24.2 → v0.25.0");
    expect(text).toContain("ghcr.io/magrhino/wud-updater:latest");
    const updateButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Pull image"));
    await updateButton?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.text()).toContain("Update WUD-Updater");
    expect(dialog.text()).toContain("Update Plan");
    expect(dialog.text()).toContain("Release Notes");
    expect(dialog.text()).not.toContain("Adds self-update review");
    expect(applySelfUpdate).not.toHaveBeenCalled();

    const notesTab = dialog
      .findAll("button")
      .find((button) => button.text().includes("Release Notes"));
    await notesTab?.trigger("click");
    await flushPromises();

    expect(dialog.text()).toContain("Release notes");
    expect(dialog.text()).toContain("Cap 10");
    expect(dialog.text()).toContain("Adds self-update review");

    const confirmButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Pull image"));
    await confirmButton?.trigger("click");
    await flushPromises();

    expect(applySelfUpdate).toHaveBeenCalledTimes(1);
  });

  it("shows pinned self-update tag prepare preview before applying", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    connection.status = statusResponse({ version: "0.24.2" });
    settings.coreUpdateTour = coreUpdateTourResponse();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const planSelfUpdate = vi
      .spyOn(updates, "planSelfUpdate")
      .mockImplementation(async () => {
        const plan = selfUpdatePlanResponse();
        updates.selfUpdatePlan = plan;
        return plan;
      });
    const applySelfUpdate = vi
      .spyOn(updates, "applySelfUpdate")
      .mockResolvedValue(selfUpdatePrepareResponse());
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await flushPromises();

    const updateButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Prepare tag update"));
    await updateButton?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    expect(planSelfUpdate).toHaveBeenCalledTimes(1);
    expect(dialog.text()).toContain("This updates the Compose image tag");
    expect(dialog.text()).toContain("Compose tag update");
    expect(dialog.text()).toContain("wud-updater");
    expect(dialog.text()).toContain("ghcr.io/magrhino/wud-updater:v0.25.0");

    const confirmButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Prepare tag update"));
    await confirmButton?.trigger("click");
    await flushPromises();

    expect(applySelfUpdate).toHaveBeenCalledTimes(1);
  });

  it("keeps pinned self-update confirmation disabled until preview loads", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    connection.status = statusResponse({ version: "0.24.2" });
    settings.coreUpdateTour = coreUpdateTourResponse();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    let resolvePlan: (plan: ReturnType<typeof selfUpdatePlanResponse>) => void;
    const planPromise = new Promise<ReturnType<typeof selfUpdatePlanResponse>>(
      (resolve) => {
        resolvePlan = resolve;
      },
    );
    vi.spyOn(updates, "planSelfUpdate").mockImplementation(async () => {
      const plan = await planPromise;
      updates.selfUpdatePlan = plan;
      return plan;
    });
    const applySelfUpdate = vi
      .spyOn(updates, "applySelfUpdate")
      .mockResolvedValue(selfUpdatePrepareResponse());
    const router = createWudRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await flushPromises();

    const updateButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Prepare tag update"));
    await updateButton?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    const confirmButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Prepare tag update"));
    expect(confirmButton?.attributes("disabled")).toBeDefined();
    await confirmButton?.trigger("click");
    expect(applySelfUpdate).not.toHaveBeenCalled();

    resolvePlan!(selfUpdatePlanResponse());
    await flushPromises();
    expect(confirmButton?.attributes("disabled")).toBeUndefined();
  });

  it("shows settings navigation and refreshes the settings route", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    const loadSettings = vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const loadOnboarding = vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const loadCoreUpdateTour = vi
      .spyOn(settings, "loadCoreUpdateTour")
      .mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/settings");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });

    expect(wrapper.text()).toContain("Settings");
    loadSettings.mockClear();
    loadCoreUpdateTour.mockClear();
    await wrapper.find('button[aria-label="Refresh current view"]').trigger("click");
    expect(loadSettings).toHaveBeenCalledTimes(1);
    expect(loadOnboarding).toHaveBeenCalledTimes(1);
    expect(loadCoreUpdateTour).toHaveBeenCalledTimes(1);
  });

  it("refreshes the audit route from the shell", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/audit");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await flushPromises();

    const navItems = wrapper.findAll(".nav-item");
    const historyItem = navItems.find((item) => item.text().includes("History"));
    expect(historyItem?.classes()).toContain("nav-item-active");
    expect(historyItem?.attributes("aria-current")).toBe("page");
    expect(navItems.some((item) => item.text().includes("Audit log"))).toBe(false);
    expect(wrapper.find("h1").text()).toBe("History");
    loadRuns.mockClear();
    await wrapper.find('button[aria-label="Refresh current view"]').trigger("click");
    expect(loadRuns).toHaveBeenCalledTimes(1);
  });

  it("shows retag navigation and refreshes the retags route", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    vi.spyOn(settings, "loadCoreUpdateTour").mockResolvedValue();
    vi.spyOn(updates, "loadSelfUpdate").mockResolvedValue();
    const loadRetagTargets = vi
      .spyOn(updates, "loadRetagTargets")
      .mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/retags");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });
    await flushPromises();

    const navItems = wrapper.findAll(".nav-item");
    const retagsItem = navItems.find((item) => item.text().includes("Retags"));
    expect(router.currentRoute.value.name).toBe("retags");
    expect(retagsItem?.classes()).toContain("nav-item-active");
    expect(retagsItem?.attributes("aria-current")).toBe("page");
    expect(wrapper.find("h1").text()).toBe("Retags");
    loadRetagTargets.mockClear();
    await wrapper.find('button[aria-label="Refresh current view"]').trigger("click");
    expect(loadRetagTargets).toHaveBeenCalledTimes(1);
  });
});
