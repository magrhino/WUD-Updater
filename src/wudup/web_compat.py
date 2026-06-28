"""Legacy compatibility exports for :mod:`wudup.web`."""

from __future__ import annotations

from typing import Any

from . import (
    web_auth,
    web_jobs,
    web_models,
    web_pending,
    web_plans,
    web_release_notes,
    web_retags,
    web_runs,
    web_scheduler,
    web_security,
    web_settings,
    web_state,
    web_static,
)

__all__ = (
    "LEGACY_EXPORT_NAMES",
    "legacy_export_names",
    "resolve_legacy_export",
)


_ExportTarget = tuple[object, str]


def _model_exports() -> dict[str, _ExportTarget]:
    return {name: (web_models, name) for name in web_models.__all__}


_EXPORT_TARGETS: dict[str, _ExportTarget] = {
    **_model_exports(),
    "WebAdminResetError": (web_auth, "WebAdminResetError"),
    "WebConfigError": (web_auth, "WebConfigError"),
    "_parse_allowed_hosts": (web_auth, "_parse_allowed_hosts"),
    "_parse_bool": (web_auth, "_parse_bool"),
    "_parse_origins": (web_auth, "_parse_origins"),
    "_parse_public_origin": (web_auth, "_parse_public_origin"),
    "_parse_secure_cookie_mode": (web_auth, "_parse_secure_cookie_mode"),
    "_parse_trusted_proxies": (web_auth, "_parse_trusted_proxies"),
    "_prepare_web_auth_state": (web_auth, "_prepare_web_auth_state"),
    "_reset_admin_url": (web_auth, "_reset_admin_url"),
    "_setup_required": (web_auth, "_setup_required"),
    "_settings": (web_auth, "_settings"),
    "_normalize_username": (web_auth, "_normalize_username"),
    "_validate_bind_host_allowed": (web_auth, "_validate_bind_host_allowed"),
    "_validate_startup_auth": (web_auth, "_validate_startup_auth"),
    "_validation_exception_handler": (web_auth, "_validation_exception_handler"),
    "api_auth_csrf": (web_auth, "api_auth_csrf"),
    "api_auth_login": (web_auth, "api_auth_login"),
    "api_auth_logout": (web_auth, "api_auth_logout"),
    "api_auth_reset_admin_claim": (web_auth, "api_auth_reset_admin_claim"),
    "api_auth_session": (web_auth, "api_auth_session"),
    "api_setup_claim": (web_auth, "api_setup_claim"),
    "api_setup_status": (web_auth, "api_setup_status"),
    "issue_admin_recovery_claim": (web_auth, "issue_admin_recovery_claim"),
    "request_safety_middleware": (web_auth, "request_safety_middleware"),
    "require_auth": (web_auth, "require_auth"),
    "CSRF_COOKIE": (web_auth, "CSRF_COOKIE"),
    "CSRF_HEADER": (web_auth, "CSRF_HEADER"),
    "LOGIN_THROTTLE_COOLDOWN_SECONDS": (
        web_auth,
        "LOGIN_THROTTLE_COOLDOWN_SECONDS",
    ),
    "LOGIN_THROTTLE_MAX_CLIENT_ENTRIES": (
        web_auth,
        "LOGIN_THROTTLE_MAX_CLIENT_ENTRIES",
    ),
    "LOGIN_THROTTLE_MAX_ENTRIES": (web_auth, "LOGIN_THROTTLE_MAX_ENTRIES"),
    "LOGIN_THROTTLE_MAX_FAILURES": (web_auth, "LOGIN_THROTTLE_MAX_FAILURES"),
    "PASSWORD_HASHER": (web_auth, "PASSWORD_HASHER"),
    "RESET_ADMIN_CLAIM_EXPIRES_KEY": (
        web_auth,
        "RESET_ADMIN_CLAIM_EXPIRES_KEY",
    ),
    "RESET_ADMIN_CLAIM_HASH_KEY": (web_auth, "RESET_ADMIN_CLAIM_HASH_KEY"),
    "RESET_ADMIN_CLAIM_USER_ID_KEY": (
        web_auth,
        "RESET_ADMIN_CLAIM_USER_ID_KEY",
    ),
    "SESSION_MAX_AGE_SECONDS": (web_auth, "SESSION_MAX_AGE_SECONDS"),
    "SETUP_CLAIM_EXPIRES_KEY": (web_auth, "SETUP_CLAIM_EXPIRES_KEY"),
    "SETUP_CLAIM_HASH_KEY": (web_auth, "SETUP_CLAIM_HASH_KEY"),
    "_claim_initial_admin": (web_auth, "_claim_initial_admin"),
    "_record_login_failure": (web_auth, "_record_login_failure"),
    "_session_user": (web_auth, "_session_user"),
    "DEFAULT_WEB_HOST": (web_settings, "DEFAULT_WEB_HOST"),
    "DEFAULT_RUN_LIMIT": (web_runs, "DEFAULT_RUN_LIMIT"),
    "DEFAULT_LOG_TAIL_BYTES": (web_runs, "DEFAULT_LOG_TAIL_BYTES"),
    "DEFAULT_JOB_LOG_TAIL_BYTES": (web_jobs, "DEFAULT_JOB_LOG_TAIL_BYTES"),
    "MAX_LOG_TAIL_BYTES": (web_runs, "MAX_LOG_TAIL_BYTES"),
    "MANAGED_THEME_PREFERENCE_KEY": (web_settings, "MANAGED_THEME_PREFERENCE_KEY"),
    "MANAGED_THEME_PREFERENCE_DB_KEY": (
        web_settings,
        "MANAGED_THEME_PREFERENCE_DB_KEY",
    ),
    "MANAGED_ONBOARDING_CHECKLIST_KEY": (
        web_settings,
        "MANAGED_ONBOARDING_CHECKLIST_KEY",
    ),
    "MANAGED_COMPOSE_IGNORE_PATHS_KEY": (
        web_settings,
        "MANAGED_COMPOSE_IGNORE_PATHS_KEY",
    ),
    "MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY": (
        web_settings,
        "MANAGED_COMPOSE_IGNORE_PATHS_DB_KEY",
    ),
    "MANAGED_DIGEST_PIN_UPDATES_KEY": (
        web_settings,
        "MANAGED_DIGEST_PIN_UPDATES_KEY",
    ),
    "MANAGED_DIGEST_PIN_UPDATES_DB_KEY": (
        web_settings,
        "MANAGED_DIGEST_PIN_UPDATES_DB_KEY",
    ),
    "THEME_PREFERENCE_VALUES": (web_settings, "THEME_PREFERENCE_VALUES"),
    "ONBOARDING_CHECKLIST_VALUES": (web_settings, "ONBOARDING_CHECKLIST_VALUES"),
    "DIGEST_PIN_UPDATES_VALUES": (web_settings, "DIGEST_PIN_UPDATES_VALUES"),
    "JOB_STREAM_HEARTBEAT_SECONDS": (web_jobs, "JOB_STREAM_HEARTBEAT_SECONDS"),
    "JOB_STREAM_LOG_POLL_SECONDS": (web_jobs, "JOB_STREAM_LOG_POLL_SECONDS"),
    "AUTO_UPDATE_POLL_SECONDS": (web_scheduler, "AUTO_UPDATE_POLL_SECONDS"),
    "AUTO_UPDATE_GRACE_SECONDS": (web_scheduler, "AUTO_UPDATE_GRACE_SECONDS"),
    "AUTO_UPDATE_DAYS": (web_scheduler, "AUTO_UPDATE_DAYS"),
    "AutoUpdateScheduleReservationError": (
        web_scheduler,
        "AutoUpdateScheduleReservationError",
    ),
    "api_pending": (web_pending, "api_pending"),
    "api_update_targets": (web_pending, "api_update_targets"),
    "api_retag_targets": (web_retags, "api_retag_targets"),
    "api_pending_cleanup": (web_pending, "api_pending_cleanup"),
    "api_pending_removal_plan": (web_pending, "api_pending_removal_plan"),
    "api_pending_removal": (web_pending, "api_pending_removal"),
    "_pending_response": (web_pending, "pending_response"),
    "_update_targets_response": (web_pending, "update_targets_response"),
    "_pending_removal_plan": (web_pending, "pending_removal_plan"),
    "_parse_pending_file": (web_pending, "parse_pending_file"),
    "api_create_plan": (web_plans, "api_create_plan"),
    "api_create_job": (web_plans, "api_create_job"),
    "api_apply_plan": (web_plans, "api_apply_plan"),
    "_build_web_plan": (web_plans, "build_web_plan"),
    "_tag_overrides_from_payload": (web_plans, "tag_overrides_from_payload"),
    "_digest_pin_label_rewrite_approvals_from_payload": (
        web_plans,
        "digest_pin_label_rewrite_approvals_from_payload",
    ),
    "_plan_can_apply": (web_plans, "plan_can_apply"),
    "_plan_response": (web_plans, "plan_response"),
    "_submit_apply_job": (web_plans, "submit_apply_job"),
    "api_release_notes": (web_release_notes, "api_release_notes"),
    "api_refresh_release_notes": (web_release_notes, "api_refresh_release_notes"),
    "api_security_scans": (web_security, "api_security_scans"),
    "api_refresh_security_scans": (web_security, "api_refresh_security_scans"),
    "api_security_scan_job": (web_security, "api_security_scan_job"),
    "_release_notes_response": (web_release_notes, "release_notes_response"),
    "_release_note_source_resolver": (
        web_release_notes,
        "release_note_source_resolver",
    ),
    "api_update_managed_settings": (
        web_settings,
        "api_update_managed_settings",
    ),
    "api_settings": (web_settings, "api_settings"),
    "_effective_config": (web_settings, "_effective_config"),
    "_effective_compose_ignore_paths": (
        web_settings,
        "_effective_compose_ignore_paths",
    ),
    "_stored_compose_ignore_paths": (web_settings, "_stored_compose_ignore_paths"),
    "_compose_ignore_env_configured": (
        web_settings,
        "_compose_ignore_env_configured",
    ),
    "_compose_ignore_paths_disabled_reason": (
        web_settings,
        "_compose_ignore_paths_disabled_reason",
    ),
    "_effective_digest_pin_updates": (
        web_settings,
        "_effective_digest_pin_updates",
    ),
    "_stored_digest_pin_updates": (web_settings, "_stored_digest_pin_updates"),
    "_digest_pin_env_configured": (web_settings, "_digest_pin_env_configured"),
    "_digest_pin_disabled_reason": (web_settings, "_digest_pin_disabled_reason"),
    "_managed_settings_entries": (web_settings, "_managed_settings_entries"),
    "_managed_settings_entries_from_conn": (
        web_settings,
        "_managed_settings_entries_from_conn",
    ),
    "_managed_settings_db_values": (web_settings, "_managed_settings_db_values"),
    "_managed_settings_entries_from_values": (
        web_settings,
        "_managed_settings_entries_from_values",
    ),
    "_validated_managed_setting_updates": (
        web_settings,
        "_validated_managed_setting_updates",
    ),
    "_apply_managed_setting_updates": (
        web_settings,
        "_apply_managed_setting_updates",
    ),
    "_managed_settings_audit_values": (
        web_settings,
        "_managed_settings_audit_values",
    ),
    "_updater_settings_entries": (web_settings, "_updater_settings_entries"),
    "_webui_settings_entries": (web_settings, "_webui_settings_entries"),
    "_secret_settings": (web_settings, "_secret_settings"),
    "_config_setting_entry": (web_settings, "_config_setting_entry"),
    "_settings_entry": (web_settings, "_settings_entry"),
    "_config_default_value": (web_settings, "_config_default_value"),
    "_static_config_default": (web_settings, "_static_config_default"),
    "_config_value": (web_settings, "_config_value"),
    "_settings_env": (web_settings, "_settings_env"),
    "_env_configured": (web_settings, "_env_configured"),
    "_format_bool": (web_settings, "_format_bool"),
    "_format_sequence": (web_settings, "_format_sequence"),
    "api_state_operation": (web_state, "api_state_operation"),
    "api_service_policies": (web_state, "api_service_policies"),
    "api_snoozes": (web_state, "api_snoozes"),
    "api_tag_exclusions": (web_state, "api_tag_exclusions"),
    "_auto_update_days_from_row": (web_state, "_auto_update_days_from_row"),
    "_service_policy_from_row": (web_state, "_service_policy_from_row"),
    "_snooze_from_row": (web_state, "_snooze_from_row"),
    "_dependency_snooze_from_row": (web_state, "_dependency_snooze_from_row"),
    "_tag_exclusion_from_row": (web_state, "_tag_exclusion_from_row"),
    "_apply_state_operation": (web_state, "_apply_state_operation"),
    "_upsert_service_policy": (web_state, "_upsert_service_policy"),
    "_service_policy_upsert_values": (
        web_state,
        "_service_policy_upsert_values",
    ),
    "_normalized_auto_update_time": (web_state, "_normalized_auto_update_time"),
    "_normalized_auto_update_days": (web_state, "_normalized_auto_update_days"),
    "_delete_service_policy": (web_state, "_delete_service_policy"),
    "_create_snooze": (web_state, "_create_snooze"),
    "_delete_snooze": (web_state, "_delete_snooze"),
    "_create_dependency_snooze": (web_state, "_create_dependency_snooze"),
    "_delete_dependency_snooze": (web_state, "_delete_dependency_snooze"),
    "_upsert_tag_exclusion": (web_state, "_upsert_tag_exclusion"),
    "_set_tag_exclusion_status": (web_state, "_set_tag_exclusion_status"),
    "_service_policy_row": (web_state, "_service_policy_row"),
    "_snooze_row": (web_state, "_snooze_row"),
    "_dependency_snooze_row": (web_state, "_dependency_snooze_row"),
    "_tag_exclusion_row": (web_state, "_tag_exclusion_row"),
    "_tag_exclusion_unique_row": (web_state, "_tag_exclusion_unique_row"),
    "_required_state_text": (web_state, "_required_state_text"),
    "_future_iso_timestamp": (web_state, "_future_iso_timestamp"),
    "_normalized_image_repo": (web_state, "_normalized_image_repo"),
    "_tag_exclusion_service_key": (web_state, "_tag_exclusion_service_key"),
    "_valid_tag": (web_state, "_valid_tag"),
    "_insert_managed_settings_audit": (
        web_settings,
        "_insert_managed_settings_audit",
    ),
    "_insert_state_audit": (web_state, "_insert_state_audit"),
    "_state_actor_type": (web_state, "_state_actor_type"),
    "_state_audit_stack_name": (web_state, "_state_audit_stack_name"),
    "_state_audit_service_name": (web_state, "_state_audit_service_name"),
    "_state_audit_image": (web_state, "_state_audit_image"),
    "_service_policy_summary": (web_state, "_service_policy_summary"),
    "_snooze_summary": (web_state, "_snooze_summary"),
    "_dependency_snooze_summary": (web_state, "_dependency_snooze_summary"),
    "_tag_exclusion_summary": (web_state, "_tag_exclusion_summary"),
    "_json_object": (web_state, "_json_object"),
    "_json_list": (web_state, "_json_list"),
    "api_run_log": (web_runs, "api_run_log"),
    "api_runs": (web_runs, "api_runs"),
    "api_run_detail": (web_runs, "api_run_detail"),
    "_run_summary_from_row": (web_runs, "_run_summary_from_row"),
    "_pending_update_from_row": (web_runs, "_pending_update_from_row"),
    "_event_from_row": (web_runs, "_event_from_row"),
    "_sanitize_run_summary": (web_runs, "_sanitize_run_summary"),
    "_sanitize_run_detail": (web_runs, "_sanitize_run_detail"),
    "_sanitize_run_event": (web_runs, "_sanitize_run_event"),
    "_metadata_from_row": (web_runs, "_metadata_from_row"),
    "_safe_log_path": (web_runs, "_safe_log_path"),
    "_path_is_or_under": (web_runs, "_path_is_or_under"),
    "_run_log_response": (web_runs, "_run_log_response"),
    "_read_log_tail": (web_runs, "_read_log_tail"),
    "_mount_static_spa_if_present": (web_static, "mount_static_spa_if_present"),
    "_static_spa_available": (web_static, "static_spa_available"),
    "_resolve_static_dir": (web_static, "resolve_static_dir"),
    "_safe_update_auto_update_schedule_runs": (
        web_scheduler,
        "_safe_update_auto_update_schedule_runs",
    ),
}

LEGACY_EXPORT_NAMES = tuple(sorted(_EXPORT_TARGETS))


def legacy_export_names() -> tuple[str, ...]:
    return LEGACY_EXPORT_NAMES


def resolve_legacy_export(name: str) -> Any:
    try:
        owner, attribute = _EXPORT_TARGETS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(owner, attribute)
