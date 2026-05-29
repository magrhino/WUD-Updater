import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../src/stores/auth";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sessionBody(overrides: Record<string, unknown> = {}) {
  return {
    authenticated: true,
    setup_required: false,
    auth_required: true,
    dev_auth_bypass: false,
    mutations_enabled: false,
    username: "admin",
    ...overrides,
  };
}

function responseQueue(...bodies: unknown[]) {
  const fetchMock = vi.fn();
  for (const body of bodies) {
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps csrf in memory, reuses it, and clears it on logout", async () => {
    const fetchMock = responseQueue(
      { csrf_token: "csrf-one" },
      sessionBody(),
      sessionBody(),
      sessionBody({ authenticated: false, username: null }),
      { csrf_token: "csrf-two" },
      sessionBody(),
    );
    const storageSet = vi.spyOn(Storage.prototype, "setItem");
    const auth = useAuthStore();

    await auth.login("admin", "password");
    await auth.login("admin", "password");
    await auth.logout();
    await auth.login("admin", "password");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/auth/csrf",
      "/api/v1/auth/login",
      "/api/v1/auth/login",
      "/api/v1/auth/logout",
      "/api/v1/auth/csrf",
      "/api/v1/auth/login",
    ]);
    expect(
      ((fetchMock.mock.calls[1][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-one");
    expect(
      ((fetchMock.mock.calls[2][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-one");
    expect(
      ((fetchMock.mock.calls[5][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-two");
    expect(storageSet).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("fetches csrf before setup claim", async () => {
    const fetchMock = responseQueue({ csrf_token: "claim-csrf" }, sessionBody());
    const auth = useAuthStore();

    await auth.claimSetup("claim", "admin", "password");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/auth/csrf",
      "/api/v1/setup/claim",
    ]);
    const claimRequest = fetchMock.mock.calls[1][1] as RequestInit;
    expect((claimRequest.headers as Headers).get("x-wud-csrf-token")).toBe(
      "claim-csrf",
    );
  });

  it("sets loading false and surfaces request errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "authentication required" }, 403),
    );
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();

    await expect(auth.loadSession()).resolves.toBeUndefined();

    expect(auth.loading).toBe(false);
    expect(auth.session).toBeNull();
    expect(auth.error).toBe("authentication required");
  });
});
