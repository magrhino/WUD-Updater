const { danger, markdown, schedule, warn } = require("danger");

const changedFiles = unique([
  ...danger.git.created_files,
  ...danger.git.modified_files,
  ...danger.git.deleted_files,
]);
const editedFiles = unique([...danger.git.created_files, ...danger.git.modified_files]);
const pr = danger.github?.pr ?? {};
const prBody = pr.body ?? "";
const prBodyLower = prBody.toLowerCase();
const prTitle = pr.title ?? "";
const prAuthor = pr.user?.login ?? "";
const globCache = new Map();

const releasePleaseBranch =
  typeof pr.head?.ref === "string" &&
  pr.head.ref.startsWith("release-please--branches--");
const releasePleaseTitle = /^chore: release \d+\.\d+\.\d+ \[skip ci\]/i.test(
  prTitle,
);
const dependencyBot =
  prAuthor === "dependabot[bot]" ||
  prAuthor === "app/dependabot" ||
  prAuthor === "renovate[bot]";

if (releasePleaseBranch || releasePleaseTitle || dependencyBot) {
  markdown(
    "Danger maintainability review skipped for release automation or dependency bot PR.",
  );
} else {
  runCompanionTestRules();
  runReviewPromptRules();
  schedule(async () => {
    await runDiffContentRules();
    await runLargeFileRules();
  });
}

function runCompanionTestRules() {
  warnWhenNoCompanionTests({
    marker: "frontend-api-tests-not-needed",
    title: "Frontend API or store contract changed without companion tests.",
    changed: [
      "webui/src/api/**",
      "webui/src/stores/**",
      "webui/src/composables/**",
    ],
    tests: [
      "webui/tests/**",
      "tests/test_python_web*.py",
    ],
    detail:
      "Update the matching Vitest/API/store coverage, backend contract tests, or add `Danger: frontend-api-tests-not-needed` with the reason.",
  });

  warnWhenNoCompanionTests({
    marker: "webui-mutation-tests-not-needed",
    title:
      "Auth, CSRF, read-only, scheduler, or mutation UX files changed without guard tests.",
    changed: [
      "src/wud_updater/web.py",
      "src/wud_updater/web_auth.py",
      "src/wud_updater/web_diagnostics.py",
      "src/wud_updater/web_jobs.py",
      "src/wud_updater/web_pending.py",
      "src/wud_updater/web_plans.py",
      "src/wud_updater/web_retags.py",
      "src/wud_updater/web_scheduler.py",
      "src/wud_updater/web_self_update.py",
      "src/wud_updater/web_settings.py",
      "src/wud_updater/web_state.py",
      "webui/src/stores/auth.ts",
      "webui/src/stores/connection.ts",
      "webui/src/stores/settings.ts",
      "webui/src/stores/updates.ts",
      "webui/src/views/PendingView.vue",
      "webui/src/views/PoliciesView.vue",
      "webui/src/views/RetagsView.vue",
      "webui/src/views/SettingsView.vue",
      "webui/src/views/SnoozesView.vue",
      "webui/src/views/TagExclusionsView.vue",
      "webui/src/views/pending/**",
      "webui/src/views/settings/**",
      "webui/src/components/app/AppSelfUpdate*.vue",
      "webui/src/components/pending/**",
      "webui/src/components/retags/**",
    ],
    tests: [
      "tests/test_python_web_apply_endpoint_guards.py",
      "tests/test_python_web_auth_*.py",
      "tests/test_python_web_jobs.py",
      "tests/test_python_web_pending_*.py",
      "tests/test_python_web_retags.py",
      "tests/test_python_web_scheduler_*.py",
      "tests/test_python_web_self_update_*.py",
      "tests/test_python_web_state_operations.py",
      "webui/tests/auth-store.test.ts",
      "webui/tests/connection-store.test.ts",
      "webui/tests/pending-view-*.test.ts",
      "webui/tests/RetagsView.test.ts",
      "webui/tests/settings-mutation-views.test.ts",
      "webui/tests/settings-store.test.ts",
      "webui/tests/updates-store.test.ts",
    ],
    detail:
      "Recent reviews caught missing read-only/mutation guards. Add focused auth/CSRF/read-only tests or add `Danger: webui-mutation-tests-not-needed` with the reason.",
  });

  warnWhenNoCompanionTests({
    marker: "compose-rewrite-tests-not-needed",
    title: "Compose rewrite, digest, or tag logic changed without focused tests.",
    changed: [
      "src/wud_updater/compose_rewrite.py",
      "src/wud_updater/compose.py",
      "src/wud_updater/digest_provenance.py",
      "src/wud_updater/digest_verifier.py",
      "src/wud_updater/images.py",
      "src/wud_updater/plan_actions.py",
      "src/wud_updater/plan_*.py",
      "src/wud_updater/plan_digest_unpin.py",
      "src/wud_updater/plan_matching.py",
      "src/wud_updater/plans.py",
      "src/wud_updater/updater_digest*.py",
      "src/wud_updater/updater_lifecycle_digest.py",
      "src/wud_updater/updater_lifecycle_rewrite.py",
      "src/wud_updater/updater_models.py",
      "src/wud_updater/updater_runner_*.py",
      "src/wud_updater/updater_tag_exclusions.py",
      "src/wud_updater/wud_file.py",
      "webui/src/utils/digestProvenance.ts",
    ],
    tests: [
      "tests/test_python_compose_*.py",
      "tests/test_python_digest_verifier.py",
      "tests/test_python_update_from_wud_*digest*.py",
      "tests/test_python_update_from_wud_*tag*.py",
      "tests/test_python_wud_parsing.py",
    ],
    detail:
      "Digest/tag rewrites are rollback-sensitive. Add focused compose/updater coverage or add `Danger: compose-rewrite-tests-not-needed` with the reason.",
  });

  warnWhenNoCompanionTests({
    marker: "demo-fixture-tests-not-needed",
    title: "Static demo API or fixture state changed without demo tests.",
    changed: [
      "webui/src/api/demo/**",
      "webui/scripts/seed_demo_state.py",
      "tests/test_python_webui_demo_state.py",
    ],
    tests: [
      "webui/tests/demo-api.test.ts",
      "webui/tests/static-security.test.ts",
      "tests/test_python_webui_demo_state.py",
    ],
    detail:
      "Recent review feedback caught broad fixture replacements and duplicate cleanup handling. Add demo coverage or add `Danger: demo-fixture-tests-not-needed` with the reason.",
  });

  warnWhenNoCompanionTests({
    marker: "responsive-tests-not-needed",
    title: "Responsive breakpoint code changed without responsive or smoke tests.",
    changed: [
      "webui/src/responsive.ts",
      "webui/src/assets/styles/responsive.css",
      "webui/src/assets/styles/foundation.css",
    ],
    tests: [
      "webui/tests/responsive.test.ts",
      "webui/tests/smoke/**",
    ],
    detail:
      "Recent reviews caught JS/CSS breakpoint parity issues. Add responsive coverage, a smoke check, or add `Danger: responsive-tests-not-needed` with the reason.",
  });
}

function runReviewPromptRules() {
  const dockerFiles = changedMatching([
    ".dockerignore",
    "Dockerfile",
    "entrypoint.sh",
    "docs/examples/docker-compose*.yml",
    "src/wud_updater/compose.py",
    "src/wud_updater/digest_verifier.py",
    "src/wud_updater/docker_cli.py",
    "src/wud_updater/doctor.py",
    "src/wud_updater/plan_actions.py",
    "src/wud_updater/self_update.py",
    "src/wud_updater/updates.py",
    "src/wud_updater/updater_cli.py",
    "src/wud_updater/updater_lifecycle*.py",
    "src/wud_updater/updater_runner_*.py",
    "src/wud_updater/web_health.py",
    "src/wud_updater/web_jobs.py",
    "src/wud_updater/web_scheduler.py",
    "src/wud_updater/web_self_update.py",
    "bin/docker-update-from-wud",
    "bin/updates",
    "tests/container-build.sh",
    "tests/e2e-docker-compose.sh",
    "tests/test-entrypoint.sh",
  ]);

  if (
    dockerFiles.length > 0 &&
    !acknowledged("docker-review-complete") &&
    !hasCheckedDockerValidation()
  ) {
    warn(
      [
        "Docker, Compose, or socket-adjacent files changed. Confirm Docker/Compose validation in the PR test plan, or add `Danger: docker-review-complete` with the reason.",
        "",
        `Changed: ${formatFiles(dockerFiles)}`,
      ].join("\n"),
    );
  }

  const publicConfigFiles = changedMatching([
    "AGENTS.md",
    ".github/CODEOWNERS",
    ".github/workflows/**",
    "dangerfile.js",
    "pyproject.toml",
    "template.env",
    "docs/examples/*.env*",
  ]);

  if (publicConfigFiles.length > 0 && !acknowledged("config-review-complete")) {
    warn(
      [
        "Review repo-facing configuration changes for path privacy, pinned actions, and documented validation.",
        "",
        `Changed: ${formatFiles(publicConfigFiles)}`,
        "",
        "Add `Danger: config-review-complete` if the review is complete and no further issue is needed.",
      ].join("\n"),
    );
  }
}

async function runDiffContentRules() {
  await warnOnNewRoutes();
  await warnOnDemoReplaceAll();
  await warnOnResponsiveSmaller();
  await warnOnVueLabelWrappingControl();
  await warnOnDockerSocketText();
}

async function warnOnNewRoutes() {
  if (!editedFiles.includes("src/wud_updater/web.py")) {
    return;
  }

  const added = await addedLinesForFile("src/wud_updater/web.py");
  const routeAdded = added.some((line) => {
    return (
      /\b(add_api_route|include_router|APIRouter)\b/.test(line) ||
      /["']\/api\/v1\//.test(line)
    );
  });

  if (!routeAdded || acknowledged("route-review-complete")) {
    return;
  }

  warn(
    [
      "New or changed WebUI route wiring detected. Confirm auth, CSRF/Origin, read-only mode, audit behavior, and matching backend/frontend tests.",
      "",
      "Add `Danger: route-review-complete` if this route review is complete.",
    ].join("\n"),
  );
}

async function warnOnDemoReplaceAll() {
  const demoFiles = changedMatching(["webui/src/api/demo/**"], editedFiles);
  for (const file of demoFiles) {
    const added = await addedLinesForFile(file);
    if (
      added.some((line) => /\.replaceAll\(/.test(line)) &&
      !acknowledged("demo-replacement-review-complete")
    ) {
      warn(
        [
          `\`${file}\` adds \`replaceAll\` in demo fixture code. Prefer generated unique tokens over replacing raw tag/version strings globally.`,
          "",
          "Add `Danger: demo-replacement-review-complete` if broad replacement is intentional and covered.",
        ].join("\n"),
      );
    }
  }
}

async function warnOnResponsiveSmaller() {
  if (
    !editedFiles.includes("webui/src/responsive.ts") ||
    acknowledged("responsive-breakpoint-review-complete")
  ) {
    return;
  }

  const added = await addedLinesForFile("webui/src/responsive.ts");
  if (added.some((line) => /\.smaller\(/.test(line))) {
    warn(
      [
        "`webui/src/responsive.ts` adds a VueUse `smaller()` breakpoint. CSS `max-width` custom media is inclusive, so use `smallerOrEqual()` or document the intentional boundary difference.",
        "",
        "Add `Danger: responsive-breakpoint-review-complete` if reviewed.",
      ].join("\n"),
    );
  }
}

async function warnOnVueLabelWrappingControl() {
  if (acknowledged("vue-label-association-review-complete")) {
    return;
  }

  const vueFiles = changedMatching(["webui/src/**/*.vue"], editedFiles);
  for (const file of vueFiles) {
    const added = await addedLinesForFile(file);
    const addedText = added.join("\n");
    if (/<label[\s>]/.test(addedText) && /<n-(switch|checkbox|radio|select|input)\b/.test(addedText)) {
      warn(
        [
          `\`${file}\` adds a label around a Naive UI form control. Confirm the control has reliable accessible naming via \`for\`/\`id\`, \`aria-labelledby\`, or \`aria-label\`.`,
          "",
          "Add `Danger: vue-label-association-review-complete` if reviewed.",
        ].join("\n"),
      );
    }
  }
}

async function warnOnDockerSocketText() {
  if (acknowledged("docker-socket-review-complete")) {
    return;
  }

  for (const file of editedFiles.filter((path) => !isIgnoredLargeFile(path))) {
    const added = await addedLinesForFile(file);
    const touchedSocket = added.some((line) => {
      return /DOCKER_HOST|docker\.sock|\/var\/run\/docker\.sock|socket-proxy|docker compose/i.test(
        line,
      );
    });
    if (touchedSocket) {
      warn(
        [
          `\`${file}\` adds Docker/socket-adjacent text. Confirm socket-proxy/raw-socket assumptions, read-only defaults, and Docker validation.`,
          "",
          "Add `Danger: docker-socket-review-complete` if reviewed.",
        ].join("\n"),
      );
    }
  }
}

async function runLargeFileRules() {
  if ((pr.additions ?? 0) <= 300 || acknowledged("large-file-review-complete")) {
    return;
  }

  for (const file of editedFiles.filter((path) => !isIgnoredLargeFile(path))) {
    const added = (await addedLinesForFile(file)).length;
    if (added > 300) {
      warn(
        [
          `\`${file}\` grew by ${added} added lines in this PR.`,
          "",
          "Consider splitting the file, extracting a narrow helper, or opening a follow-up issue. Add `Danger: large-file-review-complete` if the growth is intentional.",
        ].join("\n"),
      );
    }
  }
}

function warnWhenNoCompanionTests({ marker, title, changed, tests, detail }) {
  const files = changedMatching(changed, editedFiles);
  if (files.length === 0 || changedMatching(tests, editedFiles).length > 0) {
    return;
  }
  if (acknowledged(marker)) {
    return;
  }

  warn(
    [
      title,
      "",
      `Changed: ${formatFiles(files)}`,
      `Expected companion tests: ${tests.map((test) => `\`${test}\``).join(", ")}`,
      "",
      detail,
    ].join("\n"),
  );
}

async function addedLinesForFile(file) {
  const diff = await danger.git.structuredDiffForFile(file);
  const chunks = Array.isArray(diff?.chunks) ? diff.chunks : [];
  return chunks.flatMap((chunk) => {
    const changes = Array.isArray(chunk.changes) ? chunk.changes : [];
    return changes
      .filter((change) => change.type === "add" || change.type === "new")
      .map((change) => change.content ?? change.line ?? "")
      .filter((line) => typeof line === "string");
  });
}

function hasCheckedDockerValidation() {
  return /-\s+\[x\]\s+docker or compose validation/i.test(prBody);
}

function acknowledged(marker) {
  return prBodyLower.includes(`danger: ${marker}`.toLowerCase());
}

function changedMatching(patterns, files = changedFiles) {
  return files.filter((file) => matchesAny(file, patterns));
}

function matchesAny(file, patterns) {
  return patterns.some((pattern) => globToRegex(pattern).test(file));
}

function globToRegex(glob) {
  if (!globCache.has(glob)) {
    let pattern = "";
    for (let index = 0; index < glob.length; index += 1) {
      const char = glob[index];
      const next = glob[index + 1];
      if (char === "*" && next === "*") {
        pattern += ".*";
        index += 1;
      } else if (char === "*") {
        pattern += "[^/]*";
      } else {
        pattern += escapeRegex(char);
      }
    }
    globCache.set(glob, new RegExp(`^${pattern}$`));
  }
  return globCache.get(glob);
}

function escapeRegex(value) {
  return value.replace(/[|\\{}()[\]^$+?.]/g, "\\$&");
}

function isIgnoredLargeFile(file) {
  return (
    file.endsWith("package-lock.json") ||
    file === "dangerfile.js" ||
    file.startsWith(".github/") ||
    file.startsWith("webui/dist/") ||
    file.startsWith("webui/coverage/") ||
    file.includes("/__pycache__/") ||
    file.endsWith(".pyc") ||
    file === "CHANGELOG.md"
  );
}

function formatFiles(files) {
  return files
    .slice(0, 8)
    .map((file) => `\`${file}\``)
    .join(", ")
    .concat(files.length > 8 ? `, and ${files.length - 8} more` : "");
}

function unique(values) {
  return [...new Set(values)];
}
