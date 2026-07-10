# Command Runner And Host Install

The WebUI container is recommended for new deployments. Use these paths when
you want short-lived helper commands, host-installed commands, or legacy
file-mode WUD callbacks.

The command-runner paths read `WUD_OUT_FILE`/`images.todo` only. WUD API pending
sources are a WebUI feature.

## Docker Script Runner

The repository example is
[`docs/examples/docker-compose.example.yml`](examples/docker-compose.example.yml).
Run it from the repository root:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup doctor
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup updates --dry-run
```

Apply every pending entry through the wrapper:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup updates --yes
```

Call the updater directly:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes
```

Tag rewrites are explicit opt-in:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --allow-tag-updates
```

To write approved tag updates as digest-pinned Compose references, set
`WUD_DIGEST_PIN_UPDATES=true` in the helper environment. The updater resolves
the planned tag digest during dry run and applies `repo/app@sha256:<digest>`
only after pull verification succeeds.

Correct a bad WUD-proposed tag for one run with the original WUD file line
number:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
```

Reject a WUD-proposed tag durably by excluding the original WUD file line. The
updater writes WUD's native `wud.tag.exclude` label to the matching Compose
service, stores the managed exact-tag rule in SQLite, and removes the WUD line
after the label is written:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup docker-update-from-wud --yes --exclude-tag-lines 1
```

Add `--recreate-excluded-services` when you want Compose to recreate affected
services immediately so WUD sees the new labels before its next scan.

By default, the updater recreates only the Compose service that owns the matched
image. For services whose update should restart the whole Compose project, add
this label to the matched service:

```yaml
services:
  vpn:
    image: example/vpn:latest
    labels:
      - WUD-UPDATER-RECREATE-STACK=true
```

When the matched running service container has
`WUD-UPDATER-RECREATE-STACK=true`, `docker-update-from-wud` uses stack-level
pull/recreate behavior for that Compose project.

## Helper Mounts

The script runner example mounts:

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
`WUD_OUT_FILE` to the todo file shared with WUD and `WUD_LOG_DIR` to the mounted
log directory used by the updater.

Compose discovery searches every directory by default. To exclude archived
stacks without moving `DOCKER_BASE`, set `WUD_COMPOSE_IGNORE_PATHS` to a
comma-separated list of relative directory names or paths, such as
`old,archive/disabled`. Set it to an empty value to disable archive ignores.

Existing deployments that mount stacks at a helper-only path can keep that
layout only if the daemon-visible host root is also readable inside the helper.
For example, with `/srv/docker:/host/docker`, either switch to
`/srv/docker:/srv/docker`, or add a second `/srv/docker:/srv/docker` mount, set
`DOCKER_BASE=/host/docker`, and set `HOST_DOCKER_BASE=/srv/docker`.

The updater passes the mapped stack path to Compose as `--project-directory`.
Relative bind mounts, `.env`, `env_file`, build contexts, and similar
project-relative files must exist under `HOST_DOCKER_BASE` and be readable from
inside the helper.

## Existing WUD Compose Stack

For an existing WUD Compose file, mount the same script and output volumes into
both services:

```yaml
services:
  wud:
    volumes:
      - wud-scripts:/wud:ro
      - wud-out:/out
    # File-mode fallback: configure your WUD trigger to call:
    #   /wud/append-updates.sh
    # Use /wud/on-update.sh only for legacy shell release-note notifications.

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

See [Container Script Sync](wiki/container-script-sync.md) for managed WUD
script sync behavior.

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
runtime dependencies. Set `PYTHON_BIN` when you want a specific interpreter.

Mount the installed WUD scripts and output directory into the WUD container:

```yaml
volumes:
  - ${HOME}/docker/wud/scripts:/wud:ro
  - ${HOME}/docker/wud/out:/out
```

Configure WUD to call:

```text
/wud/append-updates.sh
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
proposed tags before calling the updater. Automatic Compose tag rewrites and
exclusion labels only support direct service `image:` values; image values
provided through interpolation or inherited YAML snippets are left pending for
manual review.

## Init Wizard

`wudup init` generates local first-run configuration without creating a separate
runtime config model. It writes env files and optional Compose overrides that
use the same variables documented in [Configuration](CONFIGURATION.md), refuses
to overwrite existing files unless `--backup-existing` is set, and keeps
`WUD_WEB_MUTATIONS_ENABLED=false` unless `--enable-web-mutations` is supplied.

Host command setup:

```bash
wudup init --profile host --stack-root "$HOME/docker" --non-interactive
updates --dry-run
```

Helper-only container setup also generates a Compose override by default:

```bash
wudup init --profile helper --stack-root /srv/docker --non-interactive
docker compose --env-file "$HOME/.config/wudup/helper.env" \
  -f docs/examples/docker-compose.example.yml \
  -f "$HOME/.config/wudup/docker-compose.helper.override.yml" \
  run --rm wudup doctor
```

## TrueNAS Status Helper

For containerized TrueNAS status checks, use
[`docs/examples/docker-compose.truenas.yml`](examples/docker-compose.truenas.yml).
That variant builds the helper image with the official TrueNAS API client so a
short-lived sibling container can run local `midclt` calls. Set
`TRUENAS_API_CLIENT_REF` to an API client tag compatible with your TrueNAS
release.

When enabled, the Python `updates` wrapper uses Docker to inspect its own
container, starts the same image with `--network none`, mounts only
`/var/run/middleware`, calls `midclt call update.status` and
`midclt call alert.list` inside the helper, reads minimized status JSON from
the helper's stdout, and exits. If the wrapper prints `TrueNAS not reachable`,
check that Docker can start sibling containers, the client tag matches the
TrueNAS release, and the TrueNAS middleware socket exists at
`/var/run/middleware` on the Docker host.

The TrueNAS status helper does not use a TrueNAS API key. Treat
`TRUENAS_STATUS_CHECK=true` as broad trusted-host TrueNAS middleware access
similar to other Docker socket workflows.

## Local Image Development

For local image development and smoke tests, use
[`docs/examples/docker-compose.build.yml`](examples/docker-compose.build.yml).
That file keeps the repository-local `build` stanza separate from deployment
examples:

```bash
docker compose -f docs/examples/docker-compose.build.yml build wudup
docker compose -f docs/examples/docker-compose.build.yml up -d --force-recreate wudup
```

For host installs, update the checkout, rerun the installer, and restart WUD so
it sees the latest mounted scripts:

```bash
git pull --ff-only
./install.sh
docker compose -f "$HOME/docker/wud/docker-compose.yml" restart
```
