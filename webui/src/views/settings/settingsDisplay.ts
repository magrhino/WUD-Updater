import type {
  CoreUpdateTourStatus,
  CoreUpdateTourStep,
  ManagedSettingEntry,
  SecretSettingStatus,
  SettingsEntry,
} from "../../api/client";
import type { SettingsDisclosureRow } from "../../components/SettingsDisclosureSection.types";

export const PATH_ENTRY_NAMES = new Set([
  "DOCKER_BASE",
  "HOST_DOCKER_BASE",
  "WUD_OUT_FILE",
  "WUD_LOG_DIR",
  "WUD_DB_PATH",
]);

export const BEHAVIOR_ENTRY_NAMES = new Set([
  "WUD_UPDATE_MODE",
  "WUD_MAX_WAIT",
  "WUD_LOCK_TIMEOUT",
  "WUD_TIMEZONE",
  "WUD_COMPOSE_IGNORE_PATHS",
  "WUD_DIGEST_PIN_UPDATES",
]);

export const SETTINGS_SECTION_LINKS = [
  { id: "settings-actions", label: "Actions" },
  { id: "settings-preferences", label: "Preferences" },
  { id: "settings-runtime", label: "Runtime" },
  { id: "settings-paths", label: "Paths" },
  { id: "settings-behavior", label: "Behavior" },
  { id: "settings-webui", label: "WebUI safety" },
  { id: "settings-secrets", label: "Secrets" },
  { id: "settings-diagnostics", label: "Diagnostics" },
  { id: "settings-docs", label: "Docs" },
] as const;

export const THEME_PREFERENCE_LABELS: Record<string, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};

export const ONBOARDING_CHECKLIST_LABELS: Record<string, string> = {
  visible: "Visible",
  dismissed: "Dismissed",
};

export const DIGEST_PIN_UPDATES_LABELS: Record<string, string> = {
  false: "Disabled",
  true: "Enabled",
};

const CORE_UPDATE_TOUR_STATUS_LABELS: Record<CoreUpdateTourStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
  dismissed: "Dismissed",
};

const CORE_UPDATE_TOUR_STEP_LABELS: Record<CoreUpdateTourStep, string> = {
  dashboard: "Dashboard",
  pending_select: "Pending selection",
  pending_preflight: "Preflight",
  pending_apply: "Apply guidance",
  runs_history: "History",
};

export function displayValue(value: string): string {
  return value || "unset";
}

export function entryCountLabel(entries: SettingsEntry[]): string {
  return `${entries.length} value${entries.length === 1 ? "" : "s"}`;
}

export function sourceLabel(entry: SettingsEntry): string {
  if (entry.source === "request") {
    return "Request scoped";
  }
  if (entry.source === "derived") {
    return "Runtime derived";
  }
  return entry.configured ? "Configured" : "Default";
}

export function sourceTagType(
  entry: SettingsEntry,
): "default" | "info" | "success" | "warning" {
  if (entry.source === "request") {
    return "info";
  }
  if (entry.source === "derived") {
    return "info";
  }
  return entry.configured ? "success" : "default";
}

export function secretLabel(secret: SecretSettingStatus): string {
  return secret.configured ? "Configured" : "Not configured";
}

export function settingRows(entries: SettingsEntry[]): SettingsDisclosureRow[] {
  return entries.map((entry) => ({
    key: entry.name,
    name: entry.name,
    detail: `Default: ${displayValue(entry.default_value)}`,
    value: displayValue(entry.value),
    valueKind: "code",
    tagLabel: sourceLabel(entry),
    tagType: sourceTagType(entry),
  }));
}

export function secretRows(
  secrets: SecretSettingStatus[],
): SettingsDisclosureRow[] {
  return secrets.map((secret) => ({
    key: secret.name,
    name: secret.name,
    detail: "Value never rendered",
    value: "Raw value hidden",
    valueKind: "text",
    valueClass: "settings-redacted-value",
    tagLabel: secretLabel(secret),
    tagType: secret.configured ? "success" : "default",
  }));
}

export function managedOptions(
  entry: ManagedSettingEntry | undefined,
  labels: Record<string, string>,
): Array<{ label: string; value: string }> {
  return (entry?.allowed_values ?? []).map((value) => ({
    label: labels[value] ?? value,
    value,
  }));
}

export function coreUpdateTourStatusLabel(
  status: CoreUpdateTourStatus | undefined,
): string {
  const value = status ?? "not_started";
  return CORE_UPDATE_TOUR_STATUS_LABELS[value] ?? value;
}

export function coreUpdateTourStepLabel(
  step: CoreUpdateTourStep | undefined,
): string {
  const value = step ?? "dashboard";
  return CORE_UPDATE_TOUR_STEP_LABELS[value] ?? value;
}
