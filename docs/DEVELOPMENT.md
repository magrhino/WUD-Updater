# Development

This page covers local development, CI behavior, and release automation. Runtime
deployment details live in [DEPLOYMENT.md](DEPLOYMENT.md).

## Local Setup

Install the Python development dependencies in a virtual environment before
running the full local suite:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the full validation entrypoint:

```bash
tests/run-all.sh
```

The suite runs Ruff, shell syntax checks, ShellCheck, Python syntax checks,
Python unit tests, and updater behavior tests.

## Focused Checks

```bash
ruff check .
shellcheck install.sh bin/updates bin/docker-update-from-wud wud/*.sh
bash -n install.sh bin/updates bin/docker-update-from-wud wud/http.sh wud/release-notes-to-discord.sh wud/github-release-embed.sh wud/tag-manager.sh
sh -n wud/on-update.sh wud/append-updates.sh
python3 -m py_compile src/wud_updater/*.py tests/run-python-tests.py tests/test_python_*.py
python3 tests/run-python-tests.py
tests/test-docker-update-from-wud.sh
tests/test-github-release-embed.sh
tests/test-wud-append-updates.sh
tests/test-updates-wrapper.sh
tests/test-entrypoint.sh
tests/test-release-notes-to-discord.sh
tests/test-tag-manager.sh
```

Container checks require Docker:

```bash
docker compose -f docs/examples/docker-compose.example.yml config
docker compose -f docs/examples/docker-compose.webui.yml config
docker compose -f docs/examples/docker-compose.hardened.yml config
docker compose -f docs/examples/docker-compose.truenas.yml config
docker compose -f docs/examples/docker-compose.build.yml config
tests/container-build.sh
```

The deployment compose example uses the published GHCR image. The build compose
artifact keeps the repository-local image build path used by smoke tests.

## WebUI Development

Install the frontend dependencies before running the Vue/Vite checks:

```bash
npm --prefix webui ci
npm --prefix webui run typecheck
npm --prefix webui run test
npm --prefix webui run build
```

Browser smoke tests use Playwright Chromium with mocked local API fixtures. Install
the browser once before running them locally:

```bash
npm --prefix webui exec playwright install chromium
npm --prefix webui run test:smoke
```

For the local demo server, seed disposable state and run both the FastAPI
backend and Vite frontend through the checked-in wrapper:

```bash
make webui-demo-state
make webui-dev
```

`make webui-dev` starts the backend on `127.0.0.1:8080`, the frontend on
`127.0.0.1:5173`, sets `WUD_WEB_DEV_NO_AUTH=true`, and allows the Vite origin
for CSRF/Origin checks. The demo server uses `local-dev/` for disposable Docker
fixtures, WUD output, logs, and `WUD_DB_PATH`.

Useful WebUI development variables:

| Variable | Purpose |
|---|---|
| `WUD_DB_PATH` | SQLite database path for WebUI setup state, sessions, run history, audit records, and managed tag exclusions. |
| `WUD_WEB_MUTATIONS_ENABLED` | Set to `true` only when testing browser-initiated plan/apply flows; default is read-only. |
| `WUD_WEB_DEV_BACKEND_PORT` | Backend port used by `webui/scripts/dev-server.mjs` and the Vite proxy; default `8080`. |
| `WUD_WEB_DEV_FRONTEND_PORT` | Vite frontend port used by the dev-server wrapper; default `5173`. |
| `VITE_WUD_BACKEND_URL` | Backend URL exported by the dev-server wrapper for frontend experiments; the checked-in SPA currently uses same-origin `/api` requests through the Vite proxy. |
| `WUD_WEB_HOST` / `WUD_WEB_PORT` | Host and port used when running `wud-updater web` manually. |
| `WUD_WEB_STATIC_DIR` | Optional built SPA directory override for manual backend testing. |
| `WUD_WEB_DEV_NO_AUTH` | Development-only auth bypass used by tests and the local demo wrapper. |
| `WUD_WEB_ALLOWED_ORIGINS` | Extra allowed origins for login, logout, setup, and mutation CSRF/Origin checks. |
| `WUD_WEB_PUBLIC_ORIGIN` | Browser-visible origin used for setup links, reverse proxies, and secure-cookie auto-detection. |
| `WUD_WEB_ALLOWED_HOSTS` | Accepted HTTP `Host` names when exposing the WebUI outside loopback. |
| `WUD_WEB_TRUSTED_PROXIES` | Proxy IP/CIDR entries whose forwarded headers are trusted. |
| `WUD_WEB_SECURE_COOKIES` | Cookie Secure mode: `auto`, `true`, or `false`; keep `auto` outside local HTTP tests. |

For manual backend-only testing with a built SPA:

```bash
npm --prefix webui run build
wud-updater web --host 127.0.0.1 --port 8080 --static-dir webui/dist
```

## CI

CI runs on pull requests targeting `main` and pushes to `main`. The default path
is intentionally Linux-only to keep private repository Actions usage predictable.
Pull requests with `[skip ci]` in the title skip CI jobs, and direct `docs:` or
`chore:` commits to `main` skip CI and Release Please jobs. Merged Release
Please PRs can still run the release automation needed to tag the release.

Optional checks are available when broader coverage is useful:

- Add the `ci:macos` pull request label, or manually dispatch CI with
  `run_macos=true`, to run the macOS test job.
- Add the `ci:docker` pull request label, manually dispatch CI with
  `run_docker=true`, or change image-impacting files to run the Docker build
  smoke test.
- Manually dispatch CI with `run_webui_smoke=true`, or change files under
  `webui/`, to run the Playwright Chromium WebUI smoke tests.
- Workflow linting runs automatically when files under `.github/workflows/`
  change, and can also be run from manual CI dispatch.

## Releases

Release Please is the normal release path. When a Release Please PR is merged,
it creates a draft GitHub Release and tag, then calls the release publisher with
that tag.

For manual backfill or retry, dispatch the release workflow with an existing
stable tag:

```bash
gh workflow run release.yml --ref main -f release_tag=v1.2.3
```

The release publisher runs the release validation gate, builds and publishes
Docker images for Linux amd64 and arm64 to `ghcr.io/magrhino/wud-updater`,
validates the published multi-arch manifests, and then creates or publishes the
GitHub Release. The public GitHub Release is published only after the GHCR image
tags are available. The release gate includes Linux validation, container build
validation, Docker Compose E2E, and WebUI smoke checks. Image tags are published
as `vX.Y.Z`, `X.Y.Z`, `X.Y`, and `latest`. Direct pushes of stable `vX.Y.Z` tags
also run the same publisher as a fallback.
