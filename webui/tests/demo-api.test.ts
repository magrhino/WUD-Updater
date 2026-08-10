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
    const retagTargets = await api.retagTargets();
    expect(retagTargets).toMatchObject({ count: 4 });
    expect(retagTargets.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          service_key: "media/wudup",
          retag_available: true,
          runtime_state: "not-running",
        }),
      ]),
    );
    const securityScans = await api.securityScans();
    const findingScan = securityScans.items.find((item) => item.verdict === "findings");
    expect(findingScan).toMatchObject({
      scanner_version: "demo",
      scanner_schema: "trivy-json",
      db_revision: "demo",
      db_updated_at: "2026-05-28T12:00:00+00:00",
      comparison: { status: "unchanged" },
      findings: [
        expect.objectContaining({
          target: "debian:12",
          target_class: "os-pkgs",
          target_type: "debian",
        }),
      ],
    });
    await expect(api.runs()).resolves.toEqual(
      expect.arrayContaining([expect.objectContaining({ id: 6 })]),
    );
    await expect(api.rollbackPlan(1)).resolves.toMatchObject({ run_id: 1 });
  });

  it("previews pending plans and blocks apply in the static demo", async () => {
    const api = createDemoWebApi();
    const tagOverrides = [{ line_no: 2, tag: "2026.6.0" }];
    const pending = await api.pending();
    const homeItem = pending.grouping.groups.find(
      (group) => group.name === "home",
    )?.items[0];
    expect(homeItem?.selection_id).toBeTruthy();
    const selections = [
      { line_no: 2, selection_id: homeItem?.selection_id ?? "" },
    ];
    const plan = await api.createPlan(
      [2],
      true,
      tagOverrides,
      [],
      "csrf",
      { selections },
    );

    expect(plan).toMatchObject({
      can_apply: false,
      status: "ready",
      selected_line_numbers: [2],
      selected_selections: selections,
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
      source_check_codes: ["webui-mutation-gate"],
      status: "FAIL",
    });
    expect(plan.stacks[0]?.lines[0]).toMatchObject({
      line_no: 2,
      service: "home-assistant",
      action: "tag-update",
      desired_tag: "2026.6.0",
      target_image: "ghcr.io/home-assistant/home-assistant:2026.6.0",
    });
    await expect(
      api.createPlan(
        [2],
        true,
        tagOverrides,
        [],
        "csrf",
        {
          selections: [{ line_no: 2, selection_id: "selection-forged" }],
        },
      ),
    ).rejects.toThrow("stale or no longer available");

    await expect(
      api.applyPlan(
        plan.plan_id,
        [2],
        true,
        [{ line_no: 2, tag: "2026.6.1" }],
        [],
        "csrf",
      ),
    ).rejects.toThrow(READ_ONLY_MESSAGE);

    await expect(
      api.applyPlan(plan.plan_id, [2], true, tagOverrides, [], "csrf"),
    ).rejects.toThrow(READ_ONLY_MESSAGE);
    await expect(api.status()).resolves.toMatchObject({ pending_count: 7 });
    await expect(api.pending()).resolves.toMatchObject({ count: 7 });
  });

  it("mirrors tag update and approval validation in demo plans", async () => {
    const api = createDemoWebApi();

    await expect(api.createPlan([2], false, [], [], "csrf")).resolves.toMatchObject({
      can_apply: false,
      status: "empty",
      skipped: [
        expect.objectContaining({
          line_no: 2,
          reason: "tag-updates-disabled",
        }),
      ],
      stacks: [],
    });
    await expect(
      api.createPlan([2], false, [{ line_no: 2, tag: "2026.6.0" }], [], "csrf"),
    ).rejects.toThrow("allow_tag_updates=true");
    await expect(
      api.createPlan([4], true, [{ line_no: 4, tag: "17" }], [], "csrf"),
    ).rejects.toThrow("does not target a tag update");
    await expect(
      api.createPlan(
        [2],
        true,
        [],
        [
          {
            stack: "home",
            service: "home-assistant",
            label_key: "demo.label",
            current_label_value: "2026.5.1",
            planned_tag: "2026.6.0",
            proposed_label_value: "2026.6.0",
          },
        ],
        "csrf",
      ),
    ).rejects.toThrow("wud.tag.include");
    await expect(
      api.createPlan(
        [4],
        true,
        [],
        [
          {
            stack: "--data!",
            service: "postgres?",
            label_key: "wud.tag.include",
            current_label_value: "16",
            planned_tag: "16",
            proposed_label_value: "16",
          },
        ],
        "csrf",
      ),
    ).resolves.toMatchObject({
      plan_id: "demo-session-4-allow-tags-data--postgres--16",
    });
  });

  it("previews retag plans and blocks apply in the static demo", async () => {
    const api = createDemoWebApi();
    const targets = await api.retagTargets();
    const serviceCounts = new Map<string, number>();
    for (const item of targets.items) {
      serviceCounts.set(item.service_key, (serviceCounts.get(item.service_key) ?? 0) + 1);
    }
    const target = targets.items.find(
      (item) => item.retag_available && serviceCounts.get(item.service_key) === 1,
    );
    expect(target).toBeDefined();
    const choices = [
      {
        service_key: target?.service_key ?? "",
        choice: "switch-to-concrete" as const,
      },
    ];

    const preview = await api.startRetagPreview(choices, "csrf");
    expect(preview).toMatchObject({
      status: "success",
      plan: {
        can_apply: false,
        selected_count: 1,
        warnings: expect.arrayContaining([READ_ONLY_MESSAGE]),
      },
    });

    const planId = preview.plan?.plan_id ?? "";
    await expect(api.applyRetagPlan(planId, choices, "csrf")).rejects.toThrow(
      READ_ONLY_MESSAGE,
    );
    await expect(api.status()).resolves.toMatchObject({ pending_count: 7 });
  });

  it("matches target_id-keyed retag choices in generated demo plans", async () => {
    const api = createDemoWebApi();
    const targets = await api.retagTargets();
    const target = targets.items.find(
      (item) =>
        item.retag_available &&
        Boolean(item.target_id) &&
        item.target_id !== item.service_key,
    );
    expect(target).toBeDefined();
    const targetId = target?.target_id ?? "";
    const choices = [
      {
        service_key: target?.service_key ?? "",
        target_id: targetId,
        choice: "switch-to-concrete" as const,
      },
    ];

    const plan = await api.createRetagPlan(choices, "csrf");
    const update = plan.stacks.flatMap((stack) => stack.tag_updates)[0];
    expect(update).toMatchObject({
      service_key: target?.service_key,
      target_id: targetId,
    });
    expect(update?.target_id).not.toBe(target?.service_key);

    const preview = await api.startRetagPreview(choices, "csrf");
    const previewUpdate = preview.plan?.stacks.flatMap(
      (stack) => stack.tag_updates,
    )[0];
    expect(previewUpdate).toMatchObject({
      service_key: target?.service_key,
      target_id: targetId,
    });

    await expect(
      api.applyRetagPlan(plan.plan_id, choices, "csrf"),
    ).rejects.toThrow(READ_ONLY_MESSAGE);
  });

  it("exposes generated managed settings as read-only in the static demo", async () => {
    const api = createDemoWebApi();
    const settings = await api.settings();

    expect(settings.managed.filter((entry) => entry.editable)).toEqual([]);
    expect(settings.managed).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "theme_preference",
          editable: false,
          disabled_reason: READ_ONLY_MESSAGE,
        }),
        expect.objectContaining({
          key: "release_notes_enabled",
          editable: false,
          disabled_reason: READ_ONLY_MESSAGE,
        }),
      ]),
    );
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
      api.refreshRetagGithubLatest("csrf"),
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
      api.applyPlan(
        "demo-session-2-allow-tags-2026.6.0",
        [2],
        true,
        [],
        [],
        "csrf",
      ),
      api.applyRetagPlan("demo-retag-empty", [], "csrf"),
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
