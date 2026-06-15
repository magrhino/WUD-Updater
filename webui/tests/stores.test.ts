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

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
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

    expect(updates.updateTargets?.items[0]?.service_key).toBe("media/app");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/update-targets");
  });

  it("loads retag targets for read-only review", async () => {
    const fetchMock = mockFetch(retagTargetsResponse());
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await updates.loadRetagTargets();

    expect(updates.retagTargets?.items[0]?.service_key).toBe("media/app");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-targets");
  });

  it("previews retag choices through the updates store", async () => {
    const fetchMock = mockFetch(retagPlanResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget(),
      retagTarget({ service_key: "media/radarr", service: "radarr" }),
    ]);
    updates.setRetagChoice("media/app", "switch-to-concrete");

    const plan = await updates.createRetagPlan();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(plan.plan_id).toBe("retag-plan-test");
    expect(updates.retagPlan?.selected_count).toBe(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-plans");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      choices: [
        { service_key: "media/app", choice: "switch-to-concrete" },
        { service_key: "media/radarr", choice: "keep-current" },
      ],
    });
  });

  it("applies a retag plan as a tracked apply job", async () => {
    const fetchMock = mockFetch(applyJobResponse({ job_id: "retag-job" }));
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    updates.retagTargets = retagTargetsResponse();
    updates.retagChoices = { "media/app": "switch-to-concrete" };
    updates.retagPlan = retagPlanResponse();

    const job = await updates.applyRetagPlan();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(job.job_id).toBe("retag-job");
    expect(updates.applyJob?.job_id).toBe("retag-job");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-plans/apply");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      plan_id: "retag-plan-test",
      choices: [{ service_key: "media/app", choice: "switch-to-concrete" }],
      confirmation: "apply-retags",
    });
  });

  it("surfaces retag target loading errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "retag targets unavailable" }, 503));
    vi.stubGlobal("fetch", fetchMock);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    await expect(updates.loadRetagTargets()).rejects.toThrow(
      "retag targets unavailable",
    );

    expect(updates.error).toBe("retag targets unavailable");
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
    settings.error = "old failure";

    await settings.loadPendingSafetyCues();

    expect(settings.servicePolicies).toEqual([existingPolicy]);
    expect(settings.snoozes).toEqual([loadedSnooze]);
    expect(settings.error).toBe("old failure");
    expect(settings.pendingSafetyCueError).toBe(
      "webApi.servicePolicies() failed: service policies unavailable",
    );
  });

  it("clears only pending safety cue errors after successful loads", async () => {
    const loadedPolicy = servicePolicy({ service_key: "media/app" });
    const loadedSnooze = snooze({ service_key: "media/radarr" });
    vi.spyOn(webApi, "servicePolicies").mockResolvedValue([loadedPolicy]);
    vi.spyOn(webApi, "snoozes").mockResolvedValue([loadedSnooze]);
        const connection = useConnectionStore();
    const settings = useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();
    settings.error = "old failure";
    settings.pendingSafetyCueError = "old safety cue failure";

    await settings.loadPendingSafetyCues();

    expect(settings.servicePolicies).toEqual([loadedPolicy]);
    expect(settings.snoozes).toEqual([loadedSnooze]);
    expect(settings.error).toBe("old failure");
    expect(settings.pendingSafetyCueError).toBe("");
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

  it("keeps settings loading through policy mutation and reload", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
    const stateOperation = deferred<ReturnType<typeof stateOperationResponse>>();
    const reloadedPolicies = [
      servicePolicy({ service_key: "media/updated", update_mode: "live" }),
    ];
    const servicePolicies = deferred<typeof reloadedPolicies>();
    const stateOperationSpy = vi
      .spyOn(webApi, "stateOperation")
      .mockReturnValue(stateOperation.promise);
    const loadServicePolicies = vi
      .spyOn(webApi, "servicePolicies")
      .mockReturnValue(servicePolicies.promise);
    const connection = useConnectionStore();
    const settings = useSettingsStore();

    const mutation = settings.upsertServicePolicy(
      "media/app",
      "live",
      true,
      null,
      "09:30",
      ["mon"],
    );
    await flushPromises();

    expect(settings.loading).toBe(true);
    expect(connection.loading).toBe(false);
    expect(settings.error).toBe("");
    expect(loadServicePolicies).not.toHaveBeenCalled();
    expect(stateOperationSpy).toHaveBeenCalledWith(
      {
        kind: "upsert_service_policy",
        service_key: "media/app",
        update_mode: "live",
        auto_update: true,
        snooze_default_seconds: null,
        auto_update_time: "09:30",
        auto_update_days: ["mon"],
      },
      "csrf-state",
    );

    stateOperation.resolve(stateOperationResponse());
    await flushPromises();

    expect(settings.loading).toBe(true);
    expect(connection.loading).toBe(false);
    expect(loadServicePolicies).toHaveBeenCalledTimes(1);

    servicePolicies.resolve(reloadedPolicies);
    await mutation;

    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("");
    expect(settings.servicePolicies).toEqual(reloadedPolicies);
  });

  it("surfaces settings mutation failures without refreshing state", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
    vi.spyOn(webApi, "stateOperation").mockRejectedValue(
      new Error("state write failed"),
    );
    const loadServicePolicies = vi
      .spyOn(webApi, "servicePolicies")
      .mockResolvedValue([servicePolicy()]);
    const settings = useSettingsStore();

    await expect(settings.deleteServicePolicy("media/app")).rejects.toThrow(
      "state write failed",
    );

    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("state write failed");
    expect(loadServicePolicies).not.toHaveBeenCalled();
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
    runs.error = "old failure";
    runs.loading = true;

    await runs.loadRuns();

    expect(runs.error).toBe("");
    expect(runs.loading).toBe(false);
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
    expect(updates.selfUpdate?.latest_tag).toBe("v0.25.0");
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
    expect(updates.selfUpdatePlan?.plan.plan_id).toBe("self-update-plan-test");
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
    expect(updates.selfUpdateMessage).toBe(
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
    expect(updates.selfUpdateMessage).toBe(
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
    expect(updates.selfUpdateError).toBe(
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
    expect(settings.settings?.updater[0]?.name).toBe("DOCKER_BASE");
    expect(settings.settings?.secrets[1]?.configured).toBe(true);
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
    expect(settings.settings?.managed[0]?.value).toBe("dark");
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
    expect(settings.settings?.managed[1]?.value).toBe("dismissed");
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
    expect(runs.loading).toBe(false);
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

  it("applies plans through the plan apply endpoint", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan-apply");
    const applyPlan = vi
      .spyOn(webApi, "applyPlan")
      .mockResolvedValue(applyJobResponse({ job_id: "job-plan", status: "running" }));
    const createJob = vi
      .spyOn(webApi, "createJob")
      .mockRejectedValue(new Error("wrong endpoint"));
    const updates = useUpdatesStore();

    const job = await updates.applyPlan("plan-test", [1], false, [], []);

    expect(applyPlan).toHaveBeenCalledWith(
      "plan-test",
      [1],
      false,
      [],
      [],
      "csrf-plan-apply",
    );
    expect(createJob).not.toHaveBeenCalled();
    expect(job.job_id).toBe("job-plan");
    expect(updates.applyJob?.job_id).toBe("job-plan");
    expect(updates.rememberedApplyJobId).toBe("job-plan");
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

describe("connection store focused coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
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

describe("runs store focused coverage", () => {
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

describe("settings store management coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads service policies, snoozes, and tag exclusions with their filters", async () => {
    vi.spyOn(webApi, "servicePolicies").mockResolvedValue([
      servicePolicy({ service_key: "media/app" }),
    ]);
    vi.spyOn(webApi, "snoozes").mockResolvedValue([
      snooze({ service_key: "media/radarr", active: false }),
    ]);
    vi.spyOn(webApi, "tagExclusions").mockResolvedValue([
      tagExclusion({ tag: "2.0", status: "disabled" }),
    ]);
    const settings = useSettingsStore();

    await settings.loadServicePolicies();
    await settings.loadSnoozes("expired");
    await settings.loadTagExclusions("disabled");

    expect(settings.servicePolicies[0]?.service_key).toBe("media/app");
    expect(settings.snoozes[0]?.service_key).toBe("media/radarr");
    expect(settings.snoozeStateFilter).toBe("expired");
    expect(settings.tagExclusions[0]?.tag).toBe("2.0");
    expect(settings.tagExclusionStatusFilter).toBe("disabled");
    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("");
  });

  it("creates snoozes through state operations and reloads the selected filter", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    const stateOperation = vi
      .spyOn(webApi, "stateOperation")
      .mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "snoozes").mockResolvedValue([
      snooze({ service_key: "media/radarr" }),
    ]);
    const settings = useSettingsStore();

    await settings.createSnooze(
      "media/radarr",
      "2026-06-01T00:00:00+00:00",
      "maintenance",
      "active",
    );

    expect(stateOperation).toHaveBeenCalledWith(
      {
        kind: "create_snooze",
        service_key: "media/radarr",
        snoozed_until: "2026-06-01T00:00:00+00:00",
        reason: "maintenance",
      },
      "csrf-snooze",
    );
    expect(webApi.snoozes).toHaveBeenCalledWith("active");
    expect(settings.snoozes[0]?.service_key).toBe("media/radarr");
    expect(settings.error).toBe("");
  });

  it("updates tag exclusions through state operations and reloads the selected filter", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-tag");
    const stateOperation = vi
      .spyOn(webApi, "stateOperation")
      .mockResolvedValue(stateOperationResponse());
    vi.spyOn(webApi, "tagExclusions").mockResolvedValue([
      tagExclusion({ scope: "service", service_key: "media/app", tag: "3.0" }),
    ]);
    const settings = useSettingsStore();

    await settings.upsertTagExclusion(
      "service",
      "repo/app",
      "media/app",
      "3.0",
      "disabled",
      "all",
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
      "csrf-tag",
    );
    expect(webApi.tagExclusions).toHaveBeenCalledWith("all");
    expect(settings.tagExclusionStatusFilter).toBe("all");
    expect(settings.tagExclusions[0]?.tag).toBe("3.0");
  });

  it("keeps loading active through tag-exclusion reloads", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-state");
    const stateOperation = deferred<ReturnType<typeof stateOperationResponse>>();
    const reloadedExclusions = deferred<ReturnType<typeof tagExclusion>[]>();
    vi.spyOn(webApi, "stateOperation").mockReturnValue(stateOperation.promise);
    vi.spyOn(webApi, "tagExclusions").mockReturnValue(reloadedExclusions.promise);
    const settings = useSettingsStore();

    const mutation = settings.setTagExclusionStatus(1, "disabled", "disabled");
    await flushPromises();

    expect(settings.loading).toBe(true);

    stateOperation.resolve(stateOperationResponse());
    await flushPromises();

    expect(settings.loading).toBe(true);

    reloadedExclusions.resolve([tagExclusion({ status: "disabled" })]);
    await mutation;

    expect(settings.loading).toBe(false);
    expect(settings.error).toBe("");
    expect(settings.tagExclusions[0]?.status).toBe("disabled");
  });

  it("does not reload snoozes after state operation failures", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-snooze");
    vi.spyOn(webApi, "stateOperation").mockRejectedValue(
      new Error("snooze write failed"),
    );
    const loadSnoozes = vi.spyOn(webApi, "snoozes").mockResolvedValue([]);
    const settings = useSettingsStore();

    await expect(settings.deleteSnooze(99, "active")).rejects.toThrow(
      "snooze write failed",
    );

    expect(settings.error).toBe("snooze write failed");
    expect(settings.loading).toBe(false);
    expect(loadSnoozes).not.toHaveBeenCalled();
  });
});

describe("updates store focused coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads release notes with independent loading state", async () => {
    const fetchMock = mockFetch(releaseNotesResponse());
    const updates = useUpdatesStore();

    await updates.loadReleaseNotes();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/release-notes");
    expect(updates.releaseNotes?.items[0]?.release_tag).toBe("v2.0.0");
    expect(updates.releaseNotesLoading).toBe(false);
    expect(updates.releaseNotesError).toBe("");
    expect(updates.loading).toBe(false);
  });

  it("surfaces release note errors without changing main loading state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "notes unavailable" }, 503)),
    );
    const updates = useUpdatesStore();

    await expect(updates.loadReleaseNotes()).rejects.toMatchObject({
      message: "notes unavailable",
    });

    expect(updates.releaseNotesError).toBe("notes unavailable");
    expect(updates.releaseNotesLoading).toBe(false);
    expect(updates.loading).toBe(false);
  });

  it("sets stream errors through the updates store action", () => {
    const updates = useUpdatesStore();

    updates.setError("Job status stream returned invalid data.");

    expect(updates.error).toBe("Job status stream returned invalid data.");
  });
});
