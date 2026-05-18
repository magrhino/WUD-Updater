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
bash -n install.sh bin/updates bin/docker-update-from-wud wud/tag-manager.sh wud/lsio-release-embed.sh wud/release-notes-to-discord.sh
sh -n wud/on-update.sh wud/append-updates.sh
python3 -m py_compile src/wud_updater/*.py tests/run-python-tests.py tests/test_python_*.py
python3 tests/run-python-tests.py
tests/test-docker-update-from-wud.sh
tests/test-wud-append-updates.sh
tests/test-updates-wrapper.sh
tests/test-entrypoint.sh
```

Container checks require Docker:

```bash
docker compose -f docs/examples/docker-compose.example.yml config
docker compose -f docs/examples/docker-compose.build.yml config
tests/container-build.sh
```

The deployment compose example uses the published GHCR image. The build compose
artifact keeps the repository-local image build path used by smoke tests.

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
- Workflow linting runs automatically when files under `.github/workflows/`
  change, and can also be run from manual CI dispatch.

## Releases

Create a stable release by pushing a `vX.Y.Z` tag:

```bash
git tag v1.2.3
git push origin v1.2.3
```

Manual release tags run the Linux validation suite, build the Docker image for
Linux amd64, publish it to `ghcr.io/magrhino/wud-updater`, and create a GitHub
Release with generated notes. Release Please-created releases publish the same
image tags without rerunning the CI validation that already passed before the
release PR. Image tags are published as `vX.Y.Z`, `X.Y.Z`, `X.Y`, and `latest`.
