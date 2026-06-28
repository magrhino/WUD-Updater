import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SnoozeKind } from "../src/api/client";
import {
  applyJobResponse,
  pendingGroupedItem,
  pendingGrouping,
  pendingItem,
  pendingResponse,
  pendingRescanResponse,
  pendingSourceInfo,
  planResponse,
  releaseNotificationResponse,
  releaseNotesResponse,
  snooze,
  wudApiStatus,
  wudContainerMetadata,
} from "./helpers/fixtures";
import {
  mockPendingLifecycle,
  mountPendingView,
  pendingWithUnmatched,
  setupStores,
  unmatchedPendingItem,
} from "./helpers/viewSecurity";

async function selectAllAndPreview(
  wrapper: ReturnType<typeof mountPendingView>,
): Promise<void> {
  await wrapper
    .findAll("button")
    .find((button) => button.text().includes("Select all stack updates"))
    ?.trigger("click");
  await wrapper
    .findAll("button")
    .find((button) => button.text().includes("Preview selected plan"))
    ?.trigger("click");
}

function mountPendingWithSnooze(kind: SnoozeKind) {
  const snoozedItem = pendingGroupedItem({
    line_no: 1,
    image: "repo/app:1.0",
    repo: "repo/app",
    services: ["app"],
  });
  const stackItem = pendingGroupedItem({
    line_no: 2,
    image: "repo/db:1.0",
    repo: "repo/db",
    services: ["db"],
  });
  const { pinia, settings, updates } = setupStores(true);
  settings.snoozes = [
    snooze({
      service_key: "media/app",
      wait_for_service_key: kind === "dependency" ? "media/db" : "",
      snoozed_until: kind === "dependency" ? null : "2026-06-20T18:36:13+00:00",
      kind,
    }),
  ];
  updates.pending = {
    ...pendingResponse([snoozedItem, stackItem]),
    grouping: pendingGrouping([snoozedItem, stackItem]),
  };
  mockPendingLifecycle(settings, updates);
  const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
  return { createPlan, wrapper: mountPendingView(pinia) };
}

describe("pending view selection actions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows unmatched cleanup preview disabled in read-only mode", async () => {
    const item = unmatchedPendingItem();
    const { pinia, settings, updates } = setupStores(false);
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
    const wrapper = mountPendingView(pinia);

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

  it("disables security scan refresh while an apply job is active", async () => {
    const { pinia, settings, updates } = setupStores(true);
    const pending = pendingResponse();
    updates.pending = pending;
    updates.securityScans = {
      source_file: pending.source_file,
      source: pending.source,
      source_hash: pending.source_hash ?? "",
      scanning_enabled: true,
      scanner: "trivy",
      scan_mode: "registry",
      count: 0,
      items: [],
      warnings: [],
    };
    updates.applyJob = applyJobResponse({ status: "running" });
    mockPendingLifecycle(settings, updates);
    const refreshSecurityScans = vi
      .spyOn(updates, "refreshSecurityScans")
      .mockResolvedValue();
    const wrapper = mountPendingView(pinia);

    const refreshButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Refresh scans"));

    expect(refreshButton?.exists()).toBe(true);
    expect(refreshButton?.attributes("disabled")).toBeDefined();
    expect(refreshButton?.attributes("title")).toBe(
      "Wait for the active WebUI mutation to finish before refreshing candidate security scans.",
    );
    await refreshButton?.trigger("click");
    expect(refreshSecurityScans).not.toHaveBeenCalled();
  });

  it("shows security scans unavailable after metadata load fails", () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse();
    updates.securityScans = null;
    updates.securityScansError = "scanner unavailable";
    mockPendingLifecycle(settings, updates);

    const wrapper = mountPendingView(pinia);

    expect(wrapper.text()).toContain(
      "Candidate security scan metadata is unavailable: scanner unavailable",
    );
    expect(wrapper.text()).toContain("Security scans unavailable");
    expect(wrapper.text()).not.toContain("Security scans loading");
  });

  it("confirms unmatched cleanup before refreshing pending state", async () => {
    const item = unmatchedPendingItem();
    const { pinia, updates, runs } = setupStores(true);
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
    const wrapper = mountPendingView(pinia);

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
    const { pinia, settings, updates } = setupStores(false);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const createRemovalPlan = vi.spyOn(updates, "createRemovalPlan");
    const wrapper = mountPendingView(pinia);

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

  it("previews and sends Discord release notes for selected pending updates", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse();
    updates.releaseNotes = releaseNotesResponse();
    mockPendingLifecycle(settings, updates);
    const previewReleaseNotifications = vi
      .spyOn(updates, "previewReleaseNotifications")
      .mockImplementation(async () => {
        updates.releaseNotification = releaseNotificationResponse();
      });
    const sendReleaseNotifications = vi
      .spyOn(updates, "sendReleaseNotifications")
      .mockImplementation(async () => {
        updates.releaseNotification = releaseNotificationResponse({
          sent: true,
          audit_run_id: 79,
        });
      });
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview release notes"))
      ?.trigger("click");
    await flushPromises();

    expect(previewReleaseNotifications).toHaveBeenCalledWith({ line_numbers: [1] });
    expect(wrapper.find("dialog").text()).toContain(
      "Send Discord notifications",
    );

    await wrapper
      .find("dialog")
      .findAll("button")
      .find((button) => button.text().includes("Send to Discord"))
      ?.trigger("click");
    await flushPromises();

    expect(sendReleaseNotifications).toHaveBeenCalledWith({ line_numbers: [1] });
    expect(wrapper.find("dialog").text()).toContain(
      "Release-note notifications sent. Audit run #79.",
    );
  });

  it("keeps Discord release-note send disabled when preview fails", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse();
    updates.releaseNotes = releaseNotesResponse();
    mockPendingLifecycle(settings, updates);
    const previewReleaseNotifications = vi
      .spyOn(updates, "previewReleaseNotifications")
      .mockImplementation(async () => {
        updates.releaseNotification = null;
        updates.releaseNotificationError = "preview failed";
        throw new Error("preview failed");
      });
    const sendReleaseNotifications = vi.spyOn(updates, "sendReleaseNotifications");
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview release notes"))
      ?.trigger("click");
    await flushPromises();

    const dialog = wrapper.find("dialog");
    expect(previewReleaseNotifications).toHaveBeenCalledWith({ line_numbers: [1] });
    expect(dialog.text()).toContain(
      "Release-note notification is unavailable: preview failed",
    );
    expect(dialog.text()).toContain(
      "Preview release-note notifications before sending.",
    );
    expect(dialog.text()).not.toContain("Release-note notifications are disabled.");
    expect(dialog.text()).not.toContain("Discord release-note webhook is not configured.");
    expect(dialog.text()).not.toContain("Missing");
    const sendButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Send to Discord"));
    expect(sendButton?.attributes("disabled")).toBeDefined();

    await sendButton?.trigger("click");
    await flushPromises();

    expect(sendReleaseNotifications).not.toHaveBeenCalled();
  });

  it("disables selected release-note notifications from metadata notification state", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse();
    updates.releaseNotes = {
      ...releaseNotesResponse(),
      notifications_enabled: false,
      notifications_disabled_reason: "Release-note notifications are disabled.",
    };
    mockPendingLifecycle(settings, updates);
    const previewReleaseNotifications = vi.spyOn(
      updates,
      "previewReleaseNotifications",
    );
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();

    expect(wrapper.text()).toContain("Release-note notifications are disabled.");
    const previewButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview release notes"));
    expect(previewButton?.attributes("disabled")).toBeDefined();
    await previewButton?.trigger("click");

    expect(previewReleaseNotifications).not.toHaveBeenCalled();
  });

  it("disables WUD rescan controls in read-only mode", async () => {
    const { pinia, settings, updates } = setupStores(false);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi.spyOn(updates, "rescanPending");
    const wrapper = mountPendingView(pinia);

    const rescanButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan WUD"));
    expect(rescanButton?.attributes("disabled")).toBeDefined();
    await rescanButton?.trigger("click");

    expect(wrapper.text()).toContain("Read-only");
    expect(rescanPending).not.toHaveBeenCalled();
  });

  it("keeps WUD rescan available while the auth session is unknown", async () => {
    const { auth, pinia, settings, updates } = setupStores(true);
    auth.session = null;
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi
      .spyOn(updates, "rescanPending")
      .mockResolvedValue(pendingRescanResponse());
    const wrapper = mountPendingView(pinia);

    const rescanButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan WUD"));
    expect(wrapper.text()).not.toContain(
      "Set WUD_WEB_MUTATIONS_ENABLED=true on the server to rescan WUD.",
    );
    expect(rescanButton?.attributes("disabled")).toBeUndefined();
    await rescanButton?.trigger("click");

    expect(rescanPending).toHaveBeenCalledWith("all");
  });

  it("disables WUD rescan controls when WUD API is degraded", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = {
      ...pendingResponse(),
      wud_api: wudApiStatus({
        state: "unavailable",
        available: false,
        metadata_available: false,
        detail: "WUD API is unavailable: connection refused",
      }),
    };
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi.spyOn(updates, "rescanPending");
    const wrapper = mountPendingView(pinia);

    expect(wrapper.text()).toContain("WUD API is unavailable: connection refused");
    const rescanButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan WUD"));
    expect(rescanButton?.attributes("disabled")).toBeDefined();
    await rescanButton?.trigger("click");

    expect(rescanPending).not.toHaveBeenCalled();
  });

  it("allows global WUD rescan when only WUD metadata is degraded", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = {
      ...pendingResponse(),
      wud_api: wudApiStatus({
        state: "ready",
        available: true,
        metadata_available: false,
        detail: "WUD API container metadata is unavailable: timeout",
      }),
    };
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi
      .spyOn(updates, "rescanPending")
      .mockResolvedValue(pendingRescanResponse());
    const wrapper = mountPendingView(pinia);

    const rescanButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan WUD"));
    expect(rescanButton?.attributes("disabled")).toBeUndefined();
    await rescanButton?.trigger("click");

    expect(rescanPending).toHaveBeenCalledWith("all");
  });

  it("disables selected WUD rescan when selected rows lack WUD metadata", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse();
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi.spyOn(updates, "rescanPending");
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();

    expect(wrapper.text()).toContain("Selected entries do not have WUD container IDs.");
    const selectedRescan = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan selected"));
    expect(selectedRescan?.attributes("disabled")).toBeDefined();
    await selectedRescan?.trigger("click");

    expect(rescanPending).not.toHaveBeenCalled();
  });

  it("rescans selected WUD metadata rows", async () => {
    const item = pendingItem({
      wud_metadata: wudContainerMetadata(),
    });
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse([item]);
    mockPendingLifecycle(settings, updates);
    const rescanPending = vi
      .spyOn(updates, "rescanPending")
      .mockResolvedValue(pendingRescanResponse({ scope: "selected" }));
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Rescan selected"))
      ?.trigger("click");

    expect(rescanPending).toHaveBeenCalledWith("selected", [1]);
  });

  it("disables selected pending removal for API pending source", async () => {
    const item = pendingItem({
      source: "api",
      source_id: "docker.local.app",
    });
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = {
      ...pendingResponse([item]),
      source_file: "WUD API",
      source: pendingSourceInfo({
        configured: "api",
        active: "api",
        label: "WUD API",
      }),
    };
    mockPendingLifecycle(settings, updates);
    const createRemovalPlan = vi.spyOn(updates, "createRemovalPlan");
    const wrapper = mountPendingView(pinia);

    await wrapper
      .find('input[aria-label="Select stack media"]')
      .setValue(true);
    await flushPromises();

    expect(wrapper.text()).toContain(
      "WUD API entries cannot be removed from the WebUI because this source is read from WUD.",
    );
    const removalButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 selected entry"));
    expect(removalButton?.attributes("disabled")).toBeDefined();
    await removalButton?.trigger("click");

    expect(createRemovalPlan).not.toHaveBeenCalled();
  });

  it("disables unmatched cleanup for API pending source", async () => {
    const item = {
      ...unmatchedPendingItem(),
      source: "api" as const,
      source_id: "docker.local.old",
    };
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = {
      ...pendingWithUnmatched(item),
      source_file: "WUD API",
      source: pendingSourceInfo({
        configured: "api",
        active: "api",
        label: "WUD API",
      }),
    };
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
    const wrapper = mountPendingView(pinia);

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
      "WUD API entries cannot be removed from the WebUI because this source is read from WUD.",
    );
    const cleanupButton = dialog
      .findAll("button")
      .find((button) => button.text().includes("Remove 1 unmatched entry"));
    expect(cleanupButton?.attributes("disabled")).toBeDefined();
    await cleanupButton?.trigger("click");

    expect(cleanupPending).not.toHaveBeenCalled();
  });

  it("confirms selected pending removal before refreshing pending state", async () => {
    const item = pendingItem({
      line_no: 1,
      raw: "repo/app:1.0 sha256=abc",
      image: "repo/app:1.0",
      repo: "repo/app",
    });
    const { pinia, updates, runs } = setupStores(true);
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
    const wrapper = mountPendingView(pinia);

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
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse([
      pendingItem({ line_no: 4, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 9, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountPendingView(pinia);

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview media plan"))
      ?.trigger("click");

    expect(createPlan).toHaveBeenCalledWith([4, 9], true, [], []);
  });

  it("marks a stack indeterminate after one grouped item is deselected", async () => {
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse([
      pendingItem({ line_no: 1, image: "repo/app:1.0", repo: "repo/app" }),
      pendingItem({ line_no: 2, image: "repo/worker:1.0", repo: "repo/worker" }),
    ]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountPendingView(pinia);
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
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = {
      ...pendingResponse([stackItem, unmatchedItem]),
      grouping: {
        ...pendingGrouping([stackItem]),
        unmatched: [unmatchedItem],
      },
    };
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountPendingView(pinia);

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

  it("excludes time-snoozed items from bulk stack selection but allows direct selection", async () => {
    const { createPlan, wrapper } = mountPendingWithSnooze("time");

    await selectAllAndPreview(wrapper);

    expect(wrapper.text()).toContain("Snoozed pending entries");
    expect(wrapper.text()).toContain("Excluded from bulk selection while snoozed.");
    expect(createPlan).toHaveBeenCalledWith([2], true, [], []);

    await wrapper
      .find('input[aria-label="Select update repo/app:1.0"]')
      .setValue(true);
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Preview selected plan"))
      ?.trigger("click");

    expect(createPlan).toHaveBeenLastCalledWith([1, 2], true, [], []);
  });

  it("excludes dependency-snoozed items from bulk stack selection", async () => {
    const { createPlan, wrapper } = mountPendingWithSnooze("dependency");

    await selectAllAndPreview(wrapper);

    expect(wrapper.text()).toContain("Snoozed pending entries");
    expect(createPlan).toHaveBeenCalledWith([2], true, [], []);
  });

  it("excludes future active snooze kinds from bulk stack selection", async () => {
    const { createPlan, wrapper } = mountPendingWithSnooze(
      "maintenance" as SnoozeKind,
    );

    await selectAllAndPreview(wrapper);

    expect(wrapper.text()).toContain("Snoozed pending entries");
    expect(createPlan).toHaveBeenCalledWith([2], true, [], []);
  });

  it("selects tag update rows and enables tag rewrites when an override is edited", async () => {
    const item = pendingItem();
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse([item]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue();
    const wrapper = mountPendingView(pinia);

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
    const { pinia, settings, updates } = setupStores(true);
    updates.pending = pendingResponse([item]);
    mockPendingLifecycle(settings, updates);
    const createPlan = vi.spyOn(updates, "createPlan");
    const wrapper = mountPendingView(pinia);

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
});
