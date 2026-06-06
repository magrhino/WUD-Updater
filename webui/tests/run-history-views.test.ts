import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory, type Router } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import type {
  PendingUpdateRecord,
  RunDetail,
  RunEventRecord,
  RunSummary,
} from "../src/api/client";
import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import RunDetailView from "../src/views/RunDetailView.vue";
import RunsView from "../src/views/RunsView.vue";
import {
  authSession,
  coreUpdateTourResponse,
  runSummary,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

function mockMediaQueries(matches: (query: string) => boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function mockDesktopViewport(): void {
  mockMediaQueries((query) => query.includes("min-width"));
}

function mockMobileViewport(): void {
  mockMediaQueries((query) => query.includes("max-width"));
}

async function setupRoute(path: string): Promise<{
  pinia: ReturnType<typeof createPinia>;
  router: Router;
  settings: ReturnType<typeof useWebuiStore>;
}> {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.session = authSession({ authenticated: true });
      const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
  settings.coreUpdateTour = coreUpdateTourResponse();
  const router = createWudRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  return { pinia, router, settings, runs };
}

function runEvent(overrides: Partial<RunEventRecord> = {}): RunEventRecord {
  return {
    id: 1,
    run_id: 1,
    created_at: "2026-05-28T12:00:00+00:00",
    service_name: "app",
    stack_name: "media",
    image: "repo/app:1.0",
    target_image: "repo/app:1.1",
    old_image_id: "",
    new_image_id: "",
    old_digest: "",
    new_digest: "",
    status: "success",
    metadata: {},
    ...overrides,
  };
}

function pendingUpdate(
  overrides: Partial<PendingUpdateRecord> = {},
): PendingUpdateRecord {
  return {
    id: 1,
    run_id: 1,
    line_no: 1,
    raw: "repo/app:1.0 sha256=abc",
    image: "repo/app:1.0",
    target_digest: "sha256:def",
    desired_tag: "1.1",
    service_key: "media/app",
    stack_name: "media",
    service_name: "app",
    status: "planned",
    status_reason: "selected",
    created_at: "2026-05-28T12:00:00+00:00",
    updated_at: "2026-05-28T12:00:00+00:00",
    metadata: {},
    ...overrides,
  };
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  const id = overrides.id ?? 42;
  return {
    ...runSummary({
      id,
      dry_run: false,
      mode: "apply",
      log_file: `/out/logs/run-${id}.log`,
      events: [runEvent({ run_id: id })],
    }),
    pending_updates: [pendingUpdate({ run_id: id })],
    ...overrides,
  };
}

function multiServiceEvents(runId: number): RunEventRecord[] {
  return [
    runEvent({ id: 1, run_id: runId, service_name: "alpha" }),
    runEvent({ id: 2, run_id: runId, service_name: "alpha" }),
    runEvent({ id: 3, run_id: runId, service_name: "", stack_name: "beta" }),
    runEvent({ id: 4, run_id: runId, service_name: "", stack_name: "" }),
    runEvent({ id: 5, run_id: runId, service_name: "delta" }),
  ];
}

function actionRuns(): RunSummary[] {
  const cases: Array<{ mode: string; dryRun: boolean }> = [
    { mode: "cli", dryRun: true },
    { mode: "cli", dryRun: false },
    { mode: "apply", dryRun: false },
    { mode: "auto-update", dryRun: false },
    { mode: "cleanup", dryRun: false },
    { mode: "snooze-created", dryRun: false },
    { mode: "snooze-removed", dryRun: false },
    { mode: "service-policy-upserted", dryRun: false },
    { mode: "service-policy-deleted", dryRun: false },
    { mode: "tag-exclusion-upserted", dryRun: false },
    { mode: "tag-exclusion-status", dryRun: false },
    { mode: "web-auth", dryRun: false },
    { mode: "web-state", dryRun: false },
    { mode: "web-pending-cleanup", dryRun: false },
    { mode: "web-pending-removal", dryRun: false },
    { mode: "web-settings", dryRun: false },
    { mode: "container-restart", dryRun: false },
    { mode: "", dryRun: false },
    { mode: "custom-action", dryRun: false },
  ];

  return cases.map((item, index) => {
    const id = index + 1;
    const events =
      id === 1
        ? multiServiceEvents(id)
        : id === 3
          ? [
              runEvent({ id: 10, run_id: id, service_name: "api" }),
              runEvent({ id: 11, run_id: id, service_name: "worker" }),
            ]
          : [];
    return runSummary({
      id,
      dry_run: item.dryRun,
      mode: item.mode,
      finished_at: id === 1 ? "2026-05-28T12:10:00+00:00" : null,
      events,
    });
  });
}

describe("RunsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mockDesktopViewport();
  });

  it("loads and renders desktop history rows with action and service labels", async () => {
    const { pinia, router, settings, runs } = await setupRoute("/runs");
    runs.error = "history database is unavailable";
    settings.coreUpdateTour = coreUpdateTourResponse({
      status: "in_progress",
      step: "runs_history",
    });
    runs.runs = actionRuns();
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue();

    const wrapper = mountWithApp(RunsView, { pinia, router });
    await flushPromises();

    expect(loadRuns).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[role="alert"]').text()).toContain(
      "history database is unavailable",
    );
    expect(wrapper.find(".history-view-tab.active").text()).toBe("All runs");
    expect(wrapper.text()).toContain(`${runs.runs.length} recent runs`);
    expect(wrapper.text()).toContain("Verify the run afterward");
    expect(wrapper.text()).toContain("Details and logs stay linked from each run");
    expect(wrapper.find('[role="table"]').exists()).toBe(true);
    expect(wrapper.find('a[href="/runs/1"]').text()).toBe("#1");

    const rows = wrapper.findAll('[role="row"]');
    expect(rows[0].text()).toContain("CLI (dry run)");
    expect(rows[0].text()).toContain("5");
    expect(rows[0].text()).toContain("alpha, beta, service, +1 more");
    expect(rows[0].text()).toContain("2026-05-28T12:10:00+00:00");
    expect(rows[1].text()).toContain("CLI");
    expect(rows[1].text()).not.toContain("dry run");
    expect(rows[2].text()).toContain("Apply");
    expect(rows[2].text()).toContain("2");
    expect(rows[2].text()).toContain("api, worker");

    for (const label of [
      "Auto update",
      "Cleanup",
      "Snooze created",
      "Snooze removed",
      "Policy changed",
      "Policy removed",
      "Tag exclusion saved",
      "Tag exclusion status changed",
      "Web auth",
      "Web state",
      "Pending cleanup",
      "Pending removal",
      "Settings changed",
      "Container restarted",
      "Unknown",
      "custom-action",
    ]) {
      expect(wrapper.text()).toContain(label);
    }
  });

  it("renders mobile run cards with running and finished states", async () => {
    mockMobileViewport();
    const { pinia, router, settings, runs } = await setupRoute("/runs");
    runs.runs = [
      runSummary({
        id: 21,
        status: "running",
        mode: "cli",
        dry_run: true,
        finished_at: null,
        events: [runEvent({ id: 21, run_id: 21, service_name: "api" })],
      }),
      runSummary({
        id: 22,
        status: "success",
        mode: "apply",
        dry_run: false,
        finished_at: "2026-05-28T12:05:00+00:00",
        events: [],
      }),
    ];
    vi.spyOn(runs, "loadRuns").mockResolvedValue();

    const wrapper = mountWithApp(RunsView, { pinia, router });
    await flushPromises();

    expect(wrapper.find('[role="table"]').exists()).toBe(false);
    expect(wrapper.findAll(".mobile-card")).toHaveLength(2);
    expect(wrapper.text()).toContain("#21 running");
    expect(wrapper.text()).toContain("CLI (dry run)");
    expect(wrapper.text()).toContain("1 (api)");
    expect(wrapper.text()).toContain("Running");
    expect(wrapper.text()).toContain("#22 success");
    expect(wrapper.text()).toContain("Apply");
    expect(wrapper.text()).toContain("2026-05-28T12:05:00+00:00");
  });

  it("renders the mobile empty state when there are no runs", async () => {
    mockMobileViewport();
    const { pinia, router, settings, runs } = await setupRoute("/runs");
    runs.runs = [];
    vi.spyOn(runs, "loadRuns").mockResolvedValue();

    const wrapper = mountWithApp(RunsView, { pinia, router });
    await flushPromises();

    expect(wrapper.find(".empty-state").text()).toBe("No runs recorded.");
  });
});

describe("RunDetailView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads run detail, renders evidence, and reloads when the route id changes", async () => {
    const { pinia, router, settings, runs } = await setupRoute("/runs/42");
    const oldDigest = "sha256:old-digest-value-12345";
    const newDigest = "sha256:new-digest-value-12345";
    const newOnlyDigest = "sha256:new-only-digest-value";
    const oldOnlyDigest = "sha256:old-only-digest-value";
    const oldImageId = "sha256:old-image-id-12345";
    const newImageId = "sha256:new-image-id-12345";
    const firstDetail = runDetail({
      id: 42,
      mode: "apply",
      dry_run: false,
      status: "success",
      pending_updates: [
        pendingUpdate({
          id: 7,
          run_id: 42,
          line_no: 7,
          service_key: "media/api",
          status: "planned",
          status_reason: "selected",
        }),
        pendingUpdate({
          id: 8,
          run_id: 42,
          line_no: 8,
          service_key: "",
          image: "repo/fallback:1.0",
          status: "skipped",
          status_reason: "stale",
        }),
      ],
      events: [
        runEvent({
          id: 100,
          run_id: 42,
          service_name: "api",
          image: "repo/api:1.0",
          old_digest: oldDigest,
          new_digest: newDigest,
          old_image_id: oldImageId,
          new_image_id: newImageId,
        }),
        runEvent({
          id: 101,
          run_id: 42,
          service_name: "",
          stack_name: "stack-only",
          image: "repo/worker:1.0",
          new_digest: newOnlyDigest,
        }),
        runEvent({
          id: 102,
          run_id: 42,
          service_name: "",
          stack_name: "",
          image: "repo/fallback:1.0",
          old_digest: oldOnlyDigest,
        }),
      ],
    });
    const secondDetail = runDetail({
      id: 43,
      mode: "cleanup",
      dry_run: true,
      status: "failure",
      log_file: "",
      pending_updates: [],
      events: [],
    });
    const loadRunDetail = vi
      .spyOn(runs, "loadRunDetail")
      .mockImplementation(async (runId: number) => {
        runs.runDetails = {
          ...settings.runDetails,
          [runId]: runId === 42 ? firstDetail : secondDetail,
        };
      });

    const wrapper = mountWithApp(RunDetailView, { pinia, router });
    await flushPromises();
    await nextTick();

    expect(loadRunDetail).toHaveBeenCalledWith(42);
    expect(wrapper.text()).toContain("#42");
    expect(wrapper.find('a[href="/runs/42/log"]').text()).toContain("View log");
    expect(wrapper.text()).toContain("Status");
    expect(wrapper.text()).toContain("success");
    expect(wrapper.text()).toContain("Mode");
    expect(wrapper.text()).toContain("apply");
    expect(wrapper.text()).toContain("Dry run");
    expect(wrapper.text()).toContain("No");
    expect(wrapper.text()).toContain("Updates");
    expect(wrapper.text()).toContain("2");
    expect(wrapper.text()).toContain("#7");
    expect(wrapper.text()).toContain("media/api");
    expect(wrapper.text()).toContain("planned selected");
    expect(wrapper.text()).toContain("#8");
    expect(wrapper.text()).toContain("repo/fallback:1.0");
    expect(wrapper.text()).toContain("skipped stale");
    expect(wrapper.text()).toContain("api");
    expect(wrapper.text()).toContain("repo/api:1.0");
    expect(wrapper.text()).toContain("stack-only");
    expect(wrapper.text()).toContain("service");
    expect(wrapper.text()).toContain(
      `Digest: ${oldDigest.substring(0, 15)}... -> ${newDigest.substring(0, 15)}...`,
    );
    expect(wrapper.text()).toContain(
      `Digest: none -> ${newOnlyDigest.substring(0, 15)}...`,
    );
    expect(wrapper.text()).toContain(
      `Digest: ${oldOnlyDigest.substring(0, 15)}... -> none`,
    );
    expect(wrapper.text()).toContain(
      `Image ID: ${oldImageId.substring(0, 15)}... -> ${newImageId.substring(0, 15)}...`,
    );

    await router.push("/runs/43");
    await flushPromises();
    await nextTick();

    expect(loadRunDetail).toHaveBeenLastCalledWith(43);
    expect(wrapper.text()).toContain("#43");
    expect(wrapper.text()).toContain("failure");
    expect(wrapper.text()).toContain("No log path");
  });

  it("renders error and empty detail states", async () => {
    const { pinia, router, settings, runs } = await setupRoute("/runs/9");
    runs.error = "run detail failed to load";
    runs.runDetails = {
      9: runDetail({
        id: 9,
        log_file: "",
        pending_updates: [],
        events: [],
      }),
    };
    vi.spyOn(runs, "loadRunDetail").mockResolvedValue();

    const wrapper = mountWithApp(RunDetailView, { pinia, router });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain(
      "run detail failed to load",
    );
    expect(wrapper.find('a[href="/runs/9/log"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("No log path");
    expect(wrapper.text()).toContain("No pending records.");
    expect(wrapper.text()).toContain("No events recorded.");
  });
});
