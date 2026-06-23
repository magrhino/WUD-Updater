# WebUI Container

The packaged image can run the FastAPI backend and Vue SPA as a long-running
WebUI container. The example keeps browser access local-only by default and
starts in read-only mode.

## Start The WebUI

Copy the env example, review the Compose stack path and browser exposure
settings, then start the service:

```bash
WEBUI_ENV="$HOME/.config/wudup/webui.env"
mkdir -p "$HOME/.config/wudup"
test -f "$WEBUI_ENV" || cp docs/examples/webui.env.example "$WEBUI_ENV"
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml up -d
```

The example publishes `127.0.0.1:7417:7417`, so the browser entrypoint is:

```text
http://127.0.0.1:7417
```

The same stack also starts WUD and syncs packaged callback scripts into the
shared `wud-scripts` volume. Configure WUD to call:

```text
/wud/on-update.sh
```

## First Login

On first start, the WebUI creates a one-time setup claim and prints a setup URL
to the server logs. Read it with:

```bash
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml logs wudup
```

Open the `/#/setup?claim=...` URL, create the first admin username, and choose a
password with at least 12 characters. After setup succeeds, return to
`http://127.0.0.1:7417` and sign in with that username and password.
The WebUI opens Settings with a first-run checklist after admin setup. Keep the
checklist visible until Docker access, WUD output sharing, Compose discovery,
script sync, persistence, browser exposure, and mutation mode match the
deployment you intended, or dismiss it once those checks are understood.

The setup claim, password hash, sessions, update runs, managed tag exclusions,
and audit records are stored in SQLite at `WUD_DB_PATH`. The example sets that
path to `/logs/wudup.sqlite`, backed by `WEBUI_LOG_DIR` on the Compose
host. Keep that directory when recreating the container, or the WebUI will
require setup again and previous run history will be lost.

## Admin Recovery

If the admin password is lost or you need to rotate the admin credentials, run
the local recovery command against the same `WUD_DB_PATH`:

```bash
wudup web reset-admin --user admin
```

For the Compose example, run the command through the WebUI container so it uses
the mounted SQLite database:

```bash
docker compose --env-file "$WEBUI_ENV" -f docs/examples/docker-compose.webui.yml run --rm wudup web reset-admin --user admin
```

The command prints a single `/#/reset-admin?claim=...` link. Opening that link
lets the named admin set a new password. Issuing the link revokes existing
sessions for that admin, invalidates the old password immediately, and records
local audit history without storing or printing the raw recovery claim.

## Network Exposure

For a local workstation, keep the default loopback port binding. For LAN or
reverse-proxy exposure, change the port binding intentionally and set the
browser-visible origin in the env file. Add allowed hosts only for extra aliases
that differ from the public origin host:

```dotenv
WUD_WEB_PUBLIC_ORIGIN=https://wud.example.test
# WUD_WEB_ALLOWED_HOSTS=updates.example.test,192.168.1.20
WUD_WEB_TRUSTED_PROXIES=127.0.0.1/32
```

If TLS terminates at a reverse proxy, keep `WUD_WEB_SECURE_COOKIES=auto` unless
you have a specific local HTTP testing reason to disable secure cookies. Only
list proxy IPs, CIDRs, or hostnames you control in `WUD_WEB_TRUSTED_PROXIES`;
hostnames resolve once at WebUI startup, so restart WUDup after proxy container
IP changes. Forwarded headers from other clients are ignored.

## Read-Only And Mutations

The WebUI is read-only by default. It can display pending updates, run history,
and logs without enabling browser-initiated Docker mutations.

To apply updates from the browser, set:

```dotenv
WUD_WEB_MUTATIONS_ENABLED=true
WUD_TIMEZONE=America/Chicago
```

Mutation requests still require the normal authenticated browser session, CSRF
checks, Origin/Host validation, one active job at a time, and the WebUI's
plan-first apply flow. Keep the Docker socket, stack root, WUD output file,
logs, and SQLite database mounted exactly as the example shows before enabling
this mode.

When mutations are enabled, service policies can also schedule automatic
updates by weekday and local `HH:MM` time. `WUD_TIMEZONE` must be an IANA
timezone name and defaults to `UTC`.
