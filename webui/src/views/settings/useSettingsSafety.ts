import { computed } from "vue";
import { AlertTriangle, ShieldCheck } from "@lucide/vue";

import { useAuthStore } from "../../stores/auth";
import { useSettingsStore } from "../../stores/settings";

export function useSettingsSafety() {
  const auth = useAuthStore();
  const settings = useSettingsStore();

  const settingsData = computed(() => settings.settings);
  const webuiEntries = computed(() => settingsData.value?.webui ?? []);
  const restartContainerEntry = computed(() =>
    webuiEntries.value.find((entry) => entry.name === "WUD_WEB_RESTART_CONTAINER"),
  );
  const restartContainerTarget = computed(
    () => restartContainerEntry.value?.value ?? "",
  );
  const mutationsEnabled = computed(
    () => auth.session?.mutations_enabled === true,
  );
  const mutationStatusIcon = computed(() =>
    mutationsEnabled.value ? AlertTriangle : ShieldCheck,
  );
  const mutationStatusLabel = computed(() =>
    mutationsEnabled.value ? "Mutations enabled" : "Read-only mode",
  );
  const mutationStatusDetail = computed(() =>
    mutationsEnabled.value
      ? "Browser actions can save managed preferences and request a WebUI container restart."
      : "Browser mutation actions are disabled server-side. Settings remain visible for inspection.",
  );
  const mutationStatusTagType = computed(() =>
    mutationsEnabled.value ? "warning" : "success",
  );
  const restartDisabledReason = computed(() => {
    if (!mutationsEnabled.value) {
      return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to restart the WebUI container.";
    }
    if (!restartContainerTarget.value) {
      return "Container restart is unavailable because no current container target was detected or configured.";
    }
    return "";
  });
  const restartTargetLabel = computed(() =>
    restartContainerTarget.value
      ? `Restart target: ${restartContainerTarget.value}`
      : "No restart target",
  );
  const preferencesDisabledReason = computed(() => {
    if (!mutationsEnabled.value) {
      const managedEntries = settingsData.value?.managed ?? [];
      if (
        managedEntries.length > 0 &&
        managedEntries.every((entry) => !entry.editable)
      ) {
        const detail = managedEntries.find(
          (entry) => entry.disabled_reason,
        )?.disabled_reason;
        if (detail) {
          return `Read-only mode is active. ${detail}`;
        }
      }
      return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to save managed WebUI preferences.";
    }
    return "";
  });

  return {
    settingsData,
    webuiEntries,
    restartContainerEntry,
    restartContainerTarget,
    mutationsEnabled,
    mutationStatusIcon,
    mutationStatusLabel,
    mutationStatusDetail,
    mutationStatusTagType,
    restartDisabledReason,
    restartTargetLabel,
    preferencesDisabledReason,
  };
}
