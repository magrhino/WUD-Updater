#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

run(){
  printf '==> %s\n' "$*"
  "$@"
}

run_python_checks() {
  python_bin="${PYTHON_BIN:-}"
  if [[ -z "$python_bin" ]]; then
    if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
      PATH="$REPO_ROOT/.venv/bin:${PATH:-}"
      export PATH
      python_bin="$REPO_ROOT/.venv/bin/python"
    elif command -v python3.14 >/dev/null 2>&1; then
      python_bin="python3.14"
    elif command -v python3.13 >/dev/null 2>&1; then
      python_bin="python3.13"
    elif command -v python3.12 >/dev/null 2>&1; then
      python_bin="python3.12"
    elif command -v python3.11 >/dev/null 2>&1; then
      python_bin="python3.11"
    elif command -v python3.10 >/dev/null 2>&1; then
      python_bin="python3.10"
    elif command -v python3 >/dev/null 2>&1; then
      python_bin="python3"
    else
      cat >&2 <<'EOF'
Python 3.10 or newer is required to run the Python package tests.
EOF
      exit 127
    fi
  fi

  run "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'

  if "$python_bin" -m ruff --version >/dev/null 2>&1; then
    run "$python_bin" -m ruff --version
  fi

  run "$python_bin" tests/check_python_deps.py "$REPO_ROOT/pyproject.toml"
  run env PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "$python_bin" -m pip check

  run "$python_bin" -m ruff check .

  run "$python_bin" -m py_compile \
    src/wudup/__init__.py \
    src/wudup/banner.py \
    src/wudup/cli.py \
    src/wudup/command.py \
    src/wudup/compose.py \
    src/wudup/compose_rewrite.py \
    src/wudup/config.py \
    src/wudup/container_identity.py \
    src/wudup/db.py \
    src/wudup/digest_provenance.py \
    src/wudup/digest_verifier.py \
    src/wudup/doctor.py \
    src/wudup/docker_cli.py \
    src/wudup/file_ops.py \
    src/wudup/images.py \
    src/wudup/init_config.py \
    src/wudup/line_specs.py \
    src/wudup/locks.py \
    src/wudup/naming.py \
    src/wudup/plan_actions.py \
    src/wudup/plan_digest_unpin.py \
    src/wudup/plan_identity.py \
    src/wudup/plan_issues.py \
    src/wudup/plan_matching.py \
    src/wudup/plan_models.py \
    src/wudup/plans.py \
    src/wudup/release_notes.py \
    src/wudup/self_update.py \
    src/wudup/terminal.py \
    src/wudup/truenas.py \
    src/wudup/updates.py \
    src/wudup/updater_audit.py \
    src/wudup/updater_digest_pin.py \
    src/wudup/updater_digest_unpin.py \
    src/wudup/updater_lifecycle.py \
    src/wudup/updater_lifecycle_digest.py \
    src/wudup/updater_lifecycle_health.py \
    src/wudup/updater_lifecycle_recreate.py \
    src/wudup/updater_lifecycle_rewrite.py \
    src/wudup/updater_lifecycle_scope.py \
    src/wudup/updater_lifecycle_state.py \
    src/wudup/updater_matching.py \
    src/wudup/updater_models.py \
    src/wudup/updater.py \
    src/wudup/updater_cli.py \
    src/wudup/updater_logging.py \
    src/wudup/updater_planning.py \
    src/wudup/updater_preflight.py \
    src/wudup/updater_runner_matching.py \
    src/wudup/updater_runner_operations.py \
    src/wudup/updater_runner_output.py \
    src/wudup/updater_tag_exclusions.py \
    src/wudup/web_auth.py \
    src/wudup/web_compat.py \
    src/wudup/web_database.py \
    src/wudup/web_demo_fixtures.py \
    src/wudup/web_diagnostics.py \
    src/wudup/web_health.py \
    src/wudup/web_jobs.py \
    src/wudup/web_metadata.py \
    src/wudup/web_models.py \
    src/wudup/web_onboarding.py \
    src/wudup/web_pending.py \
    src/wudup/web_pending_rescan.py \
    src/wudup/web_pending_rescan_audit.py \
    src/wudup/web_pending_rescan_payload.py \
    src/wudup/web_pending_sources.py \
    src/wudup/web_plans.py \
    src/wudup/web_release_notes.py \
    src/wudup/web_retag_plans.py \
    src/wudup/web_retags.py \
    src/wudup/web_run_verification.py \
    src/wudup/web_runs.py \
    src/wudup/web_scheduler.py \
    src/wudup/web_self_update.py \
    src/wudup/web_settings.py \
    src/wudup/web_startup.py \
    src/wudup/web_state.py \
    src/wudup/web_static.py \
    src/wudup/web_wud_states.py \
    src/wudup/web_wud_config.py \
    src/wudup/web_wud_api.py \
    src/wudup/web.py \
    src/wudup/wud_file.py \
    src/wud_updater/__init__.py \
    src/wud_updater/cli.py \
    src/wud_updater/self_update.py \
    tests/check_python_deps.py \
    tests/test_python_banner.py \
    tests/test_python_cli.py \
    tests/test_python_command.py \
    tests/compose_rewrite_helpers.py \
    tests/test_python_check_python_deps.py \
    tests/test_python_compose_digest_pins.py \
    tests/test_python_compose_digest_unpins.py \
    tests/test_python_compose_rewrite_core.py \
    tests/test_python_compose_tag_exclusions.py \
    tests/test_python_compose_tag_updates.py \
    tests/test_python_compose_yaml_safety.py \
    tests/test_python_config.py \
    tests/test_python_db.py \
    tests/test_python_digest_verifier.py \
    tests/test_python_doctor.py \
    tests/test_python_docker_compose.py \
    tests/test_python_init_config.py \
    tests/test_python_release_notes.py \
    tests/test_python_self_update.py \
    tests/test_python_terminal.py \
    tests/test_python_truenas.py \
    tests/test_python_updater_cli.py \
    tests/test_python_updater_logging.py \
    tests/test_python_web.py \
    tests/test_python_web_diagnostics.py \
    tests/test_python_web_demo_fixtures.py \
    tests/test_python_web_health.py \
    tests/test_python_web_jobs.py \
    tests/test_python_web_metadata.py \
    tests/test_python_web_onboarding.py \
    tests/test_python_web_release_notes.py \
    tests/test_python_web_release_notes_live.py \
    tests/test_python_web_retag_plans.py \
    tests/test_python_web_retags.py \
    tests/test_python_web_runs.py \
    tests/test_python_web_startup.py \
    tests/web_test_helpers.py \
    tests/test_python_webui_demo_state.py \
    tests/test_python_wud_file_ops.py \
    tests/test_python_wud_parsing.py \
    tests/test_python_update_from_wud_audit_errors.py \
    tests/test_python_update_from_wud_core.py \
    tests/test_python_update_from_wud_digest_pins.py \
    tests/test_python_update_from_wud_preflight.py \
    tests/test_python_update_from_wud_recreate.py \
    tests/test_python_update_from_wud_tag_exclusions.py \
    tests/test_python_update_from_wud_tag_updates.py \
    tests/test_python_updater_digest_pin.py \
    tests/test_python_updates_wrapper_core.py \
    tests/test_python_updates_wrapper_dispatch.py \
    tests/test_python_updates_wrapper_interactive.py \
    tests/test_python_updates_wrapper_invocation.py \
    tests/test_python_updates_wrapper_models.py \
    tests/test_python_updates_wrapper_self_update.py \
    tests/test_python_updates_wrapper_truenas.py \
    tests/test_python_web_apply_endpoint_execution.py \
    tests/test_python_web_apply_endpoint_guards.py \
    tests/test_python_web_auth_login_throttle.py \
    tests/test_python_web_auth_scaffold.py \
    tests/test_python_web_auth_session_reset.py \
    tests/test_python_web_auth_setup.py \
    tests/test_python_web_pending_cleanup.py \
    tests/test_python_web_pending_read.py \
    tests/test_python_web_pending_removal.py \
    tests/test_python_web_pending_rescan_guards.py \
    tests/test_python_web_pending_rescan_selected.py \
    tests/test_python_web_pending_targets.py \
    tests/test_python_web_plan_digest_pins.py \
    tests/test_python_web_plan_preview.py \
    tests/test_python_web_plan_tag_updates.py \
    tests/test_python_web_scheduler_due_policy.py \
    tests/test_python_web_scheduler_lifecycle.py \
    tests/test_python_web_scheduler_reservations.py \
    tests/test_python_web_scheduler_selection.py \
    tests/test_python_web_self_update_plan.py \
    tests/test_python_web_self_update_prepare.py \
    tests/test_python_web_self_update_pull.py \
    tests/test_python_web_self_update_restart.py \
    tests/test_python_web_self_update_status.py \
    tests/test_python_web_state_digest_pin_settings.py \
    tests/test_python_web_state_operations.py \
    tests/test_python_web_state_settings.py \
    tests/test_python_web_state_status.py \
    tests/test_python_web_wud_api.py \
    tests/update_from_wud_helpers.py \
    tests/updates_wrapper_helpers.py \
    tests/web_wud_rescan_helpers.py \
    tests/web_plan_test_helpers.py \
    tests/web_scheduler_test_helpers.py \
    webui/scripts/seed_demo_state.py

  run "$python_bin" -m pytest --cov=wudup --cov-branch --cov-report=xml
}

run_shell_checks() {
  if ! command -v shellcheck >/dev/null 2>&1; then
    cat >&2 <<'EOF'
shellcheck is required to run the full test suite.
Install it with your package manager, for example:
  brew install shellcheck
  sudo apt-get install shellcheck
EOF
    exit 127
  fi

  run bash -n \
    entrypoint.sh \
    install.sh \
    bin/updates \
    bin/docker-update-from-wud \
    wud/http.sh \
    wud/release-parser.sh \
    wud/release-notes-to-discord.sh \
    wud/github-release-embed.sh \
    wud/tag-manager.sh \
    tests/run-all.sh \
    tests/test-docker-update-from-wud.sh \
    tests/container-build.sh \
    tests/smoke-container-image.sh \
    tests/e2e-docker-compose.sh \
    tests/test-entrypoint.sh \
    tests/test-github-release-embed.sh \
    tests/test-release-parser.sh \
    tests/test-release-notes-to-discord.sh \
    tests/test-tag-manager.sh \
    tests/test-wud-append-updates.sh \
    tests/test-install.sh \
    tests/test-updates-wrapper.sh \
    tests/fakes/docker

  run sh -n \
    wud/on-update.sh \
    wud/append-updates.sh

  run shellcheck \
    entrypoint.sh \
    install.sh \
    bin/updates \
    bin/docker-update-from-wud \
    wud/on-update.sh \
    wud/append-updates.sh \
    wud/http.sh \
    wud/release-parser.sh \
    wud/release-notes-to-discord.sh \
    wud/github-release-embed.sh \
    wud/tag-manager.sh \
    tests/run-all.sh \
    tests/test-docker-update-from-wud.sh \
    tests/container-build.sh \
    tests/smoke-container-image.sh \
    tests/e2e-docker-compose.sh \
    tests/test-entrypoint.sh \
    tests/test-github-release-embed.sh \
    tests/test-release-parser.sh \
    tests/test-release-notes-to-discord.sh \
    tests/test-tag-manager.sh \
    tests/test-wud-append-updates.sh \
    tests/test-install.sh \
    tests/test-updates-wrapper.sh \
    tests/fakes/docker

  for test_script in tests/test-*.sh; do
    run "$test_script"
  done
}

run_webui_checks() {
  local required="${1:-false}"

  if command -v npm >/dev/null 2>&1 && [[ -f webui/package-lock.json ]]; then
    run node --check webui/scripts/dev-server.mjs
    run npm --prefix webui ci
    run npm --prefix webui run typecheck
    run npm --prefix webui run test
    run npm --prefix webui run build
  elif [[ "$required" == true ]]; then
    cat >&2 <<'EOF'
npm and webui/package-lock.json are required to run WebUI checks.
EOF
    exit 127
  else
    printf '==> skipping webui npm checks; npm or webui/package-lock.json not found\n'
  fi
}

replay_parallel_log() {
  local label="$1"
  local status="$2"
  local log_file="$3"

  printf '\n==> %s checks output\n' "$label"
  if [[ -s "$log_file" ]]; then
    sed 's/^/    /' "$log_file"
  else
    printf '    no output\n'
  fi
  if [[ "$status" -eq 0 ]]; then
    printf '==> %s checks passed\n' "$label"
  else
    printf '==> %s checks failed with status %s\n' "$label" "$status"
  fi
}

run_all_checks() {
  local tmp_dir
  local python_log shell_log webui_log
  local python_pid shell_pid webui_pid
  local python_status=0 shell_status=0 webui_status=0
  local failed_sections=""

  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/wud-run-all.XXXXXX")"
  python_log="$tmp_dir/python.log"
  shell_log="$tmp_dir/shell.log"
  webui_log="$tmp_dir/webui.log"

  printf '==> running python, shell, and webui checks in parallel\n'

  run_python_checks > "$python_log" 2>&1 &
  python_pid=$!
  run_shell_checks > "$shell_log" 2>&1 &
  shell_pid=$!
  run_webui_checks false > "$webui_log" 2>&1 &
  webui_pid=$!

  if wait "$python_pid"; then
    python_status=0
  else
    python_status=$?
  fi
  if wait "$shell_pid"; then
    shell_status=0
  else
    shell_status=$?
  fi
  if wait "$webui_pid"; then
    webui_status=0
  else
    webui_status=$?
  fi

  replay_parallel_log "python" "$python_status" "$python_log"
  replay_parallel_log "shell" "$shell_status" "$shell_log"
  replay_parallel_log "webui" "$webui_status" "$webui_log"

  rm -rf "$tmp_dir"

  if [[ "$python_status" -ne 0 ]]; then
    failed_sections="${failed_sections} python($python_status)"
  fi
  if [[ "$shell_status" -ne 0 ]]; then
    failed_sections="${failed_sections} shell($shell_status)"
  fi
  if [[ "$webui_status" -ne 0 ]]; then
    failed_sections="${failed_sections} webui($webui_status)"
  fi
  if [[ -n "$failed_sections" ]]; then
    printf '\nFailed test section(s):%s\n' "$failed_sections" >&2
    return 1
  fi

  printf '\n==> all test sections passed\n'
}

MODE="--all"
if [[ $# -gt 0 ]]; then
  MODE="$1"
fi

case "$MODE" in
  --python)
    run_python_checks
    ;;
  --shell)
    run_shell_checks
    ;;
  --webui)
    run_webui_checks true
    ;;
  --all)
    run_all_checks
    ;;
  *)
    echo "Usage: $0 [--python | --shell | --webui | --all]" >&2
    exit 1
    ;;
esac
