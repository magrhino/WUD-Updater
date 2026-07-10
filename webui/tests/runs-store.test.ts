import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi } from "../src/api/client";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore, errorMessage } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import {
  applyJobLogResponse,
  applyJobResponse,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  onboardingDismissResponse,
  pendingResponse,
  releaseNotesResponse,
  retagPlanResponse,
  retagTarget,
  retagTargetsResponse,
  planResponse,
  rollbackPlan,
  runVerification,
  runSummary,
  selfUpdateApplyResponse,
  selfUpdatePlanResponse,
  selfUpdatePrepareResponse,
  selfUpdateResponse,
  settingsResponse,
  servicePolicy,
  statusResponse,
  stateOperationResponse,
  snooze,
  tagExclusion,
  updateTargetsResponse,
} from "./helpers/fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockFetch(body: unknown = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(body)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonRequestBody(call: unknown[]): unknown {
  const body = (call[1] as RequestInit).body;
  if (typeof body !== "string") {
    throw new TypeError("Expected request body to be a string");
  }
  return JSON.parse(body);
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}


import {
  deferred,
  jsonRequestBody,
  jsonResponse,
  mockFetch,
} from "./helpers/storeActions";

describe("runs store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads run detail into a keyed record without clearing existing entries", async () => {
    const existingDetail = {
      ...runSummary({ id: 5 }),
      pending_updates: [],
      verification: runVerification({ items: [], total_count: 0, verified_count: 0 }),
    };
    const fetchMock = mockFetch({
      ...runSummary({ id: 7, status: "running" }),
      pending_updates: [],
      verification: runVerification({ items: [], total_count: 0, verified_count: 0 }),
    });
    const runs = useRunsStore();
    runs.runDetails = { 5: existingDetail };

    await runs.loadRunDetail(7);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/7");
    expect(runs.runDetails[5]).toEqual(existingDetail);
    expect(runs.runDetails[7]?.id).toBe(7);
    expect(runs.loading).toBe(false);
    expect(runs.error).toBe("");
  });

  it("loads rollback plans into a keyed record without clearing existing entries", async () => {
    const existingPlan = rollbackPlan({ run_id: 5 });
    const fetchMock = mockFetch(rollbackPlan({ run_id: 7, status: "blocked" }));
    const runs = useRunsStore();
    runs.rollbackPlans = { 5: existingPlan };

    await runs.loadRollbackPlan(7);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/7/rollback-plan");
    expect(runs.rollbackPlans[5]).toEqual(existingPlan);
    expect(runs.rollbackPlans[7]?.status).toBe("blocked");
    expect(runs.loading).toBe(false);
    expect(runs.error).toBe("");
  });

  it("removes a cached rollback plan when a recheck fails", async () => {
    const ready = rollbackPlan({ run_id: 7 });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(ready))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "could not verify current Compose state" }, 503),
      );
    vi.stubGlobal("fetch", fetchMock);
    const runs = useRunsStore();
    runs.rollbackPlans = { 5: rollbackPlan({ run_id: 5 }) };

    await runs.loadRollbackPlan(7);
    await expect(runs.loadRollbackPlan(7)).rejects.toMatchObject({
      message: "could not verify current Compose state",
    });

    expect(runs.rollbackPlans[5]?.run_id).toBe(5);
    expect(runs.rollbackPlans[7]).toBeUndefined();
    expect(runs.error).toBe("could not verify current Compose state");
    expect(runs.loading).toBe(false);
  });

  it("ignores an older rollback success after a newer request fails", async () => {
    const older = deferred<ReturnType<typeof rollbackPlan>>();
    const newer = deferred<ReturnType<typeof rollbackPlan>>();
    vi.spyOn(webApi, "rollbackPlan")
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const runs = useRunsStore();
    runs.rollbackPlans = { 7: rollbackPlan({ run_id: 7 }) };

    const olderRequest = runs.loadRollbackPlan(7);
    const newerRequest = runs.loadRollbackPlan(7);
    const newerFailure = expect(newerRequest).rejects.toThrow("newer failed");
    newer.reject(new Error("newer failed"));
    await newerFailure;
    older.resolve(rollbackPlan({ run_id: 7, status: "ready" }));
    await olderRequest;

    expect(runs.rollbackPlans[7]).toBeUndefined();
    expect(runs.error).toBe("newer failed");
  });

  it("keeps a newer rollback success when an older request later fails", async () => {
    const older = deferred<ReturnType<typeof rollbackPlan>>();
    const newer = deferred<ReturnType<typeof rollbackPlan>>();
    vi.spyOn(webApi, "rollbackPlan")
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const runs = useRunsStore();

    const olderRequest = runs.loadRollbackPlan(7);
    const newerRequest = runs.loadRollbackPlan(7);
    newer.resolve(rollbackPlan({ run_id: 7, status: "blocked" }));
    await newerRequest;
    older.reject(new Error("stale failed"));
    await olderRequest;

    expect(runs.rollbackPlans[7]?.status).toBe("blocked");
    expect(runs.error).toBe("");
  });

  it("merges out-of-order rollback successes for different runs", async () => {
    const first = deferred<ReturnType<typeof rollbackPlan>>();
    const second = deferred<ReturnType<typeof rollbackPlan>>();
    vi.spyOn(webApi, "rollbackPlan")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const runs = useRunsStore();

    const firstRequest = runs.loadRollbackPlan(7);
    const secondRequest = runs.loadRollbackPlan(8);
    second.resolve(rollbackPlan({ run_id: 8, status: "blocked" }));
    await secondRequest;
    first.resolve(rollbackPlan({ run_id: 7, status: "ready" }));
    await firstRequest;

    expect(runs.rollbackPlans[7]?.status).toBe("ready");
    expect(runs.rollbackPlans[8]?.status).toBe("blocked");
    expect(runs.error).toBe("");
  });

  it("loads run logs with default and custom tail sizes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: 9,
          log_file: "/out/logs/run-9.log",
          exists: true,
          content: "run 9 log content\n",
          truncated: false,
          max_bytes: 262_144,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: 11,
          log_file: "/out/logs/run-11.log",
          exists: true,
          content: "partial log\n",
          truncated: true,
          max_bytes: 4_096,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const runs = useRunsStore();

    await runs.loadRunLog(9);
    await runs.loadRunLog(11, 4_096);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/9/log?tail_bytes=262144");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/runs/11/log?tail_bytes=4096");
    expect(runs.runLogs[9]?.content).toBe("run 9 log content\n");
    expect(runs.runLogs[11]?.truncated).toBe(true);
    expect(runs.loading).toBe(false);
    expect(runs.error).toBe("");
  });

  it("surfaces run log errors through the runs store", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "run not found" }, 404)),
    );
    const runs = useRunsStore();

    await expect(runs.loadRunLog(99)).rejects.toMatchObject({
      message: "run not found",
    });

    expect(runs.error).toBe("run not found");
    expect(runs.loading).toBe(false);
  });
});
