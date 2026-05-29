import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import App from "../src/App.vue";
import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useWebuiStore } from "../src/stores/webui";
import { authSession } from "./helpers/fixtures";
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
});

describe("app shell", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows read-only and mutation-enabled shell state", async () => {
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

    expect(wrapper.text()).toContain("Read-only");

    auth.session = authSession({ mutations_enabled: true });
    await nextTick();

    expect(wrapper.text()).toContain("Mutations enabled");
  });
});
