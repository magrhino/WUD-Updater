# WUD-Updater

Small helper commands for applying Docker image updates reported by What's Up
Docker (WUD), with optional TrueNAS status checks and Discord release-note
notifications.

## What It Does

- WUD calls `/wud/on-update.sh` when an image update is available.
- The WUD-side scripts append pending image targets to `/out/images.todo`.
- The host command `updates` shows pending Docker updates and can optionally
  show TrueNAS update status and active alerts.
- When approved, `docker-update-from-wud` pulls matching Docker Compose services
  or stack-scoped service images, recreates containers, waits for health, and
  removes successfully processed lines from the WUD file.
- Interactive tag prompts can apply, change, skip, or durably exclude selected
  proposed exact tags through the native `wud.tag.exclude` Compose label.
- A Compose service can opt into full-stack recreation by running with the label
  `WUD-UPDATER-RECREATE-STACK=true`.

## Quick Start

### Container First

Review `docs/examples/docker-compose.example.yml`, especially the host Docker
stack path mounted at the same absolute path inside the helper. This matters
when Compose files use relative bind mounts such as `./config:/config`. Then
run doctor and the non-mutating default command:

If you keep an existing helper-only mount such as `/srv/docker:/host/docker`,
either switch to `/srv/docker:/srv/docker`, or add a second `/srv/docker:/srv/docker`
mount and set `HOST_DOCKER_BASE=/srv/docker`. Compose reads project-relative
files such as `.env`, `env_file`, build contexts, and relative bind mounts from
the `HOST_DOCKER_BASE` path, so that path must also be readable inside the helper.

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater doctor
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater
```

Apply all pending entries through the wrapper:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater updates --yes
```

For a socket-proxy deployment that avoids mounting the raw Docker socket into
WUD or WUD-Updater, start from
`docs/examples/docker-compose.hardened.yml`.

For containerized TrueNAS status checks, start from
`docs/examples/docker-compose.truenas.yml`. It builds a version-matched
TrueNAS client and uses an opt-in short-lived helper container for local status
checks without storing a TrueNAS API key. The helper is only used when
`TRUENAS_STATUS_CHECK=true` is set there.

### WebUI Container

For a long-running local WebUI, copy the WebUI Compose env example, review
`HOST_DOCKER_BASE`, then start from `docs/examples/docker-compose.webui.yml`:

```bash
WEBUI_ENV="$HOME/.config/wud-updater/webui.env"
mkdir -p "$HOME/.config/wud-updater"
test -f "$WEBUI_ENV" || cp docs/examples/webui.env.example "$WEBUI_ENV"
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml up -d
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml logs wud-updater
```

Open the one-time `/#/setup?claim=...` link printed in the logs, create the
first admin username and a password with at least 12 characters, then sign in at
`http://127.0.0.1:8080`. The example keeps browser access bound to loopback and
leaves WebUI mutations disabled unless you explicitly set
`WUD_WEB_MUTATIONS_ENABLED=true`. Scheduled service-policy auto updates use the
server's `WUD_TIMEZONE` value, for example `America/Chicago`, and default to
`UTC`.

If the admin password is lost or an operator needs to rotate access, issue a
new one-time recovery link from the host or container:

```bash
wud-updater web reset-admin --user admin
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml run --rm wud-updater web reset-admin --user admin
```

The reset command uses the configured `WUD_DB_PATH`, revokes existing sessions
for that admin, invalidates the old password immediately, and prints only the
new one-time recovery URL.

### Host Install

Install local commands and host-managed WUD script mounts:

```bash
./install.sh
```

The installer checks the host Python runtime used by the command wrappers. If
required Python packages are missing from host Python and from the repo-local
`.venv`, it creates `.venv` and installs the package there. The wrappers use
that venv automatically when `PYTHON_BIN` is unset and host `python3` is missing
runtime dependencies.

Make sure the install bin directory is on your `PATH`, configure WUD to call
`/wud/on-update.sh`, then review or apply pending updates:

```bash
updates --dry-run
updates --yes
```

## Common Commands

```bash
updates
updates --dry-run
updates --no-self-update
updates --yes --allow-tag-updates
wud-updater doctor
docker-update-from-wud --dry-run
docker-update-from-wud --yes
docker-update-from-wud --yes --allow-tag-updates
docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
docker-update-from-wud --yes --exclude-tag-lines 1
wud-updater web
wud-updater web reset-admin --user admin
```

The Python package also exposes the same tools through:

```bash
wud-updater doctor
wud-updater updates --dry-run
wud-updater update-from-wud --dry-run
wud-updater web
```

`wud-updater web` starts the read-only `/api/v1/*` FastAPI service for the
WebUI and serves the packaged Vue SPA when static assets are present. On first
start, the server logs a one-time setup link for creating the first admin
username and password. After setup, browser sessions use an HttpOnly cookie and
CSRF protection. API clients can optionally send `Authorization: Bearer <token>`
when `WUD_WEB_TOKEN` is set, but that token is not used for browser login and
does not bypass first-run setup. `WUD_WEB_DEV_NO_AUTH=true` is only for local
development and tests.

## Documentation

| Topic | Where |
|---|---|
| Public WebUI demo | [magrhino.github.io/WUD-Updater](https://magrhino.github.io/WUD-Updater/) |
| Security policy and private vulnerability reporting | [SECURITY.md](SECURITY.md) |
| Deployment, configuration, maintenance, and security notes | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Complete documentation index | [docs/README.md](docs/README.md) |
| Docker Compose example | [docs/examples/docker-compose.example.yml](docs/examples/docker-compose.example.yml) |
| Long-running WebUI Docker Compose example | [docs/examples/docker-compose.webui.yml](docs/examples/docker-compose.webui.yml) |
| Hardened Docker Compose example | [docs/examples/docker-compose.hardened.yml](docs/examples/docker-compose.hardened.yml) |
| TrueNAS status Docker Compose example | [docs/examples/docker-compose.truenas.yml](docs/examples/docker-compose.truenas.yml) |
| Release notes | [CHANGELOG.md](CHANGELOG.md) |
