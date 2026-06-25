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
    const retagItems = [
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
    ];
    updates.retagTargets = retagTargetsResponse(retagItems, {
      warnings: ["compose warning"],
    });
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
    const refreshRetagGithubLatest = vi
      .spyOn(updates, "refreshRetagGithubLatest")
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
    expect(text).toContain("Automatch ready");
    expect(text).toContain("GitHub release");
    expect(text).toContain("Use cached GitHub latest fallback");
    expect(text).toContain("GitHub latest fallback will update latest tracking to 1.1.");
    expect(text).toContain("media/radarr");
    expect(text).toContain("Missing provenance");

    await wrapper
      .find('input[aria-label="Use cached GitHub latest fallback"]')
      .setValue(true);
    expect(setRetagGithubLatestFallback).toHaveBeenCalledWith(true);

    await wrapper
      .get('button[aria-label="Refresh GitHub latest candidates"]')
      .trigger("click");
    expect(refreshRetagGithubLatest).toHaveBeenCalledTimes(1);

    const switchControls = wrapper.findAll('input[value="switch-to-concrete"]');
    expect(switchControls).toHaveLength(2);
    expect(switchControls[0].attributes("disabled")).toBeUndefined();
    expect(switchControls[1].attributes("disabled")).toBeDefined();
    await switchControls[0].setValue();
    expect(updates.retagChoices[retagItems[0].target_id]).toBe(
      "switch-to-concrete",
    );

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview retag changes"))
      ?.trigger("click");
    await flushPromises();

    expect(createRetagPlan).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Review retag preview");
    expect(wrapper.text()).toContain("repo/app:latest -> repo/app@sha256:abc123");
    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton).toBeDefined();
    expect(applyButton?.attributes("disabled")).toBeUndefined();
  });

  it("selects one service from the per-row retag action without previewing", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    const retagItems = [
      retagTarget(),
      retagTarget({
        service_key: "media/radarr",
        service: "radarr",
        image: "repo/radarr:latest",
        image_repo: "repo/radarr",
        proposed_tag: "5.22.4",
        final_image: "repo/radarr@sha256:def456",
        digest_provenance: {
          source_image: "repo/radarr:latest",
          resolved_tag: "5.22.4",
          watch_tag: "latest",
          target_digest: "sha256:def456",
          final_image: "repo/radarr@sha256:def456",
          provenance_source: "test",
          provenance_confidence: "high",
        },
      }),
    ];
    updates.retagTargets = retagTargetsResponse(retagItems);
    updates.setRetagChoice("media/app", "switch-to-concrete");
    updates.setRetagChoice("media/radarr", "switch-to-concrete");
    const appTarget = retagItems[0];
    const radarrTarget = retagItems[1];
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    const setRetagChoice = vi.spyOn(updates, "setRetagChoice");
    const setRetagOnlyChoice = vi.spyOn(updates, "setRetagOnlyChoice");
    const createRetagPlan = vi.spyOn(updates, "createRetagPlan").mockResolvedValue(
      retagPlanResponse(),
    );

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    await wrapper
      .get('button[aria-label="Retag only media/radarr"]')
      .trigger("click");
    await flushPromises();

    expect(setRetagChoice).not.toHaveBeenCalled();
    expect(setRetagOnlyChoice).toHaveBeenCalledTimes(1);
    expect(setRetagOnlyChoice).toHaveBeenCalledWith(radarrTarget);
    expect(updates.retagChoices[appTarget.target_id]).toBe("keep-current");
    expect(updates.retagChoices[radarrTarget.target_id]).toBe("switch-to-concrete");
    expect(createRetagPlan).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("Review retag preview");
  });

  it("bulk selects all eligible, filtered eligible, and keep-all retag choices", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    const retagItems = [
      retagTarget(),
      retagTarget({
        service_key: "data/postgres",
        stack: "data",
        service: "postgres",
        image: "postgres:16",
        image_repo: "postgres",
        current_tag: "16",
        tracking_tag: "16",
        proposed_tag: "16.1",
        final_image: "postgres@sha256:feed",
      }),
      retagTarget({
        service_key: "media/radarr",
        service: "radarr",
        image: "repo/radarr:5.21.1",
        image_repo: "repo/radarr",
        current_tag: "5.21.1",
        tracking_tag: "5.21.1",
        tracking_tag_source: "image",
        proposed_tag: "",
        final_image: "",
        retag_available: false,
        retag_reason: "not-latest-tracking",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ];
    updates.retagTargets = retagTargetsResponse(retagItems);
    updates.retagPlan = retagPlanResponse();
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    const createRetagPlan = vi.spyOn(updates, "createRetagPlan").mockResolvedValue(
      retagPlanResponse(),
    );
    const applyRetagPlan = vi.spyOn(updates, "applyRetagPlan").mockResolvedValue(
      applyJobResponse({ job_id: "bulk-retag-job" }),
    );

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    const buttonByText = (text: string) =>
      wrapper.findAll("button").find((button) => button.text().includes(text));

    await wrapper
      .find('input[aria-label="Search retag targets"]')
      .setValue("postgres");
    await buttonByText("Retag filtered eligible")?.trigger("click");
    await flushPromises();

    expect(updates.retagPlan).toBeNull();
    expect(updates.retagChoices).toMatchObject({
      [retagItems[1].target_id]: "switch-to-concrete",
    });
    expect(updates.retagChoices[retagItems[0].target_id]).toBeUndefined();
    expect(wrapper.find(".retag-summary-strip").text()).toContain(
      "Selected switches1",
    );
    expect(createRetagPlan).not.toHaveBeenCalled();
    expect(applyRetagPlan).not.toHaveBeenCalled();

    updates.retagPlan = retagPlanResponse();
    await wrapper.find('input[aria-label="Search retag targets"]').setValue("");
    await buttonByText("Retag all eligible")?.trigger("click");
    await flushPromises();

    expect(updates.retagPlan).toBeNull();
    expect(updates.retagChoices).toMatchObject({
      [retagItems[0].target_id]: "switch-to-concrete",
      [retagItems[1].target_id]: "switch-to-concrete",
      [retagItems[2].target_id]: "keep-current",
    });
    expect(wrapper.find(".retag-summary-strip").text()).toContain(
      "Selected switches2",
    );

    await buttonByText("Keep all")?.trigger("click");
    await flushPromises();

    expect(updates.retagChoices).toMatchObject({
      [retagItems[0].target_id]: "keep-current",
      [retagItems[1].target_id]: "keep-current",
      [retagItems[2].target_id]: "keep-current",
    });
    expect(wrapper.find(".retag-summary-strip").text()).toContain(
      "Selected switches0",
    );
    expect(createRetagPlan).not.toHaveBeenCalled();
    expect(applyRetagPlan).not.toHaveBeenCalled();
  });

  it("shows preview start failures in the review modal", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    vi.spyOn(updates, "createRetagPlan").mockImplementation(async () => {
      updates.error = "retag preview is already running";
      throw new Error("retag preview is already running");
    });

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview retag changes"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Review retag preview");
    expect(wrapper.text()).toContain("retag preview is already running");
    expect(wrapper.text()).not.toContain(
      "Refreshing retag candidates and building a preview.",
    );
    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton?.attributes("disabled")).toBeDefined();
  });

  it.each([
    [
      "duplicate service choices",
      "422: retag choices contain duplicate service(s): media/app",
    ],
    [
      "missing target identity",
      "422: retag choices for duplicate service(s) must include target_id: media/app",
    ],
    [
      "duplicate target choices",
      "422: retag choices contain duplicate target(s): media/app (media/app)",
    ],
  ])(
    "shows duplicate retag service recovery guidance with affected rows for %s",
    async (_label, previewError) => {
      const pinia = createPinia();
      setActivePinia(pinia);
      const auth = useAuthStore();
      auth.session = authSession({ mutations_enabled: true });
      const updates = useUpdatesStore();
      updates.retagTargets = retagTargetsResponse([
        retagTarget(),
        retagTarget({
          image: "repo/app:latest-staging",
          directory: "/docker/media-staging",
          project_directory: "/docker/media-staging",
        }),
      ]);
      vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
      vi.spyOn(updates, "createRetagPlan").mockImplementation(async () => {
        updates.error = previewError;
        throw new Error(updates.error);
      });

      const wrapper = mountWithApp(RetagsView, { pinia });
      await flushPromises();

      await wrapper
        .findAll("button")
        .find((button) => button.text().includes("Preview retag changes"))
        ?.trigger("click");
      await flushPromises();

      const text = wrapper.text();
      expect(text).toContain("Duplicate service key: media/app.");
      expect(text).toContain(
        "Retag preview stopped because 2 discovered targets share this Compose project/service identity.",
      );
      expect(text).toContain(
        "Keep only one target for this key, or update Compose so each project/service pair is unique",
      );
      expect(text).toContain("/docker/media/docker-compose.yml");
      expect(text).toContain("/docker/media-staging/docker-compose.yml");
      expect(text).toContain("repo/app:latest-staging");
    },
  );

  it("lets fallback rows retag with a manually entered target tag", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    const retagItems = [
      retagTarget({
        service_key: "media/radarr",
        service: "radarr",
        image: "repo/radarr:5.21.1",
        image_repo: "repo/radarr",
        current_tag: "5.21.1",
        tracking_tag: "5.21.1",
        tracking_tag_source: "image",
        proposed_tag: "",
        final_image: "",
        retag_available: false,
        retag_reason: "not-latest-tracking",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ];
    updates.retagTargets = retagTargetsResponse(retagItems);
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    const createRetagPlan = vi.spyOn(updates, "createRetagPlan").mockResolvedValue(
      retagPlanResponse(),
    );

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    const targetInput = wrapper.find<HTMLInputElement>(
      'input[aria-label="Target tag for media/radarr"]',
    );
    expect(targetInput.element.value).toBe("");
    await targetInput.setValue("5.22.4");
    await flushPromises();

    expect(updates.retagChoices[retagItems[0].target_id]).toBe(
      "switch-to-concrete",
    );
    expect(updates.retagChoiceRequests()).toEqual([
      {
        service_key: "media/radarr",
        target_id: retagItems[0].target_id,
        choice: "switch-to-concrete",
        target_tag: "5.22.4",
      },
    ]);

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview retag changes"))
      ?.trigger("click");
    await flushPromises();
    expect(createRetagPlan).toHaveBeenCalledTimes(1);

    await targetInput.setValue("-bad");
    await flushPromises();
    expect(wrapper.text()).toContain("media/radarr has an invalid target tag");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text().includes("Preview retag changes"))
        ?.attributes("disabled"),
    ).toBeDefined();
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
    const setRetagChoicesForItems = vi.spyOn(updates, "setRetagChoicesForItems");
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
    const retagAllButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Retag all eligible"));
    const retagFilteredButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Retag filtered eligible"));
    const keepAllButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Keep all"));
    const refreshButton = wrapper.get(
      'button[aria-label="Refresh GitHub latest candidates"]',
    );
    expect(retagAllButton?.attributes("disabled")).toBeDefined();
    expect(retagFilteredButton?.attributes("disabled")).toBeDefined();
    expect(keepAllButton?.attributes("disabled")).toBeDefined();
    expect(refreshButton.attributes("disabled")).toBeDefined();
    await retagAllButton?.trigger("click");
    await retagFilteredButton?.trigger("click");
    await keepAllButton?.trigger("click");
    await flushPromises();
    expect(setRetagChoicesForItems).not.toHaveBeenCalled();
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

  it("keeps duplicate service apply snapshot rows keyed by target id", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    const basePlan = retagPlanResponse();
    const baseStack = basePlan.stacks[0];
    const baseUpdate = baseStack.digest_pin_updates[0];
    updates.retagTargets = retagTargetsResponse([
      retagTarget({ target_id: "target-a", service_key: "media/app" }),
      retagTarget({
        target_id: "target-b",
        service_key: "media/app",
        image: "repo/app:latest-staging",
        directory: "/docker/media-staging",
        project_directory: "/docker/media-staging",
      }),
    ]);
    updates.retagPlan = retagPlanResponse({
      selected_count: 2,
      stacks: [
        {
          ...baseStack,
          digest_pin_updates: [
            { ...baseUpdate, target_id: "target-a" },
            {
              ...baseUpdate,
              target_id: "target-b",
              source_image: "repo/app:latest-staging",
              planned_digest: "sha256:def456",
              final_image: "repo/app@sha256:def456",
              digest_provenance: {
                ...baseUpdate.digest_provenance,
                target_digest: "sha256:def456",
                final_image: "repo/app@sha256:def456",
              },
            },
          ],
        },
      ],
    });
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();
    vi.spyOn(webApi, "openJobStream").mockReturnValue({
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
    });
    vi.spyOn(updates, "applyRetagPlan").mockImplementation(async () => {
      const job = applyJobResponse({
        job_id: "retag-duplicate-job",
        selected_line_numbers: [],
        status: "queued",
      });
      updates.setApplyJob(job);
      return job;
    });

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply selected retags"));
    expect(applyButton).toBeDefined();
    await applyButton?.trigger("click");
    await flushPromises();

    const confirmButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Confirm and apply"));
    expect(confirmButton).toBeDefined();
    await confirmButton?.trigger("click");
    await flushPromises();

    expect(wrapper.findAll(".apply-job-impact .list-row")).toHaveLength(2);
    expect(
      warn.mock.calls
        .map((call) => call.map((value) => String(value)).join(" "))
        .join("\n"),
    ).not.toContain("Duplicate keys");
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
