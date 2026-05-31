import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../src/stores/auth";
import {
  APPLY_JOB_RECOVERY_MESSAGE,
  useWebuiStore,
} from "../src/stores/webui";
import {
  applyJobLogResponse,
  applyJobResponse,
  doctorResponse,
  pendingResponse,
  releaseNotesResponse,
  planResponse,
  settingsResponse,
  statusResponse,
  stateOperationResponse,
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

describe("webui store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("passes csrf from auth store to plan creation", async () => {
    const fetchMock = mockFetch(planResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
    const webui = useWebuiStore();

    await webui.createPlan([1], true, [{ line_no: 1, tag: "1.1" }]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.plan?.plan_id).toBe("plan-test");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-plan");
  });

  it("passes csrf from auth store to doctor checks", async () => {
    const fetchMock = mockFetch(doctorResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-doctor");
    const webui = useWebuiStore();

    await webui.loadDoctor();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.doctor?.failures).toBe(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/doctor");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-doctor");
  });

  it("passes csrf from auth store to pending cleanup", async () => {
    const fetchMock = mockFetch({
      status: "success",
      audit_run_id: 12,
      removed_count: 1,
      removed: [
        {
          line_no: 3,
          raw: "repo/old:latest",
          image: "repo/old:latest",
          reason: "unmatched",
        },
      ],
    });
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-cleanup");
    const webui = useWebuiStore();

    await webui.cleanupPending("cleanup-test", [
      { line_no: 3, raw: "repo/old:latest" },
    ]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.pendingCleanup?.audit_run_id).toBe(12);
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      cleanup_id: "cleanup-test",
      lines: [{ line_no: 3, raw: "repo/old:latest" }],
      confirmation: "remove_unmatched",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-cleanup");
  });

  it("preserves cleanup success while refreshing pending state when requested", async () => {
    mockFetch(pendingResponse());
    const webui = useWebuiStore();
    webui.pendingCleanup = {
      status: "success",
      audit_run_id: 12,
      removed_count: 1,
      removed: [
        {
          line_no: 3,
          raw: "repo/old:latest",
          image: "repo/old:latest",
          reason: "unmatched",
        },
      ],
    };

    await webui.loadPending({ preserveCleanup: true });

    expect(webui.pendingCleanup?.audit_run_id).toBe(12);

    await webui.loadPending();

    expect(webui.pendingCleanup).toBeNull();
  });

  it("passes csrf from auth store to state operations", async () => {
    const fetchMock = mockFetch(stateOperationResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
    const webui = useWebuiStore();

    await webui.stateOperation({
      kind: "delete_service_policy",
      service_key: "media/app",
    });

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      kind: "delete_service_policy",
      service_key: "media/app",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-state");
  });

  it("passes csrf from auth store to release-note refresh", async () => {
    const fetchMock = mockFetch(releaseNotesResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-notes");
    const webui = useWebuiStore();

    await webui.refreshReleaseNotes();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.releaseNotes?.items[0].release_tag).toBe("v2.0.0");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/release-notes/refresh");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-notes");
  });

  it("clears stale errors and loading state on successful loads", async () => {
    mockFetch([]);
    const webui = useWebuiStore();
    webui.setError("old failure");

    await webui.loadRuns();

    expect(webui.error).toBe("");
    expect(webui.loading).toBe(false);
    expect(webui.runs).toEqual([]);
  });

  it("loads status for shell metadata", async () => {
    const fetchMock = mockFetch(statusResponse({ version: "0.24.2" }));
    const webui = useWebuiStore();

    await webui.loadStatus();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/status");
    expect(webui.status?.version).toBe("0.24.2");
  });

  it("loads read-only settings", async () => {
    const fetchMock = mockFetch(settingsResponse());
    const webui = useWebuiStore();

    await webui.loadSettings();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/settings");
    expect(webui.settings?.updater[0]?.name).toBe("DOCKER_BASE");
    expect(webui.settings?.secrets[1]?.configured).toBe(true);
  });

  it("surfaces backend errors and always clears loading state", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "db missing" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    const webui = useWebuiStore();

    await expect(webui.loadRuns()).rejects.toMatchObject({ message: "db missing" });

    expect(webui.error).toBe("db missing");
    expect(webui.loading).toBe(false);
  });

  it("remembers active apply jobs and clears terminal jobs", async () => {
    mockFetch(applyJobResponse({ job_id: "job-active", status: "running" }));
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-job");
    const webui = useWebuiStore();

    await webui.createJob("plan-test", [1], false, []);

    expect(webui.rememberedApplyJobId).toBe("job-active");
    expect(window.sessionStorage.getItem("applyJobId")).toBe("job-active");

    webui.setApplyJobLog(applyJobLogResponse({ job_id: "job-active" }));
    expect(webui.applyJobLog?.content).toContain("docker-update-from-wud-v2");

    webui.setApplyJob(applyJobResponse({ job_id: "job-active", status: "success" }));

    expect(webui.rememberedApplyJobId).toBe("");
    expect(window.sessionStorage.getItem("applyJobId")).toBeNull();
  });

  it("loads a terminal apply job log from the persisted run log", async () => {
    const fetchMock = mockFetch({
      run_id: 10,
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "fallback run log\n",
      truncated: false,
      max_bytes: 65_536,
    });
    const webui = useWebuiStore();

    const log = await webui.loadApplyJobLogFromRun(
      applyJobResponse({
        job_id: "job-terminal",
        run_id: 10,
        log_file: "/out/logs/job-terminal.log",
      }),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/10/log?tail_bytes=65536",
      expect.any(Object),
    );
    expect(log).toEqual({
      job_id: "job-terminal",
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "fallback run log\n",
      truncated: false,
      max_bytes: 65_536,
      error: "",
    });
    expect(webui.applyJobLog?.content).toBe("fallback run log\n");
  });

  it("marks recovery when a remembered apply job is missing", async () => {
    window.sessionStorage.setItem("applyJobId", "job-lost");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "apply job not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);
    const webui = useWebuiStore();

    const job = await webui.loadApplyJob("job-lost", { recoverMissing: true });

    expect(job).toBeNull();
    expect(webui.applyJob).toBeNull();
    expect(webui.applyJobLog).toBeNull();
    expect(webui.applyJobRecovery).toBe(APPLY_JOB_RECOVERY_MESSAGE);
    expect(webui.rememberedApplyJobId).toBe("");
    expect(webui.error).toBe("");
    expect(window.sessionStorage.getItem("applyJobId")).toBeNull();
  });
});
