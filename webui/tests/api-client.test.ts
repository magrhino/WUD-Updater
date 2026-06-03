import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiPrefixFromBasePath,
  normalizeApiPrefix,
  webApi,
  type SelfUpdateResponse,
  type StateOperation,
} from "../src/api/client";

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

function requestInit(call: unknown[]): RequestInit {
  return call[1] as RequestInit;
}

function selfUpdateStatus(): SelfUpdateResponse {
  return {
    status: "available",
    current_tag: "v0.24.2",
    latest_tag: "v0.25.0",
    current_image: "ghcr.io/magrhino/wud-updater:v0.24.2",
    target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
    restart_container: "wud-updater",
    release_notes: [],
    release_notes_truncated: false,
    release_notes_cap: 10,
    can_update: true,
    disabled_reason: "",
    warnings: [],
  };
}

describe("webApi", () => {
  it("builds API prefixes from the app base path", () => {
    expect(apiPrefixFromBasePath("/")).toBe("/api/v1");
    expect(apiPrefixFromBasePath("/wud/")).toBe("/wud/api/v1");
    expect(apiPrefixFromBasePath("wud")).toBe("/wud/api/v1");
  });

  it("normalizes configured API prefixes", () => {
    expect(normalizeApiPrefix("/wud/api/v1/")).toBe("/wud/api/v1");
    expect(normalizeApiPrefix("wud/api/v1")).toBe("/wud/api/v1");
    expect(normalizeApiPrefix("https://example.test/wud/api/v1/")).toBe(
      "https://example.test/wud/api/v1",
    );
  });

  it("uses a configured API prefix for fetch requests", async () => {
    vi.resetModules();
    const fetchMock = mockFetch({});
    const globals = globalThis as typeof globalThis & { WUD_API_PREFIX?: string };
    const originalApiPrefix = globals.WUD_API_PREFIX;
    globals.WUD_API_PREFIX = "/wud/api/v1/";

    try {
      const { webApi: configuredWebApi } = await import("../src/api/client");

      await configuredWebApi.status();

      expect(fetchMock.mock.calls[0][0]).toBe("/wud/api/v1/status");
    } finally {
      if (originalApiPrefix === undefined) {
        delete globals.WUD_API_PREFIX;
      } else {
        globals.WUD_API_PREFIX = originalApiPrefix;
      }
      vi.resetModules();
    }
  });

  it("uses same-origin credentials for every fetch request", async () => {
    const fetchMock = mockFetch([]);
    const operation: StateOperation = {
      kind: "delete_service_policy",
      service_key: "media/app",
    };

    await Promise.all([
      webApi.csrf(),
      webApi.setupStatus(),
      webApi.setupClaim("claim", "admin", "password", "csrf"),
      webApi.resetAdminClaim("claim", "admin", "password", "csrf"),
      webApi.session(),
      webApi.login("admin", "password", "csrf"),
      webApi.logout("csrf"),
      webApi.status(),
      webApi.settings(),
      webApi.updateManagedSettings({ theme_preference: "dark" }, "csrf"),
      webApi.onboardingChecklist("csrf"),
      webApi.dismissOnboarding("csrf"),
      webApi.coreUpdateTour(),
      webApi.updateCoreUpdateTour("in_progress", "dashboard", "csrf"),
      webApi.pending(),
      webApi.updateTargets(),
      webApi.cleanupPending("cleanup", [{ line_no: 1, raw: "repo/app:1.0" }], "csrf"),
      webApi.createRemovalPlan([1], "csrf"),
      webApi.removeSelectedPending("removal", [{ line_no: 1, raw: "repo/app:1.0" }], "csrf"),
      webApi.servicePolicies(),
      webApi.snoozes("active"),
      webApi.tagExclusions("active"),
      webApi.stateOperation(operation, "csrf"),
      webApi.selfUpdate(),
      webApi.applySelfUpdate("csrf", selfUpdateStatus()),
      webApi.restartContainer("csrf"),
      webApi.createPlan([1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.createJob("plan", [1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.applyPlan("plan", [1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.job("job"),
      webApi.applyJob("job"),
      webApi.runs(),
      webApi.runDetail(1),
      webApi.runLog(1),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(34);
    for (const call of fetchMock.mock.calls) {
      expect(requestInit(call).credentials).toBe("include");
    }
  });

  it("sends csrf headers on mutating requests", async () => {
    const fetchMock = mockFetch({});
    const operation: StateOperation = {
      kind: "delete_snooze",
      snooze_id: 2,
    };

    await webApi.setupClaim("claim", "admin", "password", "csrf-token");
    await webApi.resetAdminClaim("claim", "admin", "password", "csrf-token");
    await webApi.login("admin", "password", "csrf-token");
    await webApi.logout("csrf-token");
    await webApi.updateManagedSettings({ theme_preference: "dark" }, "csrf-token");
    await webApi.onboardingChecklist("csrf-token");
    await webApi.dismissOnboarding("csrf-token");
    await webApi.updateCoreUpdateTour(
      "in_progress",
      "pending_select",
      "csrf-token",
    );
    await webApi.cleanupPending(
      "cleanup",
      [{ line_no: 1, raw: "repo/app:1.0" }],
      "csrf-token",
    );
    await webApi.createRemovalPlan([1], "csrf-token");
    await webApi.removeSelectedPending(
      "removal",
      [{ line_no: 1, raw: "repo/app:1.0" }],
      "csrf-token",
    );
    await webApi.stateOperation(operation, "csrf-token");
    await webApi.applySelfUpdate("csrf-token", selfUpdateStatus());
    await webApi.restartContainer("csrf-token");
    await webApi.createPlan([1], false, [], "csrf-token");
    await webApi.createJob("plan", [1], false, [], "csrf-token");
    await webApi.applyPlan("plan", [1], false, [], "csrf-token");

    for (const call of fetchMock.mock.calls) {
      const headers = requestInit(call).headers as Headers;
      expect(headers.get("x-wud-csrf-token")).toBe("csrf-token");
    }
  });

  it("serializes cleanup, plan, and job payloads exactly", async () => {
    const fetchMock = mockFetch({});
    const tagOverrides = [{ line_no: 4, tag: "2.0" }];

    await webApi.cleanupPending(
      "cleanup-id",
      [{ line_no: 3, raw: "repo/old:latest" }],
      "csrf",
    );
    await webApi.createRemovalPlan([3], "csrf");
    await webApi.removeSelectedPending(
      "removal-id",
      [{ line_no: 3, raw: "repo/old:latest" }],
      "csrf",
    );
    await webApi.updateManagedSettings(
      { theme_preference: "dark", onboarding_checklist: "dismissed" },
      "csrf",
    );
    await webApi.updateCoreUpdateTour("in_progress", "pending_preflight", "csrf");
    await webApi.applySelfUpdate("csrf", selfUpdateStatus());
    await webApi.restartContainer("csrf");
    await webApi.createPlan([4], true, tagOverrides, "csrf");
    await webApi.createJob("plan-id", [4], true, tagOverrides, "csrf");
    await webApi.applyPlan("plan-id", [4], true, tagOverrides, "csrf");

    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[0]).body))).toEqual({
      cleanup_id: "cleanup-id",
      lines: [{ line_no: 3, raw: "repo/old:latest" }],
      confirmation: "remove_unmatched",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[1]).body))).toEqual({
      line_numbers: [3],
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[2]).body))).toEqual({
      removal_id: "removal-id",
      lines: [{ line_no: 3, raw: "repo/old:latest" }],
      confirmation: "remove_selected",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[3]).body))).toEqual({
      values: {
        theme_preference: "dark",
        onboarding_checklist: "dismissed",
      },
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[4]).body))).toEqual({
      status: "in_progress",
      step: "pending_preflight",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[5]).body))).toEqual({
      confirmation: "pull_image_and_restart",
      current_tag: "v0.24.2",
      latest_tag: "v0.25.0",
      target_image: "ghcr.io/magrhino/wud-updater:v0.25.0",
      restart_container: "wud-updater",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[6]).body))).toEqual({
      confirmation: "restart_container",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[7]).body))).toEqual({
      line_numbers: [4],
      allow_tag_updates: true,
      tag_overrides: tagOverrides,
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[8]).body))).toEqual({
      plan_id: "plan-id",
      line_numbers: [4],
      allow_tag_updates: true,
      tag_overrides: tagOverrides,
      confirmation: "apply",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[9]).body))).toEqual({
      plan_id: "plan-id",
      line_numbers: [4],
      allow_tag_updates: true,
      tag_overrides: tagOverrides,
      confirmation: "apply",
    });
  });

  it("opens job streams with browser credentials", () => {
    const constructed: Array<{ url: string; init: EventSourceInit }> = [];
    class MockEventSource {
      constructor(url: string, init: EventSourceInit) {
        constructed.push({ url, init });
      }
    }
    vi.stubGlobal("EventSource", MockEventSource);

    webApi.openJobStream("job id");

    expect(constructed).toEqual([
      {
        url: "/api/v1/jobs/job%20id/stream?log_tail_bytes=65536",
        init: { withCredentials: true },
      },
    ]);
  });

  it("surfaces backend error details", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "denied" }, 403));
    vi.stubGlobal("fetch", fetchMock);

    await expect(webApi.status()).rejects.toEqual(new ApiError(403, "denied"));
  });
});
