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
| `bin/updates` | Host CLI wrapper that displays WUD Docker updates, TrueNAS update status, alerts, and optionally calls the updater. | `README.md`, `bin/docker-update-from-wud` usage block. | Preserve prompt, `--dry-run`, `--yes`, config-file, and `sudo` behavior. | TrueNAS `midclt` handling unless the task targets system update or alert checks. |
| `bin/docker-update-from-wud` | Main host updater: parses WUD targets, discovers compose stacks, pulls/recreates services or stacks, waits for health, and cleans processed WUD lines. | Usage block, argument parser, target parsing, matching, update, health, and cleanup functions near the requested change. | Preserve confirmation before mutation, dry-run behavior, digest checks, logging, health gates, and WUD file cleanup semantics. | Running against real Docker stacks without `--dry-run` unless explicitly requested. |
| `wud/on-update.sh`, `wud/append-updates.sh` | WUD notification callback and line-oriented update-list writer. | Both files plus WUD env variable usage. | Keep POSIX `sh` compatibility and container defaults for `/wud` and `/out`. | Host-specific paths, secrets, or behavior that belongs in `bin/`. |
| `wud/tag-manager.sh`, `wud/lsio-release-embed.sh`, `wud/release-notes-to-discord.sh`, `wud/upstreams.txt` | Discord/GitHub release-note helpers and LinuxServer.io upstream mapping. | The called helper and `wud/upstreams.txt` when mapping is involved. | Keep webhook/token values environment-driven and redacted in logs. Preserve `curl`/`jq` based GitHub and Discord behavior. | Network calls unless validating release-note behavior. |
| `install.sh` | Idempotent installer that chmods scripts and creates host symlinks for CLI commands and WUD scripts. | `install.sh`, then README install section. | Preserve refusal to replace non-symlink targets and existing env overrides. | Changing default target layout unless the task asks for installer behavior changes. |
| `README.md` | User-facing overview, install, WUD mount, usage, and config notes. | Scripts being described. | Keep concise, accurate, and free of secrets or machine-specific paths. | Operational assumptions not present in code. |
| `.gitignore` | Ignore rules for local logs, temp files, WUD output, and desktop metadata. | `.gitignore` only. | Keep generated/runtime data out of Git. | Broad ignore patterns that could hide source files. |

## Task Routing

- Host CLI/updater behavior: inspect the relevant `bin/` entrypoint, direct helper functions, and README usage examples.
- WUD callback behavior: inspect `wud/on-update.sh`, `wud/append-updates.sh`, WUD env assumptions, and `bin/docker-update-from-wud` parser compatibility.
- Release notes, Discord, or GitHub behavior: inspect `wud/tag-manager.sh`, `wud/lsio-release-embed.sh`, `wud/release-notes-to-discord.sh`, and `wud/upstreams.txt`.
- Install behavior: inspect `install.sh`, `.gitignore` if generated paths change, and README install/mount sections.
- Config or docs behavior: inspect the exact changed file plus the script that consumes or demonstrates it.
- Test-only work: inspect the target behavior and nearest script style; avoid production edits unless needed.
- Bug fix: inspect the reproduction path, the owning script, and a nearby similar branch or function before editing.

## Key Invariants

- WUD output is a line-oriented file of image/container targets; blank and comment lines are ignored, and optional `sha256=` digest suffixes must stay compatible with `bin/docker-update-from-wud`.
- Mutating Docker operations require explicit confirmation or `--yes`; `--dry-run` must not pull, restart, clean the WUD file, or otherwise mutate host state.
- Secrets such as Discord webhooks and GitHub tokens must come from the environment or host-local config and must not be logged in full.
- Container-facing scripts assume `/wud` for mounted scripts and `/out` for WUD output; host paths belong in install/config, not hard-coded into container scripts.

## Repo Commands

Use the shell already used by the target script.

| Purpose | Command |
|---|---|
| install | `./install.sh` |
| lint | `shellcheck install.sh bin/updates bin/docker-update-from-wud wud/*.sh` |
| Bash syntax check | `bash -n install.sh bin/updates bin/docker-update-from-wud wud/tag-manager.sh wud/lsio-release-embed.sh wud/release-notes-to-discord.sh` |
| POSIX syntax check | `sh -n wud/on-update.sh wud/append-updates.sh` |
| updater dry run | `bin/docker-update-from-wud --base "$DOCKER_BASE" --file "$WUD_OUT_FILE" --dry-run` |
| host status dry run | `bin/updates --dry-run` |
| typecheck | Not configured; shell scripts only. |
| unit tests | Not configured. |
| build | Not configured. |
| format check | Not configured. |

## Validation Selection

- Shell script change: run syntax checks for the touched shell dialect first; run ShellCheck if available.
- Updater behavior change: prefer a `--dry-run` validation with disposable or known-safe WUD input before any mutating run.
- WUD append behavior change: validate with a temporary `WUD_OUT_FILE` and representative WUD env vars when practical.
- Installer change: syntax-check `install.sh`; if behavior changed, run it with temp env overrides for `BIN_DIR`, `DOCKER_BASE`, `WUD_SCRIPTS_LINK`, and `WUD_OUT_DIR`.
- Release-note behavior change: syntax-check the touched scripts and avoid live Discord/GitHub calls unless explicitly requested or needed.
- Docs-only change: no tests required unless examples or commands were changed enough to need syntax validation.
- Unknown command: inspect scripts/docs; do not invent a project test harness.

## Local Summaries

- `bin/`: Host commands for reviewing WUD output and applying Docker Compose updates with confirmation, logging, and health checks.
- `wud/`: Container-mounted callback scripts for collecting WUD updates and optionally posting GitHub release notes to Discord.
- `install.sh`: Host setup helper that creates symlinks and executable bits without replacing existing non-symlink targets.
- `README.md`: Concise user guide for install, mounts, usage, and local config.

## Generated/Low-Value Paths

Do not read or edit unless directly required.

- `.DS_Store`
- `*.log`
- `*.tmp`
- `out/`
- WUD runtime output such as `images.todo`

## Nested AGENTS Suggestions

No nested `AGENTS.md` files are currently suggested; the repository is small enough for this root guide.

## Edit Discipline

- Identify the owning path from `Path map` before editing.
- Read nearest implementation and test examples first.
- Make the smallest correct change.
- Do not normalize formatting outside touched lines.
- Do not move code across directories unless requested.
- If multiple areas are touched, re-check whether nested `AGENTS.md` files apply.
