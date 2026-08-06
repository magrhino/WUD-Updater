import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DiagnosticsSupportBundleResponse } from "../src/api/client";
import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import IssueDumpView from "../src/views/IssueDumpView.vue";
import {
  authSession,
  doctorResponse,
  pendingResponse,
  settingsResponse,
  wudApiConfigurationDiagnostics,
  wudApiObservationDiagnostics,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

const clipboardCopy = vi.hoisted(() => vi.fn());

vi.mock("@vueuse/core", () => ({
  useClipboard: () => ({
    copy: clipboardCopy,
    isSupported: true,
  }),
}));

function supportBundle(): DiagnosticsSupportBundleResponse {
  return {
    wudup_version: "0.24.2",
    settings: settingsResponse(),
    doctor_result: doctorResponse(),
    wud_api_diagnostics: wudApiConfigurationDiagnostics(),
    wud_api_observations: wudApiObservationDiagnostics(),
    pending_summary: pendingResponse(),
    last_run_status: null,
    diagnostics_warnings: [],
    discovery_warnings: [],
    log_tail: null,
  };
}

async function mountIssueDump(
  load: () => Promise<DiagnosticsSupportBundleResponse>,
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ mutations_enabled: false });
  const ensureCsrf = vi.spyOn(auth, "ensureCsrf");
  const connection = useConnectionStore();
  const diagnosticsSupportBundle = vi
    .spyOn(connection, "diagnosticsSupportBundle")
    .mockImplementation(load);
  const router = createWudRouter(createMemoryHistory());
  await router.push({ name: "issue-dump" });
  await router.isReady();
  const wrapper = mountWithApp(IssueDumpView, { pinia, router });
  await flushPromises();
  return {
    wrapper,
    router,
    ensureCsrf,
    diagnosticsSupportBundle,
  };
}

describe("IssueDumpView", () => {
  beforeEach(() => {
    clipboardCopy.mockReset();
    clipboardCopy.mockResolvedValue(undefined);
  });

  it("loads formatted observation diagnostics in read-only mode", async () => {
    const { wrapper, ensureCsrf, diagnosticsSupportBundle } =
      await mountIssueDump(async () => supportBundle());

    expect(diagnosticsSupportBundle).toHaveBeenCalledTimes(1);
    expect(ensureCsrf).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Issue dump loaded.");
    const dump = wrapper.find(".issue-dump-viewer").element.textContent ?? "";
    expect(dump).toContain('\n  "wud_api_observations": {');
    expect(dump).toContain('"reason_code": "reported_error"');
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text().includes("Copy issue dump"))
        ?.attributes("disabled"),
    ).toBeUndefined();
  });

  it("copies and downloads the exact displayed snapshot without refetching", async () => {
    const { wrapper, diagnosticsSupportBundle } = await mountIssueDump(
      async () => supportBundle(),
    );
    const displayed =
      wrapper.find(".issue-dump-viewer").element.textContent ?? "";

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Copy issue dump"))
      ?.trigger("click");
    await flushPromises();

    expect(clipboardCopy).toHaveBeenCalledWith(displayed);
    expect(diagnosticsSupportBundle).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Diagnostics copied to clipboard.");

    const createObjectURL = vi.fn(() => "blob:issue-dump");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Download issue dump"))
      ?.trigger("click");
    await flushPromises();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:issue-dump");
    expect(diagnosticsSupportBundle).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Diagnostics downloaded successfully.");
  });

  it("preserves the displayed snapshot and surfaces a refresh failure", async () => {
    const bundle = supportBundle();
    const load = vi
      .fn<() => Promise<DiagnosticsSupportBundleResponse>>()
      .mockResolvedValueOnce(bundle)
      .mockRejectedValueOnce(new Error("WUD API timed out"));
    const { wrapper } = await mountIssueDump(load);
    const displayed =
      wrapper.find(".issue-dump-viewer").element.textContent ?? "";

    await wrapper
      .find('button[aria-label="Refresh issue dump"]')
      .trigger("click");
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("WUD API timed out");
    expect(wrapper.find(".issue-dump-viewer").element.textContent).toBe(
      displayed,
    );
  });

  it("shows initial load, copy, and download failures inline", async () => {
    const initial = await mountIssueDump(async () => {
      throw new Error("Support bundle unavailable");
    });

    expect(initial.wrapper.text()).toContain("Support bundle unavailable");
    expect(initial.wrapper.text()).toContain(
      "Issue dump is unavailable. Refresh to try again.",
    );

    const loaded = await mountIssueDump(async () => supportBundle());
    clipboardCopy.mockRejectedValueOnce(new Error("Clipboard permission denied"));
    await loaded.wrapper
      .findAll("button")
      .find((button) => button.text().includes("Copy issue dump"))
      ?.trigger("click");
    await flushPromises();
    expect(loaded.wrapper.text()).toContain("Clipboard permission denied");

    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => {
        throw new Error("Object URL unavailable");
      }),
      revokeObjectURL: vi.fn(),
    });
    await loaded.wrapper
      .findAll("button")
      .find((button) => button.text().includes("Download issue dump"))
      ?.trigger("click");
    await flushPromises();
    expect(loaded.wrapper.text()).toContain("Object URL unavailable");
  });

  it("keeps the issue dump route behind authentication", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: false });
    const router = createWudRouter(createMemoryHistory());

    await router.push("/diagnostics/issue-dump");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe(
      "/diagnostics/issue-dump",
    );
  });
});
