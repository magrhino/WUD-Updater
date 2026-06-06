import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { nextTick } from "vue";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, webApi } from "../src/api/client";
import { createWudRouter } from "../src/router";
import DashboardView from "../src/views/DashboardView.vue";
import DoctorView from "../src/views/DoctorView.vue";
import PendingView from "../src/views/PendingView.vue";
import PoliciesView from "../src/views/PoliciesView.vue";
import SettingsView from "../src/views/SettingsView.vue";
import SnoozesView from "../src/views/SnoozesView.vue";
import TagExclusionsView from "../src/views/TagExclusionsView.vue";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import {
  applyPreflightResponse,
  applyJobLogResponse,
  applyJobResponse,
  authSession,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  pendingGroupedItem,
  pendingGrouping,
  pendingItem,
  pendingResponse,
  planResponse,
  releaseNoteInfo,
  releaseNotesResponse,
  runSummary,
  servicePolicy,
  settingsResponse,
  snooze,
  statusResponse,
  tagExclusion,
  updateTarget,
  updateTargetsResponse,
} from "./helpers/fixtures";
import { mountWithApp, naiveStubs } from "./helpers/mount";

function setupStores(mutationsEnabled: boolean) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ mutations_enabled: mutationsEnabled });
  const connection = useConnectionStore();
  const settings = useSettingsStore();
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  connection.status = statusResponse({ mutations_enabled: mutationsEnabled });
  settings.coreUpdateTour = coreUpdateTourResponse();
  return { pinia, auth, connection, settings, updates, runs };
}

function failedApplyPreflight(code: string, detail: string) {
  const base = applyPreflightResponse();
  return applyPreflightResponse({
    ok: false,
    failures: 1,
    checks: base.checks.map((check) =>
      check.code === code
        ? {
            ...check,
            status: "FAIL" as const,
            detail,
          }
        : check,
    ),
  });
}

function buttonByText(wrapperText: string, text: string) {
  return wrapperText.includes(text);
}

function emitSelectValue(
  wrapper: ReturnType<typeof mountWithApp>,
  index: number,
  value: string | number | null,
): void {
  const select = wrapper.findAllComponents(naiveStubs.NSelect)[index];
  if (!select) {
    throw new Error(`Missing select at index ${index}`);
  }
  select.vm.$emit("update:value", value);
}

function mockMobileViewport(): () => void {
  const originalMatchMedia = window.matchMedia;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches:
      !query.includes("prefers-") &&
      (query.includes("max-width") || query.includes("width <")),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  return () => {
    window.matchMedia = originalMatchMedia;
  };
}

function mockPendingLifecycle(
  settings: ReturnType<typeof useSettingsStore>,
  updates: ReturnType<typeof useUpdatesStore>,
) {
  vi.spyOn(updates, "loadPending").mockResolvedValue();
  vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
  vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
  vi.spyOn(settings, "loadPendingSafetyCues").mockResolvedValue();
}

const stalePendingPreflightFindings = [
  "Running container old still matches this pending line.",
  "Docker labels reference docker-compose.yml.",
  "The referenced Compose file was not found, but archived/nonstandard file(s) were found: docker-compose.archive.yml.",
];
const stalePendingPossibleReasons = [
  "The active Compose file was renamed to an archived or nonstandard filename.",
  "The stack was moved or the Compose file path changed after the container was created.",
];
const stalePendingRecommendedActions = [
  "Restore or rename the active Compose file to a supported Compose filename.",
  "Update Docker base or ignore paths if the stack moved.",
  "Remove the stale WUD line if the stack is intentionally gone.",
];

function unmatchedPendingItem() {
  return pendingGroupedItem({
    line_no: 1,
    raw: "repo/old:latest",
    image: "repo/old:latest",
    repo: "repo/old",
    current_tag: "latest",
    desired_tag: "",
    services: [],
    diagnostic: {
      code: "compose-label-active-file-missing",
      message:
        "Container old was created from stack media, but docker-compose.yml is missing.",
      hint: "Only docker-compose.archive.yml was found; restore an active Compose file or remove the stale pending line.",
      stack: "media",
      service: "old",
      compose_file: "docker-compose.yml",
      found_files: ["docker-compose.archive.yml"],
      details: {
        preflight_findings: stalePendingPreflightFindings,
        possible_reasons: stalePendingPossibleReasons,
        recommended_actions: stalePendingRecommendedActions,
      },
    },
  });
}

function pendingWithUnmatched(item = unmatchedPendingItem()) {
  return {
    ...pendingResponse([item]),
    grouping: {
      ...pendingGrouping([]),
      groups: [],
      unmatched: [item],
    },
  };
}

function mockApplyJobStream() {
  const close = vi.fn();
  let jobListener: ((event: MessageEvent<string>) => void) | null = null;
  let logListener: ((event: MessageEvent<string>) => void) | null = null;
  let progressListener: ((event: MessageEvent<string>) => void) | null = null;
  vi.spyOn(webApi, "openJobStream").mockReturnValue({
    addEventListener: vi.fn((type: string, listener: EventListener) => {
      if (type === "job") {
        jobListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "log") {
        logListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "progress") {
        progressListener = listener as (event: MessageEvent<string>) => void;
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
    emitProgress(
      progress: ReturnType<typeof applyJobResponse>["progress"][number],
    ): void {
      progressListener?.(
        new MessageEvent("progress", {
          data: JSON.stringify(progress),
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
      return (
        jobListener !== null &&
        logListener !== null &&
        progressListener !== null
      );
    },
  };
}

describe("mutating WebUI views", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("allows read-only pending preflight but blocks apply", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
        can_apply: false,
        apply_preflight: failedApplyPreflight(
          "mutations-enabled",
          "Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.",
        ),
      });
    });
    const createJob = vi.spyOn(updates, "createJob");
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
    expect(createPlan).toHaveBeenCalledWith([1], true, [], []);
    const applyButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Apply 1 update"));
    expect(applyButton?.exists()).toBe(true);
    expect(applyButton?.attributes("disabled")).toBeDefined();
    expect(createJob).not.toHaveBeenCalled();
  });

  it("shows blocked preflight errors without an apply action", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
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
            hint: "",
            details: {},
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
    const createJob = vi.spyOn(updates, "createJob");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    expect(createPlan).toHaveBeenCalledWith([1], true, [], []);
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

  it("rebuilds digest-pin label rewrite plans after approval", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const approval = {
      stack: "media",
      service: "app",
      label_key: "wud.tag.include",
      current_label_value: "latest|stable",
      planned_tag: "latest",
      proposed_label_value: "^latest$$",
    };
    const issue = {
      severity: "error",
      code: "compose-digest-pin-label-rewrite-unapproved",
      message:
        'media wud.tag.include is "latest|stable"; approve replacing it with "^latest$" before pinning the digest.',
      line_no: null,
      stack: "media",
      service: "app",
      hint: "Approve the label rewrite.",
      details: {
        ...approval,
        compose_file: "docker-compose.yml",
        proposed_label_regex: "^latest$",
        explanation:
          "WUD-Updater can only overwrite this include rule after explicit approval.",
      },
    };
    const createPlan = vi
      .spyOn(updates, "createPlan")
      .mockImplementation(async (_lines, _allow, _tags, approvals = []) => {
        const base = planResponse();
        updates.plan = approvals.length
          ? planResponse({
              stacks: [
                {
                  ...base.stacks[0],
                  digest_pin_updates: [
                    {
                      source_image: "repo/app:latest",
                      resolved_tag: "latest",
                      planned_digest: "sha256:abc123",
                      final_image: "repo/app@sha256:abc123",
                      watch_tag: "latest",
                      marker: "wud.updater.digest-pin.repo-app",
                      label_key: "wud.tag.include",
                      label_value: "^latest$$",
                      services: ["app"],
                      label_rewrites: [
                        {
                          service: "app",
                          label_key: "wud.tag.include",
                          current_label_value: "latest|stable",
                          planned_tag: "latest",
                          proposed_label_value: "^latest$$",
                          proposed_label_regex: "^latest$",
                          approved: true,
                          reason: "approved",
                        },
                      ],
                    },
                  ],
                },
              ],
            })
          : planResponse({
              can_apply: false,
              status: "blocked",
              summary: {
                ...base.summary,
                issue_count: 1,
              },
              issues: [issue],
              apply_preflight: failedApplyPreflight(
                "selected-services-matched",
                issue.message,
              ),
            });
      });
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.text()).toContain("Digest-pin label approvals");
    expect(dialog.text()).toContain("wud.tag.include=latest|stable");
    expect(dialog.text()).toContain("^latest$");

    await dialog
      .findAll("button")
      .find((button) => button.text().includes("Approve label rewrite"))
      ?.trigger("click");
    await flushPromises();

    expect(createPlan).toHaveBeenNthCalledWith(1, [1], true, [], []);
    expect(createPlan).toHaveBeenNthCalledWith(2, [1], true, [], [approval]);
    expect(wrapper.find('[role="dialog"]').text()).toContain(
      "Digest-pin label updates",
    );
    expect(wrapper.find('[role="dialog"]').text()).toContain(
      "wud.tag.include=latest|stable",
    );
  });

  it("does not reopen digest-pin approval preflight after close", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    let resolveSecondPlan: () => void = () => {};
    const secondPlan = new Promise<void>((resolve) => {
      resolveSecondPlan = resolve;
    });
    const approval = {
      stack: "media",
      service: "app",
      label_key: "wud.tag.include",
      current_label_value: "latest|stable",
      planned_tag: "latest",
      proposed_label_value: "^latest$$",
    };
    const issue = {
      severity: "error",
      code: "compose-digest-pin-label-rewrite-unapproved",
      message:
        'media wud.tag.include is "latest|stable"; approve replacing it with "^latest$" before pinning the digest.',
      line_no: null,
      stack: "media",
      service: "app",
      hint: "Approve the label rewrite.",
      details: {
        ...approval,
        compose_file: "docker-compose.yml",
        proposed_label_regex: "^latest$",
        explanation:
          "WUD-Updater can only overwrite this include rule after explicit approval.",
      },
    };
    const createPlan = vi
      .spyOn(updates, "createPlan")
      .mockImplementation(async (_lines, _allow, _tags, approvals = []) => {
        const base = planResponse();
        if (approvals.length) {
          await secondPlan;
          updates.plan = planResponse({
            stacks: [
              {
                ...base.stacks[0],
                digest_pin_updates: [
                  {
                    source_image: "repo/app:latest",
                    resolved_tag: "latest",
                    planned_digest: "sha256:abc123",
                    final_image: "repo/app@sha256:abc123",
                    watch_tag: "latest",
                    marker: "wud.updater.digest-pin.repo-app",
                    label_key: "wud.tag.include",
                    label_value: "^latest$$",
                    services: ["app"],
                    label_rewrites: [
                      {
                        service: "app",
                        label_key: "wud.tag.include",
                        current_label_value: "latest|stable",
                        planned_tag: "latest",
                        proposed_label_value: "^latest$$",
                        proposed_label_regex: "^latest$",
                        approved: true,
                        reason: "approved",
                      },
                    ],
                  },
                ],
              },
            ],
          });
          return;
        }
        updates.plan = planResponse({
          can_apply: false,
          status: "blocked",
          summary: {
            ...base.summary,
            issue_count: 1,
          },
          issues: [issue],
          apply_preflight: failedApplyPreflight(
            "selected-services-matched",
            issue.message,
          ),
        });
      });
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Approve label rewrite"))
      ?.trigger("click");
    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Close"))
      ?.trigger("click");

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    resolveSecondPlan();
    await flushPromises();

    expect(createPlan).toHaveBeenNthCalledWith(1, [1], true, [], []);
    expect(createPlan).toHaveBeenNthCalledWith(2, [1], true, [], [approval]);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("shows unmatched cleanup preview disabled in read-only mode", async () => {
    const item = unmatchedPendingItem();
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingWithUnmatched(item);
    mockPendingLifecycle(settings, updates);
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
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
            message: "No Compose service matched repo/old:latest.",
            line_no: 1,
            stack: "",
            service: "",
            hint: item.diagnostic?.hint ?? "",
            details: {},
          },
        ],
        skipped: [
          {
            line_no: 1,
            raw: "repo/old:latest",
            image: "repo/old:latest",
            desired_tag: "",
            reason: "unmatched",
          },
        ],
        cleanup: {
          cleanup_id: "cleanup-test",
          can_remove_unmatched: false,
          items: [
            {
              line_no: 1,
              raw: "repo/old:latest",
              image: "repo/old:latest",
              desired_tag: "",
              digest: "",
              reason: "unmatched",
              diagnostic: item.diagnostic,
            },
          ],
        },
      });
    });
    const cleanupPending = vi.spyOn(updates, "cleanupPending");
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("Stale pending entries");
    expect(wrapper.text()).toContain(
      "1 pending line needs review: Compose file missing.",
    );
    expect(wrapper.text()).toContain("Compose file missing");
    expect(wrapper.text()).toContain(
      "Running container exists, but its Compose file is missing or archived.",
    );
    expect(wrapper.text()).not.toContain("Preflight found");

    await wrapper
      .find('input[aria-label="Select update repo/old:latest"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.text()).toContain("Unmatched pending entries");
    expect(dialog.text()).toContain(
      "1 entry needs review: Compose file missing. Cleanup only removes WUD pending lines.",
    );
    expect(dialog.text()).toContain(
      "Running container exists, but its Compose file is missing or archived.",
    );
    expect(dialog.text()).not.toContain("Preflight found");
    expect(dialog.text()).not.toContain("No Compose service matched repo/old:latest.");
    expect(dialog.find(".warning-list").exists()).toBe(false);
    expect(dialog.text()).toContain("Read-only mode is active");
    const cleanupButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 unmatched entry"));
    expect(cleanupButton?.attributes("disabled")).toBeDefined();
    await cleanupButton?.trigger("click");

    expect(cleanupPending).not.toHaveBeenCalled();
  });

  it("confirms unmatched cleanup before refreshing pending state", async () => {
    const item = unmatchedPendingItem();
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingWithUnmatched(item);
    const loadPending = vi.spyOn(updates, "loadPending").mockResolvedValue();
    const loadReleaseNotes = vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    const refreshReleaseNotes = vi
      .spyOn(updates, "refreshReleaseNotes")
      .mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
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
            message: "No Compose service matched repo/old:latest.",
            line_no: 1,
            stack: "",
            service: "",
            hint: item.diagnostic?.hint ?? "",
            details: {},
          },
        ],
        skipped: [
          {
            line_no: 1,
            raw: "repo/old:latest",
            image: "repo/old:latest",
            desired_tag: "",
            reason: "unmatched",
          },
        ],
        cleanup: {
          cleanup_id: "cleanup-test",
          can_remove_unmatched: true,
          items: [
            {
              line_no: 1,
              raw: "repo/old:latest",
              image: "repo/old:latest",
              desired_tag: "",
              digest: "",
              reason: "unmatched",
              diagnostic: item.diagnostic,
            },
          ],
        },
      });
    });
    const cleanupPending = vi
      .spyOn(updates, "cleanupPending")
      .mockImplementation(async () => {
        const response = {
          status: "success" as const,
          audit_run_id: 42,
          removed_count: 1,
          removed: [
            {
              line_no: 1,
              raw: "repo/old:latest",
              image: "repo/old:latest",
              reason: "unmatched",
            },
          ],
        };
        updates.pendingCleanup = response;
        updates.plan = null;
        return response;
      });
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .find('input[aria-label="Select update repo/old:latest"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Unmatched pending entries");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 unmatched entry"))
      ?.trigger("click");
    await flushPromises();

    const cleanupDialog = wrapper
      .findAll('[role="dialog"]')
      .find((dialog) => dialog.text().includes("Pending cleanup"));
    expect(cleanupDialog?.text()).toContain("Stale entry guidance");
    expect(cleanupDialog?.text()).toContain("Docker labels reference docker-compose.yml.");
    expect(cleanupDialog?.text()).toContain(
      "The stack was moved or the Compose file path changed after the container was created.",
    );
    expect(cleanupDialog?.text()).toContain(
      "Containers, images, Compose services, and Compose files are not deleted or updated.",
    );
    expect(cleanupDialog?.text()).toContain("Source lines");
    expect(cleanupDialog?.text()).toContain("#1 repo/old:latest");
    expect(cleanupDialog?.text()).toContain("repo/old:latest");

    await cleanupDialog
      ?.findAll("button")
      .find((button) => button.text().includes("Remove 1 unmatched entry"))
      ?.trigger("click");
    await flushPromises();

    expect(cleanupPending).toHaveBeenCalledWith("cleanup-test", [
      { line_no: 1, raw: "repo/old:latest" },
    ]);
    expect(loadPending).toHaveBeenCalled();
    expect(loadReleaseNotes).toHaveBeenCalled();
    expect(refreshReleaseNotes).toHaveBeenCalled();
    expect(loadRuns).toHaveBeenCalled();
    expect(wrapper.text()).toContain("1 pending entry removed from images.todo.");
    expect(wrapper.text()).toContain("Details");
  });

  it("disables selected pending removal in read-only mode", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const createRemovalPlan = vi.spyOn(updates, "createRemovalPlan");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();

    expect(wrapper.text()).toContain("Read-only mode is active");
    const removalButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 selected entry"));
    expect(removalButton?.attributes("disabled")).toBeDefined();
    await removalButton?.trigger("click");

    expect(createRemovalPlan).not.toHaveBeenCalled();
  });

  it("confirms selected pending removal before refreshing pending state", async () => {
    const item = pendingItem({
      line_no: 1,
      raw: "repo/app:1.0 sha256=abc",
      image: "repo/app:1.0",
      repo: "repo/app",
    });
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([item]);
    const loadPending = vi.spyOn(updates, "loadPending").mockResolvedValue();
    const loadReleaseNotes = vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    const refreshReleaseNotes = vi
      .spyOn(updates, "refreshReleaseNotes")
      .mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    const removalPlan = {
      removal_id: "removal-test",
      source_file: "/out/images.todo",
      can_remove: true,
      selected_line_numbers: [1],
      lines: [
        {
          line_no: 1,
          raw: item.raw,
          image: item.image,
          desired_tag: item.desired_tag,
          digest: item.digest,
        },
      ],
    };
    const createRemovalPlan = vi
      .spyOn(updates, "createRemovalPlan")
      .mockImplementation(async () => {
        updates.pendingRemovalPlan = removalPlan;
        return removalPlan;
      });
    const removeSelectedPending = vi
      .spyOn(updates, "removeSelectedPending")
      .mockImplementation(async () => {
        const response = {
          status: "success" as const,
          audit_run_id: 77,
          removed_count: 1,
          removed: [
            {
              line_no: 1,
              raw: item.raw,
              image: item.image,
              reason: "selected",
            },
          ],
        };
        updates.pendingCleanup = response;
        updates.pendingRemovalPlan = null;
        return response;
      });
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 selected entry"))
      ?.trigger("click");
    await flushPromises();

    expect(createRemovalPlan).toHaveBeenCalledWith([1]);
    const removalDialog = wrapper
      .findAll('[role="dialog"]')
      .find((dialog) => dialog.text().includes("Pending removal"));
    expect(removalDialog?.text()).toContain("Source lines");
    expect(removalDialog?.text()).toContain("#1 repo/app:1.0");
    expect(removalDialog?.text()).toContain("Containers, images, and Compose services are not deleted or updated");

    await removalDialog
      ?.findAll("button")
      .find((button) => button.text().includes("Remove 1 selected entry"))
      ?.trigger("click");
    await flushPromises();

    expect(removeSelectedPending).toHaveBeenCalledWith("removal-test", [
      { line_no: 1, raw: item.raw },
    ]);
    expect(loadPending).toHaveBeenCalled();
    expect(loadReleaseNotes).toHaveBeenCalled();
    expect(refreshReleaseNotes).toHaveBeenCalled();
    expect(loadRuns).toHaveBeenCalled();
    expect(wrapper.text()).toContain("1 pending entry removed from images.todo.");
    expect(wrapper.text()).toContain("Details");
  });

  it("starts a stack update with the full stack line set", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([
      pendingItem({ line_no: 4, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 9, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");

    expect(createPlan).toHaveBeenCalledWith([4, 9], true, [], []);
  });

  it("marks a stack indeterminate after one grouped item is deselected", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 2, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
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
    expect(createPlan).toHaveBeenCalledWith([1], true, [], []);
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
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = {
      ...pendingResponse([stackItem, unmatchedItem]),
      grouping: {
        ...pendingGrouping([stackItem]),
        unmatched: [unmatchedItem],
      },
    };
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Select all stack updates"))
      ?.trigger("click");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");

    expect(wrapper.text()).toContain("No Compose match");
    expect(createPlan).toHaveBeenCalledWith([1], true, [], []);
  });

  it("selects tag update rows and enables tag rewrites when an override is edited", async () => {
    const item = pendingItem();
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([item]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
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
      [],
    );
  });

  it("blocks invalid pending tag overrides before planning", async () => {
    const item = pendingItem();
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([item]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan");
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
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
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
      current_tag: "5.0",
      desired_tag: "",
      target_image: "lscr.io/linuxserver/radarr:5.1",
      services: ["radarr"],
      action: "recreate_service",
    });
    const updater = pendingGroupedItem({
      line_no: 2,
      image: "ghcr.io/example/wud-updater:1.0",
      repo: "ghcr.io/example/wud-updater",
      current_tag: "1.0",
      desired_tag: "2.0",
      target_image: "ghcr.io/example/wud-updater:2.0",
      services: ["wud-updater"],
    });
    const stackItem = pendingGroupedItem({
      line_no: 3,
      image: "redis:latest@sha256:abc",
      repo: "redis",
      current_tag: "latest",
      desired_tag: "",
      digest: "sha256:abc",
      target_image: "redis:latest@sha256:abc",
      compose_images: ["redis:latest"],
      services: [],
      action: "recreate_stack",
    });
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.releaseNotes = releaseNotesResponse([
      releaseNoteInfo({
        line_no: 1,
        status: "error",
        links: [],
        error: "no supported GitHub release source found",
      }),
      releaseNoteInfo({
        line_no: 2,
        breaking: true,
        breaking_reasons: ["Major version update."],
      }),
    ]);
    settings.servicePolicies = [
      servicePolicy({ service_key: "media/wud-updater", auto_update: true }),
    ];
    settings.snoozes = [snooze({ service_key: "media/radarr" })];
    updates.pending = {
      source_file: "/out/images.todo",
      exists: true,
      count: 3,
      items: [radarr, updater, stackItem],
      grouping: {
        ...pendingGrouping([radarr, updater, stackItem]),
        groups: [
          {
            ...pendingGrouping([radarr, updater, stackItem]).groups[0],
            services_label: "radarr, wud-updater",
            services: ["radarr", "wud-updater"],
            line_numbers: [1, 2, 3],
            items: [radarr, updater, stackItem],
          },
        ],
      },
      warnings: [],
    };
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });
    const card = wrapper.find(".stack-card");

    expect(card.find(".stack-identity").text()).toContain(
      "Services radarr, wud-updater",
    );
    const previewText = card.find(".stack-change-preview").text();
    expect(previewText).toContain("radarr");
    expect(previewText).toContain("Recreate service");
    expect(previewText).toContain("No release notes");
    expect(previewText).toContain("Snoozed");
    expect(previewText).toContain("lscr.io/linuxserver/radarr:5.0");
    expect(previewText).toContain("lscr.io/linuxserver/radarr:5.1");
    expect(previewText).toContain("wud-updater");
    expect(previewText).toContain("Tag update");
    expect(previewText).toContain("Major bump");
    expect(previewText).toContain("Possible breaking");
    expect(previewText).toContain("Auto-update");
    expect(previewText).toContain("ghcr.io/example/wud-updater:1.0");
    expect(previewText).toContain("ghcr.io/example/wud-updater:2.0");
    expect(card.text()).toContain("Recreate stack");
    expect(card.text()).toContain("Mutable latest");
    expect(card.text()).toContain("Digest-only");
    expect(card.text()).toContain("Stack restart");
    expect(card.find(".stack-card-tags").text()).not.toContain(
      "radarr, wud-updater",
    );
  });

  it("shows ready preflight service impact and row tag rewrites", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
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
                action: "recreate_service",
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
    const readiness = dialog.find(".apply-readiness");
    const impact = dialog.find(".preflight-impact");
    expect(dialog.find("#preflight-modal-title").text()).toBe("Review media plan");
    expect(dialog.find(".preflight-impact-text").text()).toBe(
      "radarr, wud-updater",
    );
    expect(readiness.exists()).toBe(true);
    expect(readiness.text()).toContain("Apply readiness");
    expect(readiness.text()).toContain("Ready");
    expect(readiness.text()).toContain("8 checks passed");
    expect(readiness.text()).toContain("Docker reachable");
    expect(readiness.text()).toContain("Selected services matched");
    expect(readiness.find(".apply-readiness-passed").exists()).toBe(true);
    expect(readiness.findAll(".apply-readiness-row")).toHaveLength(0);
    expect(readiness.text()).not.toContain("docker-daemon-info");
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

  it("shows failed apply readiness and disables apply", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({
        can_apply: false,
        apply_preflight: failedApplyPreflight(
          "logs-writable",
          "/logs is not a directory",
        ),
      });
    });
    const createJob = vi.spyOn(updates, "createJob");
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    const readiness = dialog.find(".apply-readiness");
    expect(readiness.exists()).toBe(true);
    expect(readiness.text()).toContain("Blocked");
    expect(readiness.text()).toContain("7 checks passed");
    expect(readiness.text()).toContain("Logs writable");
    expect(readiness.text()).toContain("/logs is not a directory");
    expect(readiness.find(".apply-readiness-passed").exists()).toBe(true);
    expect(readiness.findAll(".apply-readiness-row")).toHaveLength(1);
    expect(readiness.text()).not.toContain("docker-daemon-info");
    expect(dialog.text()).toContain("Fix the failed apply readiness check");

    const applyButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Apply 1 update"));
    expect(applyButton?.attributes("disabled")).toBeDefined();
    await applyButton?.trigger("click");

    expect(createJob).not.toHaveBeenCalled();
  });

  it("falls back to pending file order when grouping is unavailable", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = {
      ...pendingResponse(),
      grouping: {
        status: "unavailable",
        groups: [],
        unmatched: [],
        warnings: [],
      },
    };
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain(
      "Stack grouping is unavailable. Showing pending file order.",
    );
    expect(wrapper.find('[role="table"]').exists()).toBe(true);
  });

  it("shows safety cues in the mobile pending file order fallback", () => {
    const restore = mockMobileViewport();
    try {
      const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
      updates.pending = {
        ...pendingResponse([
          pendingItem({
            image: "redis:latest@sha256:abc",
            repo: "redis",
            current_tag: "latest",
            desired_tag: "",
            digest: "sha256:abc",
          }),
        ]),
        grouping: {
          status: "unavailable",
          groups: [],
          unmatched: [],
          warnings: [],
        },
      };
      mockPendingLifecycle(settings, updates);
      const wrapper = mountWithApp(PendingView, { pinia });
      const card = wrapper.find(".mobile-card");

      expect(wrapper.find('[role="table"]').exists()).toBe(false);
      expect(card.text()).toContain("Safety cues");
      expect(card.text()).toContain("Digest-only");
      expect(card.text()).toContain("Mutable latest");
    } finally {
      restore();
    }
  });

  it("shows a pending loading skeleton before queue data is available", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = null;
    updates.loading = true;
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("Loading pending updates");
    expect(wrapper.find(".pending-loading-state").exists()).toBe(true);
    expect(wrapper.find(".selection-toolbar").exists()).toBe(false);
  });

  it("keeps failed pending loads recoverable without showing stale selection controls", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = null;
    const loadPending = vi
      .spyOn(updates, "loadPending")
      .mockImplementationOnce(async () => {
        updates.error = ("Network request failed");
        throw new Error("Network request failed");
      })
      .mockImplementationOnce(async () => {
        updates.error = ("");
        updates.pending = pendingResponse();
      });
    vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    await flushPromises();

    expect(wrapper.text()).toContain("Pending updates unavailable");
    expect(wrapper.text()).toContain("Pending updates did not load");
    expect(wrapper.text()).toContain("Network request failed");
    expect(wrapper.find(".selection-toolbar").exists()).toBe(false);

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Retry pending load"))
      ?.trigger("click");
    await flushPromises();

    expect(loadPending).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("1 pending update");
    expect(wrapper.find(".selection-toolbar").exists()).toBe(true);
  });

  it("shows pending safety cue loading failures", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    settings.pendingSafetyCueError = "service policies unavailable";
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain(
      "Pending safety cues are unavailable: service policies unavailable",
    );
  });

  it("deduplicates malformed pending line keys before selecting all stack updates", async () => {
    const itemOne = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:1.0",
      repo: "repo/app",
    });
    const itemTwo = pendingGroupedItem({
      line_no: 2,
      image: "repo/worker:1.0",
      repo: "repo/worker",
    });
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = {
      ...pendingResponse([itemOne, itemTwo]),
      grouping: {
        ...pendingGrouping([itemOne, itemTwo]),
        groups: [
          {
            ...pendingGrouping([itemOne, itemTwo]).groups[0],
            line_numbers: [1, 1, 2],
            items: [itemOne, itemTwo],
          },
        ],
      },
    };
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Select all stack updates"))
      ?.trigger("click");
    await nextTick();

    expect(wrapper.text()).toContain("2 selected");
    expect(wrapper.text()).not.toContain("3 selected");
  });

  it("wraps long pending values in the fallback table", () => {
    const longImage =
      "registry.example.test/selfhosted/very-long-namespace-with-extra-segments/service-name-that-keeps-going:2026.06.01-build-with-extra-metadata";
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = {
      ...pendingResponse([
        pendingItem({
          image: longImage,
          repo: "registry.example.test/selfhosted/very-long-namespace-with-extra-segments/service-name-that-keeps-going",
        }),
      ]),
      grouping: {
        status: "unavailable",
        groups: [],
        unmatched: [],
        warnings: [],
      },
    };
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    const wrappedValues = wrapper.findAll(".pending-table-value");
    expect(wrappedValues.length).toBeGreaterThanOrEqual(2);
    expect(wrappedValues[0].text()).toContain(longImage);
    expect(wrappedValues[0].attributes("title")).toBe(longImage);
  });

  it("renders a clear queue state when no pending updates remain", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse([]);
    runs.runs = [runSummary({ id: 42 })];
    mockPendingLifecycle(settings, updates);
    const wrapper = mountWithApp(PendingView, { pinia });

    const clearState = wrapper.find(".clear-queue-state");
    expect(clearState.exists()).toBe(true);
    expect(clearState.text()).toContain("Update queue is clear");
    expect(clearState.text()).toContain(
      "images.todo has no updates waiting for review.",
    );
    expect(clearState.text()).toContain("Review latest run #42");
    expect(clearState.find(".clear-queue-mark").exists()).toBe(true);
  });

  it("renders release-note links with breaking cues", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse();
    updates.releaseNotes = releaseNotesResponse([
      releaseNoteInfo({
        breaking: true,
        breaking_reasons: ["Major version changes from 1 to 2."],
      }),
    ]);
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("GitHub release");
    expect(wrapper.text()).toContain("Possible breaking change");
    const link = wrapper.find(
      'a[href="https://github.com/acme/app/releases/tag/v2.0.0"]',
    );
    expect(link.exists()).toBe(true);
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
  });

  it("renders both LSIO and upstream release-note links", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse([pendingItem({ image: "linuxserver/radarr:latest" })]);
    updates.releaseNotes = releaseNotesResponse([
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
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("LSIO release");
    expect(wrapper.text()).toContain("Upstream release");
  });

  it("renders unavailable release-note reasons without hiding LSIO links", () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse([
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
    updates.releaseNotes = releaseNotesResponse([
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
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
    const wrapper = mountWithApp(PendingView, { pinia });

    expect(wrapper.text()).toContain("Unavailable");
    expect(wrapper.text()).toContain(
      "Only GHCR and mapped LinuxServer.io images have release-note links.",
    );
    expect(wrapper.text()).toContain("LSIO release");
    expect(wrapper.text()).toContain("Upstream project");
  });

  it("creates an apply job only after explicit confirmation", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    let pendingRefreshRemovesSelection = false;
    const loadPending = vi.spyOn(updates, "loadPending").mockImplementation(async () => {
      updates.plan = null;
      if (pendingRefreshRemovesSelection) {
        updates.pending = pendingResponse([]);
      }
    });
    const loadReleaseNotes = vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    const refreshReleaseNotes = vi
      .spyOn(updates, "refreshReleaseNotes")
      .mockResolvedValue();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse();
    });
    const createJob = vi.spyOn(updates, "createJob").mockImplementation(async () => {
      const job = applyJobResponse();
      updates.setApplyJob(job);
      return job;
    });
    const focus = vi
      .spyOn(HTMLElement.prototype, "focus")
      .mockImplementation(() => undefined);
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

    expect(createJob).toHaveBeenCalledWith("plan-test", [1], true, [], []);
    expect(jobStream.observed).toBe(true);
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    const applyPanel = wrapper.find(".apply-job-panel");
    expect(applyPanel.text()).toContain("Applying 1 update");
    expect(applyPanel.text()).toContain("Current status");
    expect(applyPanel.text()).toContain("Queued to start");
    expect(applyPanel.text()).toContain("Latest log line");
    expect(applyPanel.text()).toContain("Applied scope");
    const panel = applyPanel.element;
    const panelStatus = wrapper.find("#apply-job-panel-status").element;
    const panelLatestLog = wrapper.find(
      '[aria-labelledby="apply-job-latest-log-title"]',
    ).element;
    const panelProgress = wrapper.find(
      '[aria-labelledby="apply-job-progress-title"]',
    ).element;
    const panelDetails = wrapper.find(".apply-job-details").element;
    expect(focus.mock.contexts).toContain(panel);
    expect(
      Boolean(panelStatus.compareDocumentPosition(panelLatestLog) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true);
    expect(
      Boolean(panelLatestLog.compareDocumentPosition(panelProgress) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true);
    expect(
      Boolean(panelProgress.compareDocumentPosition(panelDetails) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true);
    expect(wrapper.find(".apply-job-details").attributes("open")).toBeUndefined();
    expect(applyPanel.text()).toContain("repo/app:1.0");

    jobStream.emitProgress({
      job_id: "job-test",
      phase: "pull",
      status: "running",
      message: "[media] Pulling selected image updates.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["calibre"],
      line_numbers: [1],
    });
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("Update progress");
    expect(wrapper.find(".apply-job-panel").text()).toContain("Pull images");
    expect(wrapper.find(".apply-job-panel").text()).toContain("Running");
    expect(wrapper.find(".apply-job-panel").text()).toContain("media");
    expect(wrapper.find(".apply-job-panel").text()).toContain("Running: Pull images");
    expect(wrapper.find(".apply-job-panel").text()).toContain("media / calibre / lines 1");

    jobStream.emitLog(
      applyJobLogResponse({
        content: "[2026-05-28T12:00:00+00:00] [INFO] docker-update-from-wud-v2\n",
      }),
    );
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("docker-update-from-wud-v2");

    pendingRefreshRemovesSelection = true;
    jobStream.emitJob(applyJobResponse({ status: "success", run_id: 10 }));
    await flushPromises();

    expect(loadPending).toHaveBeenCalled();
    expect(loadReleaseNotes).toHaveBeenCalled();
    expect(refreshReleaseNotes).toHaveBeenCalled();
    expect(loadRuns).toHaveBeenCalled();
    expect(wrapper.find(".apply-job-panel").text()).toContain("Apply complete");
    expect(wrapper.find(".apply-job-panel").text()).toContain("repo/app:1.0");
    expect(wrapper.find(".apply-job-panel").text()).toContain("#10");
    expect(wrapper.find(".apply-job-panel").text()).toContain("Update complete");
    expect(wrapper.find(".apply-job-details").attributes("open")).toBe("");
    expect(wrapper.find(".apply-job-live-log-body").attributes("style")).toContain(
      "display: none",
    );
    const showOutputButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Show output"));
    if (!showOutputButton) {
      throw new Error("Missing completed live log toggle");
    }
    expect(showOutputButton.attributes("aria-expanded")).toBe("false");
    await showOutputButton.trigger("click");
    await nextTick();
    expect(
      wrapper.find(".apply-job-live-log-body").attributes("style") ?? "",
    ).not.toContain("display: none");
    expect(wrapper.find(".apply-job-log-viewer").text()).toContain(
      "docker-update-from-wud-v2",
    );
    expect(showOutputButton.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find(".batch-action-bar").exists()).toBe(false);
  });

  it("keeps an earlier phase failure visible after a later same-phase success", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse();
    });
    vi.spyOn(updates, "createJob").mockImplementation(async () => {
      const job = applyJobResponse();
      updates.setApplyJob(job);
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

    const failedPull = {
      job_id: "job-test",
      phase: "pull",
      status: "failure" as const,
      message: "[media] Pull failed.",
      created_at: "2026-05-28T12:00:02+00:00",
      stack: "media",
      services: ["calibre"],
      line_numbers: [1],
    };
    const laterPullSuccess = {
      job_id: "job-test",
      phase: "pull",
      status: "success" as const,
      message: "[infra] Images pulled and verified.",
      created_at: "2026-05-28T12:00:03+00:00",
      stack: "infra",
      services: ["watchtower"],
      line_numbers: [2],
    };

    jobStream.emitProgress(failedPull);
    jobStream.emitProgress(laterPullSuccess);
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("Pull images failed");
    expect(wrapper.find(".apply-job-panel").text()).toContain("[media] Pull failed.");
    expect(wrapper.find(".apply-job-panel").text()).toContain(
      "media / calibre / lines 1",
    );
    expect(wrapper.find(".apply-job-panel").text()).toContain("Pull images failed");

    jobStream.emitJob(
      applyJobResponse({
        status: "failure",
        error: "updater exited with status 1",
        progress: [failedPull, laterPullSuccess],
      }),
    );
    await flushPromises();

    expect(wrapper.find(".apply-job-panel").text()).toContain("Failed: Pull images");
    expect(wrapper.find(".apply-job-panel").text()).toContain("[media] Pull failed.");
    expect(wrapper.find(".apply-job-panel").text()).toContain(
      "media / calibre / lines 1",
    );
  });

  it("loads the persisted run log when the job stream ends without live log content", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse();
    });
    vi.spyOn(updates, "createJob").mockImplementation(async () => {
      const job = applyJobResponse({ status: "running" });
      updates.setApplyJob(job);
      return job;
    });
    const runLog = vi.spyOn(webApi, "runLog").mockResolvedValue({
      run_id: 10,
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "fallback run log\n",
      truncated: false,
      max_bytes: 65_536,
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

    jobStream.emitJob(
      applyJobResponse({
        status: "success",
        run_id: 10,
        log_file: "/out/logs/job-terminal.log",
      }),
    );
    await flushPromises();

    expect(runLog).toHaveBeenCalledWith(10, 65_536);
    expect(loadRuns).toHaveBeenCalled();
    expect(jobStream.close).toHaveBeenCalled();
    expect(wrapper.find(".apply-job-panel").text()).toContain("fallback run log");
    expect(wrapper.find(".apply-job-live-log-body").attributes("style")).toContain(
      "display: none",
    );

    const showOutputButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Show output"));
    if (!showOutputButton) {
      throw new Error("Missing completed live log toggle");
    }
    await showOutputButton.trigger("click");
    await nextTick();
    expect(
      wrapper.find(".apply-job-live-log-body").attributes("style") ?? "",
    ).not.toContain("display: none");
    expect(wrapper.find(".apply-job-log-viewer").text()).toContain("fallback run log");
  });

  it("loads the persisted run log for already-terminal apply job state", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    updates.setApplyJob(
      applyJobResponse({
        status: "success",
        run_id: 10,
        log_file: "/out/logs/job-terminal.log",
      }),
    );
    const runLog = vi.spyOn(webApi, "runLog").mockResolvedValue({
      run_id: 10,
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "existing terminal run log\n",
      truncated: false,
      max_bytes: 65_536,
    });

    const wrapper = mountWithApp(PendingView, { pinia });
    await flushPromises();

    expect(runLog).toHaveBeenCalledWith(10, 65_536);
    expect(wrapper.find(".apply-job-panel").text()).toContain(
      "existing terminal run log",
    );
    expect(wrapper.find(".apply-job-live-log-body").attributes("style")).toContain(
      "display: none",
    );

    const showOutputButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Show output"));
    if (!showOutputButton) {
      throw new Error("Missing completed live log toggle");
    }
    await showOutputButton.trigger("click");
    await nextTick();
    expect(
      wrapper.find(".apply-job-live-log-body").attributes("style") ?? "",
    ).not.toContain("display: none");
    expect(wrapper.find(".apply-job-log-viewer").text()).toContain(
      "existing terminal run log",
    );
  });

  it("keeps failed apply jobs visible with the confirmed plan impact", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse();
    });
    vi.spyOn(updates, "createJob").mockImplementation(async () => {
      const job = applyJobResponse({
        status: "running",
        started_at: "2026-05-28T12:00:00+00:00",
      });
      updates.setApplyJob(job);
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
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    vi.spyOn(runs, "loadRuns").mockResolvedValue();
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse();
    });
    vi.spyOn(updates, "createJob").mockImplementation(async () => {
      const job = applyJobResponse({ status: "running" });
      updates.setApplyJob(job);
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
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    vi.spyOn(updates, "loadPending").mockResolvedValue();
    vi.spyOn(updates, "loadReleaseNotes").mockResolvedValue();
    vi.spyOn(updates, "refreshReleaseNotes").mockResolvedValue();
    vi.spyOn(webApi, "job").mockRejectedValue(
      new ApiError(404, "apply job not found"),
    );
    const loadRuns = vi.spyOn(runs, "loadRuns").mockImplementation(async () => {
      runs.runs = [runSummary({ id: 42 })];
    });
    const wrapper = mountWithApp(PendingView, { pinia });

    await flushPromises();

    expect(webApi.job).toHaveBeenCalledWith("job-lost");
    expect(loadRuns).toHaveBeenCalled();
    expect(updates.applyJob).toBeNull();
    expect(updates.rememberedApplyJobId).toBe("");
    expect(window.sessionStorage.getItem("applyJobId")).toBeNull();
    expect(wrapper.text()).toContain(APPLY_JOB_RECOVERY_MESSAGE);
    expect(wrapper.text()).toContain("Runs");
    expect(wrapper.text()).toContain("Latest run");
    expect(wrapper.text()).toContain("Log");
  });

  it("disables policy mutations in read-only mode", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.servicePolicies = [servicePolicy()];
    updates.updateTargets = updateTargetsResponse();
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    const deletePolicy = vi.spyOn(settings, "deleteServicePolicy");
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

  it("shows policy target loading errors from the updates store", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.servicePolicies = [];
    vi.spyOn(updates, "loadUpdateTargets").mockImplementation(async () => {
      updates.error = "update targets unavailable";
      throw new Error("update targets unavailable");
    });
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();

    const wrapper = mountWithApp(PoliciesView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("update targets unavailable");
  });

  it("shows policy status loading errors from the connection store", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    connection.status = null;
    settings.servicePolicies = [];
    vi.spyOn(connection, "loadStatus").mockImplementation(async () => {
      connection.error = "status unavailable";
      throw new Error("status unavailable");
    });
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();

    const wrapper = mountWithApp(PoliciesView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("status unavailable");
  });

  it("does not assume UTC while policy schedule timezone is loading", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    connection.status = null;
    settings.servicePolicies = [servicePolicy()];
    updates.updateTargets = updateTargetsResponse();
    vi.spyOn(connection, "loadStatus").mockResolvedValue();
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    const wrapper = mountWithApp(PoliciesView, { pinia });
    await flushPromises();

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Edit"))
      ?.trigger("click");
    await flushPromises();

    const saveButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Save policy"));
    expect(wrapper.text()).toContain("Update time (loading)");
    expect(wrapper.text()).not.toContain("Update time (UTC)");
    expect(saveButton?.attributes("disabled")).toBeDefined();

    connection.status = statusResponse({
      mutations_enabled: true,
      timezone: "America/Chicago",
    });
    await nextTick();

    expect(wrapper.text()).toContain("Update time (America/Chicago)");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text().includes("Save policy"))
        ?.attributes("disabled"),
    ).toBeUndefined();
  });

  it("saves scheduled policy fields after server timezone is known", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    connection.status = statusResponse({
      mutations_enabled: true,
      timezone: "America/Chicago",
    });
    settings.servicePolicies = [
      servicePolicy({
        auto_update_time: "09:30",
        auto_update_days: ["mon", "fri"],
      }),
    ];
    updates.updateTargets = updateTargetsResponse();
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
    const upsertPolicy = vi
      .spyOn(settings, "upsertServicePolicy")
      .mockResolvedValue();
    const wrapper = mountWithApp(PoliciesView, { pinia });
    await flushPromises();

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Edit"))
      ?.trigger("click");
    await flushPromises();
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    await wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Save policy"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Update time (America/Chicago)");
    expect(upsertPolicy).toHaveBeenCalledWith(
      "media/app",
      "stop",
      true,
      null,
      "09:30",
      ["mon", "fri"],
    );
  });

  it("offers discovered services and image repositories on management forms", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "media/radarr",
        service: "radarr",
        image: "lscr.io/linuxserver/radarr:5.21.1",
        image_repo: "linuxserver/radarr",
        current_tag: "5.21.1",
      }),
    ]);
    settings.tagExclusions = [];
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const wrapper = mountWithApp(TagExclusionsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("linuxserver/radarr");

    await wrapper.findAll("select")[1]?.setValue("linuxserver/radarr");
    await nextTick();

    expect(wrapper.findAll("select")[2]?.text()).toContain("5.21.1");
  });

  it("keeps clearable management selects string-safe", async () => {
    {
      const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
      settings.servicePolicies = [servicePolicy()];
      updates.updateTargets = updateTargetsResponse();
      vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
      vi.spyOn(settings, "loadServicePolicies").mockResolvedValue();
      const wrapper = mountWithApp(PoliciesView, { pinia });
      await flushPromises();

      emitSelectValue(wrapper, 0, null);
      await nextTick();

      expect(
        wrapper
          .findAll("button")
          .find((button) => button.text().includes("Save policy"))
          ?.attributes("disabled"),
      ).toBeDefined();
    }

    {
      const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
      settings.snoozes = [];
      updates.updateTargets = updateTargetsResponse();
      vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
      vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
      const wrapper = mountWithApp(SnoozesView, { pinia });
      await flushPromises();

      emitSelectValue(wrapper, 0, null);
      await nextTick();

      expect(
        wrapper
          .findAll("button")
          .find((button) => button.text().includes("Create snooze"))
          ?.attributes("disabled"),
      ).toBeDefined();
    }

    {
      const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
      settings.tagExclusions = [];
      updates.updateTargets = updateTargetsResponse();
      vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
      vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
      const wrapper = mountWithApp(TagExclusionsView, { pinia });
      await flushPromises();

      emitSelectValue(wrapper, 1, null);
      emitSelectValue(wrapper, 2, null);
      await nextTick();

      expect(
        wrapper
          .findAll("button")
          .find((button) => button.text().includes("Save rule"))
          ?.attributes("disabled"),
      ).toBeDefined();
    }
  });

  it("disables snooze mutations in read-only mode", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.snoozes = [snooze()];
    updates.updateTargets = updateTargetsResponse();
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();
    const deleteSnooze = vi.spyOn(settings, "deleteSnooze");
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

  it("shows snooze target loading errors from the updates store", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.snoozes = [];
    vi.spyOn(updates, "loadUpdateTargets").mockImplementation(async () => {
      updates.error = "snooze targets unavailable";
      throw new Error("snooze targets unavailable");
    });
    vi.spyOn(settings, "loadSnoozes").mockResolvedValue();

    const wrapper = mountWithApp(SnoozesView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("snooze targets unavailable");
  });

  it("disables tag exclusion mutations in read-only mode", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.tagExclusions = [tagExclusion()];
    updates.updateTargets = updateTargetsResponse();
    vi.spyOn(updates, "loadUpdateTargets").mockResolvedValue();
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();
    const setStatus = vi.spyOn(settings, "setTagExclusionStatus");
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

  it("shows tag exclusion target loading errors from the updates store", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.tagExclusions = [];
    vi.spyOn(updates, "loadUpdateTargets").mockImplementation(async () => {
      updates.error = "tag targets unavailable";
      throw new Error("tag targets unavailable");
    });
    vi.spyOn(settings, "loadTagExclusions").mockResolvedValue();

    const wrapper = mountWithApp(TagExclusionsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("tag targets unavailable");
  });

  it("renders read-only settings without exposing secret values or edit controls", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain("Runtime settings");
    expect(text).toContain("DOCKER_BASE");
    expect(text).toContain("WUD_WEB_PUBLIC_ORIGIN");
    expect(text).toContain("GITHUB_TOKEN");
    expect(text).toContain("Configured");
    expect(text).toContain("Not configured");
    expect(text).not.toContain("Copy env snippet");
    expect(text).not.toContain("Copy Compose override");
    expect(text).not.toContain('DOCKER_BASE="');
    expect(text).not.toContain("github-token-secret");
    expect(text).not.toContain("Save settings");
    expect(text).not.toContain("Delete settings");
    expect(
      wrapper.find(
        'a[href="https://github.com/magrhino/WUD-Updater/blob/main/docs/DEPLOYMENT.md#environment-variables"]',
      ).exists(),
    ).toBe(true);
  });

  it("disables managed preference saves in read-only settings", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const updateManagedSettings = vi
      .spyOn(settings, "updateManagedSettings")
      .mockResolvedValue({
        managed: settingsResponse().managed,
        audit_run_id: 77,
      });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("WebUI preferences");
    expect(wrapper.text()).toContain("Read-only mode is active");
    const saveButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Save preferences"));
    const relaunchButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Relaunch onboarding"));
    expect(saveButton?.attributes("disabled")).toBeDefined();
    expect(relaunchButton?.attributes("disabled")).toBeDefined();
    for (const select of wrapper.findAll("select")) {
      expect(select.attributes("disabled")).toBeDefined();
    }
    await saveButton?.trigger("click");
    await relaunchButton?.trigger("click");
    expect(updateManagedSettings).not.toHaveBeenCalled();
  });

  it("saves managed preference changes through the store", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.settings = settingsResponse({
      webui: settingsResponse().webui.map((entry) =>
        entry.name === "WUD_WEB_MUTATIONS_ENABLED"
          ? { ...entry, value: "true", configured: true, source: "configured" as const }
          : entry,
      ),
    });
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const updateManagedSettings = vi
      .spyOn(settings, "updateManagedSettings")
      .mockResolvedValue({
        managed: settingsResponse({
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
        }).managed,
        audit_run_id: 77,
      });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();
    await wrapper.findAll("select")[0].setValue("dark");
    const saveButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Save preferences"));
    await saveButton?.trigger("click");
    await flushPromises();

    expect(updateManagedSettings).toHaveBeenCalledWith({
      theme_preference: "dark",
    });
    expect(wrapper.text()).toContain("Preferences saved. Audit run #77.");
  });

  it("relaunches the onboarding checklist from settings", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    const visibleOnboardingEntry = settingsResponse().managed[1]!;
    const dismissedOnboardingEntry = {
      ...visibleOnboardingEntry,
      value: "dismissed",
      source: "configured" as const,
    };
    const visibleSettings = settingsResponse({
      managed: [settingsResponse().managed[0]!, visibleOnboardingEntry],
    });
    settings.settings = settingsResponse({
      managed: [settingsResponse().managed[0]!, dismissedOnboardingEntry],
    });
    settings.onboarding = onboardingChecklistResponse({
      dismissed: true,
      dismissed_at: "2026-05-31T00:00:00+00:00",
      visible: false,
      items: [],
    });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const updateManagedSettings = vi
      .spyOn(settings, "updateManagedSettings")
      .mockImplementation(async (values) => {
        settings.settings = visibleSettings;
        settings.onboarding = onboardingChecklistResponse();
        return {
          managed: visibleSettings.managed,
          audit_run_id: 88,
        };
      });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();
    const relaunchButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Relaunch onboarding"));
    await relaunchButton?.trigger("click");
    await flushPromises();

    expect(updateManagedSettings).toHaveBeenCalledWith({
      onboarding_checklist: "visible",
    });
    expect(wrapper.text()).toContain("Onboarding checklist relaunched. Audit run #88.");
    expect(wrapper.text()).toContain("Setup checklist");
  });

  it("requires warning confirmation before restarting the WebUI container", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.settings = settingsResponse({
      webui: settingsResponse().webui.map((entry) =>
        entry.name === "WUD_WEB_MUTATIONS_ENABLED"
          ? { ...entry, value: "true", configured: true, source: "configured" as const }
          : entry,
      ),
    });
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const restartContainer = vi.spyOn(connection, "restartContainer").mockResolvedValue({
      status: "scheduled",
      audit_run_id: 42,
      container: "wud-updater",
    });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    const restartButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Restart container"));
    expect(restartButton?.attributes("disabled")).toBeUndefined();
    await restartButton?.trigger("click");

    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.text()).toContain("Restart WebUI container");
    expect(dialog.text()).toContain("wud-updater");
    expect(restartContainer).not.toHaveBeenCalled();

    const confirmButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Restart container"));
    await confirmButton?.trigger("click");
    await flushPromises();

    expect(restartContainer).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Restart requested for wud-updater");
  });

  it("blocks container restart controls while restart is pending", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.settings = settingsResponse({
      webui: settingsResponse().webui.map((entry) =>
        entry.name === "WUD_WEB_MUTATIONS_ENABLED"
          ? { ...entry, value: "true", configured: true, source: "configured" as const }
          : entry,
      ),
    });
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const restartContainer = vi.spyOn(connection, "restartContainer").mockResolvedValue({
      status: "scheduled",
      audit_run_id: 42,
      container: "wud-updater",
    });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    connection.loading = true;
    await nextTick();

    const restartButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Restart container"));
    expect(restartButton?.attributes("disabled")).toBeDefined();
    await restartButton?.trigger("click");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    connection.loading = false;
    await nextTick();
    await restartButton?.trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);

    connection.loading = true;
    await nextTick();

    const confirmButton = wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text().includes("Restart container"));
    expect(confirmButton?.attributes("disabled")).toBeDefined();
    await confirmButton?.trigger("click");

    expect(restartContainer).not.toHaveBeenCalled();
  });

  it("disables container restart in read-only settings", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const restartContainer = vi.spyOn(connection, "restartContainer").mockResolvedValue({
      status: "scheduled",
      audit_run_id: 42,
      container: "wud-updater",
    });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Read-only mode is active");
    const restartButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Restart container"));
    expect(restartButton?.attributes("disabled")).toBeDefined();
    await restartButton?.trigger("click");
    expect(restartContainer).not.toHaveBeenCalled();
  });

  it("renders first-run onboarding checklist with copyable suggestions", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({
      items: [
        {
          key: "docker-access",
          title: "Docker daemon access",
          status: "FAIL",
          detail: "Docker daemon info: info failed: <redacted>",
          check_codes: ["docker-daemon-info"],
          suggestions: [
            {
              label: "Wire Docker access",
              description: "Mount the Docker socket or configure DOCKER_HOST.",
              snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
            },
          ],
          docs: [
            {
              label: "Deployment Docker access",
              url: "https://github.com/magrhino/WUD-Updater/blob/main/docs/DEPLOYMENT.md#requirements",
            },
          ],
        },
      ],
    });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    vi.spyOn(settings, "dismissOnboarding").mockResolvedValue({
      dismissed: true,
      dismissed_at: "2026-05-31T00:00:00+00:00",
    });

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();
    const text = wrapper.text();
    const restartIndex = text.indexOf("Restart WebUI container");
    const checklistIndex = text.indexOf("Setup checklist");

    expect(text).toContain("Setup checklist");
    expect(restartIndex).toBeGreaterThanOrEqual(0);
    expect(restartIndex).toBeLessThan(checklistIndex);
    expect(text).toContain("Docker daemon access");
    expect(text).toContain("info failed: <redacted>");
    expect(text).toContain("Wire Docker access");
    expect(text).toContain("Copy");
    expect(text).not.toContain("github-token-secret");
    expect(
      wrapper.find(
        'a[href="https://github.com/magrhino/WUD-Updater/blob/main/docs/DEPLOYMENT.md#requirements"]',
      ).exists(),
    ).toBe(true);
  });

  it("keeps non-actionable onboarding source checks out of the visible error chips", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({
      items: [
        {
          key: "compose-discovery",
          title: "Compose stack discovery",
          status: "FAIL",
          detail:
            "compose config /srv/docker/actual/docker-compose.yml: exit 1: additional properties 'labels' not allowed",
          check_codes: [
            "compose-config-srv-docker-actual-docker-compose-yml",
            "compose-config-srv-docker-arr-docker-compose-yml",
            "compose-config-srv-docker-backrest-docker-compose-yml",
          ],
          suggestions: [],
          docs: [],
        },
      ],
    });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();
    const row = wrapper.find(".onboarding-check-row.status-fail");
    const primaryCodes = row.find(".onboarding-check-codes.is-primary");
    const diagnostics = row.find(".onboarding-check-diagnostics");

    expect(primaryCodes.text()).toContain(
      "compose-config-srv-docker-actual-docker-compose-yml",
    );
    expect(primaryCodes.text()).not.toContain(
      "compose-config-srv-docker-arr-docker-compose-yml",
    );
    expect(diagnostics.find("summary").text()).toContain("Source check codes (3)");
    expect(diagnostics.text()).toContain(
      "compose-config-srv-docker-arr-docker-compose-yml",
    );
  });

  it("starts the core update tour once setup has no failing checks", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({
      items: [
        {
          key: "admin-setup",
          title: "Admin setup",
          status: "PASS",
          detail: "The first admin account exists.",
          check_codes: ["settings-authentication"],
          suggestions: [],
          docs: [],
        },
        {
          key: "mutation-mode",
          title: "Browser mutation mode",
          status: "WARN",
          detail: "Browser apply controls are server-side enabled.",
          check_codes: ["settings-mutation-gate"],
          suggestions: [],
          docs: [],
        },
      ],
    });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(
        coreUpdateTourResponse({
          status: "in_progress",
          step: "dashboard",
        }),
      );

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Setup is ready for the update tour");
    const startButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Start update tour"));
    await startButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("in_progress", "dashboard");
  });

  it("focuses the setup checklist once onboarding deep link data renders", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    settings.settings = null;
    settings.onboarding = null;
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const focus = vi
      .spyOn(HTMLElement.prototype, "focus")
      .mockImplementation(() => undefined);
    vi.spyOn(settings, "loadSettings").mockImplementation(async () => {
      settings.settings = settingsResponse();
    });
    const loadOnboarding = vi.spyOn(settings, "loadOnboarding").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());
    await router.push("/settings?onboarding=1");
    await router.isReady();

    const wrapper = mountWithApp(SettingsView, { pinia, router });
    document.body.appendChild(wrapper.element);
    await flushPromises();
    settings.onboarding = onboardingChecklistResponse();
    await nextTick();
    await flushPromises();

    expect(loadOnboarding).toHaveBeenCalled();
    expect(wrapper.find("#onboarding-checklist").exists()).toBe(true);
    expect(scrollIntoView).toHaveBeenCalled();
    expect(focus).toHaveBeenCalled();
  });

  it("replays and dismisses the core update tour from settings", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({ visible: false });
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "completed",
      step: "runs_history",
      updated_at: "2026-05-31T00:00:00+00:00",
    });
    vi.spyOn(settings, "loadSettings").mockResolvedValue();
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(
        coreUpdateTourResponse({
          status: "dismissed",
          step: "runs_history",
        }),
      );

    const wrapper = mountWithApp(SettingsView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Core update tour");
    expect(wrapper.text()).toContain("State: Completed. Step: History.");
    const replayButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Replay tour"));
    await replayButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("in_progress", "dashboard");
    const dismissButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Dismiss tour"));
    await dismissButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith("dismissed", "runs_history");
  });

  it("shows the dashboard step of the core update tour", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    connection.status = statusResponse({
      pending_count: 2,
      db_ready: true,
      mutations_enabled: true,
    });
    updates.pending = pendingResponse();
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "dashboard",
    });
    vi.spyOn(connection, "loadStatus").mockResolvedValue(undefined as any);
vi.spyOn(updates, "loadPending").mockResolvedValue(undefined as any);
vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadServicePolicies").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadSnoozes").mockResolvedValue(undefined as any);
vi.spyOn(settings, "loadTagExclusions").mockResolvedValue(undefined as any);
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockResolvedValue(
        coreUpdateTourResponse({
          status: "in_progress",
          step: "pending_select",
        }),
      );

    const wrapper = mountWithApp(DashboardView, { pinia });
    await flushPromises();

    expect(wrapper.text()).toContain("Start from current state");
    expect(wrapper.text()).toContain("Pending: 2");
    const nextButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Open pending updates"));
    await nextButton?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith(
      "in_progress",
      "pending_select",
    );
  });

  it("closes the preflight modal before showing apply tour guidance", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(true);
    updates.pending = pendingResponse();
    updates.releaseNotes = releaseNotesResponse([]);
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "pending_preflight",
    });
    mockPendingLifecycle(settings, updates);
    vi.spyOn(updates, "createPlan").mockImplementation(async () => {
      updates.plan = planResponse({ can_apply: true });
    });
    const updateCoreUpdateTour = vi
      .spyOn(settings, "updateCoreUpdateTour")
      .mockImplementation(async (status, step) => {
        const response = coreUpdateTourResponse({ status, step });
        settings.coreUpdateTour = response;
        return response;
      });

    const wrapper = mountWithApp(PendingView, { pinia });
    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Continue to apply guidance"))
      ?.trigger("click");
    await flushPromises();

    expect(updateCoreUpdateTour).toHaveBeenCalledWith(
      "in_progress",
      "pending_apply",
    );
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Apply only after the plan is clear");
  });

  it("shows read-only pending tour guidance and the empty queue fallback", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    updates.pending = pendingResponse([]);
    updates.releaseNotes = releaseNotesResponse([]);
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "pending_apply",
    });
    mockPendingLifecycle(settings, updates);
    vi.spyOn(runs, "loadRuns").mockResolvedValue();

    const wrapper = mountWithApp(PendingView, { pinia });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain("Apply only after the plan is clear");
    expect(text).toContain("Read-only mode keeps Apply disabled");
    expect(text).toContain("Update queue is clear");
    expect(text).toContain("New WUD entries will appear here");
    expect(text).toContain("Open setup checklist");
  });

  it("renders doctor results with redacted details and copyable suggestions", async () => {
    const { pinia, auth, connection, settings, updates, runs } = setupStores(false);
    connection.doctor = doctorResponse({
      checks: [
        {
          status: "FAIL",
          code: "docker-daemon-info",
          category: "docker",
          name: "Docker daemon info",
          detail: "exit 17: info failed: <redacted>",
          target: "",
          suggestions: [
            {
              label: "Wire Docker access",
              description: "Mount the Docker socket or configure DOCKER_HOST.",
              snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
            },
          ],
        },
      ],
    });
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();

    const wrapper = mountWithApp(DoctorView, { pinia });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain("Doctor results");
    expect(text).toContain("Docker daemon info");
    expect(text).toContain("exit 17: info failed: <redacted>");
    expect(text).toContain("Wire Docker access");
    expect(text).toContain("Copy");
    expect(text).not.toContain("github-token-secret");
  });
});
