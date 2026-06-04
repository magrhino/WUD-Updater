import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useWebuiStore } from "../src/stores/webui";
import AuditView from "../src/views/AuditView.vue";
import { authSession, runSummary } from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

function event(serviceName: string) {
  return {
    id: 1,
    run_id: 1,
    created_at: "2026-05-28T12:00:00+00:00",
    service_name: serviceName,
    stack_name: "stack",
    image: `${serviceName}:old`,
    target_image: `${serviceName}:new`,
    old_image_id: "",
    new_image_id: "",
    old_digest: "",
    new_digest: "",
    status: "success",
    metadata: {},
  };
}

describe("AuditView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows operator runs and excludes scheduled automation", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    const webui = useWebuiStore();
    webui.runs = [
      runSummary({
        id: 11,
        mode: "stop",
        metadata: {},
        events: [event("cli-service")],
      }),
      runSummary({
        id: 12,
        mode: "stop",
        metadata: { source: "webui-auto" },
        events: [event("auto-service")],
      }),
      runSummary({
        id: 13,
        mode: "web-state",
        metadata: {},
        events: [event("policy-service")],
      }),
    ];
    vi.spyOn(webui, "loadRuns").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/audit");
    await router.isReady();

    const wrapper = mountWithApp(AuditView, { pinia, router });

    expect(wrapper.text()).toContain("#11");
    expect(wrapper.text()).toContain("cli-service");
    expect(wrapper.text()).not.toContain("#12");
    expect(wrapper.text()).not.toContain("auto-service");
    expect(wrapper.text()).toContain("#13");
    expect(wrapper.text()).toContain("policy-service");
  });
});
