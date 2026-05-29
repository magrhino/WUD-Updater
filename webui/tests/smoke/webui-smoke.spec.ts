import { expect, test, type Page, type Route } from "@playwright/test";

type ApiCall = {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
};

type FixtureState = {
  authenticated: boolean;
  mutationsEnabled: boolean;
  calls: ApiCall[];
};

const appOrigin = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173";
const csrfToken = "csrf-smoke";

function authSession(state: FixtureState) {
  return {
    authenticated: state.authenticated,
    setup_required: false,
    auth_required: true,
    dev_auth_bypass: false,
    mutations_enabled: state.mutationsEnabled,
    username: state.authenticated ? "admin" : null,
  };
}

function pendingResponse() {
  return {
    source_file: "/out/images.todo",
    exists: true,
    count: 1,
    warnings: [],
    items: [
      {
        line_no: 1,
        raw: "repo/app:1.0",
        image: "repo/app:1.0",
        key: "repo/app",
        repo: "repo/app",
        current_tag: "1.0",
        has_tag: true,
        allow_repo: false,
        digest: "",
        desired_tag: "1.1",
      },
    ],
  };
}

function planResponse() {
  return {
    plan_id: "plan-smoke",
    dry_run: true,
    can_apply: true,
    status: "ready",
    source_file: "/out/images.todo",
    mode: "stop",
    max_wait: 120,
    selected_line_numbers: [1],
    summary: {
      target_count: 1,
      matched_target_count: 1,
      stack_count: 1,
      service_count: 1,
      skipped_count: 0,
      issue_count: 0,
    },
    targets: [],
    stacks: [
      {
        name: "media",
        directory: "/docker/media",
        compose_file: "docker-compose.yml",
        project_directory: "/docker/media",
        services_label: "app",
        services: ["app"],
        pull_services: ["app"],
        stop_services: ["app"],
        force_recreate: false,
        up_no_deps: true,
        tag_updates: [],
        actions: [
          {
            kind: "pull",
            description: "pull app",
            cwd: "/docker/media",
            args: ["docker", "compose", "pull", "app"],
          },
        ],
        lines: [
          {
            line_no: 1,
            raw: "repo/app:1.0",
            image: "repo/app:1.0",
            resolved_image: "repo/app:1.0",
            compose_image: "repo/app:1.0",
            target_image: "repo/app:1.1",
            service: "app",
            digest: "",
            desired_tag: "1.1",
            action: "update",
          },
        ],
      },
    ],
    skipped: [],
    issues: [],
  };
}

function jobResponse(status = "queued") {
  return {
    job_id: "job-smoke",
    status,
    run_id: status === "success" ? 7 : null,
    log_file: status === "success" ? "/out/logs/job-smoke.log" : "",
    started_at: "2026-05-28T12:00:00+00:00",
    finished_at: status === "success" ? "2026-05-28T12:00:01+00:00" : null,
    error: "",
    selected_line_numbers: [1],
  };
}

async function installApiFixtures(page: Page, state: FixtureState) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== appOrigin) {
      await route.abort();
      return;
    }
    if (!url.pathname.startsWith("/api/v1/")) {
      await route.continue();
      return;
    }

    const bodyText = request.postData();
    const call: ApiCall = {
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      headers: request.headers(),
      body: bodyText ? JSON.parse(bodyText) : null,
    };
    state.calls.push(call);

    await fulfillApi(route, state, url.pathname, request.method());
  });
}

async function fulfillApi(
  route: Route,
  state: FixtureState,
  path: string,
  method: string,
) {
  if (path === "/api/v1/auth/csrf") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "set-cookie": `wud_csrf_token=${csrfToken}; Path=/; SameSite=Lax`,
      },
      body: JSON.stringify({ csrf_token: csrfToken }),
    });
    return;
  }
  if (path === "/api/v1/auth/session") {
    await json(route, authSession(state));
    return;
  }
  if (path === "/api/v1/auth/login" && method === "POST") {
    state.authenticated = true;
    await json(route, authSession(state));
    return;
  }
  if (path === "/api/v1/auth/logout" && method === "POST") {
    state.authenticated = false;
    await json(route, authSession(state));
    return;
  }
  if (path === "/api/v1/status") {
    await json(route, {
      ok: true,
      version: "test",
      wud_file: "/out/images.todo",
      wud_file_exists: true,
      pending_count: 1,
      db_path: "/out/wud.sqlite",
      db_ready: true,
      auth_required: true,
      dev_auth_bypass: false,
      setup_required: false,
      mutations_enabled: state.mutationsEnabled,
      static_spa_available: true,
      warnings: [],
    });
    return;
  }
  if (path === "/api/v1/pending") {
    await json(route, pendingResponse());
    return;
  }
  if (path === "/api/v1/service-policies") {
    await json(route, []);
    return;
  }
  if (path === "/api/v1/snoozes") {
    await json(route, []);
    return;
  }
  if (path === "/api/v1/tag-exclusions") {
    await json(route, []);
    return;
  }
  if (path === "/api/v1/runs") {
    await json(route, []);
    return;
  }
  if (path === "/api/v1/plans" && method === "POST") {
    await json(route, planResponse());
    return;
  }
  if (path === "/api/v1/jobs" && method === "POST") {
    await json(route, jobResponse());
    return;
  }
  if (path === "/api/v1/jobs/job-smoke/stream") {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: job\ndata: ${JSON.stringify(jobResponse("success"))}\n\n`,
    });
    return;
  }
  if (path === "/api/v1/jobs/job-smoke") {
    await json(route, jobResponse("success"));
    return;
  }

  await route.fulfill({
    status: 404,
    contentType: "application/json",
    body: JSON.stringify({ detail: `unhandled fixture route: ${method} ${path}` }),
  });
}

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function createState(overrides: Partial<FixtureState> = {}): FixtureState {
  return {
    authenticated: false,
    mutationsEnabled: false,
    calls: [],
    ...overrides,
  };
}

async function sensitiveStorageKeys(page: Page) {
  return page.evaluate(() => ({
    local: Object.keys(localStorage).filter((key) =>
      /(auth|csrf|password|session|token|wud)/i.test(key),
    ),
    session: Object.keys(sessionStorage).filter((key) =>
      /(auth|csrf|password|session|token|wud)/i.test(key),
    ),
  }));
}

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

test("unauthenticated protected routes redirect to login", async ({ page }) => {
  const state = createState();
  await installApiFixtures(page, state);

  await page.goto("/#/pending");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("login requests csrf and does not store secrets in browser storage", async ({ page }) => {
  const state = createState();
  await installApiFixtures(page, state);

  await page.goto("/#/login");
  await page.getByRole("textbox").nth(0).fill("admin");
  await page.getByRole("textbox").nth(1).fill("password");
  await page.getByRole("button", { name: /Sign in/ }).click();

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  expect(state.calls.map((call) => call.path)).toContain("/api/v1/auth/csrf");
  expect(state.calls.map((call) => call.path)).toContain("/api/v1/auth/login");
  await expect.poll(() => sensitiveStorageKeys(page)).toEqual({
    local: [],
    session: [],
  });
});

test("read-only pending view cannot plan or apply selected updates", async ({ page }) => {
  const state = createState({ authenticated: true, mutationsEnabled: false });
  await installApiFixtures(page, state);

  await page.goto("/#/pending");
  await page.getByRole("button", { name: /Select all/ }).click();

  await expect(page.getByText("Read-only mode is active")).toBeVisible();
  await expect(page.getByRole("button", { name: /Update selected/ })).toBeDisabled();
  expect(state.calls.some((call) => call.path === "/api/v1/plans")).toBe(false);
});

test("mobile shell keeps page width stable and preserves link targets", async ({
  page,
}) => {
  const state = createState({ authenticated: true, mutationsEnabled: false });
  await page.setViewportSize({ width: 390, height: 844 });
  await installApiFixtures(page, state);

  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await expect(page.locator(".brand")).toHaveAttribute(
    "aria-label",
    "WUD-Updater dashboard",
  );
  await expect
    .poll(() =>
      page.evaluate(() => ({
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ innerWidth: 390, scrollWidth: 390 });

  const pendingLinkBox = await page
    .locator('a.text-link[href="#/pending"]')
    .boundingBox();
  const historyLinkBox = await page
    .locator('a.text-link[href="#/runs"]')
    .boundingBox();
  expect(pendingLinkBox?.height).toBeGreaterThanOrEqual(44);
  expect(historyLinkBox?.height).toBeGreaterThanOrEqual(44);
});

test("mutation-enabled pending flow creates jobs only after confirmation", async ({
  page,
}) => {
  const state = createState({ authenticated: true, mutationsEnabled: true });
  await installApiFixtures(page, state);

  await page.goto("/#/pending");
  await page.getByRole("button", { name: /Select all/ }).click();
  await page.getByRole("button", { name: /Update selected/ }).click();

  const dialog = page.getByRole("dialog").filter({
    hasText: "Apply selected updates",
  });
  await expect(dialog).toBeVisible();
  expect(state.calls.some((call) => call.path === "/api/v1/jobs")).toBe(false);

  await dialog.getByRole("button", { name: "Apply" }).click();

  const planCall = state.calls.find((call) => call.path === "/api/v1/plans");
  const jobCall = state.calls.find((call) => call.path === "/api/v1/jobs");
  expect(planCall?.headers["x-wud-csrf-token"]).toBe(csrfToken);
  expect(jobCall?.headers["x-wud-csrf-token"]).toBe(csrfToken);
  expect(jobCall?.body).toMatchObject({
    plan_id: "plan-smoke",
    line_numbers: [1],
    confirmation: "apply",
  });
});

test("logout returns to login and leaves storage empty", async ({ page }) => {
  const state = createState({ authenticated: true });
  await installApiFixtures(page, state);

  await page.goto("/");
  await page.getByRole("button", { name: /Sign out/ }).click();

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(state.calls.map((call) => call.path)).toContain("/api/v1/auth/logout");
  await expect.poll(() => sensitiveStorageKeys(page)).toEqual({
    local: [],
    session: [],
  });
});
