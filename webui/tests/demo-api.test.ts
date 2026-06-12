import { afterEach, describe, expect, it, vi } from "vitest";

import { createDemoWebApi } from "../src/api/demo";
import type { ApplyJobLogResponse, ApplyJobResponse } from "../src/api/client";

const postgresDigest =
  "sha256:1111111111111111111111111111111111111111111111111111111111111111";

describe("demo web API", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("serves authenticated sanitized fixture state", async () => {
    const api = createDemoWebApi();

    await expect(api.session()).resolves.toMatchObject({
      authenticated: true,
      auth_required: false,
      dev_auth_bypass: true,
      mutations_enabled: true,
    });
    await expect(api.status()).resolves.toMatchObject({
      wud_file: "demo/out/images.todo",
      db_path: "demo/logs/wud-updater.sqlite",
      pending_count: 7,
      mutations_enabled: true,
    });
    await expect(api.settings()).resolves.toMatchObject({
      updater: expect.arrayContaining([
        expect.objectContaining({
          name: "DOCKER_BASE",
          value: "demo/docker",
        }),
      ]),
      secrets: expect.arrayContaining([
        { name: "GITHUB_TOKEN", configured: false },
      ]),
      managed: expect.arrayContaining([
        expect.objectContaining({
          key: "theme_preference",
          value: "system",
        }),
      ]),
    });
    await expect(
      api.updateManagedSettings({ theme_preference: "dark" }, "csrf"),
    ).resolves.toMatchObject({
      audit_run_id: expect.any(Number),
      managed: expect.arrayContaining([
        expect.objectContaining({
          key: "theme_preference",
          value: "dark",
        }),
      ]),
    });
    await expect(
      api.updateManagedSettings({ theme_preference: "system" }, "csrf"),
    ).resolves.toMatchObject({
      managed: expect.arrayContaining([
        expect.objectContaining({
          key: "theme_preference",
          value: "system",
          source: "configured",
        }),
      ]),
    });
    await expect(api.onboardingChecklist("csrf")).resolves.toMatchObject({
      visible: true,
      items: expect.arrayContaining([
        expect.objectContaining({
          key: "mutation-mode",
          status: "WARN",
        }),
      ]),
    });
    await expect(api.dismissOnboarding("csrf")).resolves.toMatchObject({
      dismissed: true,
    });
    await expect(api.onboardingChecklist("csrf")).resolves.toMatchObject({
      visible: false,
    });
    await expect(
      api.updateManagedSettings({ onboarding_checklist: "visible" }, "csrf"),
    ).resolves.toMatchObject({
      managed: expect.arrayContaining([
        expect.objectContaining({
          key: "onboarding_checklist",
          value: "visible",
        }),
      ]),
    });
    await expect(api.onboardingChecklist("csrf")).resolves.toMatchObject({
      visible: true,
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
    expect(pending.grouping.unmatched.map((item) => item.repo)).toEqual([
      "gethomepage/homepage",
      "vaultwarden/server",
      "containrrr/watchtower",
    ]);
    expect(pending.source_file.startsWith("/")).toBe(false);
    expect(pending.grouping.groups.every((group) => !group.directory.startsWith("/"))).toBe(
      true,
    );
    expect(
      pending.grouping.groups.flatMap((group) =>
        group.items.map((item) => item.diagnostic),
      ),
    ).toEqual([null, null, null, null]);
    expect(
      pending.grouping.unmatched.every(
        (item) =>
          item.action === "unmatched" &&
          item.compose_images.length === 0 &&
          item.services.length === 0 &&
          item.diagnostic?.code === "unmatched",
      ),
    ).toBe(true);
    expect(pending.grouping.unmatched[0]?.diagnostic).toMatchObject({
      message: "This pending update no longer matches any discovered Compose service.",
      details: {
        possible_reasons: expect.arrayContaining([
          "The Compose service was removed or renamed.",
        ]),
        recommended_actions: expect.arrayContaining([
          "Remove the stale WUD line when the service is intentionally gone or already updated.",
        ]),
      },
    });

    await expect(api.updateTargets()).resolves.toMatchObject({
      status: "ready",
      count: 4,
      items: expect.arrayContaining([
        expect.objectContaining({
          service_key: "media/radarr",
          image_repo: "linuxserver/radarr",
        }),
      ]),
    });

    const runs = await api.runs();
    const seededRun = runs.find((run) => run.id === 1);
    expect(seededRun?.events).toHaveLength(2);
    expect(seededRun?.events.map((event) => event.service_name)).toEqual([
      "sonarr",
      "redis",
    ]);
    const seededAuditRuns = runs.filter((run) =>
      ["web-auth", "web-settings", "web-state"].includes(run.mode),
    );
    expect(seededAuditRuns).toHaveLength(3);
    expect(seededAuditRuns.map((run) => run.metadata.resource_id)).toEqual([
      "webui_preferences",
      "media/radarr",
      "admin",
    ]);
  });

  it("creates plans from the current fixture state", async () => {
    const api = createDemoWebApi();

    const plan = await api.createPlan([3, 5], true, [], [], "csrf");

    expect(plan.status).toBe("ready");
    expect(plan.can_apply).toBe(true);
    expect(plan.summary).toMatchObject({
      target_count: 2,
      matched_target_count: 2,
      stack_count: 1,
      service_count: 2,
      issue_count: 0,
    });
    expect(plan.stacks[0]?.name).toBe("media");
    expect(plan.stacks[0]?.services).toEqual(["radarr", "wud-updater"]);
    expect(plan.cleanup).toEqual({
      cleanup_id: "",
      can_remove_unmatched: false,
      items: [],
    });
    expect(plan.issues).toEqual([]);

    const digestPlan = await api.createPlan([4], true, [], [], "csrf");
    const digestLine = digestPlan.stacks[0]?.lines[0];

    expect(digestLine).toMatchObject({
      line_no: 4,
      digest: postgresDigest,
      target_image: `postgres@${postgresDigest}`,
      digest_provenance: {
        source_image: "postgres:16",
        target_digest: postgresDigest,
        final_image: `postgres@${postgresDigest}`,
      },
    });
  });

  it("blocks unmatched fixture lines and previews cleanup", async () => {
    const api = createDemoWebApi();

    const plan = await api.createPlan([6], true, [], [], "csrf");

    expect(plan.status).toBe("blocked");
    expect(plan.can_apply).toBe(false);
    expect(plan.summary).toMatchObject({
      target_count: 1,
      matched_target_count: 0,
      stack_count: 0,
      service_count: 0,
      skipped_count: 1,
      issue_count: 1,
    });
    expect(plan.targets[0]).toMatchObject({
      line_no: 6,
      matched: false,
      action: "unmatched",
    });
    expect(plan.skipped).toEqual([
      {
        line_no: 6,
        raw: "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
        image: "ghcr.io/gethomepage/homepage:v0.9.12",
        desired_tag: "v0.10.9",
        reason: "unmatched",
      },
    ]);
    expect(plan.issues[0]).toMatchObject({
      severity: "error",
      code: "unmatched",
      line_no: 6,
    });
    expect(plan.cleanup).toMatchObject({
      cleanup_id: "demo-cleanup",
      can_remove_unmatched: true,
      items: [
        {
          line_no: 6,
          raw: "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
          reason: "unmatched",
          diagnostic: {
            details: {
              possible_reasons: expect.arrayContaining([
                "The update tag was already applied and WUD left the old pending line behind.",
              ]),
            },
          },
        },
      ],
    });
  });

  it("removes exact pending lines through demo cleanup", async () => {
    const api = createDemoWebApi();
    const pending = await api.pending();
    const line = pending.grouping.unmatched[0];
    const matchedLine = pending.items.find((item) => item.line_no === 2);

    expect(matchedLine).toBeDefined();
    await expect(
      api.cleanupPending(
        "demo-cleanup",
        [{ line_no: matchedLine?.line_no ?? 0, raw: matchedLine?.raw ?? "" }],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");

    const cleanup = await api.cleanupPending(
      "demo-cleanup",
      [{ line_no: line.line_no, raw: line.raw }],
      "csrf",
    );

    expect(cleanup).toMatchObject({
      status: "success",
      audit_run_id: 7,
      removed_count: 1,
      removed: [{ line_no: line.line_no, raw: line.raw, reason: "unmatched" }],
    });
    const refreshed = await api.pending();
    expect(refreshed.count).toBe(6);
    expect(refreshed.grouping.unmatched.map((item) => item.line_no)).toEqual([7, 8]);
    await expect(api.runDetail(cleanup.audit_run_id)).resolves.toMatchObject({
      id: cleanup.audit_run_id,
      mode: "web-pending-cleanup",
      metadata: { operation: "remove_unmatched_pending" },
      pending_updates: [
        {
          line_no: line.line_no,
          status: "resolved",
          status_reason: "removed-unmatched",
        },
      ],
      events: [{ status: "success" }],
    });

    const cleanupSummary = (await api.runs()).find(
      (run) => run.id === cleanup.audit_run_id,
    );
    const cleanupDetail = await api.runDetail(cleanup.audit_run_id);
    expect(cleanupSummary?.events).toHaveLength(cleanupDetail.events.length);
    expect(cleanupSummary?.events[0]).toMatchObject({
      service_name: cleanupDetail.events[0]?.service_name,
      status: cleanupDetail.events[0]?.status,
    });
    await expect(
      api.cleanupPending(
        "demo-cleanup",
        [{ line_no: line.line_no, raw: line.raw }],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");
  });

  it("removes selected matched pending lines through demo removal", async () => {
    const api = createDemoWebApi();
    const pending = await api.pending();
    const matchedLine = pending.items.find((item) => item.line_no === 2);

    expect(matchedLine).toBeDefined();
    const plan = await api.createRemovalPlan([matchedLine?.line_no ?? 0], "csrf");
    expect(plan).toMatchObject({
      removal_id: "demo-removal",
      can_remove: true,
      selected_line_numbers: [matchedLine?.line_no],
      lines: [{ line_no: matchedLine?.line_no, raw: matchedLine?.raw }],
    });

    const removal = await api.removeSelectedPending(
      plan.removal_id,
      [{ line_no: matchedLine?.line_no ?? 0, raw: matchedLine?.raw ?? "" }],
      "csrf",
    );

    expect(removal).toMatchObject({
      status: "success",
      audit_run_id: 7,
      removed_count: 1,
      removed: [
        { line_no: matchedLine?.line_no, raw: matchedLine?.raw, reason: "selected" },
      ],
    });
    const refreshed = await api.pending();
    expect(refreshed.count).toBe(6);
    expect(refreshed.items.some((item) => item.line_no === matchedLine?.line_no)).toBe(
      false,
    );
    await expect(api.runDetail(removal.audit_run_id)).resolves.toMatchObject({
      id: removal.audit_run_id,
      mode: "web-pending-removal",
      metadata: { operation: "remove_selected_pending" },
      pending_updates: [
        {
          line_no: matchedLine?.line_no,
          status: "resolved",
          status_reason: "removed-selected",
        },
      ],
      events: [{ status: "success" }],
    });

    const removalSummary = (await api.runs()).find(
      (run) => run.id === removal.audit_run_id,
    );
    const removalDetail = await api.runDetail(removal.audit_run_id);
    expect(removalSummary?.events).toHaveLength(removalDetail.events.length);
    expect(removalSummary?.events[0]).toMatchObject({
      service_name: removalDetail.events[0]?.service_name,
      status: removalDetail.events[0]?.status,
    });
    await expect(
      api.removeSelectedPending(
        plan.removal_id,
        [{ line_no: matchedLine?.line_no ?? 0, raw: matchedLine?.raw ?? "" }],
        "csrf",
      ),
    ).rejects.toThrow("removal is stale");
  });

  it("streams apply jobs and updates pending state and run history", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const jobs: ApplyJobResponse[] = [];
    const logs: ApplyJobLogResponse[] = [];
    const progress: ApplyJobResponse["progress"] = [];

    const job = await api.createJob("demo-plan", [4], true, [], [], "csrf");
    const source = api.openJobStream(job.job_id);
    source.addEventListener("job", (event) => {
      jobs.push(JSON.parse((event as MessageEvent<string>).data) as ApplyJobResponse);
    });
    source.addEventListener("log", (event) => {
      logs.push(
        JSON.parse((event as MessageEvent<string>).data) as ApplyJobLogResponse,
      );
    });
    source.addEventListener("progress", (event) => {
      progress.push(
        JSON.parse((event as MessageEvent<string>).data) as ApplyJobResponse["progress"][number],
      );
    });

    await vi.advanceTimersByTimeAsync(200);
    source.close();

    expect(jobs.map((item) => item.status)).toEqual(["running", "success"]);
    expect(progress.map((item) => item.phase)).toContain("completion");
    expect(jobs.at(-1)?.progress.at(-1)?.status).toBe("success");
    expect(logs.at(-1)?.content).toContain("Done. See log");
    expect((await api.pending()).count).toBe(6);
    expect((await api.runs())[0]).toMatchObject({
      id: 7,
      status: "success",
      wud_file: "demo/out/images.todo",
    });
    await expect(api.runDetail(7)).resolves.toMatchObject({
      id: 7,
      pending_updates: [
        {
          service_key: "data/postgres",
          target_digest: postgresDigest,
          digest_provenance: {
            source_image: "postgres:16",
            target_digest: postgresDigest,
          },
        },
      ],
      events: [
        {
          stack_name: "data",
          service_name: "postgres",
          old_digest: postgresDigest,
          new_digest: postgresDigest,
          digest_provenance: {
            final_image: `postgres@${postgresDigest}`,
          },
        },
      ],
    });

    const applySummary = (await api.runs()).find((run) => run.id === 7);
    const applyDetail = await api.runDetail(7);
    expect(applySummary?.events).toHaveLength(applyDetail.events.length);
    expect(applySummary?.events[0]).toMatchObject({
      service_name: applyDetail.events[0]?.service_name,
      status: applyDetail.events[0]?.status,
    });
  });

  it("keeps policy, snooze, and tag exclusion mutations in memory", async () => {
    const api = createDemoWebApi();

    await api.stateOperation(
      {
        kind: "upsert_service_policy",
        service_key: "media/wud-updater",
        update_mode: "stop",
        auto_update: true,
        snooze_default_seconds: null,
        auto_update_time: "02:15",
        auto_update_days: ["tue", "thu"],
      },
      "csrf",
    );
    await api.stateOperation(
      {
        kind: "upsert_service_policy",
        service_key: "media/radarr",
        snooze_default_seconds: null,
      },
      "csrf",
    );
    await api.stateOperation(
      {
        kind: "create_snooze",
        service_key: "home/home-assistant",
        snoozed_until: "2099-02-01T00:00:00+00:00",
        reason: "demo test",
      },
      "csrf",
    );
    await api.stateOperation(
      {
        kind: "upsert_tag_exclusion",
        scope: "service",
        image_repo: "ghcr.io/magrhino/wud-updater",
        service_key: "media/wud-updater",
        tag: "v0.25.1",
        status: "active",
      },
      "csrf",
    );

    expect(await api.servicePolicies()).toContainEqual(
      expect.objectContaining({
        service_key: "media/wud-updater",
        auto_update: true,
        auto_update_time: "02:15",
        auto_update_days: ["tue", "thu"],
      }),
    );
    expect(await api.servicePolicies()).toContainEqual(
      expect.objectContaining({
        service_key: "media/radarr",
        snooze_default_seconds: null,
      }),
    );
    expect(await api.snoozes("active")).toContainEqual(
      expect.objectContaining({
        service_key: "home/home-assistant",
        reason: "demo test",
      }),
    );
    expect(await api.tagExclusions("active")).toContainEqual(
      expect.objectContaining({
        image_repo: "magrhino/wud-updater",
        service_key: "media/wud-updater",
      }),
    );
  });

  it("createPlan accepts and ignores digestPinLabelRewriteApprovals", async () => {
    const api = createDemoWebApi();
    const approvals = [
      {
        stack: "media",
        service: "plex",
        label_key: "wud.tag.include",
        current_label_value: "^beta|^stable",
        planned_tag: "2.0",
        proposed_label_value: "^2\\.0$$",
      },
    ];

    const plan = await api.createPlan([3, 5], true, [], approvals, "csrf");

    expect(plan.status).toBe("ready");
    expect(plan.can_apply).toBe(true);
  });

  it("createJob passes digestPinLabelRewriteApprovals to plan creation", async () => {
    const api = createDemoWebApi();
    const approvals = [
      {
        stack: "media",
        service: "plex",
        label_key: "wud.tag.include",
        current_label_value: "^beta|^stable",
        planned_tag: "2.0",
        proposed_label_value: "^2\\.0$$",
      },
    ];

    const job = await api.createJob("demo-plan", [3], true, [], approvals, "csrf");

    expect(job.job_id).toBeTruthy();
    expect(["queued", "running"]).toContain(job.status);
  });

  it("applyPlan passes digestPinLabelRewriteApprovals to plan creation", async () => {
    const api = createDemoWebApi();
    const approvals = [
      {
        stack: "media",
        service: "plex",
        label_key: "wud.tag.include",
        current_label_value: "^beta|^stable",
        planned_tag: "2.0",
        proposed_label_value: "^2\\.0$$",
      },
    ];

    const job = await api.applyPlan("demo-plan", [3], true, [], approvals, "csrf");

    expect(job.job_id).toBeTruthy();
    expect(["queued", "running"]).toContain(job.status);
  });
});
