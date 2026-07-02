import { describe, expect, it } from "vitest";

import { createDemoWebApi } from "../src/api/demo";
import { generatedFixtures } from "../src/api/demo/generatedFixtures";

const READ_ONLY_MESSAGE =
  "The public static demo is read-only. Run WUDup locally to apply changes.";

describe("demo web API", () => {
  it("serves read-only sanitized fixture state", async () => {
    const api = createDemoWebApi();

    await expect(api.session()).resolves.toMatchObject({
      authenticated: true,
      auth_required: false,
      dev_auth_bypass: false,
      mutations_enabled: false,
    });
    await expect(api.status()).resolves.toMatchObject({
      wud_file: "demo/out/images.todo",
      db_path: "demo/logs/wudup.sqlite",
      pending_count: 7,
      dev_auth_bypass: false,
      mutations_enabled: false,
      auto_update_scheduler_enabled: false,
    });
    await expect(api.settings()).resolves.toMatchObject({
      updater: expect.arrayContaining([
        expect.objectContaining({ name: "DOCKER_BASE", value: "demo/docker" }),
      ]),
      webui: expect.arrayContaining([
        expect.objectContaining({
          name: "WUD_WEB_MUTATIONS_ENABLED",
          value: "false",
        }),
      ]),
      secrets: expect.arrayContaining([
        { name: "GITHUB_TOKEN", configured: false },
      ]),
    });

    const pending = await api.pending();
    expect(pending.count).toBe(7);
    expect(pending.source_file).toBe("demo/out/images.todo");
    expect(pending.grouping.groups.map((group) => group.name)).toEqual([
      "data",
      "home",
      "media",
    ]);
    expect(pending.grouping.unmatched.map((item) => item.line_no)).toEqual([
      6,
      7,
      8,
    ]);

    const doctor = await api.doctor("csrf");
    expect(doctor).toMatchObject({ ok: true });
    expect(doctor.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "webui-authentication",
          detail: "development auth bypass is disabled",
          status: "PASS",
          suggestions: [],
        }),
        expect.objectContaining({
          code: "webui-mutation-gate",
          detail: "browser mutations are disabled",
          status: "PASS",
          suggestions: [],
        }),
      ]),
    );
    await expect(api.diagnosticsSupportBundle()).resolves.toMatchObject({
      doctor_result: {
        checks: expect.arrayContaining([
          expect.objectContaining({
            code: "webui-mutation-gate",
            detail: "browser mutations are disabled",
            status: "PASS",
          }),
        ]),
      },
    });
    await expect(api.releaseNotes()).resolves.toMatchObject({ count: 7 });
    await expect(api.updateTargets()).resolves.toMatchObject({ count: 4 });
    await expect(api.retagTargets()).resolves.toMatchObject({ count: 4 });
    await expect(api.runs()).resolves.toEqual(
      expect.arrayContaining([expect.objectContaining({ id: 6 })]),
    );
  });

  it("previews pending plans without enabling apply", async () => {
    const api = createDemoWebApi();
    const plan = await api.createPlan([2], false, [], [], "csrf");

    expect(plan).toMatchObject({
      can_apply: false,
      status: "ready",
      selected_line_numbers: [2],
      summary: {
        target_count: 1,
        matched_target_count: 1,
        stack_count: 1,
        service_count: 1,
      },
      apply_preflight: {
        ok: false,
        failures: 1,
      },
    });
    expect(plan.apply_preflight.checks[0]).toMatchObject({
      code: "mutations-enabled",
      detail: READ_ONLY_MESSAGE,
    });
    expect(plan.stacks[0]?.lines[0]).toMatchObject({
      line_no: 2,
      service: "home-assistant",
      action: "tag-update",
    });
    await expect(api.status()).resolves.toMatchObject({ pending_count: 7 });
  });

  it("blocks static demo mutation endpoints", async () => {
    const api = createDemoWebApi();
    const update = await api.selfUpdate();
    const selfUpdatePlan = await api.planSelfUpdate("csrf");
    expect(selfUpdatePlan.plan.apply_preflight.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "mutations-enabled",
          detail: READ_ONLY_MESSAGE,
          status: "FAIL",
        }),
      ]),
    );
    const mutationExpectations = [
      api.updateManagedSettings({ theme_preference: "dark" }, "csrf"),
      api.dismissOnboarding("csrf"),
      api.updateCoreUpdateTour("completed", "runs_history", "csrf"),
      api.startRetagPreview([], "csrf"),
      api.refreshRetagGithubLatest("csrf"),
      api.createRetagPlan([], "csrf"),
      api.applyRetagPlan("demo", [], "csrf"),
      api.cleanupPending("demo", [{ line_no: 6, raw: "" }], "csrf"),
      api.createRemovalPlan([6], "csrf"),
      api.removeSelectedPending("demo", [{ line_no: 6, raw: "" }], "csrf"),
      api.previewReleaseNotifications({ line_numbers: [2] }, "csrf"),
      api.sendReleaseNotifications({ line_numbers: [2] }, "csrf"),
      api.testReleaseNotificationWebhook("csrf"),
      api.refreshSecurityScans("csrf"),
      api.applySelfUpdate("csrf", update),
      api.prepareSelfUpdate("csrf", update, selfUpdatePlan),
      api.stateOperation(
        {
          kind: "delete_service_policy",
          service_key: "media/radarr",
        },
        "csrf",
      ),
      api.restartContainer("csrf"),
      api.createJob("demo", [2], false, [], [], "csrf"),
      api.applyPlan("demo", [2], false, [], [], "csrf"),
    ];

    for (const promise of mutationExpectations) {
      await expect(promise).rejects.toThrow(READ_ONLY_MESSAGE);
    }
    await expect(api.status()).resolves.toMatchObject({ pending_count: 7 });
  });

  it("keeps static fixture catalogs empty", () => {
    expect(generatedFixtures.planCases).toEqual([]);
    expect(generatedFixtures.removalCases).toEqual([]);
    expect(generatedFixtures.retagCases).toEqual([]);
  });
});
