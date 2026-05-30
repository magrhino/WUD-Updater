import { afterEach, describe, expect, it, vi } from "vitest";

import { createDemoWebApi } from "../src/api/demo";
import type { ApplyJobLogResponse, ApplyJobResponse } from "../src/api/client";

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
      pending_count: 4,
      mutations_enabled: true,
    });

    const pending = await api.pending();
    expect(pending.count).toBe(4);
    expect(pending.source_file).toBe("demo/out/images.todo");
    expect(pending.grouping.groups.map((group) => group.name)).toEqual([
      "data",
      "home",
      "media",
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
  });

  it("creates plans from the current fixture state", async () => {
    const api = createDemoWebApi();

    const plan = await api.createPlan([3, 5], true, [], "csrf");

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
  });

  it("removes exact pending lines through demo cleanup", async () => {
    const api = createDemoWebApi();
    const pending = await api.pending();
    const line = pending.items[0];

    const cleanup = await api.cleanupPending(
      "demo-cleanup",
      [{ line_no: line.line_no, raw: line.raw }],
      "csrf",
    );

    expect(cleanup).toMatchObject({
      status: "success",
      audit_run_id: 4,
      removed_count: 1,
      removed: [{ line_no: line.line_no, raw: line.raw, reason: "unmatched" }],
    });
    expect((await api.pending()).count).toBe(3);
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
    await expect(
      api.cleanupPending(
        "demo-cleanup",
        [{ line_no: line.line_no, raw: line.raw }],
        "csrf",
      ),
    ).rejects.toThrow("cleanup is stale");
  });

  it("streams apply jobs and updates pending state and run history", async () => {
    vi.useFakeTimers();
    const api = createDemoWebApi();
    const jobs: ApplyJobResponse[] = [];
    const logs: ApplyJobLogResponse[] = [];

    const job = await api.createJob("demo-plan", [2], true, [], "csrf");
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

    expect(jobs.map((item) => item.status)).toEqual(["running", "success"]);
    expect(logs.at(-1)?.content).toContain("Done. See log");
    expect((await api.pending()).count).toBe(3);
    expect((await api.runs())[0]).toMatchObject({
      id: 4,
      status: "success",
      wud_file: "demo/out/images.todo",
    });
    await expect(api.runDetail(4)).resolves.toMatchObject({
      id: 4,
      pending_updates: [{ service_key: "home/home-assistant" }],
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
        image_repo: "ghcr.io/magrhino/wud-updater",
        service_key: "media/wud-updater",
      }),
    );
  });
});
