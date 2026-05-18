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
| `wud/on-update.sh`, `wud/append-updates.sh` | WUD notification callback and line-oriented update-list writer. | Both files plus WUD env variable usage. | Keep POSIX `sh` compatibility and container defaults for `/wud` and `/out`. | Host-specific paths, secrets, or behavior that belongs in `bin/`. |
| `wud/tag-manager.sh`, `wud/lsio-release-embed.sh`, `wud/release-notes-to-discord.sh`, `wud/upstreams.txt` | Discord/GitHub release-note helpers and LinuxServer.io upstream mapping. | The called helper; for `wud/lsio-release-embed.sh`, inspect args, router, and relevant provider section first; read `wud/upstreams.txt` when mapping is involved. | Keep webhook/token values environment-driven and redacted in logs. Preserve `curl`/`jq` based GitHub and Discord behavior. | Network calls unless validating release-note behavior. |
| `install.sh` | Idempotent installer that chmods scripts and creates host symlinks for CLI commands and WUD scripts. | `install.sh`, then README install section. | Preserve refusal to replace non-symlink targets and existing env overrides. | Changing default target layout unless the task asks for installer behavior changes. |
| `Dockerfile`, `entrypoint.sh`, `docs/examples/docker-compose.example.yml`, `docs/examples/docker-compose.hardened.yml`, `docs/examples/docker-compose.build.yml`, `.dockerignore` | Container packaging for running the updater helpers with Docker CLI access. | `README.md`, `docs/DEPLOYMENT.md`, `entrypoint.sh`, `bin/updates`, `bin/docker-update-from-wud`. | Keep the default command non-mutating, preserve command dispatch, and keep Docker socket or socket-proxy access and host stack mounts explicit in examples. | Replacing WUD's separate `/wud` script mount. |
| `tests/` | Local test runner, focused shell tests, Python config tests, and fake command implementations. | `tests/run-all.sh`, then the focused test for the behavior being changed. | Keep tests temp-dir based and fake external commands; never call real Docker mutations; keep Python dev dependencies explicit in `pyproject.toml`. | Adding dependencies or broad fixtures when a small shell fake or unittest is enough. |
| `.github/workflows/ci.yml` | Cost-conscious CI for PRs to `main`, pushes to `main`, optional macOS/Docker checks, and workflow linting. | `tests/run-all.sh`, `tests/container-build.sh`, workflow file. | Keep default CI Linux-only; keep macOS gated by `ci:macos` or manual dispatch; keep Docker gated by `ci:docker`, manual dispatch, or image-impacting path changes. | Scheduled workflows, broad matrices, caches, artifacts, or always-on macOS/Docker jobs unless explicitly requested. |
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
- Release notes, Discord, or GitHub behavior: inspect `wud/tag-manager.sh`, `wud/lsio-release-embed.sh`, `wud/release-notes-to-discord.sh`, and `wud/upstreams.txt`.
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
| Bash syntax check | `bash -n install.sh bin/updates bin/docker-update-from-wud wud/tag-manager.sh wud/lsio-release-embed.sh wud/release-notes-to-discord.sh` |
| POSIX syntax check | `sh -n wud/on-update.sh wud/append-updates.sh` |
| updater dry run | `bin/docker-update-from-wud --base "$DOCKER_BASE" --file "$WUD_OUT_FILE" --dry-run` |
| host status dry run | `bin/updates --dry-run` |
| GitHub Actions lint | `actionlint` |
| Release Please config JSON check | `python3 -m json.tool release-please-config.json` and `python3 -m json.tool .release-please-manifest.json` |
| full local test suite | `tests/run-all.sh` |
| updater behavior tests | `tests/test-docker-update-from-wud.sh` |
| WUD append tests | `tests/test-wud-append-updates.sh` |
| release-note payload tests | `tests/test-release-notes-to-discord.sh` |
| installer tests | `tests/test-install.sh` |
| host wrapper tests | `tests/test-updates-wrapper.sh` |
| container entrypoint tests | `tests/test-entrypoint.sh` |
| container build test | `tests/container-build.sh` |
| deployment compose config check | `docker compose -f docs/examples/docker-compose.example.yml config` |
| hardened deployment compose config check | `docker compose -f docs/examples/docker-compose.hardened.yml config` |
| local build compose config check | `docker compose -f docs/examples/docker-compose.build.yml config` |
| container image build | `docker build -t wud-updater:local .` |
| Python dev dependency install | `python3 -m venv .venv`, `. .venv/bin/activate`, then `python -m pip install -e '.[dev]'` |
| Python lint | `ruff check .` |
| Python syntax check | `python3 -m py_compile src/wud_updater/*.py tests/run-python-tests.py tests/test_python_*.py` |
| Python tests | `python3 tests/run-python-tests.py` |
| typecheck | Not configured; shell scripts only. |
| unit tests | `tests/run-all.sh` |
| build | Not configured. |
| format check | Not configured. |

## Validation Selection

- Shell script change: run syntax checks for the touched shell dialect first, then ShellCheck and the focused test for the touched behavior.
- Updater behavior change: run `tests/test-docker-update-from-wud.sh`; prefer fake Docker tests and `--dry-run` validation with disposable or known-safe WUD input before any mutating run.
- WUD append behavior change: run `tests/test-wud-append-updates.sh`; use a temporary `WUD_OUT_FILE` and representative WUD env vars.
- Installer change: run `tests/test-install.sh`; tests should use temp env overrides for `BIN_DIR`, `DOCKER_BASE`, `WUD_SCRIPTS_LINK`, and `WUD_OUT_DIR`.
- Host wrapper change: run `tests/test-updates-wrapper.sh`; fake `sudo` and configured updater commands rather than invoking real system mutation.
- Container packaging change: run `bash -n entrypoint.sh`, ShellCheck through `tests/run-all.sh`, `tests/test-entrypoint.sh`, and `tests/container-build.sh` when Docker is available. The container build test validates Compose config, builds the image, and smoke-runs the default non-mutating command.
- Release-note behavior change: syntax-check the touched scripts, run ShellCheck, run `tests/test-release-notes-to-discord.sh` when Discord payload or release-note behavior changes, and avoid live Discord/GitHub calls unless explicitly requested or needed.
- Python updater/config change: run `ruff check .`, Python syntax check, `tests/run-python-tests.py`, and `tests/run-all.sh` when practical.
- GitHub Actions workflow change: run `actionlint` when available; if not installed, inspect the touched workflow YAML and report that local actionlint was not available. For release workflow changes, also inspect tag, permission, and GHCR image-tag behavior.
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
- `wud/`: Container-mounted callback scripts for collecting WUD updates and optionally posting GitHub release notes to Discord.
- `install.sh`: Host setup helper that creates symlinks and executable bits without replacing existing non-symlink targets.
- `tests/`: Shell-based local and CI validation using temp directories and fake external commands.
- `.github/workflows/ci.yml`: Runs default Linux CI plus opt-in macOS, Docker build, and workflow lint checks.
- `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/`: PR and issue intake templates for contributors.
- `.github/workflows/release-please.yml`: Runs Release Please on `main` to maintain release PRs and create release tags.
- `.github/workflows/release.yml`: Publishes GHCR Docker images and creates GitHub Releases from stable `vX.Y.Z` tags.
- `README.md`: Concise user guide for install, mounts, usage, and local config.
- `CHANGELOG.md`: Tracks notable changes at release time using versioned sections.
- `Dockerfile`, `entrypoint.sh`, `docs/examples/docker-compose.example.yml`, `docs/examples/docker-compose.hardened.yml`, `docs/examples/docker-compose.build.yml`: Optional container packaging that runs the existing shell helpers against mounted host Docker resources.

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
