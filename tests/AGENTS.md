# AGENTS.md

## Scope

Rules for files under `tests/`. Root `AGENTS.md` controls repo-wide safety, commands, and files outside this directory; `src/wudup/AGENTS.md` owns backend behavior rules; `webui/AGENTS.md` owns frontend validation.

## Context Budget

- Read `tests/run-all.sh`, then the focused test or helper for the behavior being changed.
- For WebUI backend behavior, read the owning `src/wudup/web_*.py` module and `src/wudup/AGENTS.md` after locating the focused test.
- Avoid broad fixture, fake Docker, or E2E harness reads unless the touched behavior uses them.

## Test Ownership

| Area | Prefer | Notes |
|---|---|---|
| WebUI backend API, auth, pending, jobs, scheduler, self-update, retag, and state behavior | Focused `tests/test_python_web_*.py` files plus `tests/web_*_helpers.py` when shared setup is needed. | Do not grow `tests/test_python_web.py` unless the behavior is app-factory wiring or has no focused owner yet. |
| Updater, Compose, config, DB, and CLI Python behavior | Existing focused `tests/test_python_*` modules and narrow helper modules. | Keep tests temp-dir based and use fake Docker/Compose by default. |
| Shell wrappers, installer, WUD callbacks, and container entrypoints | Focused `tests/test-*.sh` scripts and `tests/fakes/docker`. | Keep shell tests temp-dir based and avoid real host mutation. |
| Docker build, Compose E2E, and live probes | Existing Docker-gated harnesses. | Run only when the task explicitly touches container or live integration behavior. |

Python syntax coverage uses `compileall` over `tests` in `tests/run-all.sh`; no file manifest update is needed when adding Python tests or helpers.

## Validation

Choose the smallest useful set:

- Instruction-only or docs-only test change: `git diff --check`.
- Python test/helper change: focused `python -m pytest tests/<file>.py`, then `tests/run-all.sh --python` when practical.
- WebUI backend safety or API test change: focused WebUI backend test modules plus `tests/run-all.sh --python`.
- Shell test change: syntax-check the touched shell dialect, then run the focused `tests/test-*.sh`; use ShellCheck when available.
- Container or Docker-gated harness change: run the focused harness and follow root `AGENTS.md` container validation.
