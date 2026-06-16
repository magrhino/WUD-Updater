import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import type { ManagedSettingEntry } from "../../api/client";
import { useSettingsStore } from "../../stores/settings";
import { focusOnboardingChecklist } from "./settingsDom";
import {
  coreUpdateTourStatusLabel,
  coreUpdateTourStepLabel,
  DIGEST_PIN_UPDATES_LABELS,
  managedOptions,
  ONBOARDING_CHECKLIST_LABELS,
  THEME_PREFERENCE_LABELS,
} from "./settingsDisplay";
import { useSettingsSafety } from "./useSettingsSafety";

function managedSourceLabel(entry: ManagedSettingEntry | undefined): string {
  return entry?.source === "configured" ? "Configured" : "Default";
}

export function useManagedPreferences() {
  const settings = useSettingsStore();
  const router = useRouter();
  const { preferencesDisabledReason } = useSettingsSafety();

  const settingsData = computed(() => settings.settings);
  const managedEntries = computed(() => settingsData.value?.managed ?? []);
  const themePreferenceEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "theme_preference"),
  );
  const onboardingChecklistEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "onboarding_checklist"),
  );
  const composeIgnorePathsEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "compose_ignore_paths"),
  );
  const digestPinUpdatesEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "digest_pin_updates"),
  );

  const themePreferenceValue = ref("system");
  const onboardingChecklistValue = ref("visible");
  const composeIgnorePathsValue = ref("");
  const digestPinUpdatesValue = ref("false");
  const preferencesMessage = ref("");
  const preferencesError = ref("");

  const preferenceControlsDisabled = computed(
    () => settings.loading || preferencesDisabledReason.value !== "",
  );
  const composeIgnorePathsEditable = computed(
    () => composeIgnorePathsEntry.value?.editable === true,
  );
  const digestPinUpdatesEditable = computed(
    () => digestPinUpdatesEntry.value?.editable === true,
  );
  const preferencesDirty = computed(
    () =>
      themePreferenceValue.value !==
        (themePreferenceEntry.value?.value ?? "system") ||
      onboardingChecklistValue.value !==
        (onboardingChecklistEntry.value?.value ?? "visible") ||
      (composeIgnorePathsEditable.value &&
        composeIgnorePathsValue.value !==
          (composeIgnorePathsEntry.value?.value ?? "")) ||
      (digestPinUpdatesEditable.value &&
        digestPinUpdatesValue.value !==
          (digestPinUpdatesEntry.value?.value ?? "false")),
  );
  const preferenceSaveDisabled = computed(
    () => preferenceControlsDisabled.value || !preferencesDirty.value,
  );
  const themePreferenceOptions = computed(() =>
    managedOptions(themePreferenceEntry.value, THEME_PREFERENCE_LABELS),
  );
  const onboardingChecklistOptions = computed(() =>
    managedOptions(onboardingChecklistEntry.value, ONBOARDING_CHECKLIST_LABELS),
  );
  const digestPinUpdatesOptions = computed(() =>
    managedOptions(digestPinUpdatesEntry.value, DIGEST_PIN_UPDATES_LABELS),
  );
  const coreUpdateTourStatus = computed(() =>
    coreUpdateTourStatusLabel(settings.coreUpdateTour?.status),
  );
  const coreUpdateTourStep = computed(() =>
    coreUpdateTourStepLabel(settings.coreUpdateTour?.step),
  );

  function hydratePreferenceForm(): void {
    themePreferenceValue.value = themePreferenceEntry.value?.value ?? "system";
    onboardingChecklistValue.value =
      onboardingChecklistEntry.value?.value ?? "visible";
    composeIgnorePathsValue.value = composeIgnorePathsEntry.value?.value ?? "";
    digestPinUpdatesValue.value = digestPinUpdatesEntry.value?.value ?? "false";
  }

  function resetPreferenceForm(): void {
    hydratePreferenceForm();
    preferencesMessage.value = "";
    preferencesError.value = "";
  }

  async function saveManagedPreferences(): Promise<void> {
    if (preferenceControlsDisabled.value) {
      return;
    }
    preferencesMessage.value = "";
    preferencesError.value = "";
    const values: Record<string, string> = {};
    if (themePreferenceValue.value !== (themePreferenceEntry.value?.value ?? "system")) {
      values.theme_preference = themePreferenceValue.value;
    }
    if (
      onboardingChecklistValue.value !==
      (onboardingChecklistEntry.value?.value ?? "visible")
    ) {
      values.onboarding_checklist = onboardingChecklistValue.value;
    }
    if (
      composeIgnorePathsEditable.value &&
      composeIgnorePathsValue.value !==
        (composeIgnorePathsEntry.value?.value ?? "")
    ) {
      values.compose_ignore_paths = composeIgnorePathsValue.value;
    }
    if (
      digestPinUpdatesEditable.value &&
      digestPinUpdatesValue.value !==
        (digestPinUpdatesEntry.value?.value ?? "false")
    ) {
      values.digest_pin_updates = digestPinUpdatesValue.value;
    }
    if (!Object.keys(values).length) {
      return;
    }

    try {
      const response = await settings.updateManagedSettings(values);
      preferencesMessage.value = `Preferences saved. Audit run #${response.audit_run_id}.`;
      hydratePreferenceForm();
    } catch (error_) {
      preferencesError.value =
        error_ instanceof Error ? error_.message : "Preferences could not be saved";
    }
  }

  async function relaunchOnboardingChecklist(): Promise<void> {
    if (preferenceControlsDisabled.value) {
      return;
    }
    preferencesMessage.value = "";
    preferencesError.value = "";
    try {
      const response = await settings.updateManagedSettings({
        onboarding_checklist: "visible",
      });
      hydratePreferenceForm();
      if (settings.onboarding?.visible === true) {
        preferencesMessage.value = `Onboarding checklist relaunched. Audit run #${response.audit_run_id}.`;
        await focusOnboardingChecklist();
      } else {
        preferencesMessage.value = `Onboarding checklist marked visible. Audit run #${response.audit_run_id}.`;
      }
    } catch (error_) {
      preferencesError.value =
        error_ instanceof Error
          ? error_.message
          : "Onboarding checklist could not be relaunched";
    }
  }

  async function replayCoreUpdateTour(): Promise<void> {
    if (preferenceControlsDisabled.value) {
      return;
    }
    preferencesMessage.value = "";
    preferencesError.value = "";
    try {
      await settings.updateCoreUpdateTour("in_progress", "dashboard");
      await router?.push({ name: "dashboard" });
    } catch (error_) {
      preferencesError.value =
        error_ instanceof Error ? error_.message : "Core update tour could not be started";
    }
  }

  async function dismissCoreUpdateTour(): Promise<void> {
    if (preferenceControlsDisabled.value) {
      return;
    }
    preferencesMessage.value = "";
    preferencesError.value = "";
    try {
      await settings.updateCoreUpdateTour(
        "dismissed",
        settings.coreUpdateTour?.step ?? "dashboard",
      );
      preferencesMessage.value = "Core update tour dismissed.";
    } catch (error_) {
      preferencesError.value =
        error_ instanceof Error
          ? error_.message
          : "Core update tour could not be dismissed";
    }
  }

  watch(managedEntries, hydratePreferenceForm, { immediate: true });

  return {
    settings,
    themePreferenceEntry,
    onboardingChecklistEntry,
    composeIgnorePathsEntry,
    digestPinUpdatesEntry,
    themePreferenceValue,
    onboardingChecklistValue,
    composeIgnorePathsValue,
    digestPinUpdatesValue,
    preferencesMessage,
    preferencesError,
    preferencesDisabledReason,
    preferenceControlsDisabled,
    composeIgnorePathsEditable,
    digestPinUpdatesEditable,
    preferencesDirty,
    preferenceSaveDisabled,
    themePreferenceOptions,
    onboardingChecklistOptions,
    digestPinUpdatesOptions,
    coreUpdateTourStatus,
    coreUpdateTourStep,
    managedSourceLabel,
    resetPreferenceForm,
    saveManagedPreferences,
    relaunchOnboardingChecklist,
    replayCoreUpdateTour,
    dismissCoreUpdateTour,
  };
}
