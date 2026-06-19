import { afterEach, describe, expect, it, vi } from "vitest";

import { createDemoWebApi } from "../src/api/demo";
import type { ApplyJobLogResponse, ApplyJobResponse } from "../src/api/client";
import { DemoApiState } from "../src/api/demo/state";

const postgresDigest =
  "sha256:1111111111111111111111111111111111111111111111111111111111111111";
const wudUpdaterDigest =
  "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

function completedRunId(jobs: ApplyJobResponse[]): number {
  const runId = jobs.at(-1)?.run_id;
  expect(runId).toEqual(expect.any(Number));
  if (typeof runId !== "number") {
    throw new TypeError("Expected completed demo job to include a run id");
  }
  return runId;
}

async function streamDemoJob(
  api: ReturnType<typeof createDemoWebApi>,
  jobId: string,
): Promise<{ jobs: ApplyJobResponse[]; logs: ApplyJobLogResponse[] }> {
  const jobs: ApplyJobResponse[] = [];
  const logs: ApplyJobLogResponse[] = [];
  const source = api.openJobStream(jobId);
  source.addEventListener("job", (event) => {
    jobs.push(JSON.parse((event as MessageEvent<string>).data) as ApplyJobResponse);
  });
  source.addEventListener("log", (event) => {
    logs.push(
      JSON.parse((event as MessageEvent<string>).data) as ApplyJobLogResponse,
    );
  });

  await vi.advanceTimersByTimeAsync(200);
  source.close();
  return { jobs, logs };
}

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
    expect(pending.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          line_no: 5,
          image: "ghcr.io/magrhino/wud-updater:latest",
          current_tag: "latest",
          desired_tag: "v0.16.1",
        }),
      ]),
    );
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
          Boolean(item.diagnostic),
      ),
    ).toBe(true);
    expect(pending.grouping.unmatched[0]?.diagnostic).toMatchObject({
      message:
        "A running container still matches this WUD entry, but Docker did not report Compose labels that tie it to a discovered stack.",
      details: {
        possible_reasons: expect.arrayContaining([
          "The container is not managed by Docker Compose.",
        ]),
        recommended_actions: expect.arrayContaining([
          "Remove the stale WUD line if this container should not be managed by WUD-Updater.",
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

    const retagTargets = await api.retagTargets();
    expect(retagTargets).toMatchObject({
      status: "ready",
      count: 4,
    });
    expect(retagTargets.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          service_key: "media/wud-updater",
          retag_available: true,
          retag_reason: "eligible",
          label_value: "^latest$$",
          choices: ["keep-current", "switch-to-concrete"],
        }),
        expect.objectContaining({
          service_key: "home/home-assistant",
          retag_available: false,
          retag_reason: "not-latest-tracking",
        }),
        expect.objectContaining({
          service_key: "data/postgres",
          retag_reason: "not-latest-tracking",
        }),
        expect.objectContaining({
          service_key: "media/radarr",
          retag_reason: "not-latest-tracking",
        }),
      ]),
    );
    expect(retagTargets.items.every((item) => !item.directory.startsWith("/"))).toBe(
      true,
    );
    expect(
      retagTargets.items.find((item) => item.service_key === "media/wud-updater"),
    ).toMatchObject({
      final_image: `ghcr.io/magrhino/wud-updater@${wudUpdaterDigest}`,
      digest_provenance: expect.objectContaining({
        target_digest: wudUpdaterDigest,
      }),
    });
    expect(
      retagTargets.items.find((item) => item.service_key === "media/radarr"),
    ).toMatchObject({
      final_image: "",
      digest_provenance: null,
    });
    const retagChoices = [
      {
        service_key: "media/wud-updater",
        choice: "switch-to-concrete" as const,
      },
      { service_key: "media/radarr", choice: "keep-current" as const },
    ];
    const retagPreview = await api.startRetagPreview(retagChoices, "csrf");
    expect(retagPreview).toMatchObject({
      preview_job_id: expect.stringMatching(/^demo-retag-preview-/),
      status: "queued",
      plan: null,
    });
    const polledRetagPreview = await api.retagPreviewJob(
      retagPreview.preview_job_id,
    );
    expect(polledRetagPreview).toMatchObject({
      status: "success",
      plan: expect.objectContaining({
        can_apply: true,
        selected_count: 1,
      }),
    });
    const retagPlan = await api.createRetagPlan(retagChoices, "csrf");
    expect(retagPlan).toMatchObject({
      status: "ready",
      can_apply: true,
      selected_count: 1,
      keep_current_count: 3,
      stacks: [
        expect.objectContaining({
          stack: "media",
          services: ["wud-updater"],
          digest_pin_updates: [
            expect.objectContaining({
              service_key: "media/wud-updater",
              final_image: expect.stringContaining("@sha256:"),
            }),
          ],
        }),
      ],
    });
    const retagJob = await api.applyRetagPlan(
      retagPlan.plan_id,
      retagChoices,
      "csrf",
    );
    expect(retagJob).toMatchObject({
      job_id: expect.stringMatching(/^demo-retag-job-/),
      status: "queued",
      selected_line_numbers: [],
    });
    await expect(
      api.applyRetagPlan(`${retagPlan.plan_id}-stale`, retagChoices, "csrf"),
    ).rejects.toThrow("Demo retag plan is stale.");

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
      target_image: "postgres:16",
      digest_provenance: null,
    });
  });

  it("serves a select-all blocked plan with cleanup items", async () => {
    const api = createDemoWebApi();

    const plan = await api.createPlan([8, 7, 6, 5, 4, 3, 2], true, [], [], "csrf");

    expect(plan.status).toBe("blocked");
    expect(plan.can_apply).toBe(false);
    expect(plan.selected_line_numbers).toEqual([2, 3, 4, 5, 6, 7, 8]);
    expect(plan.summary).toMatchObject({
      target_count: 7,
      matched_target_count: 4,
      skipped_count: 3,
    });
    expect(
      plan.stacks.map((stack) => stack.name).sort((left, right) => left.localeCompare(right)),
    ).toEqual([
      "data",
      "home",
      "media",
    ]);
    expect(plan.cleanup).toMatchObject({
      can_remove_unmatched: true,
      items: [
        expect.objectContaining({ line_no: 6 }),
        expect.objectContaining({ line_no: 7 }),
        expect.objectContaining({ line_no: 8 }),
      ],
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
      code: "matching-container-without-compose-labels",
      line_no: 6,
    });
    expect(plan.cleanup.cleanup_id).toBeTruthy();
    expect(plan.cleanup).toMatchObject({
      can_remove_unmatched: true,
      items: [
        {
          line_no: 6,
          raw: "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
          reason: "unmatched",
          diagnostic: {
            details: {
              possible_reasons: expect.arrayContaining([
                "The container is not managed by Docker Compose.",
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
    const cleanupPlan = await api.createPlan(
      [line.line_no],
      true,
      [],
      [],
      "csrf",
    );
    const cleanupId = cleanupPlan.cleanup.cleanup_id;

    expect(matchedLine).toBeDefined();
    expect(cleanupId).toBeTruthy();
    await expect(
      api.cleanupPending(
        cleanupId,
        [{ line_no: matchedLine?.line_no ?? 0, raw: matchedLine?.raw ?? "" }],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");
    await expect(
      api.cleanupPending(
        cleanupId,
        [
          { line_no: line.line_no, raw: line.raw },
          { line_no: line.line_no, raw: line.raw },
        ],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");

    const cleanup = await api.cleanupPending(
      cleanupId,
      [{ line_no: line.line_no, raw: line.raw }],
      "csrf",
    );

    expect(cleanup).toMatchObject({
      status: "success",
      audit_run_id: expect.any(Number),
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
        cleanupId,
        [{ line_no: line.line_no, raw: line.raw }],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");
  });

  it("removes multiple stale pending lines through demo cleanup", async () => {
    const api = createDemoWebApi();
    const plan = await api.createPlan([6, 7], true, [], [], "csrf");
    const cleanupLines = plan.cleanup.items.map((item) => ({
      line_no: item.line_no,
      raw: item.raw,
    }));

    const cleanup = await api.cleanupPending(
      plan.cleanup.cleanup_id,
      cleanupLines,
      "csrf",
    );

    expect(cleanup).toMatchObject({
      status: "success",
      removed_count: 2,
    });
    expect(cleanup.removed.map((line) => line.line_no)).toEqual([6, 7]);
    const refreshed = await api.pending();
    expect(refreshed.count).toBe(5);
    expect(refreshed.grouping.unmatched.map((item) => item.line_no)).toEqual([8]);
  });

  it("removes selected matched pending lines through demo removal", async () => {
    const api = createDemoWebApi();
    const pending = await api.pending();
    const matchedLine = pending.items.find((item) => item.line_no === 2);

    expect(matchedLine).toBeDefined();
    const plan = await api.createRemovalPlan([matchedLine?.line_no ?? 0], "csrf");
    expect(plan.removal_id).toBeTruthy();
    expect(plan).toMatchObject({
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
      audit_run_id: expect.any(Number),
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

  it("removes arbitrary selected pending subsets through demo removal", async () => {
    const api = createDemoWebApi();
    const pending = await api.pending();
    const selected = pending.items
      .filter((item) => [3, 4, 8].includes(item.line_no))
      .map((item) => ({ line_no: item.line_no, raw: item.raw }));

    const plan = await api.createRemovalPlan(
      selected.map((item) => item.line_no),
      "csrf",
    );
    const removal = await api.removeSelectedPending(plan.removal_id, selected, "csrf");

    expect(removal).toMatchObject({
      status: "success",
      removed_count: 3,
    });
    expect(removal.removed.map((line) => line.line_no)).toEqual([3, 4, 8]);
    const refreshed = await api.pending();
    expect(refreshed.count).toBe(4);
    expect(refreshed.items.some((item) => [3, 4, 8].includes(item.line_no))).toBe(
      false,
    );
    await expect(
      api.removeSelectedPending(plan.removal_id, selected, "csrf"),
    ).rejects.toThrow("removal is stale");
  });

  it("streams apply jobs and updates pending state and run history", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const jobs: ApplyJobResponse[] = [];
    const logs: ApplyJobLogResponse[] = [];
    const progress: ApplyJobResponse["progress"] = [];

    const plan = await api.createPlan([4], true, [], [], "csrf");
    const job = await api.createJob(plan.plan_id, [4], true, [], [], "csrf");
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
    const runId = completedRunId(jobs);
    expect((await api.runs())[0]).toMatchObject({
      id: runId,
      status: "success",
      wud_file: "demo/out/images.todo",
    });
    await expect(api.runDetail(runId)).resolves.toMatchObject({
      id: runId,
      pending_updates: [
        {
          service_key: "data/postgres",
          target_digest: postgresDigest,
          digest_provenance: null,
        },
      ],
      events: [
        {
          stack_name: "data",
          service_name: "postgres",
          old_digest: postgresDigest,
          new_digest: "sha256:demo-new",
          digest_provenance: null,
        },
      ],
    });

    const applySummary = (await api.runs()).find((run) => run.id === runId);
    const applyDetail = await api.runDetail(runId);
    expect(applySummary?.events).toHaveLength(applyDetail.events.length);
    expect(applySummary?.events[0]).toMatchObject({
      service_name: applyDetail.events[0]?.service_name,
      status: applyDetail.events[0]?.status,
    });
  });

  it("keeps multi-line tag overrides scoped when an override matches another default tag", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const jobs: ApplyJobResponse[] = [];
    const logs: ApplyJobLogResponse[] = [];
    const selected = [2, 3];
    const tagOverrides = [
      { line_no: 2, tag: "5.22.4" },
      { line_no: 3, tag: "5.23.0" },
    ];

    const plan = await api.createPlan(selected, true, tagOverrides, [], "csrf");
    const planLines = new Map(
      plan.stacks.flatMap((stack) =>
        stack.lines.map((line) => [line.line_no, line] as const),
      ),
    );

    expect(planLines.get(2)).toMatchObject({
      desired_tag: "5.22.4",
      target_image: "ghcr.io/home-assistant/home-assistant:5.22.4",
    });
    expect(planLines.get(3)).toMatchObject({
      desired_tag: "5.23.0",
      target_image: "lscr.io/linuxserver/radarr:5.23.0",
    });
    expect(plan.stacks[0]?.actions[0]).toMatchObject({
      kind: "compose-tag-update",
      description: "Rewrite ghcr.io/home-assistant/home-assistant:2026.5.1 to ghcr.io/home-assistant/home-assistant:5.22.4 for home-assistant",
    });
    expect(plan.stacks[0]?.tag_updates[0]).toMatchObject({
      desired_tag: "5.22.4",
      new_image: "ghcr.io/home-assistant/home-assistant:5.22.4",
    });

    const job = await api.createJob(
      plan.plan_id,
      selected,
      true,
      tagOverrides,
      [],
      "csrf",
    );
    const source = api.openJobStream(job.job_id);
    source.addEventListener("job", (event) => {
      jobs.push(JSON.parse((event as MessageEvent<string>).data) as ApplyJobResponse);
    });
    source.addEventListener("log", (event) => {
      logs.push(
        JSON.parse((event as MessageEvent<string>).data) as ApplyJobLogResponse,
      );
    });

    await vi.advanceTimersByTimeAsync(200);
    source.close();

    expect(jobs.at(-1)?.status).toBe("success");
    const logContent = logs.at(-1)?.content ?? "";
    expect(logContent).toContain(
      "ghcr.io/home-assistant/home-assistant:2026.5.1 -> ghcr.io/home-assistant/home-assistant:5.22.4",
    );
    expect(logContent).toContain(
      "lscr.io/linuxserver/radarr:5.21.1 -> lscr.io/linuxserver/radarr:5.23.0",
    );
    expect(logContent).not.toContain(
      "ghcr.io/home-assistant/home-assistant:2026.5.1 -> ghcr.io/home-assistant/home-assistant:5.23.0",
    );

    const detail = await api.runDetail(completedRunId(jobs));
    const pendingByLine = new Map(
      detail.pending_updates.map((item) => [item.line_no, item] as const),
    );
    const eventByService = new Map(
      detail.events.map((event) => [event.service_name, event] as const),
    );
    expect(pendingByLine.get(2)).toMatchObject({ desired_tag: "5.22.4" });
    expect(pendingByLine.get(3)).toMatchObject({ desired_tag: "5.23.0" });
    expect(eventByService.get("home-assistant")).toMatchObject({
      target_image: "ghcr.io/home-assistant/home-assistant:5.22.4",
    });
    expect(eventByService.get("radarr")).toMatchObject({
      target_image: "lscr.io/linuxserver/radarr:5.23.0",
    });
  });

  it("applies multi-stack matched plans and filters released pending notes", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const selected = [2, 3, 4, 5];

    const plan = await api.createPlan(selected, true, [], [], "csrf");
    const job = await api.createJob(plan.plan_id, selected, true, [], [], "csrf");
    const { jobs } = await streamDemoJob(api, job.job_id);

    expect(jobs.at(-1)?.status).toBe("success");
    expect((await api.pending()).items.map((item) => item.line_no)).toEqual([6, 7, 8]);
    const runId = completedRunId(jobs);
    const detail = await api.runDetail(runId);
    expect(
      detail.events
        .map((event) => event.stack_name)
        .sort((left, right) => left.localeCompare(right)),
    ).toEqual([
      "data",
      "home",
      "media",
      "media",
    ]);
    const remainingReleaseNoteLines = (await api.releaseNotes()).items.map((item) => item.line_no);
    expect(remainingReleaseNoteLines.filter((lineNo) => selected.includes(lineNo))).toEqual([]);
  });

  it("materializes arbitrary tag overrides into plan, job log, and run detail", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const selected = [2];
    const tagOverrides = [{ line_no: 2, tag: "2026.6.0" }];

    const plan = await api.createPlan(selected, true, tagOverrides, [], "csrf");
    expect(plan.stacks[0]?.lines[0]).toMatchObject({
      desired_tag: "2026.6.0",
      target_image: "ghcr.io/home-assistant/home-assistant:2026.6.0",
    });

    const job = await api.createJob(
      plan.plan_id,
      selected,
      true,
      tagOverrides,
      [],
      "csrf",
    );
    const { jobs, logs } = await streamDemoJob(api, job.job_id);

    expect(jobs.at(-1)?.status).toBe("success");
    expect(logs.at(-1)?.content).toContain("2026.6.0");
    expect((await api.pending()).items.some((item) => item.line_no === 2)).toBe(false);
    const detail = await api.runDetail(completedRunId(jobs));
    expect(detail.events[0]).toMatchObject({
      target_image: "ghcr.io/home-assistant/home-assistant:2026.6.0",
    });
    expect(detail.pending_updates[0]).toMatchObject({
      desired_tag: "2026.6.0",
    });
  });

  it("blocks tag update selections when tag updates are disabled", async () => {
    const api = createDemoWebApi();

    const plan = await api.createPlan([2], false, [], [], "csrf");

    expect(plan).toMatchObject({
      status: "empty",
      can_apply: false,
    });
    expect(plan.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "tag-updates-disabled" }),
      ]),
    );
  });

  it("streams retag apply jobs and records demo run history", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const jobs: ApplyJobResponse[] = [];
    const logs: ApplyJobLogResponse[] = [];
    const progress: ApplyJobResponse["progress"] = [];
    const choices = [
      {
        service_key: "media/wud-updater",
        choice: "switch-to-concrete" as const,
      },
    ];
    const plan = await api.createRetagPlan(choices, "csrf");
    const job = await api.applyRetagPlan(plan.plan_id, choices, "csrf");
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
    expect(progress.map((item) => item.phase)).toEqual([
      "compose-digest-pin",
      "compose-digest-pin",
      "pull",
      "pull",
      "recreate",
      "recreate",
      "health",
      "health",
      "completion",
    ]);
    expect(progress.at(-1)?.message).toBe("Retag changes applied.");
    expect(logs.at(-1)).toMatchObject({
      exists: true,
      log_file: "demo/logs/demo-retag-switch-media-wud-updater.log",
      content: expect.stringContaining("Retag changes applied."),
    });
    expect((await api.pending()).count).toBe(7);
    const runId = completedRunId(jobs);
    expect((await api.runs())[0]).toMatchObject({
      id: runId,
      status: "success",
      mode: "web-retag",
      events: [
        expect.objectContaining({
          service_name: "wud-updater",
          target_image: `ghcr.io/magrhino/wud-updater@${wudUpdaterDigest}`,
        }),
      ],
    });
    await expect(api.runDetail(runId)).resolves.toMatchObject({
      id: runId,
      mode: "web-retag",
      pending_updates: [],
      events: [
        expect.objectContaining({
          service_name: "wud-updater",
          target_image: `ghcr.io/magrhino/wud-updater@${wudUpdaterDigest}`,
        }),
      ],
      verification: expect.objectContaining({
        total_count: 0,
        verified_count: 0,
        items: [],
      }),
    });
    await expect(api.runLog(runId)).resolves.toMatchObject({
      exists: true,
      log_file: "demo/logs/demo-retag-switch-media-wud-updater.log",
      content: expect.stringContaining("Retag changes applied."),
    });
  });

  it("reports polished retag apply errors for blocked demo plans", async () => {
    const api = createDemoWebApi();
    const choices = [
      {
        service_key: "media/wud-updater",
        choice: "keep-current" as const,
      },
    ];
    const plan = await api.createRetagPlan(choices, "csrf");

    await expect(api.applyRetagPlan(plan.plan_id, choices, "csrf")).resolves.toMatchObject({
      status: "failure",
      error: "Demo retag plan is not applicable.",
    });
  });

  it("deduplicates retag choices by service key before planning", async () => {
    const api = createDemoWebApi();

    const plan = await api.createRetagPlan(
      [
        {
          service_key: "media/wud-updater",
          choice: "switch-to-concrete" as const,
        },
        {
          service_key: "media/wud-updater",
          choice: "switch-to-concrete" as const,
        },
        { service_key: "media/wud-updater", choice: "keep-current" as const },
      ],
      "csrf",
    );

    expect(plan).toMatchObject({
      status: "ready",
      selected_count: 1,
      keep_current_count: 3,
    });
    expect(plan.stacks).toHaveLength(1);
    expect(plan.stacks[0]?.services).toEqual(["wud-updater"]);
    expect(plan.stacks[0]?.digest_pin_updates).toHaveLength(1);
  });

  it("normalizes missing retag choices to keep-current and blocks non-eligible switches", async () => {
    const api = createDemoWebApi();

    const empty = await api.createRetagPlan([], "csrf");
    expect(empty).toMatchObject({
      status: "empty",
      can_apply: false,
      selected_count: 0,
      keep_current_count: 4,
    });

    const blocked = await api.createRetagPlan(
      [
        {
          service_key: "home/home-assistant",
          choice: "switch-to-concrete" as const,
        },
      ],
      "csrf",
    );
    expect(blocked).toMatchObject({
      status: "blocked",
      can_apply: false,
      selected_count: 0,
      keep_current_count: 3,
    });
    expect(blocked.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "retag-target-not-eligible" }),
      ]),
    );
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
    const dependencySnooze = await api.stateOperation(
      {
        kind: "create_dependency_snooze",
        service_key: "media/radarr",
        wait_for_service_key: "media/prowlarr",
        reason: "demo dependency",
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
    expect(await api.snoozes("active")).toContainEqual(
      expect.objectContaining({
        service_key: "media/radarr",
        wait_for_service_key: "media/prowlarr",
        snoozed_until: null,
        kind: "dependency",
      }),
    );
    await api.stateOperation(
      {
        kind: "delete_dependency_snooze",
        snooze_id: Number(dependencySnooze.resource_id),
      },
      "csrf",
    );
    expect(await api.snoozes("all")).not.toContainEqual(
      expect.objectContaining({
        id: Number(dependencySnooze.resource_id),
      }),
    );
    expect(await api.tagExclusions("active")).toContainEqual(
      expect.objectContaining({
        image_repo: "magrhino/wud-updater",
        service_key: "media/wud-updater",
      }),
    );
  });

  it("computes dependency snooze activity from successful demo events", () => {
    const state = new DemoApiState();
    const baseDependency = state.snoozes.find(
      (snooze) => snooze.kind === "dependency",
    );
    expect(baseDependency).toBeDefined();
    if (!baseDependency) {
      throw new Error("Expected demo dependency snooze fixture");
    }

    state.snoozes = [
      {
        ...baseDependency,
        id: 50,
        service_key: "media/app",
        wait_for_service_key: "media/sonarr",
        created_at: "2099-05-28T12:00:02+00:00",
        active: false,
      },
      {
        ...baseDependency,
        id: 51,
        service_key: "media/worker",
        wait_for_service_key: "media/sonarr",
        created_at: "2020-05-28T12:00:00+00:00",
        active: true,
      },
    ];

    expect(state.snoozeRecords("active")).toContainEqual(
      expect.objectContaining({ id: 50, active: true }),
    );
    expect(state.snoozeRecords("expired")).toContainEqual(
      expect.objectContaining({ id: 51, active: false }),
    );
  });

  it("deletes demo snoozes by id and kind", () => {
    const state = new DemoApiState();
    const timeSnooze = state.snoozes.find((snooze) => snooze.kind === "time");
    const dependencySnooze = state.snoozes.find(
      (snooze) => snooze.kind === "dependency",
    );
    expect(timeSnooze).toBeDefined();
    expect(dependencySnooze).toBeDefined();
    if (!timeSnooze || !dependencySnooze) {
      throw new Error("Expected demo snooze fixtures");
    }

    state.snoozes = [
      { ...dependencySnooze, id: 99 },
      { ...timeSnooze, id: 99 },
    ];
    state.stateOperation({ kind: "delete_snooze", snooze_id: 99 });
    expect(state.snoozeRecords("all")).toEqual([
      expect.objectContaining({ id: 99, kind: "dependency" }),
    ]);

    state.snoozes = [
      { ...dependencySnooze, id: 99 },
      { ...timeSnooze, id: 99 },
    ];
    state.stateOperation({ kind: "delete_dependency_snooze", snooze_id: 99 });
    expect(state.snoozeRecords("all")).toEqual([
      expect.objectContaining({ id: 99, kind: "time" }),
    ]);
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
        proposed_label_value: String.raw`^2\.0$$`,
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
        proposed_label_value: String.raw`^2\.0$$`,
      },
    ];

    const plan = await api.createPlan([3], true, [], approvals, "csrf");
    const job = await api.createJob(
      plan.plan_id,
      [3],
      true,
      [],
      approvals,
      "csrf",
    );

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
        proposed_label_value: String.raw`^2\.0$$`,
      },
    ];

    const plan = await api.createPlan([3], true, [], approvals, "csrf");
    const job = await api.applyPlan(
      plan.plan_id,
      [3],
      true,
      [],
      approvals,
      "csrf",
    );

    expect(job.job_id).toBeTruthy();
    expect(["queued", "running"]).toContain(job.status);
  });
});
