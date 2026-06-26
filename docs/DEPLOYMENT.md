# Deployment

This is the canonical reference for running WUDup through Docker Compose,
as a WebUI container, as a Docker script runner, or through host-installed
commands. The WebUI container is the recommended deployment for new installs.
The WebUI/API is the primary supported workflow; the `updates` CLI is retained
as an admin convenience, and CLI/WebUI feature parity is not a project goal. New
review and interactive features should generally go to the WebUI/API first.
For a short entrypoint, see the [README](../README.md).

WUDup controls the Docker daemon it is pointed at. Review the socket and
stack-directory mounts before using any command without `--dry-run`.

## Docker Image

Build a local helper image from this repository:

```bash
docker build -t wudup:local .
```

Release images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/magrhino/wudup:latest
```

Deployments that previously used `ghcr.io/magrhino/wud-updater` must update
their Compose image reference to `ghcr.io/magrhino/wudup`; new releases are
published only under the `wudup` image name.

Use the exact `vX.Y.Z` release tag for reproducible deployments. Release images
are also published as `X.Y.Z`, `X.Y`, and `latest`. The same tags support
`linux/amd64` and `linux/arm64`, and Docker selects the matching image for the
host platform automatically.

The image uses a multi-stage Dockerfile that first compiles the frontend with a
Node.js `webui-build` stage. The final stage uses `python:3.14.5-slim-bookworm`,
installs the Docker CLI with the Compose plugin, copies `bin/`, `src/`, and `wud/`
into `/app`, and packages the built SPA into `/app/src/wudup/web_static/`
so the container natively serves the compiled WebUI without requiring static
directory mounts. It starts through `tini`, and with no command it runs the
WebUI on the container's `0.0.0.0:7417`. Run doctor first to validate Docker
access, mounted paths, script permissions, and Compose rendering:

```bash
doctor
```

For the explicit non-mutating helper path, run:

```bash
updates --dry-run
```

For direct `docker run` usage, mount the Docker socket, the host stack directory,
the WUD output path, logs, and publish the WebUI port:

```bash
docker run --rm \
  -p 127.0.0.1:7417:7417 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /srv/docker:/srv/docker \
  -v wud-out:/out \
  -v "$PWD/logs":/logs \
  -e DOCKER_BASE=/srv/docker \
  -e WUD_OUT_FILE=/out/images.todo \
  -e WUD_LOG_DIR=/logs \
  -e WUD_DB_PATH=/logs/wudup.sqlite \
  ghcr.io/magrhino/wudup:latest
```

## Requirements

- Python 3.10 or newer for the host Python updater.
- Bash for host-side wrapper scripts and WUD callback scripts.
- Docker with the Compose plugin on the host.
- Standard shell tools used by wrapper and callback scripts: `awk`, `sort`,
  `sed`, `perl`, `find`, `grep`, `cut`, `column`, and `mktemp`.
- `midclt` is optional for local TrueNAS status checks.
- Containerized TrueNAS status checks require Docker access and a helper image
  built with a compatible TrueNAS API client.
- `curl` and `jq` are required for release-note helper scripts.

## Docker Compose

### Docker Script Runner

The repository example is at
[`docs/examples/docker-compose.example.yml`](examples/docker-compose.example.yml).
It uses the published GHCR image by default. Run it from the repository root:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup doctor
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup updates --dry-run
```

To apply every pending entry through the wrapper:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup updates --yes
```

To call the updater directly:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes
```

For tag updates, keep the explicit opt-in:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --allow-tag-updates
```

To write approved tag updates as digest-pinned Compose references, set
`WUD_DIGEST_PIN_UPDATES=true` in the helper environment. The updater resolves the
planned tag digest during dry run and applies `repo/app@sha256:<digest>` only
after pull verification succeeds.

To correct a bad WUD-proposed tag for one run, use the original WUD file line
number:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
```

To reject a WUD-proposed tag durably, exclude the original WUD file line. The
updater writes WUD's native `wud.tag.exclude` label to the matching Compose
service, stores the managed exact-tag rule in SQLite, and removes the WUD line
after the label is written:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --exclude-tag-lines 1
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

Compose discovery skips `old/` directories by default for backward
compatibility. To change archived-stack discovery without moving `DOCKER_BASE`,
set `WUD_COMPOSE_IGNORE_PATHS` to a comma-separated list of relative directory
names or paths, for example `old,archive/disabled`. A single component such as
`old` matches any directory with that name under `DOCKER_BASE`; a
multi-component value such as `archive/disabled` matches that relative path and
its descendants. Set `WUD_COMPOSE_IGNORE_PATHS` to an empty value, or save an
empty Compose ignore paths setting in the WebUI, to disable archive ignores.

Existing deployments that mount stacks at a helper-only path can keep that
layout only if the daemon-visible host root is also readable inside the helper.
For example, with `/srv/docker:/host/docker`, either switch to
`/srv/docker:/srv/docker`, or add a second `/srv/docker:/srv/docker` mount, set
`DOCKER_BASE=/host/docker`, and set `HOST_DOCKER_BASE=/srv/docker`.

The updater passes the mapped stack path to Compose as `--project-directory`.
That means relative bind mounts, `.env`, `env_file`, build contexts, and similar
project-relative files must exist under `HOST_DOCKER_BASE` and be readable from
inside the helper.

For a socket-proxy WebUI deployment, use
[`docs/examples/docker-compose.hardened.yml`](examples/docker-compose.hardened.yml).
That variant mounts `/var/run/docker.sock` only into a LinuxServer.io socket
proxy sidecar, points WUD and the WebUI container at
`tcp://socket-proxy-wudup:2375`, keeps the proxy on an internal Docker
network, and keeps browser mutations disabled unless
`WUD_WEB_MUTATIONS_ENABLED=true` is set.

### WebUI Container

For a long-running WebUI container, use
[`docs/examples/docker-compose.webui.yml`](examples/docker-compose.webui.yml).
That variant relies on the image's default WebUI command, serves the packaged
SPA on `127.0.0.1:7417`, persists SQLite state in `/logs/wudup.sqlite`, and
keeps browser mutations disabled unless `WUD_WEB_MUTATIONS_ENABLED=true` is set.
Copy the WebUI env example, review the stack path and browser exposure settings,
then start it and read the one-time setup link from the service logs:

```bash
WEBUI_ENV="$HOME/.config/wudup/webui.env"
mkdir -p "$HOME/.config/wudup"
test -f "$WEBUI_ENV" || cp docs/examples/webui.env.example "$WEBUI_ENV"
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml up -d
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml logs wudup
```

The env file keeps first-run defaults in one place. `HOST_DOCKER_BASE` must
match the daemon-visible root that contains your Compose stack directories,
`WEBUI_HTTP_BIND` controls the host-side published address and defaults to
loopback, and `WEBUI_LOG_DIR` persists logs plus SQLite state. The Compose
examples place WUD and WUDup on a private app network and set
`WUD_API_BASE_URL=http://wud:3000` so the WebUI can show best-effort WUD
metadata without publishing WUD's port to the host. The examples also gate
WUDup startup on WUD's container healthcheck and set
`WUD_API_STARTUP_WAIT_SECONDS=5` as a short in-app retry for startup races.
After startup, WUD API metadata discovery retries automatically on later
WebUI requests when the API is temporarily unavailable.
If WUD's internal API is protected by a reverse proxy or another static
authentication layer, configure WUDup's outbound WUD API client with bearer,
basic, or JSON header-file credentials. Prefer the `_FILE` variables for
container deployments so secrets stay out of Compose YAML, logs, and support
bundles.
By default, pending updates still come from the WUD callback todo file. The
experimental `WUD_PENDING_SOURCE=api` mode reads WebUI pending entries from
WUD's `/api/containers` metadata, and `WUD_PENDING_SOURCE=auto` uses that API
when usable before falling back to `WUD_OUT_FILE`. The host `updates` CLI and
`docker-update-from-wud` remain file-based.
For LAN or reverse-proxy exposure, set `WUD_WEB_PUBLIC_ORIGIN`; use
`WUD_WEB_ALLOWED_HOSTS` only for extra host aliases, and review
`WUD_WEB_TRUSTED_PROXIES` plus `WUD_WEB_SECURE_COOKIES` for reverse proxies.

Open the setup link, create the first admin username and a password with at
least 12 characters, then sign in at `http://127.0.0.1:7417`. See
[`docs/wiki/webui-container.md`](wiki/webui-container.md) for reverse-proxy,
LAN exposure, login, and mutation notes.

After sign-in, open the WebUI Settings page to review the effective non-secret
configuration, safety status, secret presence, and first-run checklist for the
running process.

The packaged image defines a default Docker healthcheck against `/readyz`, a
no-auth, loopback-only readiness endpoint. Override the service healthcheck only
when you need custom timing or need to disable it for a non-WebUI command. The
`/api/v1/ready` endpoint requires authentication for API client checks.

The Settings page separates runtime configuration from managed UI preferences.
Runtime values come from command-line overrides for the running command, then
process or generated environment config, then code defaults. SQLite-backed
managed preferences are limited to allowlisted non-secret WebUI preferences,
such as theme preference and onboarding checklist state, and do not override
CLI arguments, environment variables, paths, secrets, Docker commands, or
updater behavior. Browser saves for managed preferences still require
authentication, CSRF/Origin validation, audit records, and
`WUD_WEB_MUTATIONS_ENABLED=true`.

For containerized TrueNAS status checks, use
[`docs/examples/docker-compose.truenas.yml`](examples/docker-compose.truenas.yml).
That variant builds the helper image with the official TrueNAS API client so a
short-lived sibling container can run local `midclt` calls. Set
`TRUENAS_API_CLIENT_REF` to an API client tag that is compatible with your
TrueNAS release. The example uses the Python/container `updates` wrapper by
default, keeps sudo disabled, and sets `TRUENAS_STATUS_CHECK=true`; the
TrueNAS helper is only wired into that wrapper.

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

  wudup:
    image: ghcr.io/magrhino/wudup:latest
    environment:
      DOCKER_BASE: ${HOST_DOCKER_BASE:-/srv/docker}
      WUD_OUT_FILE: /out/images.todo
      WUD_LOG_DIR: /logs
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

When the managed script volume is mounted at `/managed-wud`, the container
automatically copies packaged WUD scripts from `/app/wud` before normal command
execution. Set `WUD_SYNC_SCRIPTS=false` to opt out, or set
`WUD_SYNC_SCRIPTS=true` to force a sync when using a custom destination.

The sync refuses unsafe destinations:

- `/`
- the application directory
- the Docker stack base
- the WUD output directory
- any non-empty directory that is not already marked as managed

Managed directories are marked with `.wudup-managed`. Sync removes the
previous managed contents, copies the packaged scripts, marks `*.sh` executable,
and writes the marker again.

Start or recreate `wudup` once before relying on `/wud/on-update.sh` in a
fresh empty script volume. You can also run the sync directly:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup sync-wud-scripts
```

Use the same `sync-wud-scripts` command with
`docs/examples/docker-compose.hardened.yml` when bootstrapping the hardened
socket-proxy example.

## Doctor Mode

Use `doctor` after changing container mounts, Docker socket access, or helper
environment variables:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup doctor
```

The authenticated WebUI Doctor page runs the same checks from the browser and
adds WebUI database, auth, host/origin, secure-cookie, static asset, and mutation
gate checks. The browser route is read-only for Docker workloads, but it uses the
same short-lived writable-directory permission probes as the CLI.

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
WUD_DIGEST_PIN_UPDATES=true updates --yes --allow-tag-updates
```

During interactive runs, `updates` prompts for selected tag updates and lets you
apply them as shown, skip them, change the tag, or exclude selected exact
proposed tags before calling the updater. Tag exclusions update `wud.tag.exclude` in
Compose and can optionally recreate affected services immediately. Automatic
Compose tag rewrites and exclusion labels only support direct service `image:`
values; image values provided through interpolation or inherited YAML snippets
are left pending for manual review.
With `WUD_DIGEST_PIN_UPDATES=true`, approved tag updates temporarily pull the
resolved tag, then write the final digest-pinned image plus
`# wudup.resolved-tag=<tag>` and an exact `wud.tag.include` label.

## Init Wizard

`wudup init` generates local first-run configuration without creating a
separate runtime config model. It writes env files and optional Compose
overrides that use the same variables documented below, refuses to overwrite
existing files unless `--backup-existing` is set, and keeps
`WUD_WEB_MUTATIONS_ENABLED=false` unless `--enable-web-mutations` is supplied.

Host command setup:

```bash
wudup init --profile host --stack-root "$HOME/docker" --non-interactive
updates --dry-run
```

WebUI container setup:

```bash
wudup init --profile webui --stack-root /srv/docker --non-interactive
docker compose --env-file "$HOME/.config/wudup/webui.env" \
  -f docs/examples/docker-compose.webui.yml up -d
```

Helper-only container setup also generates a Compose override by default:

```bash
wudup init --profile helper --stack-root /srv/docker --non-interactive
docker compose --env-file "$HOME/.config/wudup/helper.env" \
  -f docs/examples/docker-compose.example.yml \
  -f "$HOME/.config/wudup/docker-compose.helper.override.yml" \
  run --rm wudup doctor
```

Hardened WebUI setup can be checked with `doctor` before starting the WebUI:

```bash
wudup init --profile hardened --stack-root /srv/docker --non-interactive
docker compose --env-file "$HOME/.config/wudup/hardened.env" \
  -f docs/examples/docker-compose.hardened.yml \
  -f "$HOME/.config/wudup/docker-compose.hardened.override.yml" \
  run --rm wudup doctor
docker compose --env-file "$HOME/.config/wudup/hardened.env" \
  -f docs/examples/docker-compose.hardened.yml \
  -f "$HOME/.config/wudup/docker-compose.hardened.override.yml" \
  up -d
```

For LAN or reverse-proxy WebUI exposure, pass the browser-visible origin
explicitly:

```bash
wudup init --profile webui --stack-root /srv/docker --non-interactive \
  --web-exposure reverse-proxy \
  --public-origin https://wud.example.test \
  --trusted-proxies 127.0.0.1/32
```

Use `--dry-run` to preview generated paths without writing files. Container
profiles print the `docker compose ... doctor` command to run manually because
Compose may create transient containers or volumes.

## Environment Variables

`updates` reads optional host overrides from the environment or from
`$HOME/.config/wudup/env`. Start from the tracked template:

```bash
mkdir -p "$HOME/.config/wudup"
cp docs/examples/template.env "$HOME/.config/wudup/env"
```

Common host values:

```bash
DOCKER_BASE="$HOME/docker"
WUD_OUT_FILE="$DOCKER_BASE/wud/out/images.todo"
WUD_LOG_DIR="./logs"
WUD_UPDATE_MODE="stop"
WUD_MAX_WAIT="180"
WUD_LOCK_TIMEOUT="30"
WUD_TIMEZONE="UTC"
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
| `WEBUI_LOG_DIR` | `./logs` | Host-side directory mounted at `/logs` by the long-running WebUI Compose examples; persists updater logs and SQLite state. |
| `WEBUI_HTTP_BIND` | `127.0.0.1` | Host-side bind address used by the long-running WebUI Compose examples. Keep loopback for first run; use a LAN address or `0.0.0.0` only with `WUD_WEB_PUBLIC_ORIGIN` configured. |
| `DOCKER_HOST` | Docker CLI default | Optional Docker daemon endpoint, such as the hardened example's socket proxy. |
| `WUD_OUT_FILE` | Host: `$DOCKER_BASE/wud/out/images.todo`; container: `/out/images.todo` | Shared pending-update file. |
| `WUD_LOG_DIR` | Host: `./logs`; container: `/logs` | Updater log directory. Set to `$DOCKER_BASE/logs` to keep the previous layout. |
| `WUD_DB_PATH` | `$WUD_LOG_DIR/wudup.sqlite` | SQLite database path for setup state, sessions, run history, audit records, and managed tag exclusions. Preserve this file for WebUI login continuity and history. |
| `WUD_UPDATE_MODE` | `stop` | Update mode for matched Compose services or stacks: `pause`, `stop`, or `live`. |
| `WUD_MAX_WAIT` | `180` | Seconds to wait for health after recreation. |
| `WUD_LOCK_TIMEOUT` | `30` | Seconds to wait for the shared todo-file lock. |
| `WUD_TIMEZONE` | `UTC` | IANA timezone name, such as `America/Chicago`, used for WebUI auto-update policy schedules. |
| `WUD_COMPOSE_IGNORE_PATHS` | `old` | Comma-separated relative directory names or paths excluded from Compose discovery. Set an empty value to disable archive ignores; when unset in the WebUI, the managed Settings value can control this. |
| `WUD_DIGEST_PIN_UPDATES` | `false` | Opt-in digest-pin mode for approved tag updates. When `true`, supported tag updates resolve the planned tag/index digest and write Compose as `repo/app@sha256:<digest>` with `wudup.resolved-tag` and `wud.tag.include` metadata. Environment configuration overrides the managed WebUI setting. |
| `OUT_UID` / `OUT_GID` | unset | Optional owner for rewritten todo files and updater logs. `OUT_GUID` is accepted as an alias for `OUT_GID`. |
| `WUDUP_UPDATER` | Host: repo-local `bin/docker-update-from-wud`; image: `/app/bin/docker-update-from-wud` | Updater command invoked by `updates`. |
| `WUDUP_CONFIG` | `$HOME/.config/wudup/env` | Host config file read by `updates`. |
| `WUDUP_USE_SUDO` | `false` | For the Python `updates` wrapper, set to `true` only when a host install needs sudo file fallbacks and should run `WUDUP_UPDATER` through sudo. |
| `WUDUP_BANNER` | `auto` | Startup banner mode: `auto` prints on TTY startup, `true` forces it, and `false` disables it. |
| `WUDUP_RELEASE_CHECK` | `auto` | Latest-release check mode: `auto` or `true` lets startup banner, WebUI self-update banner, and self-update release checks try GitHub briefly, and `false` disables the network check. |
| `WUDUP_SELF_UPDATE` | enabled | Set to `false`, `0`, `no`, or `off` to disable the default `updates` self-update preflight. |
| `PYTHON_BIN` | `python3`, with repo `.venv` fallback when unset | Python interpreter used by Python entrypoint wrappers. Set this to bypass automatic `.venv` fallback. |
| `WUDUP_VENV` | Repo-local `.venv` | Optional installer and wrapper venv path for host runtime dependencies. |
| `WUD_WEB_TOKEN` | unset | Optional bearer token for API clients after first-run setup. This token is not accepted by the browser login form and does not bypass setup. |
| `WUD_WEB_DEV_NO_AUTH` | `false` | Explicitly disables WebUI API auth for tests or local development only. |
| `WUD_WEB_ALLOWED_ORIGINS` | same origin only | Comma-separated extra origins accepted by the CSRF/Origin checks for login, logout, and future mutating WebUI routes. |
| `WUD_WEB_PUBLIC_ORIGIN` | unset | Public `http://` or `https://` origin used for setup links, CSRF origin checks, allowed-host derivation, and secure-cookie auto-detection. Set this for LAN or reverse-proxy exposure. |
| `WUD_WEB_ALLOWED_HOSTS` | loopback, configured public origin, and bind host | Optional comma-separated hostnames or IPs accepted in the HTTP `Host` header in addition to the public origin. Use this for extra LAN aliases or proxy-facing hostnames. |
| `WUD_WEB_TRUSTED_PROXIES` | unset | Comma-separated proxy IP/CIDR/hostname entries whose `Forwarded` or `X-Forwarded-*` headers are trusted for scheme/host detection. Hostnames resolve once at WebUI startup. |
| `WUD_WEB_SECURE_COOKIES` | `auto` | Cookie `Secure` mode: `auto` enables it for effective HTTPS origins, `true` always enables it, and `false` disables it for local HTTP testing. |
| `WUD_WEB_MUTATIONS_ENABLED` | `false` | Enables browser plan/apply update mutations and Settings container restart when set to `true`. Leave unset or `false` for read-only WebUI deployments. |
| `WUD_WEB_RESTART_CONTAINER` | Docker `HOSTNAME` inside a container, otherwise unset | Optional Docker container name or ID restarted from Settings. Set this explicitly only when the auto-detected current container target is unavailable or wrong. |
| `WUD_API_BASE_URL` | `http://wud:3000` | Internal WUD API base URL used for best-effort WebUI metadata discovery and experimental API-backed pending source modes. Unavailable or error states are reported as degraded and retried faster on later WebUI requests; auth-required WUD still uses the normal cache TTL. |
| `WUD_API_STARTUP_WAIT_SECONDS` | `0`, `5` in Compose examples | Seconds to retry the initial WUD API health probe during WebUI startup before reporting degraded WUD API discovery. This startup wait is separate from automatic runtime retries. |
| `WUD_API_AUTH_BEARER_TOKEN_FILE` / `WUD_API_AUTH_BEARER_TOKEN` | unset | Optional bearer token for WUDup's outbound WUD API calls. Prefer the `_FILE` form in containers; direct values are intended for local development. Do not combine bearer and basic auth. |
| `WUD_API_AUTH_BASIC_USER` + `WUD_API_AUTH_BASIC_PASSWORD_FILE` / `WUD_API_AUTH_BASIC_PASSWORD` | unset | Optional basic auth credentials for WUDup's outbound WUD API calls. The user and one password source must be set together. Prefer the `_FILE` password form in containers. |
| `WUD_API_HEADERS_FILE` | unset | Optional UTF-8 JSON object of static WUD API request headers, such as `{"X-Api-Key":"example"}`. Header names and values are validated, values are redacted, and an `Authorization` header cannot be combined with bearer or basic auth. |
| `WUD_PENDING_SOURCE` | `file` | Experimental WebUI/API pending-update source: `file` keeps the callback todo file as the source of truth, `api` derives pending entries from WUD `/api/containers`, and `auto` uses API metadata when usable before falling back to `WUD_OUT_FILE`. Host CLI update commands remain file-based. |
| `WUD_RELEASE_NOTES_ENABLED` | unset | Optional env override for WebUI Discord release-note notifications. Leave unset to manage the setting from Settings; set `true` or `false` only when the deployment should force the value and make the Settings toggle read-only. |
| `WUD_WEB_HOST` | Host/direct app: `127.0.0.1`; container image: `0.0.0.0` | Host passed to Uvicorn when running `wudup web`. The image default makes published Docker ports reachable; Compose still controls host-side exposure with `WEBUI_HTTP_BIND`. |
| `WUD_WEB_PORT` | `7417` | Port passed to Uvicorn when running `wudup web`. |
| `WUD_WEB_STATIC_DIR` | packaged SPA, auto-detected if present | Optional built SPA directory override. Backend tests and API startup do not require a frontend build. |
| `WUD_WEB_UPSTREAM_MAP` | auto-detected | Optional LinuxServer.io image to upstream GitHub repository map used by WebUI release-note link metadata. |

Legacy `WUD_UPDATER`, `WUD_UPDATER_CONFIG`, `WUD_UPDATER_USE_SUDO`,
`WUD_UPDATER_BANNER`, `WUD_UPDATER_RELEASE_CHECK`, `WUD_UPDATER_SELF_UPDATE`,
and `WUD_UPDATER_VENV` variables remain accepted as fallbacks. Prefer the
`WUDUP_*` names for new configuration.

On first WebUI start, if no admin user exists in `WUD_DB_PATH`, the server logs
a one-time setup link. Open that link, create the first admin username and a
password of at least 12 characters, then use the normal sign-in page. Setup
claim values, password hashes, and browser sessions are stored in the existing
SQLite database; only hashed secrets are persisted.

When publishing the WebUI through a reverse proxy, set
`WUD_WEB_PUBLIC_ORIGIN` to the browser-visible origin. Configure the proxy to
preserve that `Host` header, or add the proxy-facing host to
`WUD_WEB_ALLOWED_HOSTS`. List only proxy IPs, CIDRs, or hostnames you control in
`WUD_WEB_TRUSTED_PROXIES`; hostnames resolve once at WebUI startup, so restart
WUDup after proxy container IP changes. Forwarded headers from other clients are
ignored.

Container and installer values:

| Variable | Default | Purpose |
|---|---|---|
| `WUD_SYNC_SCRIPTS` | `auto` | Set `auto` or leave unset to sync only when the managed script directory exists and is writable. Set `true` to force startup sync or `false` to opt out. |
| `WUD_SCRIPTS_DIR` | `/managed-wud` | Optional managed script sync destination override. |
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

Release-note notification values:

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_RELEASES_WEBHOOK` | unset | Discord webhook for WebUI-sent release-note notifications and for the legacy `/wud/release-notes-to-discord.sh` helper. Prefer this name for new deployments. |
| `DISCORD_WEBHOOK` | unset | Alternate webhook name accepted by the WebUI notification sender and shell helper. |
| `ADMIN_WEBHOOK` | selected release webhook | Optional webhook for missing LinuxServer.io upstream mapping alerts. |
| `GITHUB_TOKEN` | unset | Optional GitHub API token for higher release-note lookup rate limits in WUD notifications and WebUI metadata refreshes. |
| `MAX_COMMITS` | `3` | Maximum representative commits or pull requests included in Discord release embeds. |
| `COLOR_HEX` | `0x57F287` | Discord embed color used by `/wud/release-notes-to-discord.sh`. |
| `UPSTREAM_MAP` | `/wud/upstreams.txt` | LinuxServer.io image to upstream repository map used by explicit LSIO release-note mode and legacy `/wud/tag-manager.sh`. |
| `RELEASE_EMBED` | `/wud/github-release-embed.sh` | Compatibility hook used when legacy `/wud/tag-manager.sh` is configured. |
| `LOG_DIR` | `/out` | Compatibility log directory used when legacy `/wud/tag-manager.sh` is configured. |

WUD supplies callback fields such as `update_available`, `image_name`,
`image_tag_value`, `name`, `update_kind_kind`, `update_kind_remote_value`, and
`result_tag`; these are runtime inputs to the mounted scripts, not deployment
settings you normally set yourself. Provide webhook and GitHub token values
through the WUDup/WebUI runtime environment for WebUI-sent notifications, or
through the WUD container environment when using the legacy shell callback path.
Do not put secrets in this repository or in SQLite.

For the WebUI workflow, keep WUD's append-only callback or API pending source in
place, enable release-note notifications from Settings or by setting
`WUD_RELEASE_NOTES_ENABLED=true`, configure `DISCORD_RELEASES_WEBHOOK` in the
WUDup runtime, and set `WUD_WEB_MUTATIONS_ENABLED=true` before sending from the
browser. Then use **Preview release notes** from selected pending updates or
from a successful apply job. The WebUI reads WUD trigger summaries through the
WUD API when available, but it does not invoke WUD trigger POST endpoints.

Do not keep a legacy WUD shell release-note callback enabled unless you still
want that separate path. Running both the shell helper and WebUI sender for the
same update can duplicate Discord notifications.

## Security Notes

Mounting `/var/run/docker.sock` gives a container root-equivalent control over
the host Docker daemon. Only run trusted images with that socket, and keep the
stack, script, and output mounts scoped to the directories the updater needs.
The hardened compose example reduces direct socket exposure for WUD and the
WebUI by putting the raw socket behind a sidecar proxy, but `POST=1` is still
required for Docker Compose pull/recreate operations.

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

By default, `updates` checks for a WUDup update before applying other
pending Docker updates. It first honors a matching WUD todo entry, and if none
exists it can use the GitHub latest-release check. Floating tags such as
`latest` are pulled directly and then ask you to restart the container; pinned
release tags use the normal updater path so the Compose image tag can be
rewritten before restart. Use `updates --no-self-update` or
`WUDUP_SELF_UPDATE=0` to skip this preflight. `WUDUP_RELEASE_CHECK=0`
disables only the GitHub release-check source; WUD todo-file detection still
runs unless self-update is disabled.

## Maintenance And Upgrades

For container-first deployments, pull the new image and recreate `wudup`
so startup sync refreshes the managed WUD script volume:

```bash
docker compose pull wudup
docker compose up -d --force-recreate wudup
```

For local image development, rebuild with the development compose artifact and
recreate the helper:

```bash
docker compose -f docs/examples/docker-compose.build.yml build wudup
docker compose -f docs/examples/docker-compose.build.yml up -d --force-recreate wudup
```

For host installs, update the checkout, rerun the installer, and restart the WUD
container so it sees the latest mounted scripts:

```bash
git pull --ff-only
./install.sh
docker compose -f "$HOME/docker/wud/docker-compose.yml" restart
```
