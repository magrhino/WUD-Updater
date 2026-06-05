import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi } from "../src/api/client";
import { useAuthStore } from "../src/stores/auth";
import {
  APPLY_JOB_RECOVERY_MESSAGE,
  useWebuiStore,
} from "../src/stores/webui";
import {
  applyJobLogResponse,
  applyJobResponse,
  coreUpdateTourResponse,
  doctorResponse,
  onboardingChecklistResponse,
  onboardingDismissResponse,
  pendingResponse,
  releaseNotesResponse,
  planResponse,
  selfUpdateApplyResponse,
  selfUpdatePlanResponse,
  selfUpdatePrepareResponse,
  selfUpdateResponse,
  settingsResponse,
  servicePolicy,
  statusResponse,
  stateOperationResponse,
  snooze,
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

  it("passes csrf from auth store to onboarding checks and dismissal", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(onboardingChecklistResponse()))
      .mockResolvedValueOnce(jsonResponse(onboardingDismissResponse()));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-onboarding");
    const webui = useWebuiStore();

    await webui.loadOnboarding();
    await webui.dismissOnboarding();

    expect(ensureCsrf).toHaveBeenCalledTimes(2);
    expect(webui.onboarding?.visible).toBe(false);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/onboarding/checklist");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/onboarding/dismiss");
    for (const call of fetchMock.mock.calls) {
      expect((call[1] as RequestInit).method).toBe("POST");
      expect(
        ((call[1] as RequestInit).headers as Headers).get("x-wud-csrf-token"),
      ).toBe("csrf-onboarding");
    }
  });

  it("loads and updates the server-managed core update tour", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(coreUpdateTourResponse()))
      .mockResolvedValueOnce(
        jsonResponse(
          coreUpdateTourResponse({
            status: "in_progress",
            step: "pending_select",
            updated_at: "2026-05-31T00:00:00+00:00",
          }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-tour");
    const webui = useWebuiStore();

    await webui.loadCoreUpdateTour();
    await webui.updateCoreUpdateTour("in_progress", "pending_select");

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.coreUpdateTour?.status).toBe("in_progress");
    expect(webui.coreUpdateTour?.step).toBe("pending_select");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/onboarding/core-update-tour",
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/onboarding/core-update-tour",
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBeUndefined();
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({
      status: "in_progress",
      step: "pending_select",
    });
    expect(
      ((fetchMock.mock.calls[1][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-tour");
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

  it("loads update targets for management selectors", async () => {
    const fetchMock = mockFetch(updateTargetsResponse());
    const webui = useWebuiStore();

    await webui.loadUpdateTargets();

    expect(webui.updateTargets?.items[0]?.service_key).toBe("media/app");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/update-targets");
  });

  it("keeps fulfilled pending safety cue data when another cue source fails", async () => {
    const existingPolicy = servicePolicy({ service_key: "media/app" });
    const loadedSnooze = snooze({ service_key: "media/radarr" });
    vi.spyOn(webApi, "servicePolicies").mockRejectedValue(
      new Error("service policies unavailable"),
    );
    vi.spyOn(webApi, "snoozes").mockResolvedValue([loadedSnooze]);
    const webui = useWebuiStore();
    webui.servicePolicies = [existingPolicy];

    await webui.loadPendingSafetyCues();

    expect(webui.servicePolicies).toEqual([existingPolicy]);
    expect(webui.snoozes).toEqual([loadedSnooze]);
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

  it("passes csrf from auth store to container restart", async () => {
    const fetchMock = mockFetch({
      status: "scheduled",
      audit_run_id: 42,
      container: "wud-updater",
    });
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-restart");
    const webui = useWebuiStore();

    const response = await webui.restartContainer();

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

  it("loads self-update status for the shell banner", async () => {
    const fetchMock = mockFetch(selfUpdateResponse());
    const webui = useWebuiStore();

    await webui.loadSelfUpdate();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update");
    expect(webui.selfUpdate?.latest_tag).toBe("v0.25.0");
  });

  it("loads self-update tag prepare plan", async () => {
    const fetchMock = mockFetch(selfUpdatePlanResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
    const webui = useWebuiStore();

    const response = await webui.planSelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update/plan");
    expect(webui.selfUpdatePlan?.plan.plan_id).toBe("self-update-plan-test");
    expect(response.external_recreate_required).toBe(true);
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-plan");
  });

  it("passes csrf from auth store to self-update apply", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(selfUpdateApplyResponse()))
      .mockResolvedValueOnce(jsonResponse(selfUpdateResponse()));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    const webui = useWebuiStore();
    webui.selfUpdate = selfUpdateResponse();

    const response = await webui.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.container).toBe("wud-updater");
    expect(webui.selfUpdateMessage).toBe(
      "Image pulled. Recreate the WUD-Updater container to run the new version. Tagged deployments are recommended for predictable updates.",
    );
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      confirmation: "pull_image",
      current_tag: "v0.24.2",
      latest_tag: "v0.25.0",
      target_image: "ghcr.io/magrhino/wud-updater:latest",
      restart_container: "wud-updater",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-self-update");
  });

  it("prepares pinned self-update tags from cached plan", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(selfUpdatePrepareResponse()))
      .mockResolvedValueOnce(jsonResponse(selfUpdateResponse({ strategy: "prepare_tag_update" })));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    const webui = useWebuiStore();
    webui.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });
    webui.selfUpdatePlan = selfUpdatePlanResponse();

    const response = await webui.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.status).toBe("tag_prepared");
    expect(webui.selfUpdateMessage).toBe(
      "Tag updated and image pulled. Recreate the WUD-Updater container from outside the WebUI to run the new version. Tagged deployments are recommended for predictable updates.",
    );
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update/prepare");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      confirmation: "prepare_tag_update",
      plan_id: "self-update-plan-test",
      current_tag: "v0.24.2",
      latest_tag: "v0.25.0",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      restart_container: "wud-updater",
    });
  });

  it("requires a loaded self-update tag prepare plan before applying", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    const webui = useWebuiStore();
    webui.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });

    await expect(webui.applySelfUpdate()).rejects.toThrow(
      "Self-update tag update preview must be loaded before applying",
    );

    expect(ensureCsrf).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(webui.selfUpdateError).toBe(
      "Self-update tag update preview must be loaded before applying",
    );
  });

  it("loads read-only settings", async () => {
    const fetchMock = mockFetch(settingsResponse());
    const webui = useWebuiStore();

    await webui.loadSettings();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/settings");
    expect(webui.settings?.updater[0]?.name).toBe("DOCKER_BASE");
    expect(webui.settings?.secrets[1]?.configured).toBe(true);
  });

  it("passes csrf from auth store to managed settings updates", async () => {
    const updatedSettings = settingsResponse({
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
        {
          key: "onboarding_checklist",
          value: "visible",
          default_value: "visible",
          source: "default",
          editable: true,
          allowed_values: ["visible", "dismissed"],
          restart_required: false,
        },
      ],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ managed: updatedSettings.managed, audit_run_id: 44 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-settings");
    const webui = useWebuiStore();
    webui.settings = settingsResponse();

    const response = await webui.updateManagedSettings({
      theme_preference: "dark",
    });

    expect(response.audit_run_id).toBe(44);
    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(webui.settings?.managed[0]?.value).toBe("dark");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/settings/managed");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-settings");
  });

  it("keeps managed settings saves successful when onboarding refresh fails", async () => {
    const updatedSettings = settingsResponse({
      managed: [
        settingsResponse().managed[0]!,
        {
          key: "onboarding_checklist",
          value: "dismissed",
          default_value: "visible",
          source: "configured",
          editable: true,
          allowed_values: ["visible", "dismissed"],
          restart_required: false,
        },
      ],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ managed: updatedSettings.managed, audit_run_id: 45 }),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "doctor unavailable" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-settings");
    const webui = useWebuiStore();
    webui.settings = settingsResponse();
    webui.onboarding = onboardingChecklistResponse({ visible: true });

    const response = await webui.updateManagedSettings({
      onboarding_checklist: "dismissed",
    });

    expect(response.audit_run_id).toBe(45);
    expect(webui.settings?.managed[1]?.value).toBe("dismissed");
    expect(webui.onboarding?.visible).toBe(true);
    expect(webui.error).toBe("");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/settings/managed",
      "/api/v1/onboarding/checklist",
    ]);
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
