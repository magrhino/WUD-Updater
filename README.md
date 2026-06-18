# WUD-Updater

WUD-Updater turns image update notices from What's Up Docker (WUD) into a
reviewable Docker Compose update workflow. The recommended deployment is the
long-running WebUI container, which provides a local browser dashboard,
read-only safety defaults, Doctor checks, run history, logs, diagnostics, and an
optional plan-first apply flow.

## Web Deployment
_Check out the demo: https://magrhino.github.io/WUD-Updater/_

The WebUI container serves the FastAPI backend and packaged Vue SPA from the
same image. WUD records pending image updates into a shared todo file, and the
WebUI reads that file to show pending updates and prepare apply plans. When WUD
shares the Compose app network, the WebUI also probes WUD's internal API for
display metadata; if that API is unavailable, the todo file remains the source
of truth.

```text
WUD detects an image update
-> /wud/on-update.sh records it in /out/images.todo
-> the WebUI shows pending updates, checks readiness, and builds an apply plan
-> approved plans run docker-update-from-wud and clean successful todo lines
```

The WebUI deployment starts read-only. Browser-initiated Docker mutations stay
disabled unless `WUD_WEB_MUTATIONS_ENABLED=true` is set intentionally.

### Start The WebUI

If the `wud-updater` CLI is available, generate first-run hardened WebUI config
instead of downloading the env template:

```bash
wud-updater init --profile hardened --stack-root /srv/docker --non-interactive
```

That writes a hardened env file and Compose override under
`$HOME/.config/wud-updater/`. Use them with the hardened Compose example before
starting the service.

To start without the CLI, download the published hardened WebUI Compose example
plus an env template in your deployment directory:

```bash
curl -fsSL \
  -o docker-compose.yml https://raw.githubusercontent.com/magrhino/WUD-Updater/main/docs/examples/docker-compose.hardened.yml \
  -o .env https://raw.githubusercontent.com/magrhino/WUD-Updater/main/docs/examples/webui.env.example
```

Review `.env` before starting: set `HOST_DOCKER_BASE` to your Compose stack
root, then keep loopback-only browser access or set `WUD_WEB_PUBLIC_ORIGIN` for
LAN or reverse-proxy exposure. Start the service, then read the one-time setup
link from the logs:

```bash
docker compose up -d
docker compose logs wud-updater
```

Open the printed `/#/setup?claim=...` link, create the first admin username and
a password with at least 12 characters, then sign in at
`http://127.0.0.1:7417`. The example binds browser access to loopback by
default.

See [WebUI container deployment](docs/DEPLOYMENT.md#webui-container) for the
full Compose walkthrough and [WebUI container operations](docs/wiki/webui-container.md)
for login, admin recovery, LAN or reverse-proxy exposure, SQLite persistence,
managed preferences, and mutation mode.

## Other Deployment Paths

The WebUI container is recommended for new deployments. The non-web paths remain
supported when you want a smaller command-runner workflow or host-installed
commands:

| Path | Use when | Docs |
|---|---|---|
| Docker script runner | You want short-lived `docker compose run` commands for `doctor`, dry runs, and applies without a persistent WebUI. | [Docker script runner](docs/DEPLOYMENT.md#docker-script-runner) |
| Host install | You want `updates` and `docker-update-from-wud` on the host `PATH` with host-managed WUD script mounts. | [Host install](docs/DEPLOYMENT.md#host-install) |

The WebUI/API is the primary supported workflow. The `updates` CLI is retained
as an admin convenience for host and helper-container operators; CLI/WebUI
feature parity is not a project goal. New review and interactive features
should generally go to the WebUI/API first.

## Documentation

| Topic | Where |
|---|---|
| Public WebUI demo | [magrhino.github.io/WUD-Updater](https://magrhino.github.io/WUD-Updater/) |
| Full deployment reference | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| WebUI container deployment | [docs/DEPLOYMENT.md#webui-container](docs/DEPLOYMENT.md#webui-container) |
| WebUI operations guide | [docs/wiki/webui-container.md](docs/wiki/webui-container.md) |
| Docker script runner | [docs/DEPLOYMENT.md#docker-script-runner](docs/DEPLOYMENT.md#docker-script-runner) |
| Host install | [docs/DEPLOYMENT.md#host-install](docs/DEPLOYMENT.md#host-install) |
| Digest verification and digest-pin updates | [docs/wiki/digest-verification.md](docs/wiki/digest-verification.md) |
| Complete documentation index | [docs/README.md](docs/README.md) |
| Security policy and private vulnerability reporting | [SECURITY.md](SECURITY.md) |
| Release notes | [CHANGELOG.md](CHANGELOG.md) |

## Apprieciate my work on this?

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-orange?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/magrhino)

or

BTC: `bc1q3r9g3k8fyzxr29njgfjdqs53z9tuezwuaagx0h`
ETH: `0x118c1b3b927b870a0cf0bd692e06cd769e5af6d9`
