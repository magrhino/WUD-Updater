import { describe, expect, it, vi } from "vitest";

import { ApiError, webApi, type StateOperation } from "../src/api/client";

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

describe("webApi", () => {
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
      webApi.session(),
      webApi.login("admin", "password", "csrf"),
      webApi.logout("csrf"),
      webApi.status(),
      webApi.pending(),
      webApi.servicePolicies(),
      webApi.snoozes("active"),
      webApi.tagExclusions("active"),
      webApi.stateOperation(operation, "csrf"),
      webApi.createPlan([1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.createJob("plan", [1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.applyPlan("plan", [1], true, [{ line_no: 1, tag: "1.1" }], "csrf"),
      webApi.job("job"),
      webApi.applyJob("job"),
      webApi.runs(),
      webApi.runDetail(1),
      webApi.runLog(1),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(20);
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
    await webApi.login("admin", "password", "csrf-token");
    await webApi.logout("csrf-token");
    await webApi.stateOperation(operation, "csrf-token");
    await webApi.createPlan([1], false, [], "csrf-token");
    await webApi.createJob("plan", [1], false, [], "csrf-token");
    await webApi.applyPlan("plan", [1], false, [], "csrf-token");

    for (const call of fetchMock.mock.calls) {
      const headers = requestInit(call).headers as Headers;
      expect(headers.get("x-wud-csrf-token")).toBe("csrf-token");
    }
  });

  it("serializes plan and job payloads exactly", async () => {
    const fetchMock = mockFetch({});
    const tagOverrides = [{ line_no: 4, tag: "2.0" }];

    await webApi.createPlan([4], true, tagOverrides, "csrf");
    await webApi.createJob("plan-id", [4], true, tagOverrides, "csrf");
    await webApi.applyPlan("plan-id", [4], true, tagOverrides, "csrf");

    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[0]).body))).toEqual({
      line_numbers: [4],
      allow_tag_updates: true,
      tag_overrides: tagOverrides,
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[1]).body))).toEqual({
      plan_id: "plan-id",
      line_numbers: [4],
      allow_tag_updates: true,
      tag_overrides: tagOverrides,
      confirmation: "apply",
    });
    expect(JSON.parse(String(requestInit(fetchMock.mock.calls[2]).body))).toEqual({
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
        url: "/api/v1/jobs/job%20id/stream",
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
