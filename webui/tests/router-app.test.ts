import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import App from "../src/App.vue";
import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useWebuiStore } from "../src/stores/webui";
import SetupView from "../src/views/SetupView.vue";
import { themeStorageKey } from "../src/theme";
import { authSession, settingsResponse, statusResponse } from "./helpers/fixtures";
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
    const webui = useWebuiStore();
    webui.status = statusResponse({ version: "0.24.2" });
    vi.spyOn(webui, "loadDashboard").mockResolvedValue();
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

    webui.status = statusResponse({ version: "dev-build" });
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
    const webui = useWebuiStore();
    vi.spyOn(webui, "loadDashboard").mockResolvedValue();
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
    const webui = useWebuiStore();
    webui.settings = settingsResponse({
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
    vi.spyOn(webui, "loadDashboard").mockResolvedValue();
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

  it("shows settings navigation and refreshes the settings route", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
    const webui = useWebuiStore();
    vi.spyOn(webui, "loadStatus").mockResolvedValue();
    const loadSettings = vi.spyOn(webui, "loadSettings").mockResolvedValue();
    const loadOnboarding = vi.spyOn(webui, "loadOnboarding").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/settings");
    await router.isReady();

    const wrapper = mountWithApp(App, { pinia, router });

    expect(wrapper.text()).toContain("Settings");
    loadSettings.mockClear();
    await wrapper.find('button[aria-label="Refresh current view"]').trigger("click");
    expect(loadSettings).toHaveBeenCalledTimes(1);
    expect(loadOnboarding).toHaveBeenCalledTimes(1);
  });
});
