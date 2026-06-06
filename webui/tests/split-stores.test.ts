import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, webApi } from "../src/api/client";
import { errorMessage, useConnectionStore } from "../src/stores/connection";
import { useRunsStore } from "../src/stores/runs";
import { useSettingsStore } from "../src/stores/settings";
import { useAuthStore } from "../src/stores/auth";
import {
  authSession,
  doctorResponse,
  runSummary,
  settingsResponse,
  snooze,
  stateOperationResponse,
  statusResponse,
  tagExclusion,
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

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function runDetail(runId: number) {
  return {
    ...runSummary({ id: runId }),
    pending_updates: [],
  };
}

function runLogResponse(runId: number, content = "log content\n") {
  return {
    run_id: runId,
    log_file: `/out/logs/run-${runId}.log`,
    exists: true,
    content,
    truncated: false,
    max_bytes: 262_144,
  };
}

function diagnosticsSupportBundleResponse() {
  return {
    wud_updater_version: "0.24.2",
    settings: settingsResponse(),
    doctor_result: doctorResponse(),
    pending_summary: { source_file: "/out/images.todo", exists: true, count: 0, items: [], grouping: { status: "ready", groups: [], unmatched: [], warnings: [] }, warnings: [] },
    last_run_status: null,
    diagnostics_warnings: [],
    discovery_warnings: [],
    log_tail: null,
  };
}

describe("errorMessage helper", () => {
  it("extracts message from ApiError instances", () => {
    const err = new ApiError(503, "service unavailable");
    expect(errorMessage(err)).toBe("service unavailable");
  });

  it("extracts message from plain Error instances", () => {
    const err = new Error("plain error");
    expect(errorMessage(err)).toBe("plain error");
  });

  it("returns a generic message for non-Error values", () => {
    expect(errorMessage("string error")).toBe("Request failed");
    expect(errorMessage(42)).toBe("Request failed");
    expect(errorMessage(null)).toBe("Request failed");
    expect(errorMessage({})).toBe("Request failed");
    expect(errorMessage(undefined)).toBe("Request failed");
  });
});

describe("connection store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads diagnostics support bundle", async () => {
    const fetchMock = mockFetch(diagnosticsSupportBundleResponse());
    const connection = useConnectionStore();

    const response = await connection.diagnosticsSupportBundle();

    expect(response.wud_updater_version).toBe("0.24.2");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/diagnostics/support-bundle");
    expect(connection.loading).toBe(false);
  });

  it("surfaces error and clears loading when diagnostics bundle fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "bundle unavailable" }, 503)));
    const connection = useConnectionStore();

    await expect(connection.diagnosticsSupportBundle()).rejects.toMatchObject({
      message: "bundle unavailable",
    });

    expect(connection.error).toBe("bundle unavailable");
    expect(connection.loading).toBe(false);
  });

  it("sets error directly via setError", () => {
    const connection = useConnectionStore();

    connection.setError("manual error message");

    expect(connection.error).toBe("manual error message");
    expect(connection.loading).toBe(false);
  });

  it("clears error on subsequent successful load", async () => {
    mockFetch(statusResponse());
    const connection = useConnectionStore();
    connection.error = "stale error";

    await connection.loadStatus();

    expect(connection.error).toBe("");
  });

  it("keeps loading true through stateOperation and clears on completion", async () => {
    const auth = useAuthStore();
    auth.session = authSession({ authenticated: true });
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-test");
    const stateOp = deferred<ReturnType<typeof stateOperationResponse>>();
    vi.spyOn(webApi, "stateOperation").mockReturnValue(stateOp.promise);
    const connection = useConnectionStore();

    const operation = connection.stateOperation({
      kind: "delete_service_policy",
      service_key: "media/app",
    });
    await flushPromises();

    expect(connection.loading).toBe(true);

    stateOp.resolve(stateOperationResponse());
    await operation;

    expect(connection.loading).toBe(false);
    expect(connection.error).toBe("");
  });
});

describe("runs store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads run detail and preserves existing entries", async () => {
    const existingDetail = runDetail(5);
    const fetchMock = mockFetch(runDetail(7));
    const runs = useRunsStore();
    runs.runDetails = { 5: existingDetail };

    await runs.loadRunDetail(7);

    expect(runs.runDetails[5]).toEqual(existingDetail);
    expect(runs.runDetails[7]?.id).toBe(7);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/7");
    expect(runs.loading).toBe(false);
  });

  it("loads run log with default tail bytes", async () => {
    const fetchMock = mockFetch(runLogResponse(3, "default tail log\n"));
    const runs = useRunsStore();

    await runs.loadRunLog(3);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/3/log?tail_bytes=262144");
    expect(runs.runLogs[3]?.content).toBe("default tail log\n");
    expect(runs.loading).toBe(false);
  });

  it("loads run log with custom tail bytes", async () => {
    const fetchMock = mockFetch(runLogResponse(4, "short log\n"));
    const runs = useRunsStore();

    await runs.loadRunLog(4, 65_536);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/4/log?tail_bytes=65536");
    expect(runs.runLogs[4]?.content).toBe("short log\n");
  });

  it("loads run log and preserves logs for other runs", async () => {
    const existingLog = runLogResponse(1, "existing log\n");
    mockFetch(runLogResponse(2, "new log\n"));
    const runs = useRunsStore();
    runs.runLogs = { 1: existingLog };

    await runs.loadRunLog(2);

    expect(runs.runLogs[1]).toEqual(existingLog);
    expect(runs.runLogs[2]?.content).toBe("new log\n");
  });

  it("surfaces run detail error and clears loading state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "run not found" }, 404)));
    const runs = useRunsStore();

    await expect(runs.loadRunDetail(99)).rejects.toMatchObject({
      message: "run not found",
    });

    expect(runs.error).toBe("run not found");
    expect(runs.loading).toBe(false);
  });

  it("loads multiple runs and stores them in order", async () => {
    const run1 = runSummary({ id: 10 });
    const run2 = runSummary({ id: 11 });
    mockFetch([run2, run1]);
    const runs = useRunsStore();

    await runs.loadRuns();

    expect(runs.runs).toHaveLength(2);
    expect(runs.runs[0]?.id).toBe(11);
    expect(runs.runs[1]?.id).toBe(10);
    expect(runs.loading).toBe(false);
    expect(runs.error).toBe("");
  });
});

describe("settings store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads snoozes and sets the state filter", async () => {
    const activeSnooze = snooze({ service_key: "media/app", active: true });
    mockFetch([activeSnooze]);
    const settings = useSettingsStore();

    await settings.loadSnoozes("active");

    expect(settings.snoozes).toHaveLength(1);
    expect(settings.snoozes[0]?.service_key).toBe("media/app");
    expect(settings.snoozeStateFilter).toBe("active");
    expect(settings.loading).toBe(false);
  });

  it("loads expired snoozes and updates the state filter", async () => {
    const expiredSnooze = snooze({ service_key: "media/db", active: false });
    mockFetch([expiredSnooze]);
    const settings = useSettingsStore();
    settings.snoozeStateFilter = "active";

    await settings.loadSnoozes("expired");

    expect(settings.snoozeStateFilter).toBe("expired");
    expect(settings.snoozes[0]?.service_key).toBe("media/db");
  });

  it("loads tag exclusions and sets the status filter", async () => {
    const activeExclusion = tagExclusion({ tag: "2.0", status: "active" });
    mockFetch([activeExclusion]);
    const settings = useSettingsStore();

    await settings.loadTagExclusions("active");

    expect(settings.tagExclusions).toHaveLength(1);
    expect(settings.tagExclusions[0]?.tag).toBe("2.0");
    expect(settings.tagExclusionStatusFilter).toBe("active");
    expect(settings.loading).toBe(false);
  });

  it("loads disabled tag exclusions and updates the status filter", async () => {
    const disabledExclusion = tagExclusion({ tag: "3.0", status: "disabled" });
    mockFetch([disabledExclusion]);
    const settings = useSettingsStore();
    settings.tagExclusionStatusFilter = "active";

    await settings.loadTagExclusions("disabled");

    expect(settings.tagExclusionStatusFilter).toBe("disabled");
    expect(settings.tagExclusions[0]?.tag).toBe("3.0");
  });

  it("creates a snooze via mutateAndReload using stateOperation then reload", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    const createdSnooze = snooze({ service_key: "media/radarr" });
    vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "snoozes").mockResolvedValue([createdSnooze]);
    const settings = useSettingsStore();

    await settings.createSnooze("media/radarr", "2026-07-01T00:00:00Z", "maintenance", "active");

    expect(settings.snoozes).toHaveLength(1);
    expect(settings.snoozes[0]?.service_key).toBe("media/radarr");
    expect(settings.snoozeStateFilter).toBe("active");
    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("");
  });

  it("deletes a snooze via mutateAndReload and reloads with the current filter", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse({
      operation: "delete_snooze",
      resource_type: "snooze",
    }));
    vi.spyOn(webApi, "snoozes").mockResolvedValue([]);
    const settings = useSettingsStore();
    settings.snoozes = [snooze({ id: 10, service_key: "media/app" })];

    await settings.deleteSnooze(10, "active");

    expect(settings.snoozes).toHaveLength(0);
    expect(settings.snoozeStateFilter).toBe("active");
  });

  it("passes the stateOperation kind for snooze deletion", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    const stateOperation = vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "snoozes").mockResolvedValue([]);

    const settings = useSettingsStore();
    await settings.deleteSnooze(5, "expired");

    expect(stateOperation).toHaveBeenCalledWith(
      { kind: "delete_snooze", snooze_id: 5 },
      expect.any(String),
    );
    expect(settings.snoozeStateFilter).toBe("expired");
  });

  it("upserts a tag exclusion and reloads with the status filter", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-tag");
    const newExclusion = tagExclusion({ image_repo: "repo/app", tag: "2.0", status: "active" });
    vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "tagExclusions").mockResolvedValue([newExclusion]);
    const settings = useSettingsStore();

    await settings.upsertTagExclusion(
      "image_repo", "repo/app", "", "2.0", "active", "active",
    );

    expect(settings.tagExclusions).toHaveLength(1);
    expect(settings.tagExclusions[0]?.tag).toBe("2.0");
    expect(settings.tagExclusionStatusFilter).toBe("active");
    expect(settings.loading).toBe(false);
  });

  it("passes the correct stateOperation payload for upsert tag exclusion", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-tag");
    const stateOperation = vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "tagExclusions").mockResolvedValue([]);

    const settings = useSettingsStore();
    await settings.upsertTagExclusion(
      "service", "repo/app", "media/app", "3.0", "disabled", "all",
    );

    expect(stateOperation).toHaveBeenCalledWith(
      {
        kind: "upsert_tag_exclusion",
        scope: "service",
        image_repo: "repo/app",
        service_key: "media/app",
        match_type: "exact",
        tag: "3.0",
        status: "disabled",
      },
      expect.any(String),
    );
    expect(settings.tagExclusionStatusFilter).toBe("all");
  });

  it("sets tag exclusion status and reloads with the status filter", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-tag");
    const disabledExclusion = tagExclusion({ id: 7, tag: "1.0", status: "disabled" });
    vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "tagExclusions").mockResolvedValue([disabledExclusion]);
    const settings = useSettingsStore();

    await settings.setTagExclusionStatus(7, "disabled", "disabled");

    expect(settings.tagExclusions).toHaveLength(1);
    expect(settings.tagExclusions[0]?.status).toBe("disabled");
    expect(settings.tagExclusionStatusFilter).toBe("disabled");
  });

  it("surfaces settings snooze creation failure without reloading snoozes", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    vi.spyOn(webApi, "stateOperation").mockRejectedValue(new Error("write failed"));
    const loadSnoozes = vi.spyOn(webApi, "snoozes").mockResolvedValue([]);
    const settings = useSettingsStore();

    await expect(
      settings.createSnooze("media/app", "2026-07-01T00:00:00Z", "test", "active"),
    ).rejects.toThrow("write failed");

    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("write failed");
    expect(loadSnoozes).not.toHaveBeenCalled();
  });

  it("keeps loading during mutateAndReload through stateOperation and the reload", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
    const stateOp = deferred<ReturnType<typeof stateOperationResponse>>();
    const reloadedTagExclusions = deferred<ReturnType<typeof tagExclusion>[]>();
    vi.spyOn(webApi, "stateOperation").mockReturnValue(stateOp.promise);
    vi.spyOn(webApi, "tagExclusions").mockReturnValue(reloadedTagExclusions.promise);
    const settings = useSettingsStore();

    const mutation = settings.setTagExclusionStatus(1, "disabled", "disabled");
    await flushPromises();

    expect(settings.loading).toBe(true);

    stateOp.resolve(stateOperationResponse());
    await flushPromises();

    expect(settings.loading).toBe(true);

    reloadedTagExclusions.resolve([tagExclusion({ status: "disabled" })]);
    await mutation;

    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("");
    expect(settings.tagExclusions[0]?.status).toBe("disabled");
  });

  it("passes correct snooze creation payload to stateOperation", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    const stateOperation = vi.spyOn(webApi, "stateOperation").mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "snoozes").mockResolvedValue([]);

    const settings = useSettingsStore();
    await settings.createSnooze("media/db", "2026-06-30T12:00:00Z", "planned work", "active");

    expect(stateOperation).toHaveBeenCalledWith(
      {
        kind: "create_snooze",
        service_key: "media/db",
        snoozed_until: "2026-06-30T12:00:00Z",
        reason: "planned work",
      },
      expect.any(String),
    );
  });
});
