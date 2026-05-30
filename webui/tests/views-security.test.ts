import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, webApi } from "../src/api/client";
import PendingView from "../src/views/PendingView.vue";
import PoliciesView from "../src/views/PoliciesView.vue";
import SnoozesView from "../src/views/SnoozesView.vue";
import TagExclusionsView from "../src/views/TagExclusionsView.vue";
import { useAuthStore } from "../src/stores/auth";
import {
  APPLY_JOB_RECOVERY_MESSAGE,
  useWebuiStore,
} from "../src/stores/webui";
import {
  applyJobLogResponse,
  applyJobResponse,
  authSession,
  pendingGroupedItem,
  pendingGrouping,
  pendingItem,
  pendingResponse,
  planResponse,
  releaseNoteInfo,
  releaseNotesResponse,
  runSummary,
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

function mockPendingLifecycle(webui: ReturnType<typeof useWebuiStore>) {
  vi.spyOn(webui, "loadPending").mockResolvedValue();
  vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
  vi.spyOn(webui, "refreshReleaseNotes").mockResolvedValue();
}

function mockApplyJobStream() {
  const close = vi.fn();
  let jobListener: ((event: MessageEvent<string>) => void) | null = null;
  let logListener: ((event: MessageEvent<string>) => void) | null = null;
  vi.spyOn(webApi, "openJobStream").mockReturnValue({
    addEventListener: vi.fn((type: string, listener: EventListener) => {
      if (type === "job") {
        jobListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "log") {
        logListener = listener as (event: MessageEvent<string>) => void;
      }
    }),
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

  return {
    close,
    emitJob(job: ReturnType<typeof applyJobResponse>): void {
      jobListener?.(
        new MessageEvent("job", {
          data: JSON.stringify(job),
        }),
      );
    },
    emitLog(log: ReturnType<typeof applyJobLogResponse>): void {
      logListener?.(
        new MessageEvent("log", {
          data: JSON.stringify(log),
        }),
      );
    },
    emitInvalidLog(): void {
      logListener?.(
        new MessageEvent("log", {
          data: "{",
        }),
      );
    },
    get observed(): boolean {
      return jobListener !== null && logListener !== null;
    },
  };
}

describe("mutating WebUI views", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("allows read-only pending preflight but blocks apply", async () => {
    const { pinia, webui } = setupStores(false);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse({ can_apply: false });
    });
    const createJob = vi.spyOn(webui, "createJob");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Read-only mode is active");
    expect(createPlan).toHaveBeenCalledWith([1], true, []);
    expect(
      wrapper
        .findAll("button")
        .some((button) => button.text().includes("Apply 1 update")),
    ).toBe(false);
    expect(createJob).not.toHaveBeenCalled();
  });

  it("shows blocked preflight errors without an apply action", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse({
        can_apply: false,
        status: "blocked",
        summary: {
          target_count: 1,
          matched_target_count: 0,
          stack_count: 0,
          service_count: 0,
          skipped_count: 1,
          issue_count: 1,
        },
        stacks: [],
        issues: [
          {
            severity: "error",
            code: "unmatched",
            message: "No Compose service matched repo/app:1.0.",
            line_no: 1,
            stack: "",
            service: "",
          },
        ],
        skipped: [
          {
            line_no: 1,
            raw: "repo/app:1.0",
            image: "repo/app:1.0",
            desired_tag: "1.1",
            reason: "unmatched",
          },
        ],
      });
    });
    const createJob = vi.spyOn(webui, "createJob");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    expect(createPlan).toHaveBeenCalledWith([1], true, []);
    expect(wrapper.find('[role="dialog"]').text()).toContain("Plan blocked");
    expect(wrapper.find('[role="dialog"]').text()).toContain(
      "No Compose service matched repo/app:1.0.",
    );
    expect(
      wrapper
        .find('[role="dialog"]')
        .findAll("button")
        .some((button) => button.text().includes("Apply 1 update")),
    ).toBe(false);
    expect(createJob).not.toHaveBeenCalled();
  });

  it("starts a stack update with the full stack line set", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse([
      pendingItem({ line_no: 4, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 9, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");

    expect(createPlan).toHaveBeenCalledWith([4, 9], true, []);
  });

  it("marks a stack indeterminate after one grouped item is deselected", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse([
      pendingItem({ line_no: 1, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 2, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });
    const stackCheckbox = wrapper.find('input[aria-label="Select stack media"]');

    await stackCheckbox.setValue(true);
    await wrapper
      .find('input[aria-label="Select update repo/worker:1.0"]')
      .setValue(false);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");

    expect(
      wrapper.find('input[aria-label="Select stack media"]').attributes("aria-checked"),
    ).toBe("mixed");
    expect(createPlan).toHaveBeenCalledWith([1], true, []);
  });

  it("excludes unmatched items from select all stack updates", async () => {
    const stackItem = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:1.0",
      repo: "repo/app",
    });
    const unmatchedItem = pendingGroupedItem({
      line_no: 2,
      image: "repo/loose:1.0",
      repo: "repo/loose",
      services: [],
    });
    const { pinia, webui } = setupStores(true);
    webui.pending = {
      ...pendingResponse([stackItem, unmatchedItem]),
      grouping: {
        ...pendingGrouping([stackItem]),
        unmatched: [unmatchedItem],
      },
    };
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Select all stack updates"))
      ?.trigger("click");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");

    expect(wrapper.text()).toContain("Needs review");
    expect(createPlan).toHaveBeenCalledWith([1], true, []);
  });

  it("selects tag update rows and enables tag rewrites when an override is edited", async () => {
    const item = pendingItem();
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse([item]);
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .find(`input[aria-label="New tag for ${item.image}"]`)
      .setValue("1.2");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");

    expect(
      (wrapper.find(`input[aria-label="Select update ${item.image}"]`).element as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(createPlan).toHaveBeenCalledWith(
      [1],
      true,
      [{ line_no: 1, tag: "1.2" }],
    );
  });

  it("blocks invalid pending tag overrides before planning", async () => {
    const item = pendingItem();
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse([item]);
    mockPendingLifecycle(webui);
    const createPlan = vi.spyOn(webui, "createPlan");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Select all"))
      ?.trigger("click");
    await wrapper
      .find(`input[aria-label="New tag for ${item.image}"]`)
      .setValue("bad tag");

    expect(wrapper.text()).toContain(`${item.image} has an invalid new tag`);
    const updateButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"));
    expect(updateButton?.attributes("disabled")).toBeDefined();
    await updateButton?.trigger("click");
    expect(createPlan).not.toHaveBeenCalled();
  });

  it("keeps grouped update details collapsed by default", () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.find("details.stack-details").attributes("open")).toBeUndefined();
    expect(wrapper.text()).toContain("Details");
    expect(wrapper.find('summary[aria-label="Details for media"]').exists()).toBe(true);
  });

  it("renders stack services and change preview text", () => {
    const radarr = pendingGroupedItem({
      line_no: 1,
      image: "lscr.io/linuxserver/radarr:5.0",
      repo: "lscr.io/linuxserver/radarr",
      desired_tag: "",
      target_image: "lscr.io/linuxserver/radarr:5.1",
      services: ["radarr"],
      action: "update",
    });
    const updater = pendingGroupedItem({
      line_no: 2,
      image: "ghcr.io/example/wud-updater:1.0",
      repo: "ghcr.io/example/wud-updater",
      desired_tag: "1.1",
      target_image: "ghcr.io/example/wud-updater:1.1",
      services: ["wud-updater"],
    });
    const { pinia, webui } = setupStores(true);
    webui.pending = {
      source_file: "/out/images.todo",
      exists: true,
      count: 2,
      items: [radarr, updater],
      grouping: {
        ...pendingGrouping([radarr, updater]),
        groups: [
          {
            ...pendingGrouping([radarr, updater]).groups[0],
            services_label: "radarr, wud-updater",
            services: ["radarr", "wud-updater"],
            line_numbers: [1, 2],
            items: [radarr, updater],
          },
        ],
      },
      warnings: [],
    };
    mockPendingLifecycle(webui);
    const wrapper = mountWithApp(PendingView, { pinia });
    const card = wrapper.find(".stack-card");

    expect(card.find(".stack-identity").text()).toContain(
      "Services radarr, wud-updater",
    );
    const previewText = card.find(".stack-change-preview").text();
    expect(previewText).toContain("radarr");
    expect(previewText).toContain("Image update");
    expect(previewText).toContain("lscr.io/linuxserver/radarr:5.0");
    expect(previewText).toContain("lscr.io/linuxserver/radarr:5.1");
    expect(previewText).toContain("wud-updater");
    expect(previewText).toContain("Tag update");
    expect(previewText).toContain("ghcr.io/example/wud-updater:1.0");
    expect(previewText).toContain("ghcr.io/example/wud-updater:1.1");
    expect(card.find(".stack-card-tags").text()).not.toContain(
      "radarr, wud-updater",
    );
  });

  it("shows ready preflight service impact and row tag rewrites", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse({
        selected_line_numbers: [1, 2],
        summary: {
          target_count: 2,
          matched_target_count: 2,
          stack_count: 1,
          service_count: 2,
          skipped_count: 0,
          issue_count: 0,
        },
        stacks: [
          {
            ...planResponse().stacks[0],
            services_label: "radarr, wud-updater",
            services: ["radarr", "wud-updater"],
            pull_services: ["radarr", "wud-updater"],
            stop_services: ["radarr", "wud-updater"],
            tag_updates: [
              {
                old_image: "lscr.io/linuxserver/radarr:5.0",
                desired_tag: "5.1",
                new_image: "lscr.io/linuxserver/radarr:5.1",
                services: ["radarr"],
              },
            ],
            lines: [
              {
                line_no: 1,
                raw: "lscr.io/linuxserver/radarr:5.0",
                image: "lscr.io/linuxserver/radarr:5.0",
                resolved_image: "lscr.io/linuxserver/radarr:5.0",
                compose_image: "lscr.io/linuxserver/radarr:5.0",
                target_image: "lscr.io/linuxserver/radarr:5.1",
                service: "radarr",
                digest: "",
                desired_tag: "5.1",
                action: "tag-update",
              },
              {
                line_no: 2,
                raw: "ghcr.io/example/wud-updater:1.0",
                image: "ghcr.io/example/wud-updater:1.0",
                resolved_image: "ghcr.io/example/wud-updater:1.0",
                compose_image: "ghcr.io/example/wud-updater:1.0",
                target_image: "ghcr.io/example/wud-updater:1.1",
                service: "wud-updater",
                digest: "",
                desired_tag: "",
                action: "update",
              },
            ],
          },
        ],
      });
    });
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    const impact = dialog.find(".preflight-impact");
    expect(dialog.find("#preflight-modal-title").text()).toBe("Review media plan");
    expect(dialog.find(".preflight-impact-text").text()).toBe(
      "radarr, wud-updater",
    );
    expect(impact.exists()).toBe(true);
    expect(impact.text()).toContain("Services and images");
    expect(impact.text()).toContain("radarr");
    expect(impact.text()).toContain("wud-updater");
    expect(impact.find(".tag-rewrite-detail").text()).toContain(
      "lscr.io/linuxserver/radarr:5.0 -> lscr.io/linuxserver/radarr:5.1",
    );
    expect(
      dialog
        .findAll("details.preflight-details")
        .some((details) => details.text().includes("Services and images")),
    ).toBe(false);
    expect(
      dialog
        .findAll("details.preflight-details")
        .some((details) => details.text().includes("Commands")),
    ).toBe(true);
    expect(
      dialog
        .findAll("details.preflight-details")
        .some((details) => details.text().includes("Source lines")),
    ).toBe(true);
  });

  it("falls back to pending file order when grouping is unavailable", () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = {
      ...pendingResponse(),
      grouping: {
        status: "unavailable",
        groups: [],
        unmatched: [],
        warnings: [],
      },
    };
    mockPendingLifecycle(webui);
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain(
      "Stack grouping is unavailable. Showing pending file order.",
    );
    expect(wrapper.find('[role="table"]').exists()).toBe(true);
  });

  it("renders release-note links with breaking cues", () => {
    const { pinia, webui } = setupStores(false);
    webui.pending = pendingResponse();
    webui.releaseNotes = releaseNotesResponse([
      releaseNoteInfo({
        breaking: true,
        breaking_reasons: ["Major version changes from 1 to 2."],
      }),
    ]);
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(webui, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("GitHub release");
    expect(wrapper.text()).toContain("Possible breaking change");
    expect(wrapper.find('a[href="https://github.com/acme/app/releases/tag/v2.0.0"]').exists()).toBe(true);
  });

  it("renders both LSIO and upstream release-note links", () => {
    const { pinia, webui } = setupStores(false);
    webui.pending = pendingResponse([pendingItem({ image: "linuxserver/radarr:latest" })]);
    webui.releaseNotes = releaseNotesResponse([
      releaseNoteInfo({
        provider: "lsio",
        image_repo: "linuxserver/docker-radarr",
        upstream_repo: "Radarr/Radarr",
        links: [
          {
            label: "LSIO release",
            url: "https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls1",
            kind: "lsio_release",
          },
          {
            label: "Upstream release",
            url: "https://github.com/Radarr/Radarr/releases/tag/v5.1.0",
            kind: "github_release",
          },
        ],
      }),
    ]);
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(webui, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("LSIO release");
    expect(wrapper.text()).toContain("Upstream release");
  });

  it("renders unavailable release-note reasons without hiding LSIO links", () => {
    const { pinia, webui } = setupStores(false);
    webui.pending = pendingResponse([
      pendingItem({
        line_no: 1,
        image: "advplyr/audiobookshelf:latest",
        repo: "advplyr/audiobookshelf",
      }),
      pendingItem({
        line_no: 2,
        image: "linuxserver/calibre:latest",
        repo: "linuxserver/calibre",
      }),
    ]);
    webui.releaseNotes = releaseNotesResponse([
      releaseNoteInfo({
        line_no: 1,
        status: "unsupported",
        provider: "unsupported",
        image_repo: "advplyr/audiobookshelf",
        upstream_repo: "",
        links: [],
        error: "no supported GitHub release source found",
      }),
      releaseNoteInfo({
        line_no: 2,
        provider: "lsio",
        image_repo: "linuxserver/docker-calibre",
        upstream_repo: "kovidgoyal/calibre",
        links: [
          {
            label: "LSIO release",
            url: "https://github.com/linuxserver/docker-calibre/releases/tag/1.0.0-ls1",
            kind: "lsio_release",
          },
          {
            label: "Upstream project",
            url: "https://github.com/kovidgoyal/calibre",
            kind: "github_project",
          },
        ],
      }),
    ]);
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(webui, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("Unavailable");
    expect(wrapper.text()).toContain(
      "Only GHCR and mapped LinuxServer.io images have release-note links.",
    );
    expect(wrapper.text()).toContain("LSIO release");
    expect(wrapper.text()).toContain("Upstream project");
  });

  it("creates an apply job only after explicit confirmation", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    const loadPending = vi.spyOn(webui, "loadPending").mockImplementation(async () => {
      webui.plan = null;
    });
    const loadReleaseNotes = vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
    const refreshReleaseNotes = vi
      .spyOn(webui, "refreshReleaseNotes")
      .mockResolvedValue();
    const loadRuns = vi.spyOn(webui, "loadRuns").mockResolvedValue();
    vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse();
    });
    const createJob = vi.spyOn(webui, "createJob").mockImplementation(async () => {
      const job = applyJobResponse();
      webui.setApplyJob(job);
      return job;
    });
    const jobStream = mockApplyJobStream();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    expect(createJob).not.toHaveBeenCalled();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);

    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Apply 1 update"))
      ?.trigger("click");

    expect(createJob).toHaveBeenCalledWith("plan-test", [1], true, []);
    expect(jobStream.observed).toBe(true);
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').text()).toContain("Applying 1 update");
    expect(wrapper.find(".apply-job-panel").text()).toContain("Applying 1 update");
    expect(wrapper.find(".apply-job-panel").text()).toContain("repo/app:1.0");

    jobStream.emitLog(
      applyJobLogResponse({
        content: "[2026-05-28T12:00:00+00:00] [INFO] docker-update-from-wud-v2\n",
      }),
    );
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').text()).toContain("Live log");
    expect(wrapper.find('[role="dialog"]').text()).toContain("docker-update-from-wud-v2");
    expect(wrapper.find(".apply-job-panel").text()).toContain("docker-update-from-wud-v2");

    jobStream.emitJob(applyJobResponse({ status: "success", run_id: 10 }));
    await flushPromises();

    expect(loadPending).toHaveBeenCalled();
    expect(loadReleaseNotes).toHaveBeenCalled();
    expect(refreshReleaseNotes).toHaveBeenCalled();
    expect(loadRuns).toHaveBeenCalled();
    expect(wrapper.find(".apply-job-panel").text()).toContain("Apply complete");
    expect(wrapper.find(".apply-job-panel").text()).toContain("repo/app:1.0");
    expect(wrapper.find(".apply-job-panel").text()).toContain("#10");
  });

  it("keeps failed apply jobs visible with the confirmed plan impact", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    vi.spyOn(webui, "loadRuns").mockResolvedValue();
    vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse();
    });
    vi.spyOn(webui, "createJob").mockImplementation(async () => {
      const job = applyJobResponse({
        status: "running",
        started_at: "2026-05-28T12:00:00+00:00",
      });
      webui.setApplyJob(job);
      return job;
    });
    const jobStream = mockApplyJobStream();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();
    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Apply 1 update"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').text()).toContain("Applying 1 update");
    expect(wrapper.find(".apply-job-panel").text()).toContain("running");
    expect(wrapper.find(".apply-job-panel").text()).toContain("repo/app:1.0");

    jobStream.emitJob(
      applyJobResponse({
        status: "failure",
        error: "updater exited with status 1",
      }),
    );
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("Apply failed");
    expect(wrapper.find(".apply-job-panel").text()).toContain(
      "updater exited with status 1",
    );
    expect(wrapper.find(".apply-job-panel").text()).toContain("repo/app:1.0");
    expect(jobStream.close).toHaveBeenCalled();
  });

  it("reports invalid log stream payloads without closing the job stream", async () => {
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    mockPendingLifecycle(webui);
    vi.spyOn(webui, "loadRuns").mockResolvedValue();
    vi.spyOn(webui, "createPlan").mockImplementation(async () => {
      webui.plan = planResponse();
    });
    vi.spyOn(webui, "createJob").mockImplementation(async () => {
      const job = applyJobResponse({ status: "running" });
      webui.setApplyJob(job);
      return job;
    });
    const jobStream = mockApplyJobStream();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();
    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Apply 1 update"))
      ?.trigger("click");
    await flushPromises();

    jobStream.emitInvalidLog();
    await flushPromises();

    expect(wrapper.text()).toContain("Job log stream returned invalid data.");
    expect(jobStream.close).not.toHaveBeenCalled();

    jobStream.emitLog(applyJobLogResponse({ content: "next log line\n" }));
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("next log line");
  });

  it("shows recovery guidance when a remembered apply job is missing", async () => {
    window.sessionStorage.setItem("applyJobId", "job-lost");
    const { pinia, webui } = setupStores(true);
    webui.pending = pendingResponse();
    vi.spyOn(webui, "loadPending").mockResolvedValue();
    vi.spyOn(webui, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(webui, "refreshReleaseNotes").mockResolvedValue();
    vi.spyOn(webApi, "job").mockRejectedValue(
      new ApiError(404, "apply job not found"),
    );
    const loadRuns = vi.spyOn(webui, "loadRuns").mockImplementation(async () => {
      webui.runs = [runSummary({ id: 42 })];
    });
    const wrapper = mountWithApp(PendingView, { pinia });

    await flushPromises();

    expect(webApi.job).toHaveBeenCalledWith("job-lost");
    expect(loadRuns).toHaveBeenCalled();
    expect(webui.applyJob).toBeNull();
    expect(webui.rememberedApplyJobId).toBe("");
    expect(window.sessionStorage.getItem("applyJobId")).toBeNull();
    expect(wrapper.text()).toContain(APPLY_JOB_RECOVERY_MESSAGE);
    expect(wrapper.text()).toContain("Runs");
    expect(wrapper.text()).toContain("Latest run");
    expect(wrapper.text()).toContain("Log");
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
