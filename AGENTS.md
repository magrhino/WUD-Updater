# AGENTS.md

## Scope

Repo-local routing/context only for WUD-Updater. Global instructions control default behavior, commits, security, validation, and final response format unless this file gives a more specific repo-local rule.

## Context Budget

- Start with `Path map`; read only rows relevant to the task.
- Prefer `rg`, targeted file reads, manifest reads, and nearby examples.
- If editing a path with a nested `AGENTS.md`, read that file before editing.
- Avoid broad tree reads.

## Path Map

| Path | Purpose | Read first | Edit notes | Avoid unless required |
|---|---|---|---|---|
| `bin/updates` | Host CLI wrapper that displays WUD Docker updates, TrueNAS update status, alerts, and optionally calls the updater. | `README.md`, `bin/docker-update-from-wud` usage block. | Preserve prompt, `--dry-run`, `--yes`, config-file, `sudo`, and updater handoff behavior. | TrueNAS `midclt` handling unless the task targets system update or alert checks. |
| `bin/docker-update-from-wud` | Symlink-safe dispatcher for the default Python updater. | `README.md`, `src/wud_updater/cli.py`, `src/wud_updater/updater.py`, and dispatcher tests. | Keep argument pass-through exact; preserve `PYTHON_BIN` and `PYTHONPATH` behavior. | Adding updater logic here instead of in Python. |
| `pyproject.toml`, `src/wud_updater/` | Default Python updater package plus the opt-in Python `updates` wrapper. | `pyproject.toml`, `src/wud_updater/cli.py`, relevant Python module, and relevant Python tests. | Keep `wud-updater updates` opt-in until promoted separately. | Moving WUD callback scripts out of shell. |
| `webui/` | Vue 3/Vite/TypeScript SPA for the read-only WebUI. | `webui/package.json`, `src/wud_updater/web.py`, `tests/test_python_web.py`, and relevant Vue view/store files. | Keep auth/session state out of localStorage; use the typed API client and Pinia stores; prefer read-only views unless mutation work is explicitly requested. | Adding mutation UX without matching backend CSRF/origin, read-only-mode, and audit tests. |
| `wud/on-update.sh`, `wud/append-updates.sh` | WUD notification callback and line-oriented update-list writer. | Both files plus WUD env variable usage. | Keep POSIX `sh` compatibility and container defaults for `/wud` and `/out`. | Host-specific paths, secrets, or behavior that belongs in `bin/`. |
| `wud/tag-manager.sh`, `wud/github-release-embed.sh`, `wud/release-notes-to-discord.sh`, `wud/http.sh`, `wud/upstreams.txt` | Discord/GitHub release-note helpers, shared HTTP behavior, and LinuxServer.io upstream mapping. | The called helper; for `wud/github-release-embed.sh`, inspect args, router, and relevant provider section first; read `wud/http.sh` for release-note curl behavior and `wud/upstreams.txt` when mapping is involved. | Keep webhook/token values environment-driven and redacted in logs. Preserve standardized `curl`/`jq` based GitHub and Discord behavior. | Network calls unless validating release-note behavior. |
| `install.sh` | Idempotent installer that chmods scripts and creates host symlinks for CLI commands and WUD scripts. | `install.sh`, then README install section. | Preserve refusal to replace non-symlink targets and existing env overrides. | Changing default target layout unless the task asks for installer behavior changes. |
| `Dockerfile`, `entrypoint.sh`, `docs/examples/docker-compose.example.yml`, `docs/examples/docker-compose.hardened.yml`, `docs/examples/docker-compose.truenas.yml`, `docs/examples/docker-compose.build.yml`, `.dockerignore` | Container packaging for running the updater helpers with Docker CLI access and optional TrueNAS API reachability. | `README.md`, `docs/DEPLOYMENT.md`, `entrypoint.sh`, `bin/updates`, `bin/docker-update-from-wud`. | Keep the default command non-mutating, preserve command dispatch, keep Docker socket or socket-proxy access and host stack mounts explicit, and keep TrueNAS API keys secret-file based in examples. | Replacing WUD's separate `/wud` script mount or baking version-specific TrueNAS clients into the default image. |
| `tests/` | Local test runner, focused shell tests, Python config tests, fake command implementations, and Docker E2E harnesses. | `tests/run-all.sh`, then the focused test for the behavior being changed. | Keep tests temp-dir based; fake Docker for default tests; reserve real Docker mutations for explicit Docker-gated harnesses such as `tests/e2e-docker-compose.sh`; keep Python dev dependencies explicit in `pyproject.toml`. | Adding dependencies or broad fixtures when a small shell fake, unittest, or Docker-gated E2E fixture is enough. |
| `.github/workflows/ci.yml` | Cost-conscious CI for PRs to `main`, pushes to `main`, optional macOS/Docker checks, Docker E2E, and workflow linting. | `tests/run-all.sh`, `tests/container-build.sh`, `tests/e2e-docker-compose.sh`, workflow file. | Keep default CI Linux-only; keep macOS gated by `ci:macos` or manual dispatch; keep Docker build gated by `ci:docker`, manual dispatch, or image-impacting path changes; keep Docker E2E separate and gated by `ci:e2e`, manual dispatch, or image-impacting path changes. | Scheduled workflows, broad matrices, caches, artifacts, or always-on macOS/Docker jobs unless explicitly requested. |
| `.github/workflows/security.yml`, `.github/CODEOWNERS`, `.github/zizmor.yml` | Security scanning suite, sensitive-path ownership, and GitHub Actions audit policy. | Existing workflow/release workflow rows plus the security files. | Keep PR-blocking jobs high-signal; skip GHAS-backed scans while the repo is private; keep Scorecard advisory; preserve readable Action version tags unless policy changes. | Repo-setting assumptions that cannot be enforced from files alone. |
| `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/*.yml` | GitHub PR and issue intake templates. | Existing template file, README, and docs terms relevant to the changed question. | Keep prompts concise, repo-specific, actionable, and free of secrets or machine-specific paths. | Workflow changes unless the task targets CI behavior. |
| `.github/workflows/release-please.yml`, `release-please-config.json`, `.release-please-manifest.json` | Release Please automation that opens release PRs, bumps Python version files and changelog entries, and creates `vX.Y.Z` GitHub releases/tags. | Release Please config and manifest, `.github/workflows/release.yml`, `pyproject.toml`, `src/wud_updater/__init__.py`, `CHANGELOG.md`. | Keep tag names compatible with `vX.Y.Z`; use the configured Release Please token secret so release-created tags trigger publishing workflows. | Manual manifest edits after bootstrap unless repairing release automation state. |
| `.github/workflows/release.yml` | Tag-driven release workflow that validates, builds the Docker image, publishes GHCR tags, and creates a GitHub Release. | `README.md` release notes, `Dockerfile`, `tests/run-all.sh`, workflow file. | Keep releases limited to stable `vX.Y.Z` tags and single-platform Linux amd64 image publishing unless requested otherwise. | Extra registries, prerelease tag handling, multi-arch builds, or package publishing outside GHCR unless requested. |
| `README.md`, `docs/` | User-facing overview, deployment reference, examples, and feature explainers. | Scripts being described, plus `docs/README.md` for docs routing. | Keep concise, accurate, and free of secrets or machine-specific paths. Keep root README as the short entrypoint and detailed references under `docs/`. | Operational assumptions not present in code. |
| `CHANGELOG.md` | Release-time record of notable versioned changes. | `CHANGELOG.md`, recent commits since the previous tag, and changed user-facing docs. | Author versioned `## [vX.Y.Z] — YYYY-MM-DD` sections only during explicit release prep. | Ordinary feature, docs, or maintenance work outside release prep. |
| `template.env` | Example host and optional WUD environment configuration. | `template.env`, then the script consuming the changed variable. | Keep values example-only, environment-driven, and free of real secrets or machine-specific paths. | Adding new knobs not supported by scripts or README examples. |
| `.gitignore` | Ignore rules for local logs, temp files, WUD output, and desktop metadata. | `.gitignore` only. | Keep generated/runtime data out of Git. | Broad ignore patterns that could hide source files. |

## Task Routing

- Host CLI/updater behavior: inspect the relevant `bin/` entrypoint, direct helper functions, and README usage examples.
- WUD callback behavior: inspect `wud/on-update.sh`, `wud/append-updates.sh`, WUD env assumptions, and Python parser compatibility.
- Release notes, Discord, or GitHub behavior: inspect `wud/tag-manager.sh`, `wud/github-release-embed.sh`, `wud/release-notes-to-discord.sh`, `wud/http.sh`, and `wud/upstreams.txt`.
- Release automation behavior: inspect Release Please config/manifest, `.github/workflows/release-please.yml`, `.github/workflows/release.yml`, and version/changelog files.
- Install behavior: inspect `install.sh`, `.gitignore` if generated paths change, and README install/mount sections.
- Container packaging behavior: inspect `Dockerfile`, `entrypoint.sh`, the relevant `docs/examples/docker-compose*.yml` file, README Docker usage, deployment docs, and the entrypoint test.
- Config or docs behavior: inspect the exact changed file plus the script that consumes or demonstrates it.
- Changelog maintenance: leave `CHANGELOG.md` alone during ordinary feature and docs work; update it only when explicitly preparing a release.
- Test-only work: inspect the target behavior and nearest script style; avoid production edits unless needed.
- Bug fix: inspect the reproduction path, the owning script, and a nearby similar branch or function before editing.

## Key Invariants

- WUD output is a line-oriented file of image/container targets; blank and comment lines are ignored, and optional `sha256=` digest suffixes must stay compatible with the Python updater path.
- Mutating Docker operations require explicit confirmation or `--yes`; `--dry-run` must not pull, restart, clean the WUD file, or otherwise mutate host state.
- Secrets such as Discord webhooks and GitHub tokens must come from the environment or host-local config and must not be logged in full.
- Container-facing scripts assume `/wud` for mounted scripts and `/out` for WUD output; host paths belong in install/config, not hard-coded into container scripts.

## Repo Commands

Use the shell already used by the target script.

| Purpose | Command |
|---|---|
| install | `./install.sh` |
| lint | `ruff check .` and `shellcheck install.sh bin/updates bin/docker-update-from-wud wud/*.sh` |
| Bash syntax check | `bash -n install.sh bin/updates bin/docker-update-from-wud wud/tag-manager.sh wud/http.sh wud/github-release-embed.sh wud/release-notes-to-discord.sh` |
| POSIX syntax check | `sh -n wud/on-update.sh wud/append-updates.sh` |
| updater dry run | `bin/docker-update-from-wud --base "$DOCKER_BASE" --file "$WUD_OUT_FILE" --dry-run` |
| host status dry run | `bin/updates --dry-run` |
| GitHub Actions lint | `actionlint` |
| GitHub Actions security scan | `zizmor --config .github/zizmor.yml --min-severity high --min-confidence medium .github/workflows` |
| Release Please config JSON check | `python3 -m json.tool release-please-config.json` and `python3 -m json.tool .release-please-manifest.json` |
| full local test suite | `tests/run-all.sh` |
| updater behavior tests | `tests/test-docker-update-from-wud.sh` |
| WUD append tests | `tests/test-wud-append-updates.sh` |
| GitHub release-note embed tests | `tests/test-github-release-embed.sh` |
| release-note payload tests | `tests/test-release-notes-to-discord.sh` |
| release-note router tests | `tests/test-tag-manager.sh` |
| installer tests | `tests/test-install.sh` |
| host wrapper tests | `tests/test-updates-wrapper.sh` |
| container entrypoint tests | `tests/test-entrypoint.sh` |
| container build test | `tests/container-build.sh` |
| Docker Compose E2E test | `tests/e2e-docker-compose.sh` |
| deployment compose config check | `docker compose -f docs/examples/docker-compose.example.yml config` |
| hardened deployment compose config check | `docker compose -f docs/examples/docker-compose.hardened.yml config` |
| TrueNAS API deployment compose config check | `docker compose -f docs/examples/docker-compose.truenas.yml config` |
| local build compose config check | `docker compose -f docs/examples/docker-compose.build.yml config` |
| container image build | `docker build -t wud-updater:local .` |
| Python dev dependency install | Check for `.venv/bin/python` first and activate it when present; otherwise run `python3 -m venv .venv`, `. .venv/bin/activate`, then `python -m pip install -e '.[dev]'` |
| Python lint | `ruff check .` |
| Python syntax check | `python3 -m py_compile src/wud_updater/*.py tests/run-python-tests.py tests/test_python_*.py` |
| Python tests | `python3 tests/run-python-tests.py` |
| WebUI dependency install | `npm --prefix webui ci` |
| WebUI typecheck | `npm --prefix webui run typecheck` |
| WebUI build | `npm --prefix webui run build` |
| typecheck | Python typecheck is not configured; WebUI typecheck uses `npm --prefix webui run typecheck`. |
| unit tests | `tests/run-all.sh` |
| build | WebUI build uses `npm --prefix webui run build`; container image build uses `docker build -t wud-updater:local .`. |
| format check | Not configured. |

## Validation Selection

- Shell script change: run syntax checks for the touched shell dialect first, then ShellCheck and the focused test for the touched behavior.
- Updater behavior change: run `tests/test-docker-update-from-wud.sh`; prefer fake Docker tests and `--dry-run` validation with disposable or known-safe WUD input before any mutating run.
- WUD append behavior change: run `tests/test-wud-append-updates.sh`; use a temporary `WUD_OUT_FILE` and representative WUD env vars.
- Installer change: run `tests/test-install.sh`; tests should use temp env overrides for `BIN_DIR`, `DOCKER_BASE`, `WUD_SCRIPTS_LINK`, and `WUD_OUT_DIR`.
- Host wrapper change: run `tests/test-updates-wrapper.sh`; fake `sudo` and configured updater commands rather than invoking real system mutation.
- Container packaging change: run `bash -n entrypoint.sh`, ShellCheck through `tests/run-all.sh`, `tests/test-entrypoint.sh`, and `tests/container-build.sh` when Docker is available. Run `tests/e2e-docker-compose.sh` when Docker socket, updater handoff, WUD script sync, or real Compose update behavior changes. The container build test validates Compose config, including the TrueNAS API example, builds the image, and smoke-runs the default non-mutating command; the Docker E2E test uses a local registry and real Compose stack to verify update and callback wiring.
- Release-note behavior change: syntax-check the touched scripts, run ShellCheck, run `tests/test-github-release-embed.sh`, `tests/test-release-notes-to-discord.sh`, and `tests/test-tag-manager.sh` when Discord payload or release-note routing changes, and avoid live Discord/GitHub calls unless explicitly requested or needed.
- Python updater/config change: run `ruff check .`, Python syntax check, `tests/run-python-tests.py`, and `tests/run-all.sh` when practical.
- Rich terminal rendering change: create or update focused tests that exercise the Rich-enabled path for the touched surface, using mocks when local Rich is unavailable; run `python3 -m unittest tests.test_python_terminal` plus Python syntax checks before broader suites.
- WebUI frontend change: run `npm --prefix webui ci`, `npm --prefix webui run typecheck`, `npm --prefix webui run build`, and `tests/test_python_web.py` when API contracts or auth assumptions are involved. Run `tests/container-build.sh` when packaged static assets, Dockerfile behavior, or container startup changes.
- GitHub Actions workflow change: run `actionlint` when available; if not installed, inspect the touched workflow YAML and report that local actionlint was not available. For release workflow changes, also inspect tag, permission, and GHCR image-tag behavior.
- Security workflow change: run `actionlint` when available, `git diff --check`, `tests/run-all.sh`, and the local `zizmor` command when installed; verify CodeQL, Dependency Review, and SARIF uploads in the first GitHub run after the repository is public or GHAS-backed scanning is enabled.
- GitHub template change: validate issue-template YAML when practical, run `git diff --check`, and skip application tests unless executable examples or commands changed.
- Release Please config change: validate `release-please-config.json` and `.release-please-manifest.json` as JSON, run `actionlint` when workflow files change, and verify tag naming stays compatible with `.github/workflows/release.yml`.
- Cross-cutting behavior change: run `tests/run-all.sh` when practical before finishing.
- Docs-only change: no tests required unless examples or commands were changed enough to need syntax validation.
- Unknown command: inspect scripts/docs, then prefer extending `tests/run-all.sh` or a focused `tests/test-*.sh` instead of inventing a separate harness.

## Maintenance Notes

- When adding a top-level file, script, test harness, workflow, or user-facing config surface, update `Path Map`, `Repo Commands`, and `Validation Selection` in the same change when relevant.
- During release prep, draft `CHANGELOG.md` from commits since the previous tag and group entries by user-visible impact (`Added`, `Changed`, `Fixed`, `Docs`, `Removed`, or `Internal` as appropriate).

## Local Summaries

- `bin/`: Host commands for reviewing WUD output and dispatching the default Python updater.
- `src/wud_updater/`: Default Python updater package plus the opt-in Python host wrapper.
- `webui/`: Vue/Vite SPA for login, dashboard, pending updates, run history, and logs.
- `wud/`: Container-mounted callback scripts for collecting WUD updates and optionally posting GitHub release notes to Discord.
- `install.sh`: Host setup helper that creates symlinks and executable bits without replacing existing non-symlink targets.
- `tests/`: Shell-based local and CI validation using temp directories, fake external commands, and a Docker-gated Compose E2E harness.
- `.github/workflows/ci.yml`: Runs default Linux CI plus opt-in macOS, Docker build, Docker E2E, and workflow lint checks.
- `.github/workflows/security.yml`, `.github/CODEOWNERS`, `.github/zizmor.yml`: Runs high-signal security checks and owns sensitive CI/release paths.
- `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/`: PR and issue intake templates for contributors.
- `.github/workflows/release-please.yml`: Runs Release Please on `main` to maintain release PRs and create release tags.
- `.github/workflows/release.yml`: Publishes GHCR Docker images and creates GitHub Releases from stable `vX.Y.Z` tags.
- `README.md`: Concise user guide for install, mounts, usage, and local config.
- `CHANGELOG.md`: Tracks notable changes at release time using versioned sections.
- `Dockerfile`, `entrypoint.sh`, `docs/examples/docker-compose.example.yml`, `docs/examples/docker-compose.hardened.yml`, `docs/examples/docker-compose.truenas.yml`, `docs/examples/docker-compose.build.yml`: Optional container packaging that runs the existing shell helpers against mounted host Docker resources and can opt into remote TrueNAS API checks.

## Generated/Low-Value Paths

Do not read or edit unless directly required.

- `.DS_Store`
- `*.log`
- `*.tmp`
- `out/`
- WUD runtime output such as `images.todo`

## Nested AGENTS Suggestions

No nested `AGENTS.md` files are currently suggested; the repository is small enough for this root guide. Add nested files only when a directory grows enough that local rules can replace, not duplicate, root detail.

## Edit Discipline

- Identify the owning path from `Path map` before editing.
- Read nearest implementation and test examples first.
- Make the smallest correct change.
- Do not normalize formatting outside touched lines.
- Do not move code across directories unless requested.
- If multiple areas are touched, re-check whether nested `AGENTS.md` files apply.
