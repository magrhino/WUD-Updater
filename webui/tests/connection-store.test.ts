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

describe("connection store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("passes csrf from auth store to doctor checks", async () => {
    const fetchMock = mockFetch(doctorResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-doctor");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await connection.loadDoctor();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(connection.doctor?.failures).toBe(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/doctor");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-doctor");
  });

  it("passes csrf from auth store to container restart", async () => {
    const fetchMock = mockFetch({
      status: "scheduled",
      audit_run_id: 42,
      container: "wud-updater",
    });
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-restart");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    const response = await connection.restartContainer();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.container).toBe("wud-updater");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/container/restart");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      confirmation: "restart_container",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-restart");
  });

  it("loads status for shell metadata", async () => {
    const fetchMock = mockFetch(statusResponse({ version: "0.24.2" }));
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await connection.loadStatus();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/status");
    expect(connection.status?.version).toBe("0.24.2");
  });

  it("extracts error messages without accepting plain objects", () => {
    expect(errorMessage(new Error("plain error"))).toBe("plain error");
    expect(errorMessage("string error")).toBe("Request failed");
    expect(errorMessage({ message: "object message" })).toBe("Request failed");
  });

  it("loads diagnostics support bundle without csrf", async () => {
    const bundlePayload = {
      wud_updater_version: "0.24.2",
      settings: settingsResponse(),
      doctor_result: doctorResponse(),
      pending_summary: pendingResponse(),
      last_run_status: null,
      diagnostics_warnings: [],
      discovery_warnings: [],
      log_tail: null,
    };
    const fetchMock = mockFetch(bundlePayload);
    const connection = useConnectionStore();

    const response = await connection.diagnosticsSupportBundle();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/diagnostics/support-bundle");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBeUndefined();
    expect(response.wud_updater_version).toBe("0.24.2");
    expect(connection.loading).toBe(false);
    expect(connection.error).toBe("");
  });

  it("surfaces diagnostics support bundle errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "bundle unavailable" }, 503)),
    );
    const connection = useConnectionStore();

    await expect(connection.diagnosticsSupportBundle()).rejects.toMatchObject({
      message: "bundle unavailable",
    });

    expect(connection.error).toBe("bundle unavailable");
    expect(connection.loading).toBe(false);
  });

  it("sets connection errors through the store action", () => {
    const connection = useConnectionStore();

    connection.setError("manual connection error");

    expect(connection.error).toBe("manual connection error");
    expect(connection.loading).toBe(false);
  });
});
