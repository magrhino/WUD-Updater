# Deployment

This is the canonical reference for running WUD-Updater through Docker Compose,
as a container helper image, or through host-installed commands. For a short
entrypoint, see the [README](../README.md).

WUD-Updater controls the Docker daemon it is pointed at. Review the socket and
stack-directory mounts before using any command without `--dry-run`.

## Docker Image

Build a local helper image from this repository:

```bash
docker build -t wud-updater:local .
```

Release images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/magrhino/wud-updater:latest
```

Use the exact `vX.Y.Z` release tag for reproducible deployments. Release images
are also published as `X.Y.Z`, `X.Y`, and `latest`.

The image uses `python:3.14-slim-bookworm`, installs the Docker CLI with the
Compose plugin, copies `bin/`, `src/`, and `wud/` into `/app`, and starts through
`tini`. Run doctor first to validate Docker access, mounted paths, script
permissions, and Compose rendering:

```bash
doctor
```

With no command, the image runs the non-mutating default:

```bash
updates --dry-run
```

For direct `docker run` usage, mount the Docker socket, the host stack directory,
and the WUD output path:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /srv/docker:/srv/docker \
  -v wud-out:/out \
  -v "$PWD/logs":/logs \
  -e DOCKER_BASE=/srv/docker \
  -e WUD_OUT_FILE=/out/images.todo \
  -e WUD_LOG_DIR=/logs \
  ghcr.io/magrhino/wud-updater:latest
```

## Requirements

- Python 3.10 or newer for the host Python updater.
- Bash for host-side wrapper scripts and WUD callback scripts.
- Docker with the Compose plugin on the host.
- Standard shell tools used by wrapper and callback scripts: `awk`, `sort`,
  `sed`, `perl`, `find`, `grep`, `cut`, `column`, and `mktemp`.
- `jq` and `midclt` are optional for the legacy Bash `updates` fallback's
  local TrueNAS status checks.
- Containerized TrueNAS status checks require Docker access and a helper image
  built with a compatible TrueNAS API client.
- `curl` and `jq` are required for release-note helper scripts.

## Docker Compose

The repository example is at
[`docs/examples/docker-compose.example.yml`](examples/docker-compose.example.yml).
It uses the published GHCR image by default. Run it from the repository root:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater doctor
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater
```

To apply every pending entry through the wrapper:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater updates --yes
```

To call the updater directly:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater docker-update-from-wud --yes
```

For tag updates, keep the explicit opt-in:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater docker-update-from-wud --yes --allow-tag-updates
```

To correct a bad WUD-proposed tag for one run, use the original WUD file line
number:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
```

To reject a WUD-proposed tag durably, exclude the original WUD file line. The
updater writes WUD's native `wud.tag.exclude` label to the matching Compose
service, stores the managed exact-tag rule in SQLite, and removes the WUD line
after the label is written:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater docker-update-from-wud --yes --exclude-tag-lines 1
```

Add `--recreate-excluded-services` when you want Compose to recreate affected
services immediately so WUD sees the new container labels before its next scan.

By default, the updater recreates only the Compose service that owns the matched
image. For services whose update should restart the whole Compose project, add a
label to that service:

```yaml
services:
  vpn:
    image: example/vpn:latest
    labels:
      - WUD-UPDATER-RECREATE-STACK=true
```

When the matched running service container has
`WUD-UPDATER-RECREATE-STACK=true`, `docker-update-from-wud` uses stack-level
pull/recreate behavior for that Compose project. In stop mode, that means
pulling only the matched service image, stopping the project services, and
running `docker compose up -d --remove-orphans` for the stack. This recreates
needed containers while preserving Compose networks instead of using
`docker compose down`.

The example mounts:

| Mount | Purpose |
|---|---|
| `/var/run/docker.sock:/var/run/docker.sock` | Lets the helper inspect, pull, and recreate host Docker workloads. |
| `${HOST_DOCKER_BASE:-/srv/docker}:${HOST_DOCKER_BASE:-/srv/docker}` | Makes host Compose stacks visible inside the helper at the same absolute path the Docker daemon uses. |
| `./logs:/logs` | Stores updater logs outside the Docker stack root. |
| `wud-scripts:/managed-wud` | Managed volume that receives packaged WUD scripts. |
| `wud-out:/out` | Shared WUD todo-file output volume. |

Set `DOCKER_BASE` to the path that contains the Compose projects. For
containerized updater runs, mount that path at the same absolute location inside
the helper; otherwise relative Compose bind mounts such as `./config:/config`
can resolve to helper-only paths that the host Docker daemon cannot create. Set
`WUD_OUT_FILE` to the todo file shared with WUD. Set `WUD_LOG_DIR` to the
mounted log directory used by the updater.

Existing deployments that mount stacks at a helper-only path can keep that
layout only if the daemon-visible host root is also readable inside the helper.
For example, with `/srv/docker:/host/docker`, either switch to
`/srv/docker:/srv/docker`, or add a second `/srv/docker:/srv/docker` mount, set
`DOCKER_BASE=/host/docker`, and set `HOST_DOCKER_BASE=/srv/docker`.

The updater passes the mapped stack path to Compose as `--project-directory`.
That means relative bind mounts, `.env`, `env_file`, build contexts, and similar
project-relative files must exist under `HOST_DOCKER_BASE` and be readable from
inside the helper.

For a socket-proxy deployment, use
[`docs/examples/docker-compose.hardened.yml`](examples/docker-compose.hardened.yml).
That variant mounts `/var/run/docker.sock` only into a LinuxServer.io socket
proxy sidecar, points WUD and the helper at `tcp://socket-proxy-wud-updater:2375`,
and keeps the proxy on an internal Docker network.

For containerized TrueNAS status checks, use
[`docs/examples/docker-compose.truenas.yml`](examples/docker-compose.truenas.yml).
That variant builds the helper image with the official TrueNAS API client so a
short-lived sibling container can run local `midclt` calls. Set
`TRUENAS_API_CLIENT_REF` to an API client tag that is compatible with your
TrueNAS release. The example uses the Python/container `updates` wrapper by
default and sets `WUD_UPDATER_USE_SUDO=false` and `TRUENAS_STATUS_CHECK=true`;
the TrueNAS helper is only wired into that wrapper.

When enabled, the Python `updates` wrapper uses Docker to inspect its own
container, starts the same image with `--network none`, mounts only
`/var/run/middleware` through Docker `--mount` so a missing host path fails,
calls `midclt call update.status` and `midclt call alert.list` inside the
helper, reads minimized status JSON from the helper's stdout, and exits. If the
wrapper prints `TrueNAS not reachable`, check that Docker can start sibling
containers, the client tag matches the TrueNAS release, and the TrueNAS
middleware socket exists at `/var/run/middleware` on the Docker host.

For local image development and smoke tests, use
[`docs/examples/docker-compose.build.yml`](examples/docker-compose.build.yml).
That file keeps the repository-local `build` stanza separate from the
deployment example.

For an existing WUD Compose file, mount the same script and output volumes into
both services:

```yaml
services:
  wud:
    volumes:
      - wud-scripts:/wud:ro
      - wud-out:/out
    # Configure your WUD trigger to call:
    #   /wud/on-update.sh

  wud-updater:
    image: ghcr.io/magrhino/wud-updater:latest
    environment:
      DOCKER_BASE: ${HOST_DOCKER_BASE:-/srv/docker}
      WUD_OUT_FILE: /out/images.todo
      WUD_LOG_DIR: /logs
      WUD_SYNC_SCRIPTS: "true"
      WUD_SCRIPTS_DIR: /managed-wud
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${HOST_DOCKER_BASE:-/srv/docker}:${HOST_DOCKER_BASE:-/srv/docker}
      - ./logs:/logs
      - wud-scripts:/managed-wud
      - wud-out:/out

volumes:
  wud-scripts:
  wud-out:
```

## WUD Script Sync

Set `WUD_SYNC_SCRIPTS=true` to copy packaged WUD scripts from `/app/wud` into a
managed shared volume before normal command execution. The destination defaults
to `/managed-wud`; set `WUD_SCRIPTS_DIR` to override it.

The sync refuses unsafe destinations:

- `/`
- the application directory
- the Docker stack base
- the WUD output directory
- any non-empty directory that is not already marked as managed

Managed directories are marked with `.wud-updater-managed`. Sync removes the
previous managed contents, copies the packaged scripts, marks `*.sh` executable,
and writes the marker again.

Start or recreate `wud-updater` once before relying on `/wud/on-update.sh` in a
fresh empty script volume. You can also run the sync directly:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater sync-wud-scripts
```

Use the same `sync-wud-scripts` command with
`docs/examples/docker-compose.hardened.yml` when bootstrapping the hardened
socket-proxy example.

## Doctor Mode

Use `doctor` after changing container mounts, Docker socket access, or helper
environment variables:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater doctor
```

Doctor mode is read-only except for short-lived permission probe files that it
creates and removes in writable runtime directories. It checks:

- Docker CLI, Docker Compose plugin, Docker daemon reachability, and the Docker
  socket or configured `DOCKER_HOST`.
- `DOCKER_BASE`, `HOST_DOCKER_BASE`, `WUD_OUT_FILE`, `WUD_LOG_DIR`, packaged WUD
  scripts, and managed script-sync destination permissions.
- Compose stack discovery under `DOCKER_BASE`; every discovered compose file
  must render with `docker compose config`.
- Known helper-only bind-source prefixes such as `/host`, `/docker-host`, and
  `/container-host`, which the host Docker daemon usually cannot see.

The command uses strict exit status: Docker access failures, missing required
mounts, bad permissions, invalid script sync destinations, and missing or
invalid Compose stacks exit nonzero. Disabled optional checks such as
`TRUENAS_STATUS_CHECK=false` are reported as warnings.

## Host Install

Use the host installer when you want local shell commands and host-managed WUD
script mounts instead of the container-first shared script volume:

```bash
./install.sh
```

The installer creates symlinks for `updates` and `docker-update-from-wud`, makes
scripts executable, and links the `wud/` directory for the WUD container. It
refuses to replace existing non-symlink targets.

The installer also checks the host Python runtime used by the command wrappers.
If required Python packages are missing from host Python and from the repo-local
`.venv`, it creates `.venv` and installs the package there. The wrappers use
that venv automatically when `PYTHON_BIN` is unset and host `python3` is missing
runtime dependencies. Set `PYTHON_BIN` when you want the wrappers to use a
specific interpreter instead.

Mount the installed WUD scripts and output directory into the WUD container:

```yaml
volumes:
  - ${HOME}/docker/wud/scripts:/wud:ro
  - ${HOME}/docker/wud/out:/out
```

Configure WUD to call:

```text
/wud/on-update.sh
```

Then run:

```bash
updates --dry-run
updates --yes
updates --yes --allow-tag-updates
```

During interactive runs, `updates` prompts for selected tag updates and lets you
apply them as shown, skip them, change the tag, or exclude selected exact
proposed tags before calling the updater. Tag exclusions update `wud.tag.exclude` in
Compose and can optionally recreate affected services immediately. Automatic
Compose tag rewrites and exclusion labels only support direct service `image:`
values; image values provided through interpolation or inherited YAML snippets
are left pending for manual review.

## Environment Variables

`updates` reads optional host overrides from the environment or from
`$HOME/.config/wud-updater/env`. Start from the tracked template:

```bash
mkdir -p "$HOME/.config/wud-updater"
cp docs/examples/template.env "$HOME/.config/wud-updater/env"
```

Common host values:

```bash
DOCKER_BASE="$HOME/docker"
WUD_OUT_FILE="$DOCKER_BASE/wud/out/images.todo"
WUD_LOG_DIR="./logs"
WUD_UPDATE_MODE="stop"
WUD_MAX_WAIT="180"
WUD_LOCK_TIMEOUT="30"
OUT_UID="1000"
OUT_GID="1000"
```

Core updater and wrapper values:

Boolean examples use `true` and `false`; legacy aliases `1`, `0`, `yes`, `no`,
`on`, and `off` are still accepted where boolean parsing is supported.

| Variable | Default | Purpose |
|---|---|---|
| `DOCKER_BASE` | Host: `$HOME/docker`; container examples: `${HOST_DOCKER_BASE:-/srv/docker}` | Compose project search root. Containerized runs should mount this at the same absolute path the Docker daemon uses. |
| `HOST_DOCKER_BASE` | unset | Optional daemon-visible host root matching `DOCKER_BASE` inside the helper. The path must also be mounted/readable inside the helper because Compose uses it as `--project-directory`. |
| `DOCKER_HOST` | Docker CLI default | Optional Docker daemon endpoint, such as the hardened example's socket proxy. |
| `WUD_OUT_FILE` | Host: `$DOCKER_BASE/wud/out/images.todo`; container: `/out/images.todo` | Shared pending-update file. |
| `WUD_LOG_DIR` | Host: `./logs`; container: `/logs` | Updater log directory. Set to `$DOCKER_BASE/logs` to keep the previous layout. |
| `WUD_UPDATE_MODE` | `stop` | Update mode for matched Compose services or stacks: `pause`, `stop`, or `live`. |
| `WUD_MAX_WAIT` | `180` | Seconds to wait for health after recreation. |
| `WUD_LOCK_TIMEOUT` | `30` | Seconds to wait for the shared todo-file lock. |
| `OUT_UID` / `OUT_GID` | unset | Optional owner for rewritten todo files and updater logs. `OUT_GUID` is accepted as an alias for `OUT_GID`. |
| `WUD_UPDATER` | Host: repo-local `bin/docker-update-from-wud`; image: `/app/bin/docker-update-from-wud` | Updater command invoked by `updates`. |
| `WUD_UPDATER_CONFIG` | `$HOME/.config/wud-updater/env` | Host config file read by `updates`. |
| `WUD_UPDATER_PYTHON` | `true` | Set to `false` to use the temporary legacy Bash `updates` fallback. |
| `WUD_UPDATER_USE_SUDO` | `true` | For the Python `updates` wrapper, set to `false` to disable sudo file fallbacks and run `WUD_UPDATER` directly. |
| `WUD_UPDATER_BANNER` | `auto` | Startup banner mode: `auto` prints on TTY startup, `true` forces it, and `false` disables it. |
| `WUD_UPDATER_RELEASE_CHECK` | `auto` | Latest-release check mode: `auto` or `true` lets startup banner and self-update release checks try GitHub briefly, and `false` disables the network check. |
| `WUD_UPDATER_SELF_UPDATE` | enabled | Set to `false`, `0`, `no`, or `off` to disable the default `updates` self-update preflight. |
| `PYTHON_BIN` | `python3`, with repo `.venv` fallback when unset | Python interpreter used by Python entrypoint wrappers. Set this to bypass automatic `.venv` fallback. |
| `WUD_UPDATER_VENV` | Repo-local `.venv` | Optional installer and wrapper venv path for host runtime dependencies. |

Container and installer values:

| Variable | Default | Purpose |
|---|---|---|
| `WUD_SYNC_SCRIPTS` | unset | Set to `true` in the helper container to sync packaged WUD scripts before normal commands. |
| `WUD_SCRIPTS_DIR` | `/managed-wud` | Managed script sync destination. |
| `WUD_APP_DIR` | `/app` | Application root inside the helper container. |
| `BIN_DIR` | `$HOME/bin` | Host installer destination for the `updates` and `docker-update-from-wud` symlinks. |
| `WUD_SCRIPTS_LINK` | `$DOCKER_BASE/wud/scripts` | Host installer symlink target for the mounted `wud/` scripts. |
| `WUD_OUT_DIR` | `$DOCKER_BASE/wud/out` | Host installer-created output directory that should be mounted at `/out`. |
| `TRUENAS_API_CLIENT_REF` | TrueNAS example: `TS-26.0.0-BETA.1`; Dockerfile default: unset | Build arg used by the TrueNAS Compose example to install a compatible TrueNAS API client. |

TrueNAS status helper values for the Python `updates` wrapper:

| Variable | Default | Purpose |
|---|---|---|
| `TRUENAS_STATUS_CHECK` | unset | For the Python/container `updates` wrapper, set to `true` to run the short-lived local `midclt` status helper. |
| `TRUENAS_STATUS_TIMEOUT` | `5` | Seconds to wait for each helper `midclt` call before skipping it. The parent wrapper derives a longer Docker helper timeout from this value. |

Release-note notification values for the WUD container:

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_RELEASES_WEBHOOK` | unset | Required by the default `/wud/release-notes-to-discord.sh` helper when rich release notes are enabled. |
| `DISCORD_WEBHOOK` | unset | Webhook used by the optional `/wud/tag-manager.sh` router for normal release embeds. |
| `ADMIN_WEBHOOK` | `DISCORD_WEBHOOK` | Optional webhook for tag-manager missing-mapping alerts. |
| `GITHUB_TOKEN` | unset | Optional GitHub API token for higher release-note lookup rate limits. |
| `MAX_COMMITS` | `3` | Maximum representative commits or pull requests included in release embeds. |
| `COLOR_HEX` | `0x57F287` | Discord embed color used by `github-release-embed.sh`. |
| `UPSTREAM_MAP` | `/wud/upstreams.txt` | LinuxServer.io image to upstream repository map used by `tag-manager.sh`. |
| `RELEASE_EMBED` | `/wud/github-release-embed.sh` | Embed builder invoked by `tag-manager.sh`. |
| `LOG_DIR` | `/out` | Directory for `tag-manager.YYYYMMDD.log`. |

WUD supplies callback fields such as `update_available`, `image_name`,
`image_tag_value`, `name`, `update_kind_kind`, `update_kind_remote_value`, and
`result_tag`; these are runtime inputs to the mounted scripts, not deployment
settings you normally set yourself. Provide webhook and GitHub token values
through the WUD container environment or another host-local secret store. Do not
put secrets in this repository.

## Security Notes

Mounting `/var/run/docker.sock` gives the helper root-equivalent control over
the host Docker daemon. Only run trusted images with that socket, and keep the
stack, script, and output mounts scoped to the directories the updater needs.
The hardened compose example reduces direct socket exposure by putting the raw
socket behind a sidecar proxy, but `POST=1` is still required for Docker Compose
pull/recreate operations.

Secrets such as Discord webhooks and GitHub tokens must come from environment
variables or host-local secret stores. The scripts redact webhook values in
logs where they print helper commands.

The TrueNAS status helper does not use a TrueNAS API key. It relies on Docker
access to start a short-lived container with the local middleware socket
mounted, so treat `TRUENAS_STATUS_CHECK=true` as broad trusted-host TrueNAS
middleware access similar to other Docker socket workflows. The helper uses a
read-only bind mount and only calls read status methods, but Unix socket method
authorization is still controlled by TrueNAS middleware, not by the mount flag.

`--dry-run` does not pull images, recreate containers, remove WUD lines, or
otherwise mutate host state. Mutating Docker operations require interactive
confirmation or `--yes`.

By default, `updates` checks for a WUD-Updater update before applying other
pending Docker updates. It first honors a matching WUD todo entry, and if none
exists it can use the GitHub latest-release check. Floating tags such as
`latest` are pulled directly and then ask you to restart the container; pinned
release tags use the normal updater path so the Compose image tag can be
rewritten before restart. Use `updates --no-self-update` or
`WUD_UPDATER_SELF_UPDATE=0` to skip this preflight. `WUD_UPDATER_RELEASE_CHECK=0`
disables only the GitHub release-check source; WUD todo-file detection still
runs unless self-update is disabled.

## Maintenance And Upgrades

For container-first deployments, pull the new image and recreate `wud-updater`
so startup sync refreshes the managed WUD script volume:

```bash
docker compose pull wud-updater
docker compose up -d --force-recreate wud-updater
```

For local image development, rebuild with the development compose artifact and
recreate the helper:

```bash
docker compose -f docs/examples/docker-compose.build.yml build wud-updater
docker compose -f docs/examples/docker-compose.build.yml up -d --force-recreate wud-updater
```

For host installs, update the checkout, rerun the installer, and restart the WUD
container so it sees the latest mounted scripts:

```bash
git pull --ff-only
./install.sh
docker compose -f "$HOME/docker/wud/docker-compose.yml" restart
```
