# Documentation

This is the full documentation index for WUD-Updater. The root README stays
short; detailed setup and behavior notes live here.

## Start Here

| Topic | Where |
|---|---|
| Project overview and quick commands | [../README.md](../README.md) |
| Deployment reference | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Development, CI, and release automation | [DEVELOPMENT.md](DEVELOPMENT.md) |
| Docker Compose example | [examples/docker-compose.example.yml](examples/docker-compose.example.yml) |
| Hardened Docker Compose example | [examples/docker-compose.hardened.yml](examples/docker-compose.hardened.yml) |
| Local Docker Compose build artifact | [examples/docker-compose.build.yml](examples/docker-compose.build.yml) |
| Environment template | [examples/template.env](examples/template.env) |
| Changelog | [../CHANGELOG.md](../CHANGELOG.md) |

## Feature Explainers

| Topic | Where |
|---|---|
| WUD callback flow, todo-file format, digest updates, and tag updates | [wiki/wud-update-flow.md](wiki/wud-update-flow.md) |
| Managed WUD script volume sync behavior | [wiki/container-script-sync.md](wiki/container-script-sync.md) |
| GitHub and Discord release-note notifications | [wiki/release-note-notifications.md](wiki/release-note-notifications.md) |

## Repository Areas

| Area | Purpose |
|---|---|
| `bin/` | Host-facing wrapper commands. |
| `src/wud_updater/` | Python updater package and CLI entrypoints. |
| `wud/` | Scripts mounted into the WUD container. |
| `docs/examples/` | Copyable deployment examples. |
| `tests/` | Shell and Python validation using fakes and temp directories. |
