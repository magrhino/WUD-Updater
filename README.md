# WUD-Updater

Small helper commands for applying Docker image updates reported by What's Up
Docker (WUD), with optional TrueNAS status checks and Discord release-note
notifications.

## What It Does

- WUD calls `/wud/on-update.sh` when an image update is available.
- The WUD-side scripts append pending image targets to `/out/images.todo`.
- The host command `updates` shows pending Docker updates, TrueNAS update status,
  and active alerts.
- When approved, `docker-update-from-wud` pulls matching Docker Compose services
  or stacks, recreates them, waits for health, and removes successfully processed
  lines from the WUD file.

## Quick Start

### Container First

Review `docs/examples/docker-compose.example.yml`, especially the host Docker
stack path mounted at `/host/docker`, then run the non-mutating default command:

```bash
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
TrueNAS API client and keeps the API key in a mounted secret file.

### Host Install

Install local commands and host-managed WUD script mounts:

```bash
./install.sh
```

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
updates --yes --allow-tag-updates
docker-update-from-wud --dry-run
docker-update-from-wud --yes
docker-update-from-wud --yes --allow-tag-updates
```

The Python package also exposes the same tools through:

```bash
wud-updater updates --dry-run
wud-updater update-from-wud --dry-run
```

## Documentation

| Topic | Where |
|---|---|
| Deployment, configuration, maintenance, and security notes | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Complete documentation index | [docs/README.md](docs/README.md) |
| Docker Compose example | [docs/examples/docker-compose.example.yml](docs/examples/docker-compose.example.yml) |
| Hardened Docker Compose example | [docs/examples/docker-compose.hardened.yml](docs/examples/docker-compose.hardened.yml) |
| TrueNAS API Docker Compose example | [docs/examples/docker-compose.truenas.yml](docs/examples/docker-compose.truenas.yml) |
| Release notes | [CHANGELOG.md](CHANGELOG.md) |
