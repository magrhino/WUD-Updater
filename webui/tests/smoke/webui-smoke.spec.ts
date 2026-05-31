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
  const item = {
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
  };
  const groupedItem = {
    ...item,
    resolved_image: "repo/app:1.0",
    target_image: "repo/app:1.1",
    compose_images: ["repo/app:1.0"],
    services: ["app"],
    action: "tag-update",
  };
  return {
    source_file: "/out/images.todo",
    exists: true,
    count: 1,
    warnings: [],
    items: [item],
    grouping: {
      status: "ready",
      groups: [
        {
          name: "media",
          directory: "/docker/media",
          compose_file: "docker-compose.yml",
          project_directory: "/docker/media",
          services_label: "app",
          services: ["app"],
          line_numbers: [1],
          items: [groupedItem],
        },
      ],
      unmatched: [],
      warnings: [],
    },
  };
}

function updateTargetsResponse() {
  return {
    status: "ready",
    count: 1,
    warnings: [],
    items: [
      {
        service_key: "media/app",
        stack: "media",
        service: "app",
        image: "repo/app:1.0",
        image_repo: "repo/app",
        current_tag: "1.0",
        directory: "/docker/media",
        compose_file: "docker-compose.yml",
        project_directory: "/docker/media",
      },
    ],
  };
}

function releaseNotesResponse() {
  return {
    source_file: "/out/images.todo",
    count: 1,
    warnings: [],
    items: [
      {
        line_no: 1,
        status: "ready",
        provider: "github",
        image_repo: "repo/app",
        upstream_repo: "repo/app",
        release_tag: "v1.1",
        title: "v1.1",
        published_at: "2026-01-02T00:00:00Z",
        breaking: true,
        breaking_reasons: ["Release notes mention a migration."],
        links: [
          {
            label: "GitHub release",
            url: "https://github.com/repo/app/releases/tag/v1.1",
            kind: "github_release",
          },
        ],
        refreshed_at: "2026-01-02T00:00:00Z",
        error: "",
      },
    ],
  };
}

function planResponse(overrides: Record<string, unknown> = {}) {
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
    cleanup: {
      cleanup_id: "",
      can_remove_unmatched: false,
      items: [],
    },
    ...overrides,
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

function runSummary() {
  return {
    id: 7,
    started_at: "2026-05-28T12:00:00+00:00",
    finished_at: "2026-05-28T12:00:01+00:00",
    status: "success",
    dry_run: false,
    mode: "stop",
    wud_file: "/out/images.todo",
    log_file: "/out/logs/job-smoke.log",
    metadata: { source: "webui" },
  };
}

function runDetail() {
  return {
    ...runSummary(),
    pending_updates: [
      {
        id: 70,
        run_id: 7,
        line_no: 1,
        raw: "repo/app:1.0 tag=1.1",
        image: "repo/app:1.0",
        target_digest: "",
        desired_tag: "1.1",
        service_key: "media/app",
        stack_name: "media",
        service_name: "app",
        status: "resolved",
        status_reason: "updated by smoke fixture",
        created_at: "2026-05-28T12:00:00+00:00",
        updated_at: "2026-05-28T12:00:01+00:00",
        metadata: {},
      },
    ],
    events: [
      {
        id: 71,
        run_id: 7,
        created_at: "2026-05-28T12:00:01+00:00",
        service_name: "app",
        stack_name: "media",
        image: "repo/app:1.0",
        target_image: "repo/app:1.1",
        old_image_id: "sha256:old",
        new_image_id: "sha256:new",
        old_digest: "sha256:old",
        new_digest: "sha256:new",
        status: "success",
        metadata: {},
      },
    ],
  };
}

function runLog() {
  return {
    run_id: 7,
    log_file: "/out/logs/job-smoke.log",
    exists: true,
    content: "[2026-05-28T12:00:01+00:00] Done.\\n",
    truncated: false,
    max_bytes: 262144,
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
      timezone: "UTC",
      auto_update_scheduler_enabled: state.mutationsEnabled,
      static_spa_available: true,
      warnings: [],
    });
    return;
  }
  if (path === "/api/v1/pending") {
    await json(route, pendingResponse());
    return;
  }
  if (path === "/api/v1/update-targets") {
    await json(route, updateTargetsResponse());
    return;
  }
  if (path === "/api/v1/release-notes") {
    await json(route, releaseNotesResponse());
    return;
  }
  if (path === "/api/v1/release-notes/refresh" && method === "POST") {
    await json(route, releaseNotesResponse());
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
    await json(route, [runSummary()]);
    return;
  }
  if (path === "/api/v1/runs/7") {
    await json(route, runDetail());
    return;
  }
  if (path === "/api/v1/runs/7/log") {
    await json(route, runLog());
    return;
  }
  if (path === "/api/v1/plans" && method === "POST") {
    await json(route, planResponse({ can_apply: state.mutationsEnabled }));
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
      body: [
        `event: log\ndata: ${JSON.stringify({
          job_id: "job-smoke",
          log_file: "/out/logs/job-smoke.log",
          exists: true,
          content: "[2026-05-28T12:00:00+00:00] [INFO] docker-update-from-wud-v2\n",
          truncated: false,
          max_bytes: 65536,
          error: "",
        })}\n\n`,
        `event: job\ndata: ${JSON.stringify(jobResponse("success"))}\n\n`,
      ].join(""),
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

async function sidebarForegroundStyles(page: Page, selector: string) {
  return page.locator(selector).evaluate((element) => {
    const normalizeColor = (value: string) => {
      const probe = document.createElement("span");
      probe.style.color = value;
      document.body.append(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    };
    const rootStyles = getComputedStyle(document.documentElement);
    return {
      color: getComputedStyle(element).color,
      sidebarText: normalizeColor(
        rootStyles.getPropertyValue("--color-sidebar-text").trim(),
      ),
      surface: normalizeColor(
        rootStyles.getPropertyValue("--color-surface").trim(),
      ),
    };
  });
}

async function expectSidebarForegroundToken(page: Page, selector: string) {
  await expect
    .poll(async () => {
      const styles = await sidebarForegroundStyles(page, selector);
      return (
        styles.color === styles.sidebarText && styles.color !== styles.surface
      );
    })
    .toBe(true);
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

test("read-only pending flow can preflight a stack but cannot apply", async ({ page }) => {
  const state = createState({ authenticated: true, mutationsEnabled: false });
  await installApiFixtures(page, state);

  await page.goto("/#/pending");
  await page.getByRole("checkbox", { name: /Select stack media/ }).check();
  await page.getByRole("button", { name: /Preview selected plan/ }).click();

  await expect(page.getByText("Read-only mode is active").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review media plan" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Apply 1 update/ })).toHaveCount(0);
  expect(state.calls.some((call) => call.path === "/api/v1/plans")).toBe(true);
  expect(state.calls.some((call) => call.path === "/api/v1/jobs")).toBe(false);
});

test("mutation-enabled pending flow applies and links to run details", async ({
  page,
}) => {
  const state = createState({ authenticated: true, mutationsEnabled: true });
  await installApiFixtures(page, state);

  await page.goto("/#/pending");
  await page.locator('summary[aria-label="Details for media"]').click();
  await expect(
    page.getByRole("textbox", { name: "New tag for repo/app:1.0" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Preview media plan/ }).click();

  await expect(page.getByRole("heading", { name: "Review media plan" })).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Apply 1 update/ })
    .click();

  const applyDialog = page.getByRole("dialog").filter({
    hasText: "Apply complete",
  });
  await expect(
    applyDialog.getByRole("heading", { name: "Apply complete" }),
  ).toBeVisible();
  await expect(applyDialog.getByText("docker-update-from-wud-v2")).toBeVisible();
  await expect(applyDialog.getByRole("link", { name: "Details" })).toBeVisible();
  await expect(applyDialog.getByRole("link", { name: "Log" })).toBeVisible();
  expect(state.calls.some((call) => call.path === "/api/v1/jobs")).toBe(true);
  expect(
    state.calls.some((call) =>
      call.path.startsWith("/api/v1/jobs/job-smoke/stream?"),
    ),
  ).toBe(true);

  await applyDialog.getByRole("link", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "#7" })).toBeVisible();
  await expect(page.getByText("Pending records")).toBeVisible();

  await page.getByRole("link", { name: "View log" }).click();
  await expect(page.getByRole("heading", { name: "#7 log" })).toBeVisible();
  await expect(page.getByText("Done.")).toBeVisible();
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

  await page.goto("/#/pending");
  await expect(page.getByRole("checkbox", { name: /Select stack media/ })).toBeVisible();
  await page.getByText("Details").first().click();
  await expect(page.getByText("Possible breaking change")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => ({
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ innerWidth: 390, scrollWidth: 390 });
});

test("theme toggle follows system dark mode and cycles preferences", async ({
  page,
}) => {
  const state = createState({ authenticated: true, mutationsEnabled: false });
  await page.emulateMedia({ colorScheme: "dark" });
  await installApiFixtures(page, state);

  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--color-body-bg")
          .trim(),
      ),
    )
    .toBe("#0f171a");
  await expectSidebarForegroundToken(page, ".nav-item.router-link-active");

  await page.getByRole("button", { name: /System theme/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectSidebarForegroundToken(page, ".nav-item.router-link-active");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("theme-preference")))
    .toBe("light");

  await page.getByRole("button", { name: /Light theme/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("theme-preference")))
    .toBe("dark");

  await page.getByRole("button", { name: /Dark theme/ }).click();
  await expect(page.getByRole("button", { name: /System theme/ })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("theme-preference")))
    .toBe("auto");
  await expect.poll(() => sensitiveStorageKeys(page)).toEqual({
    local: [],
    session: [],
  });
});

test("login mark uses sidebar foreground token in light and dark themes", async ({
  page,
}) => {
  const state = createState();
  await page.emulateMedia({ colorScheme: "dark" });
  await installApiFixtures(page, state);

  await page.goto("/#/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expectSidebarForegroundToken(page, ".login-mark");

  await page.evaluate(() => localStorage.setItem("theme-preference", "light"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectSidebarForegroundToken(page, ".login-mark");
});

test("mutation-enabled pending flow creates jobs only after confirmation", async ({
  page,
}) => {
  const state = createState({ authenticated: true, mutationsEnabled: true });
  await installApiFixtures(page, state);

  await page.goto("/#/pending");
  await page.getByRole("checkbox", { name: /Select stack media/ }).check();
  await page.getByRole("button", { name: /Preview selected plan/ }).click();
  await expect(page.getByRole("heading", { name: "Review media plan" })).toBeVisible();

  const dialog = page.getByRole("dialog").filter({
    hasText: "Review media plan",
  });
  await expect(dialog).toBeVisible();
  expect(state.calls.some((call) => call.path === "/api/v1/jobs")).toBe(false);

  await dialog.getByRole("button", { name: "Apply 1 update" }).click();

  const planCall = state.calls.find((call) => call.path === "/api/v1/plans");
  const jobCall = state.calls.find((call) => call.path === "/api/v1/jobs");
  expect(planCall?.headers["x-wud-csrf-token"]).toBe(csrfToken);
  expect(planCall?.body).toMatchObject({
    line_numbers: [1],
    allow_tag_updates: true,
  });
  expect(jobCall?.headers["x-wud-csrf-token"]).toBe(csrfToken);
  expect(jobCall?.body).toMatchObject({
    plan_id: "plan-smoke",
    line_numbers: [1],
    allow_tag_updates: true,
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
