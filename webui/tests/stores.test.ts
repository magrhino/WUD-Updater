import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi } from "../src/api/client";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
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

describe("settings store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("passes csrf from auth store to plan creation", async () => {
    const fetchMock = mockFetch(planResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.createPlan([1], true, [{ line_no: 1, tag: "1.1" }]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.plan?.plan_id).toBe("plan-test");
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await settings.loadOnboarding();
    await settings.dismissOnboarding();

    expect(ensureCsrf).toHaveBeenCalledTimes(2);
    expect(settings.onboarding?.visible).toBe(false);
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await settings.loadCoreUpdateTour();
    await settings.updateCoreUpdateTour("in_progress", "pending_select");

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(settings.coreUpdateTour?.status).toBe("in_progress");
    expect(settings.coreUpdateTour?.step).toBe("pending_select");
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.cleanupPending("cleanup-test", [
      { line_no: 3, raw: "repo/old:latest" },
    ]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.pendingCleanup?.audit_run_id).toBe(12);
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.pendingCleanup = {
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

    await updates.loadPending({ preserveCleanup: true });

    expect(updates.pendingCleanup?.audit_run_id).toBe(12);

    await updates.loadPending();

    expect(updates.pendingCleanup).toBeNull();
  });

  it("loads update targets for management selectors", async () => {
    const fetchMock = mockFetch(updateTargetsResponse());
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.loadUpdateTargets();

    expect((connection as any).updateTargets?.items[0]?.service_key || (updates as any).updateTargets?.items[0]?.service_key || (runs as any).updateTargets?.items[0]?.service_key || (settings as any).updateTargets?.items[0]?.service_key).toBe("media/app");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/update-targets");
  });

  it("keeps fulfilled pending safety cue data when another cue source fails", async () => {
    const existingPolicy = servicePolicy({ service_key: "media/app" });
    const loadedSnooze = snooze({ service_key: "media/radarr" });
    vi.spyOn(webApi, "servicePolicies").mockRejectedValue(
      new Error("service policies unavailable"),
    );
    vi.spyOn(webApi, "snoozes").mockResolvedValue([loadedSnooze]);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.servicePolicies = [existingPolicy];

    await settings.loadPendingSafetyCues();

    expect(settings.servicePolicies).toEqual([existingPolicy]);
    expect(settings.snoozes).toEqual([loadedSnooze]);
  });

  it("passes csrf from auth store to state operations", async () => {
    const fetchMock = mockFetch(stateOperationResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await connection.stateOperation({
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

  it("passes csrf from auth store to release-note refresh", async () => {
    const fetchMock = mockFetch(releaseNotesResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-notes");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.refreshReleaseNotes();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.releaseNotes?.items[0].release_tag).toBe("v2.0.0");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/release-notes/refresh");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-notes");
  });

  it("clears stale errors and loading state on successful loads", async () => {
    mockFetch([]);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.error = ("old failure");

    await runs.loadRuns();

    expect(runs.error).toBe("");
    expect(updates.loading).toBe(false);
    expect(runs.runs).toEqual([]);
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

  it("loads self-update status for the shell banner", async () => {
    const fetchMock = mockFetch(selfUpdateResponse());
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.loadSelfUpdate();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update");
    expect((connection as any).selfUpdate?.latest_tag || (updates as any).selfUpdate?.latest_tag || (runs as any).selfUpdate?.latest_tag || (settings as any).selfUpdate?.latest_tag).toBe("v0.25.0");
  });

  it("loads self-update tag prepare plan", async () => {
    const fetchMock = mockFetch(selfUpdatePlanResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    const response = await updates.planSelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update/plan");
    expect((connection as any).selfUpdatePlan?.plan.plan_id || (updates as any).selfUpdatePlan?.plan.plan_id || (runs as any).selfUpdatePlan?.plan.plan_id || (settings as any).selfUpdatePlan?.plan.plan_id).toBe("self-update-plan-test");
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.selfUpdate = selfUpdateResponse();

    const response = await updates.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.container).toBe("wud-updater");
    expect((connection as any).selfUpdateMessage || (updates as any).selfUpdateMessage || (runs as any).selfUpdateMessage || (settings as any).selfUpdateMessage).toBe(
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });
    updates.selfUpdatePlan = selfUpdatePlanResponse();

    const response = await updates.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.status).toBe("tag_prepared");
    expect((connection as any).selfUpdateMessage || (updates as any).selfUpdateMessage || (runs as any).selfUpdateMessage || (settings as any).selfUpdateMessage).toBe(
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      external_recreate_required: true,
    });

    await expect(updates.applySelfUpdate()).rejects.toThrow(
      "Self-update tag update preview must be loaded before applying",
    );

    expect(ensureCsrf).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect((connection as any).selfUpdateError || (updates as any).selfUpdateError || (runs as any).selfUpdateError || (settings as any).selfUpdateError).toBe(
      "Self-update tag update preview must be loaded before applying",
    );
  });

  it("loads read-only settings", async () => {
    const fetchMock = mockFetch(settingsResponse());
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await settings.loadSettings();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/settings");
    expect((connection as any).settings?.updater[0]?.name || (updates as any).settings?.updater[0]?.name || (runs as any).settings?.updater[0]?.name || (settings as any).settings?.updater[0]?.name).toBe("DOCKER_BASE");
    expect((connection as any).settings?.secrets[1]?.configured || (updates as any).settings?.secrets[1]?.configured || (runs as any).settings?.secrets[1]?.configured || (settings as any).settings?.secrets[1]?.configured).toBe(true);
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.settings = settingsResponse();

    const response = await settings.updateManagedSettings({
      theme_preference: "dark",
    });

    expect(response.audit_run_id).toBe(44);
    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect((connection as any).settings?.managed[0]?.value || (updates as any).settings?.managed[0]?.value || (runs as any).settings?.managed[0]?.value || (settings as any).settings?.managed[0]?.value).toBe("dark");
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.settings = settingsResponse();
    settings.onboarding = onboardingChecklistResponse({ visible: true });

    const response = await settings.updateManagedSettings({
      onboarding_checklist: "dismissed",
    });

    expect(response.audit_run_id).toBe(45);
    expect((connection as any).settings?.managed[1]?.value || (updates as any).settings?.managed[1]?.value || (runs as any).settings?.managed[1]?.value || (settings as any).settings?.managed[1]?.value).toBe("dismissed");
    expect(settings.onboarding?.visible).toBe(true);
    expect(runs.error).toBe("");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/settings/managed",
      "/api/v1/onboarding/checklist",
    ]);
  });

  it("surfaces backend errors and always clears loading state", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "db missing" }, 503));
    vi.stubGlobal("fetch", fetchMock);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await expect(runs.loadRuns()).rejects.toMatchObject({ message: "db missing" });

    expect(runs.error).toBe("db missing");
    expect(updates.loading).toBe(false);
  });

  it("remembers active apply jobs and clears terminal jobs", async () => {
    mockFetch(applyJobResponse({ job_id: "job-active", status: "running" }));
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-job");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.createJob("plan-test", [1], false, []);

    expect(updates.rememberedApplyJobId).toBe("job-active");
    expect(window.sessionStorage.getItem("applyJobId")).toBe("job-active");

    updates.setApplyJobLog(applyJobLogResponse({ job_id: "job-active" }));
    expect(updates.applyJobLog?.content).toContain("docker-update-from-wud-v2");

    updates.setApplyJob(applyJobResponse({ job_id: "job-active", status: "success" }));

    expect(updates.rememberedApplyJobId).toBe("");
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
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    const log = await updates.loadApplyJobLogFromRun(
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
    expect(updates.applyJobLog?.content).toBe("fallback run log\n");
  });

  it("marks recovery when a remembered apply job is missing", async () => {
    window.sessionStorage.setItem("applyJobId", "job-lost");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "apply job not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    const job = await updates.loadApplyJob("job-lost", { recoverMissing: true });

    expect(job).toBeNull();
    expect(updates.applyJob).toBeNull();
    expect(updates.applyJobLog).toBeNull();
    expect(updates.applyJobRecovery).toBe(APPLY_JOB_RECOVERY_MESSAGE);
    expect(updates.rememberedApplyJobId).toBe("");
    expect(runs.error).toBe("");
    expect(window.sessionStorage.getItem("applyJobId")).toBeNull();
  });
});
