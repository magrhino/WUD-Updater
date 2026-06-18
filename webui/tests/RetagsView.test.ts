import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RetagsView from "../src/views/RetagsView.vue";
import { webApi } from "../src/api/client";
import { useAuthStore } from "../src/stores/auth";
import { useUpdatesStore } from "../src/stores/updates";
import {
  applyJobResponse,
  authSession,
  retagPlanResponse,
  retagTarget,
  retagTargetsResponse,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

describe("RetagsView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setActivePinia(createPinia());
  });

  it("renders retag choices and previews selected changes", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse(
      [
        retagTarget({
          candidate_source: "github-latest",
          candidate_warning:
            "GitHub latest fallback will update latest tracking to 1.1.",
          candidate_link_label: "GitHub release",
          candidate_link_url: "https://github.com/acme/app/releases/tag/1.1",
        }),
        retagTarget({
          service_key: "media/radarr",
          service: "radarr",
          image: "repo/radarr:latest",
          image_repo: "repo/radarr",
          proposed_tag: "",
          final_image: "",
          retag_available: false,
          retag_reason: "missing-provenance",
          choices: ["keep-current"],
          digest_provenance: null,
        }),
      ],
      { warnings: ["compose warning"] },
    );
    const loadRetagTargets = vi
      .spyOn(updates, "loadRetagTargets")
      .mockResolvedValue();
    const createRetagPlan = vi.spyOn(updates, "createRetagPlan").mockImplementation(
      async () => {
        const plan = retagPlanResponse();
        updates.retagPlan = plan;
        return plan;
      },
    );
    const setRetagGithubLatestFallback = vi
      .spyOn(updates, "setRetagGithubLatestFallback")
      .mockResolvedValue();

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    const text = wrapper.text();
    expect(loadRetagTargets).toHaveBeenCalledTimes(1);
    expect(text).toContain("Retag review");
    expect(text).toContain("Total services");
    expect(text).toContain("Retag candidates");
    expect(text).toContain("Needs attention");
    expect(text).toContain("compose warning");
    expect(text).toContain("media/app");
    expect(text).toContain("Retag available");
    expect(text).toContain("Candidate ready");
    expect(text).toContain("Use GitHub latest fallback");
    expect(text).toContain("GitHub latest fallback will update latest tracking to 1.1.");
    expect(text).toContain("media/radarr");
    expect(text).toContain("Missing provenance");

    await wrapper
      .find('input[aria-label="Use GitHub latest fallback"]')
      .setValue(true);
    expect(setRetagGithubLatestFallback).toHaveBeenCalledWith(true);

    const switchControls = wrapper.findAll('input[value="switch-to-concrete"]');
    expect(switchControls).toHaveLength(2);
    expect(switchControls[0].attributes("disabled")).toBeUndefined();
    expect(switchControls[1].attributes("disabled")).toBeDefined();
    await switchControls[0].setValue();
    expect(updates.retagChoices["media/app"]).toBe("switch-to-concrete");

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview retag changes"))
      ?.trigger("click");
    await flushPromises();

    expect(createRetagPlan).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Selected retag changes");
    expect(wrapper.text()).toContain("repo/app:latest -> repo/app@sha256:abc123");
    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton).toBeDefined();
    expect(applyButton?.attributes("disabled")).toBeUndefined();
  });

  it("disables switch and apply controls in read-only mode", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: false });
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();
    updates.retagPlan = retagPlanResponse();
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    const applyRetagPlan = vi.spyOn(updates, "applyRetagPlan").mockResolvedValue(
      applyJobResponse({ job_id: "blocked-retag-job" }),
    );

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Read-only mode keeps retag switch/apply disabled.");
    expect(
      wrapper.find('input[value="switch-to-concrete"]').attributes("disabled"),
    ).toBeDefined();
    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton).toBeDefined();
    expect(applyButton?.attributes("disabled")).toBeDefined();
    await applyButton?.trigger("click");
    await flushPromises();
    expect(applyRetagPlan).not.toHaveBeenCalled();
  });

  it("confirms and tracks retag apply jobs after submit", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();
    updates.retagPlan = retagPlanResponse();
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    const eventSource: EventSource = {
      addEventListener: vi.fn(),
      close: vi.fn(),
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
    };
    const openJobStream = vi
      .spyOn(webApi, "openJobStream")
      .mockReturnValue(eventSource);
    const applyRetagPlan = vi.spyOn(updates, "applyRetagPlan").mockImplementation(
      async () => {
        const job = applyJobResponse({
          job_id: "retag-job",
          selected_line_numbers: [],
          status: "queued",
        });
        updates.setApplyJob(job);
        return job;
      },
    );

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton).toBeDefined();
    expect(applyButton?.attributes("disabled")).toBeUndefined();

    await applyButton?.trigger("click");
    await flushPromises();

    expect(applyRetagPlan).not.toHaveBeenCalled();
    expect(wrapper.find("dialog").exists()).toBe(true);
    expect(wrapper.text()).toContain("Confirm retag apply");
    expect(wrapper.text()).toContain("Review the selected Compose metadata changes");
    expect(wrapper.text()).toContain("1 service in media");
    expect(wrapper.text()).toContain("media/app");
    expect(wrapper.text()).toContain("repo/app:latest -> repo/app@sha256:abc123");
    expect(wrapper.text()).toContain(String.raw`wud.tag.include: ^latest$$ -> ^1\.1$$`);

    const confirmButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Confirm and apply"));
    expect(confirmButton).toBeDefined();
    await confirmButton?.trigger("click");
    await flushPromises();

    expect(applyRetagPlan).toHaveBeenCalledTimes(1);
    expect(openJobStream).toHaveBeenCalledWith("retag-job");
    expect(wrapper.text()).toContain("Applying 1 retag");
    expect(wrapper.text()).toContain("Waiting for the updater job to start.");
    expect(wrapper.text()).toContain("repo/app:latest -> repo/app@sha256:abc123");
    expect(wrapper.text()).toContain("wud.tag.include");
    const disabledApplyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(disabledApplyButton?.attributes("disabled")).toBeDefined();
  });

  it("filters retag targets by search text and review status", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget(),
      retagTarget({
        service_key: "data/postgres",
        stack: "data",
        service: "postgres",
        image: "postgres:16",
        image_repo: "postgres",
        current_tag: "16",
        tracking_tag: "16",
        proposed_tag: "",
        final_image: "",
        retag_available: false,
        retag_reason: "not-latest-tracking",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ]);
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    await wrapper
      .find('input[aria-label="Search retag targets"]')
      .setValue("postgres");
    await flushPromises();

    expect(wrapper.text()).toContain("data/postgres");
    expect(wrapper.text()).not.toContain("media/app");

    await wrapper.find('input[aria-label="Search retag targets"]').setValue("");
    await wrapper.find("select").setValue("available");
    await flushPromises();

    expect(wrapper.text()).toContain("media/app");
    expect(wrapper.text()).not.toContain("data/postgres");

    await wrapper.find("select").setValue("attention");
    await flushPromises();

    expect(wrapper.text()).not.toContain("media/app");
    expect(wrapper.text()).toContain("data/postgres");
  });

  it("renders empty, unavailable, loading, and error states", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    const loadRetagTargets = vi
      .spyOn(updates, "loadRetagTargets")
      .mockResolvedValue();

    updates.loading = true;
    let wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("Loading retag targets");
    expect(loadRetagTargets).toHaveBeenCalledTimes(1);

    updates.loading = false;
    updates.error = "retag targets unavailable";
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("retag targets unavailable");
    expect(wrapper.text()).toContain("The backend could not load retag review state.");

    updates.error = "";
    updates.retagTargets = retagTargetsResponse([]);
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("No Compose services found");

    updates.retagTargets = retagTargetsResponse([], {
      status: "unavailable",
      warnings: ["compose discovery failed"],
    });
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("compose discovery failed");
    expect(wrapper.text()).toContain("Compose discovery unavailable");
  });
});
