import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi } from "../src/api/client";
import PendingView from "../src/views/PendingView.vue";
import PoliciesView from "../src/views/PoliciesView.vue";
import SnoozesView from "../src/views/SnoozesView.vue";
import TagExclusionsView from "../src/views/TagExclusionsView.vue";
import { useAuthStore } from "../src/stores/auth";
import { useWebuiStore } from "../src/stores/webui";
import {
  applyJobResponse,
  authSession,
  pendingItem,
  pendingResponse,
  planResponse,
  servicePolicy,
  snooze,
  tagExclusion,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

function setupStores(mutationsEnabled: boolean) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ mutations_enabled: mutationsEnabled });
  const webui = useWebuiStore();
  return { pinia, auth, webui };
}

function buttonByText(wrapperText: string, text: string) {
  return wrapperText.includes(text);
}

describe("mutating WebUI views", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps pending updates read-only when mutations are disabled", async () => {
    const { pinia, webui } = setupStores(false);
    webui.pending = pendingResponse();
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    const createPlan = vi.spyOn(webui, "createPlan");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("All"))
      ?.trigger("click");

    expect(wrapper.text()).toContain("Read-only mode is active");
    const updateButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Update selected"));
    expect(updateButton?.attributes("disabled")).toBeDefined();
    await updateButton?.trigger("click");
    expect(createPlan).not.toHaveBeenCalled();
  });

  it("blocks invalid pending tag overrides before planning", async () => {
    const item = pendingItem();
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse([item]);
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    const createPlan = vi.spyOn(webui, "createPlan");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper.findAll("button").find((button) => button.text().includes("All"))?.trigger("click");
    await wrapper
      .find(`input[aria-label="New tag for ${item.image}"]`)
      .setValue("bad tag");

    expect(wrapper.text()).toContain("Line 1 has an invalid new tag");
    const previewButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview plan"));
    expect(previewButton?.attributes("disabled")).toBeDefined();
    await previewButton?.trigger("click");
    expect(createPlan).not.toHaveBeenCalled();
  });

  it("creates an apply job only after explicit confirmation", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    webui.plan = planResponse();
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    vi.spyOn(webui, "loadRuns").mockResolvedValue();
    const createJob = vi
      .spyOn(webui, "createJob")
      .mockResolvedValue(applyJobResponse());
    const close = vi.fn();
    vi.spyOn(webApi, "openJobStream").mockReturnValue({
      addEventListener: vi.fn(),
      close,
      onerror: null,
      onmessage: null,
      onopen: null,
      readyState: 1,
      url: "",
      withCredentials: true,
      CONNECTING: 0,
      OPEN: 1,
      CLOSED: 2,
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as EventSource);
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply"))
      ?.trigger("click");

    expect(createJob).not.toHaveBeenCalled();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);

    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Apply"))
      ?.trigger("click");

    expect(createJob).toHaveBeenCalledWith("plan-test", [1], false, []);
  });

  it("disables policy mutations in read-only mode", async () => {
    const { pinia, webui } = setupStores(false);
    webui.servicePolicies = [servicePolicy()];
    vi.spyOn(webui, "loadServicePolicies").mockResolvedValue();
    const deletePolicy = vi.spyOn(webui, "deleteServicePolicy");
    const wrapper = mountWithApp(PoliciesView, { pinia });

    expect(wrapper.text()).toContain("Read-only mode is active");
    expect(buttonByText(wrapper.text(), "Save")).toBe(true);
    expect(
      wrapper.findAll("button").find((button) => button.text().includes("Save"))?.attributes(
        "disabled",
      ),
    ).toBeDefined();
    const deleteButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Delete"));
    expect(deleteButton?.attributes("disabled")).toBeDefined();
    await deleteButton?.trigger("click");
    expect(deletePolicy).not.toHaveBeenCalled();
  });

  it("disables snooze mutations in read-only mode", async () => {
    const { pinia, webui } = setupStores(false);
    webui.snoozes = [snooze()];
    vi.spyOn(webui, "loadSnoozes").mockResolvedValue();
    const deleteSnooze = vi.spyOn(webui, "deleteSnooze");
    const wrapper = mountWithApp(SnoozesView, { pinia });

    expect(wrapper.text()).toContain("Read-only mode is active");
    expect(
      wrapper.findAll("button").find((button) => button.text().includes("Create"))?.attributes(
        "disabled",
      ),
    ).toBeDefined();
    const deleteButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Delete"));
    expect(deleteButton?.attributes("disabled")).toBeDefined();
    await deleteButton?.trigger("click");
    expect(deleteSnooze).not.toHaveBeenCalled();
  });

  it("disables tag exclusion mutations in read-only mode", async () => {
    const { pinia, webui } = setupStores(false);
    webui.tagExclusions = [tagExclusion()];
    vi.spyOn(webui, "loadTagExclusions").mockResolvedValue();
    const setStatus = vi.spyOn(webui, "setTagExclusionStatus");
    const wrapper = mountWithApp(TagExclusionsView, { pinia });

    expect(wrapper.text()).toContain("Read-only mode is active");
    expect(
      wrapper.findAll("button").find((button) => button.text().includes("Save"))?.attributes(
        "disabled",
      ),
    ).toBeDefined();
    const disableButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Disable"));
    expect(disableButton?.attributes("disabled")).toBeDefined();
    await disableButton?.trigger("click");
    expect(setStatus).not.toHaveBeenCalled();
  });
});
