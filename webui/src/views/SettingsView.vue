<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useClipboard, useMediaQuery } from "@vueuse/core";
import { useRoute, useRouter } from "vue-router";
import {
  AlertTriangle,
  Copy,
  Download,
  ExternalLink,
  FileJson,
  KeyRound,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
} from "@lucide/vue";
import {
  NAlert,
  NButton,
  NButtonGroup,
  NEmpty,
  NFlex,
  NGi,
  NGrid,
  NInput,
  NModal,
  NSelect,
  NSkeleton,
  NTag,
} from "naive-ui";

import type {
  ManagedSettingEntry,
  SecretSettingStatus,
  SettingsEntry,
} from "../api/client";
import OnboardingChecklist from "../components/OnboardingChecklist.vue";
import SettingsDisclosureSection, {
  type SettingsDisclosureRow,
} from "../components/SettingsDisclosureSection.vue";
import { useAuthStore } from "../stores/auth";
import { useSettingsStore } from "../stores/settings";
import { useConnectionStore } from "../stores/connection";

const auth = useAuthStore();
const settings = useSettingsStore();
const connection = useConnectionStore();
const route = useRoute();
const router = useRouter();

const PATH_ENTRY_NAMES = new Set([
  "DOCKER_BASE",
  "HOST_DOCKER_BASE",
  "WUD_OUT_FILE",
  "WUD_LOG_DIR",
  "WUD_DB_PATH",
]);
const BEHAVIOR_ENTRY_NAMES = new Set([
  "WUD_UPDATE_MODE",
  "WUD_MAX_WAIT",
  "WUD_LOCK_TIMEOUT",
  "WUD_TIMEZONE",
  "WUD_COMPOSE_IGNORE_PATHS",
  "WUD_DIGEST_PIN_UPDATES",
]);
const THEME_PREFERENCE_LABELS: Record<string, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};
const ONBOARDING_CHECKLIST_LABELS: Record<string, string> = {
  visible: "Visible",
  dismissed: "Dismissed",
};
const DIGEST_PIN_UPDATES_LABELS: Record<string, string> = {
  false: "Disabled",
  true: "Enabled",
};
const CORE_UPDATE_TOUR_STATUS_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
  dismissed: "Dismissed",
};
const CORE_UPDATE_TOUR_STEP_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  pending_select: "Pending selection",
  pending_preflight: "Preflight",
  pending_apply: "Apply guidance",
  runs_history: "History",
};
const SETTINGS_SECTION_LINKS = [
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

const settingsData = computed(() => settings.settings);
const updaterEntries = computed(() => settingsData.value?.updater ?? []);
const webuiEntries = computed(() => settingsData.value?.webui ?? []);
const secrets = computed(() => settingsData.value?.secrets ?? []);
const managedEntries = computed(() => settingsData.value?.managed ?? []);
const restartDialogVisible = ref(false);
const restartMessage = ref("");
const restartError = ref("");
const themePreferenceValue = ref("system");
const onboardingChecklistValue = ref("visible");
const composeIgnorePathsValue = ref("");
const digestPinUpdatesValue = ref("false");
const preferencesMessage = ref("");
const preferencesError = ref("");
const compactSettingsLayout = useMediaQuery("(max-width: 560px)");
const allEntries = computed(() => [...updaterEntries.value, ...webuiEntries.value]);
const pathEntries = computed(() =>
  updaterEntries.value.filter((entry) => PATH_ENTRY_NAMES.has(entry.name)),
);
const behaviorEntries = computed(() =>
  updaterEntries.value.filter((entry) => BEHAVIOR_ENTRY_NAMES.has(entry.name)),
);
const configuredEntryCount = computed(
  () => allEntries.value.filter((entry) => entry.configured).length,
);
const inheritedEntryCount = computed(
  () => allEntries.value.length - configuredEntryCount.value,
);
const runtimeScopedEntryCount = computed(
  () =>
    allEntries.value.filter(
      (entry) => entry.source === "derived" || entry.source === "request",
    ).length,
);
const configuredSecretCount = computed(
  () => secrets.value.filter((secret) => secret.configured).length,
);
const missingSecretCount = computed(
  () => secrets.value.length - configuredSecretCount.value,
);
const restartContainerEntry = computed(() =>
  webuiEntries.value.find((entry) => entry.name === "WUD_WEB_RESTART_CONTAINER"),
);
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
const restartContainerTarget = computed(() => restartContainerEntry.value?.value ?? "");
const mutationsEnabled = computed(() => auth.session?.mutations_enabled === true);
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
const restartButtonDisabled = computed(
  () => connection.loading || restartDisabledReason.value !== "",
);
const preferencesDisabledReason = computed(() => {
  if (!mutationsEnabled.value) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to save managed WebUI preferences.";
  }
  return "";
});
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
    themePreferenceValue.value !== (themePreferenceEntry.value?.value ?? "system") ||
    onboardingChecklistValue.value !==
      (onboardingChecklistEntry.value?.value ?? "visible") ||
    (composeIgnorePathsEditable.value &&
      composeIgnorePathsValue.value !== (composeIgnorePathsEntry.value?.value ?? "")) ||
    (digestPinUpdatesEditable.value &&
      digestPinUpdatesValue.value !== (digestPinUpdatesEntry.value?.value ?? "false")),
);
const preferenceSaveDisabled = computed(
  () => preferenceControlsDisabled.value || !preferencesDirty.value,
);
const restartTargetLabel = computed(() =>
  restartContainerTarget.value
    ? `Restart target: ${restartContainerTarget.value}`
    : "No restart target",
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
const coreUpdateTourStatusLabel = computed(() => {
  const status = settings.coreUpdateTour?.status ?? "not_started";
  return CORE_UPDATE_TOUR_STATUS_LABELS[status] ?? status;
});
const coreUpdateTourStepLabel = computed(() => {
  const step = settings.coreUpdateTour?.step ?? "dashboard";
  return CORE_UPDATE_TOUR_STEP_LABELS[step] ?? step;
});
const shouldFocusOnboardingChecklist = computed(
  () =>
    route?.query.onboarding === "1" &&
    settingsData.value !== null &&
    settings.onboarding?.visible === true,
);

function displayValue(value: string): string {
  return value || "unset";
}

function entryCountLabel(entries: SettingsEntry[]): string {
  return `${entries.length} value${entries.length === 1 ? "" : "s"}`;
}

function sourceLabel(entry: SettingsEntry): string {
  if (entry.source === "request") {
    return "Request scoped";
  }
  if (entry.source === "derived") {
    return "Runtime derived";
  }
  return entry.configured ? "Configured" : "Default";
}

function sourceTagType(entry: SettingsEntry): "default" | "info" | "success" | "warning" {
  if (entry.source === "request") {
    return "info";
  }
  if (entry.source === "derived") {
    return "info";
  }
  return entry.configured ? "success" : "default";
}

function secretLabel(secret: SecretSettingStatus): string {
  return secret.configured ? "Configured" : "Not configured";
}

function settingRows(entries: SettingsEntry[]): SettingsDisclosureRow[] {
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

const pathRows = computed(() => settingRows(pathEntries.value));
const behaviorRows = computed(() => settingRows(behaviorEntries.value));
const webuiRows = computed(() => settingRows(webuiEntries.value));
const secretRows = computed<SettingsDisclosureRow[]>(() =>
  secrets.value.map((secret) => ({
    key: secret.name,
    name: secret.name,
    detail: "Value never rendered",
    value: "Raw value hidden",
    valueKind: "text" as const,
    valueClass: "settings-redacted-value",
    tagLabel: secretLabel(secret),
    tagType: secret.configured ? "success" : "default",
  })),
);

function managedOptions(
  entry: ManagedSettingEntry | undefined,
  labels: Record<string, string>,
): Array<{ label: string; value: string }> {
  return (entry?.allowed_values ?? []).map((value) => ({
    label: labels[value] ?? value,
    value,
  }));
}

function hydratePreferenceForm(): void {
  themePreferenceValue.value = themePreferenceEntry.value?.value ?? "system";
  onboardingChecklistValue.value =
    onboardingChecklistEntry.value?.value ?? "visible";
  composeIgnorePathsValue.value = composeIgnorePathsEntry.value?.value ?? "";
  digestPinUpdatesValue.value = digestPinUpdatesEntry.value?.value ?? "false";
}

function openRestartDialog(): void {
  if (restartButtonDisabled.value) {
    return;
  }
  restartMessage.value = "";
  restartError.value = "";
  restartDialogVisible.value = true;
}

async function confirmRestartContainer(): Promise<void> {
  if (restartButtonDisabled.value) {
    return;
  }
  restartMessage.value = "";
  restartError.value = "";
  try {
    const response = await connection.restartContainer();
    restartDialogVisible.value = false;
    restartMessage.value = `Restart requested for ${response.container}. The WebUI may disconnect while the container comes back.`;
  } catch (exc) {
    restartError.value = exc instanceof Error ? exc.message : "Container restart failed";
  }
}

function resetPreferenceForm(): void {
  hydratePreferenceForm();
  preferencesMessage.value = "";
  preferencesError.value = "";
}

function scrollToSettingsSection(id: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const target = document.getElementById(id);
  if (!target) {
    return;
  }
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}

async function saveManagedPreferences(): Promise<void> {
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
    composeIgnorePathsValue.value !== (composeIgnorePathsEntry.value?.value ?? "")
  ) {
    values.compose_ignore_paths = composeIgnorePathsValue.value;
  }
  if (
    digestPinUpdatesEditable.value &&
    digestPinUpdatesValue.value !== (digestPinUpdatesEntry.value?.value ?? "false")
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
  } catch (exc) {
    preferencesError.value =
      exc instanceof Error ? exc.message : "Preferences could not be saved";
  }
}

async function relaunchOnboardingChecklist(): Promise<void> {
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
  } catch (exc) {
    preferencesError.value =
      exc instanceof Error ? exc.message : "Onboarding checklist could not be relaunched";
  }
}

async function replayCoreUpdateTour(): Promise<void> {
  preferencesMessage.value = "";
  preferencesError.value = "";
  try {
    await settings.updateCoreUpdateTour("in_progress", "dashboard");
    await router?.push({ name: "dashboard" });
  } catch (exc) {
    preferencesError.value =
      exc instanceof Error ? exc.message : "Core update tour could not be started";
  }
}

async function dismissCoreUpdateTour(): Promise<void> {
  preferencesMessage.value = "";
  preferencesError.value = "";
  try {
    await settings.updateCoreUpdateTour(
      "dismissed",
      settings.coreUpdateTour?.step ?? "dashboard",
    );
    preferencesMessage.value = "Core update tour dismissed.";
  } catch (exc) {
    preferencesError.value =
      exc instanceof Error ? exc.message : "Core update tour could not be dismissed";
  }
}

async function focusOnboardingChecklist(): Promise<void> {
  if (typeof document === "undefined") {
    return;
  }
  await nextTick();
  const target = document.getElementById("onboarding-checklist");
  if (!target) {
    return;
  }
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  target.focus({ preventScroll: true });
}

const { copy, isSupported: isClipboardSupported } = useClipboard();
const diagnosticsDownloading = ref(false);
const diagnosticsMessage = ref("");
const diagnosticsError = ref("");

async function loadSupportBundleText(): Promise<string | null> {
  diagnosticsMessage.value = "";
  diagnosticsError.value = "";
  diagnosticsDownloading.value = true;
  try {
    const bundle = await connection.diagnosticsSupportBundle();
    return JSON.stringify(bundle, null, 2);
  } catch (exc) {
    diagnosticsError.value = exc instanceof Error ? exc.message : "Failed to load support bundle";
    return null;
  } finally {
    diagnosticsDownloading.value = false;
  }
}

async function copySupportBundle(): Promise<void> {
  const text = await loadSupportBundleText();
  if (text !== null) {
    await copy(text);
    // Since copied is a ref updated by useClipboard asynchronously,
    // we just assume success if it didn't throw and set a generic message.
    diagnosticsMessage.value = "Diagnostics copied to clipboard.";
  }
}

async function downloadSupportBundle(): Promise<void> {
  const text = await loadSupportBundleText();
  if (text !== null) {
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "wud-updater-diagnostics.json";
    a.click();
    URL.revokeObjectURL(url);
    diagnosticsMessage.value = "Diagnostics downloaded successfully.";
  }
}

watch(managedEntries, hydratePreferenceForm, { immediate: true });
watch(
  shouldFocusOnboardingChecklist,
  (shouldFocus) => {
    if (shouldFocus) {
      void focusOnboardingChecklist();
    }
  },
  { immediate: true, flush: "post" },
);

onMounted(() => {
  void (async () => {
    await settings.loadSettings();
    if (settings.coreUpdateTour === null) {
      await settings.loadCoreUpdateTour();
    }
  })().catch(() => undefined);
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="settings.error" type="error" :show-icon="false">
      {{ settings.error }}
    </n-alert>

    <div
      v-if="settingsData"
      class="settings-safety-strip"
      :class="{ 'is-mutable': mutationsEnabled, 'is-read-only': !mutationsEnabled }"
      role="status"
    >
      <div class="settings-safety-main">
        <component :is="mutationStatusIcon" :size="18" aria-hidden="true" />
        <div>
          <strong>{{ mutationStatusLabel }}</strong>
          <span>{{ mutationStatusDetail }}</span>
        </div>
      </div>
      <div class="settings-safety-meta">
        <n-tag size="small" :type="mutationStatusTagType">
          {{ mutationStatusLabel }}
        </n-tag>
        <n-tag size="small">
          {{ restartTargetLabel }}
        </n-tag>
      </div>
    </div>

    <nav v-if="settingsData" class="settings-jump-nav" aria-label="Settings sections">
      <button
        v-for="link in SETTINGS_SECTION_LINKS"
        :key="link.id"
        type="button"
        class="settings-jump-button"
        @click="scrollToSettingsSection(link.id)"
      >
        {{ link.label }}
      </button>
    </nav>

    <div v-if="settingsData" id="settings-actions" class="settings-zone">
      <div class="settings-zone-heading">
        <div>
          <h2>Actions</h2>
        </div>
      </div>

      <n-grid
        class="settings-zone-grid settings-actions-grid"
        item-responsive
        responsive="self"
        cols="1 760:12"
        :x-gap="16"
        :y-gap="16"
      >
        <n-gi span="1 760:5">
          <section class="section-panel">
            <div class="section-heading">
              <div class="section-heading-main">
                <p class="eyebrow">Maintenance</p>
                <h2>Container</h2>
                <p class="section-copy">
                  Restart the running WebUI container after a helper image update or
                  runtime configuration change.
                </p>
              </div>
              <RefreshCw :size="20" class="section-heading-icon" />
            </div>
            <n-alert
              v-if="restartMessage"
              type="success"
              :show-icon="false"
              class="settings-action-alert"
            >
              {{ restartMessage }}
            </n-alert>
            <n-alert
              v-if="restartError"
              type="error"
              :show-icon="false"
              class="settings-action-alert"
            >
              {{ restartError }}
            </n-alert>
            <n-grid
              class="settings-risk-facts"
              aria-label="Container restart facts"
              responsive="self"
              :cols="compactSettingsLayout ? 1 : '1 220:2 340:3'"
              :x-gap="8"
              :y-gap="8"
            >
              <n-gi>
                <div class="settings-risk-fact">
                  <span>Target</span>
                  <strong>{{ restartContainerTarget || "Unavailable" }}</strong>
                </div>
              </n-gi>
              <n-gi>
                <div class="settings-risk-fact">
                  <span>Permission</span>
                  <strong>{{ mutationsEnabled ? "Allowed" : "Read-only" }}</strong>
                </div>
              </n-gi>
              <n-gi>
                <div class="settings-risk-fact">
                  <span>Impact</span>
                  <strong>Temporary disconnect</strong>
                </div>
              </n-gi>
            </n-grid>
            <div class="settings-action-row">
              <div>
                <strong>Restart WebUI container</strong>
                <span>The current browser session will temporarily lose connection.</span>
                <code v-if="restartContainerTarget">{{ restartContainerTarget }}</code>
              </div>
              <n-button
                type="warning"
                :disabled="restartButtonDisabled"
                :loading="connection.loading"
                @click="openRestartDialog"
              >
                <template #icon>
                  <RefreshCw :size="16" />
                </template>
                Restart container
              </n-button>
            </div>
            <n-alert
              v-if="restartDisabledReason"
              type="info"
              :show-icon="false"
              class="settings-action-alert"
            >
              {{ restartDisabledReason }}
            </n-alert>
          </section>
        </n-gi>

        <n-gi span="1 760:7">
          <OnboardingChecklist />
        </n-gi>
      </n-grid>
    </div>

    <div v-if="settingsData" id="settings-preferences" class="settings-zone">
      <div class="settings-zone-heading">
        <div>
          <h2>Preferences</h2>
        </div>
      </div>

      <section class="section-panel">
        <div class="section-heading">
          <div class="section-heading-main">
            <p class="eyebrow">Managed preferences</p>
            <h2>WebUI preferences</h2>
            <p class="section-copy">
              Browser-facing preferences persisted in SQLite. Runtime configuration,
              paths, and secrets stay controlled by server config.
            </p>
          </div>
          <Save :size="20" class="section-heading-icon" />
        </div>
        <n-alert
          v-if="preferencesMessage"
          type="success"
          :show-icon="false"
          class="settings-action-alert"
        >
          {{ preferencesMessage }}
        </n-alert>
        <n-alert
          v-if="preferencesError"
          type="error"
          :show-icon="false"
          class="settings-action-alert"
        >
          {{ preferencesError }}
        </n-alert>
        <div class="settings-preference-list">
          <div class="settings-preference-row">
            <div>
              <strong>Theme preference</strong>
              <span>
                Source:
                {{ themePreferenceEntry?.source === "configured" ? "Configured" : "Default" }}
              </span>
            </div>
            <n-select
              v-model:value="themePreferenceValue"
              :options="themePreferenceOptions"
              :disabled="preferenceControlsDisabled"
              aria-label="Theme preference"
            />
          </div>
          <div class="settings-preference-row">
            <div>
              <strong>Onboarding checklist</strong>
              <span>
                Source:
                {{
                  onboardingChecklistEntry?.source === "configured"
                    ? "Configured"
                    : "Default"
                }}
              </span>
            </div>
            <div class="settings-preference-controls">
              <n-select
                v-model:value="onboardingChecklistValue"
                :options="onboardingChecklistOptions"
                :disabled="preferenceControlsDisabled"
                aria-label="Onboarding checklist"
              />
              <n-button
                size="small"
                :disabled="preferenceControlsDisabled"
                :loading="settings.loading"
                @click="relaunchOnboardingChecklist"
              >
                <template #icon>
                  <RotateCcw :size="16" />
                </template>
                Relaunch onboarding
              </n-button>
            </div>
          </div>
          <div class="settings-preference-row">
            <div>
              <strong>Compose ignore paths</strong>
              <span>
                Source:
                {{
                  composeIgnorePathsEntry?.source === "configured"
                    ? "Configured"
                    : "Default"
                }}
              </span>
            </div>
            <div class="settings-preference-controls settings-textarea-controls">
              <n-input
                v-model:value="composeIgnorePathsValue"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 4 }"
                :disabled="preferenceControlsDisabled || !composeIgnorePathsEditable"
                placeholder="old, archive/disabled"
                aria-label="Compose ignore paths"
              />
              <n-alert
                v-if="composeIgnorePathsEntry?.disabled_reason"
                type="info"
                :show-icon="false"
                class="settings-action-alert"
              >
                {{ composeIgnorePathsEntry.disabled_reason }}
              </n-alert>
            </div>
          </div>
          <div class="settings-preference-row">
            <div>
              <strong>Digest-pin updates</strong>
              <span>
                Source:
                {{
                  digestPinUpdatesEntry?.source === "configured"
                    ? "Configured"
                    : "Default"
                }}
              </span>
            </div>
            <div class="settings-preference-controls">
              <n-select
                v-model:value="digestPinUpdatesValue"
                :options="digestPinUpdatesOptions"
                :disabled="preferenceControlsDisabled || !digestPinUpdatesEditable"
                aria-label="Digest-pin updates"
              />
              <n-alert
                v-if="digestPinUpdatesEntry?.disabled_reason"
                type="info"
                :show-icon="false"
                class="settings-action-alert"
              >
                {{ digestPinUpdatesEntry.disabled_reason }}
              </n-alert>
            </div>
          </div>
          <div class="settings-preference-row">
            <div>
              <strong>Core update tour</strong>
              <span>
                State: {{ coreUpdateTourStatusLabel }}. Step:
                {{ coreUpdateTourStepLabel }}.
              </span>
            </div>
            <n-flex
              class="settings-button-group"
              :justify="compactSettingsLayout ? 'flex-start' : 'flex-end'"
              :size="8"
            >
              <n-button
                size="small"
                :loading="settings.loading"
                @click="dismissCoreUpdateTour"
              >
                Dismiss tour
              </n-button>
              <n-button
                size="small"
                type="primary"
                :loading="settings.loading"
                @click="replayCoreUpdateTour"
              >
                <template #icon>
                  <RotateCcw :size="16" />
                </template>
                Replay tour
              </n-button>
            </n-flex>
          </div>
        </div>
        <div class="settings-action-row settings-preference-actions">
          <div>
            <strong>No restart required</strong>
            <span>Managed values apply to new WebUI requests immediately.</span>
          </div>
          <n-flex
            class="settings-button-group"
            :justify="compactSettingsLayout ? 'flex-start' : 'flex-end'"
            :size="8"
          >
            <n-button :disabled="settings.loading || !preferencesDirty" @click="resetPreferenceForm">
              <template #icon>
                <RotateCcw :size="16" />
              </template>
              Reset
            </n-button>
            <n-button
              type="primary"
              :disabled="preferenceSaveDisabled"
              :loading="settings.loading"
              @click="saveManagedPreferences"
            >
              <template #icon>
                <Save :size="16" />
              </template>
              Save preferences
            </n-button>
          </n-flex>
        </div>
        <n-alert
          v-if="preferencesDisabledReason"
          type="info"
          :show-icon="false"
          class="settings-action-alert"
        >
          {{ preferencesDisabledReason }}
        </n-alert>
      </section>
    </div>

    <div id="settings-runtime" class="settings-zone">
      <div class="settings-zone-heading">
        <div>
          <h2>Effective configuration</h2>
        </div>
        <div v-if="settingsData" class="settings-source-legend" aria-label="Source label legend">
          <span><strong>Default</strong> fallback</span>
          <span><strong>Configured</strong> explicit</span>
          <span><strong>Runtime derived</strong> computed</span>
          <span><strong>Request scoped</strong> current request</span>
        </div>
      </div>

      <section class="section-panel">
        <div class="section-heading">
          <div class="section-heading-main">
            <p class="eyebrow">Overview</p>
            <h2>Runtime settings</h2>
            <p class="section-copy">
              Secret names are shown, raw values stay hidden.
            </p>
          </div>
          <SlidersHorizontal :size="20" class="section-heading-icon settings-overview-icon" />
        </div>
        <n-empty
          v-if="!settingsData && !settings.loading"
          class="empty-state"
          description="Settings are unavailable."
          :show-icon="false"
        />
        <n-flex
          v-else-if="!settingsData"
          vertical
          :size="8"
          style="margin-top: 14px"
          aria-busy="true"
        >
          <span class="sr-only">Loading settings.</span>
          <n-skeleton aria-hidden="true" height="42px" />
          <n-skeleton aria-hidden="true" height="42px" />
          <n-skeleton aria-hidden="true" height="42px" />
        </n-flex>
        <n-grid
          v-else
          class="summary-grid"
          aria-label="Settings summary"
          responsive="self"
          cols="1 560:2 920:4"
          :x-gap="12"
          :y-gap="12"
        >
          <n-gi>
            <div class="summary-item">
              <span>Configured values</span>
              <strong>{{ configuredEntryCount }}</strong>
            </div>
          </n-gi>
          <n-gi>
            <div class="summary-item">
              <span>Not explicitly set</span>
              <strong>{{ inheritedEntryCount }}</strong>
            </div>
          </n-gi>
          <n-gi>
            <div class="summary-item">
              <span>Runtime scoped</span>
              <strong>{{ runtimeScopedEntryCount }}</strong>
            </div>
          </n-gi>
          <n-gi>
            <div class="summary-item">
              <span>Secrets configured</span>
              <strong>{{ configuredSecretCount }} / {{ secrets.length }}</strong>
            </div>
          </n-gi>
        </n-grid>
      </section>
    </div>

    <SettingsDisclosureSection
      v-if="settingsData"
      id="settings-paths"
      eyebrow="Updater"
      title="Paths"
      :open="!compactSettingsLayout"
      :compact="compactSettingsLayout"
      ariaLabel="Updater path settings"
      :header-tags="[{ label: entryCountLabel(pathEntries) }]"
      :table-headers="['Setting', 'Effective value', 'Source']"
      :entries="pathRows"
      empty-description="Path settings are unavailable."
    />

    <SettingsDisclosureSection
      v-if="settingsData"
      id="settings-behavior"
      eyebrow="Updater"
      title="Behavior"
      :open="!compactSettingsLayout"
      :compact="compactSettingsLayout"
      ariaLabel="Updater behavior settings"
      :header-tags="[{ label: entryCountLabel(behaviorEntries) }]"
      :table-headers="['Setting', 'Effective value', 'Source']"
      :entries="behaviorRows"
      empty-description="Behavior settings are unavailable."
    />

    <SettingsDisclosureSection
      v-if="settingsData"
      id="settings-webui"
      eyebrow="WebUI"
      title="Safety status"
      :open="!compactSettingsLayout"
      :compact="compactSettingsLayout"
      ariaLabel="WebUI safety settings"
      :header-tags="[{ label: entryCountLabel(webuiEntries) }]"
      :table-headers="['Setting', 'Effective value', 'Source']"
      :entries="webuiRows"
      empty-description="WebUI safety settings are unavailable."
      :icon="ShieldCheck"
    />

    <SettingsDisclosureSection
      v-if="settingsData"
      id="settings-secrets"
      eyebrow="Secrets"
      title="Configured values"
      :open="!compactSettingsLayout"
      :compact="compactSettingsLayout"
      ariaLabel="Secret settings"
      :header-tags="[
        { label: `${configuredSecretCount} configured` },
        ...(missingSecretCount ? [{ label: `${missingSecretCount} missing` }] : []),
      ]"
      :table-headers="['Secret', 'Value', 'Status']"
      :entries="secretRows"
      empty-description="No secret settings reported."
      :icon="KeyRound"
    />

    <section id="settings-diagnostics" class="section-panel">
      <div class="section-heading">
        <div class="section-heading-main">
          <p class="eyebrow">Diagnostics</p>
          <h2>Support Bundle</h2>
          <p class="section-copy">
            Generate a redacted support bundle containing application settings, update state, and recent logs for troubleshooting. Raw environment variables, private paths, and secrets are automatically scrubbed.
          </p>
        </div>
        <FileJson :size="20" class="section-heading-icon" />
      </div>
      <n-alert
        v-if="diagnosticsMessage"
        type="success"
        :show-icon="false"
        class="settings-action-alert"
      >
        {{ diagnosticsMessage }}
      </n-alert>
      <n-alert
        v-if="diagnosticsError"
        type="error"
        :show-icon="false"
        class="settings-action-alert"
      >
        {{ diagnosticsError }}
      </n-alert>
      <div class="settings-action-row">
        <n-button-group>
          <n-button
            secondary
            type="primary"
            :loading="diagnosticsDownloading"
            @click="downloadSupportBundle"
          >
            <template #icon>
              <Download :size="16" />
            </template>
            Download support bundle
          </n-button>
          <n-button
            secondary
            v-if="isClipboardSupported"
            :loading="diagnosticsDownloading"
            @click="copySupportBundle"
          >
            <template #icon>
              <Copy :size="16" />
            </template>
            Copy
          </n-button>
        </n-button-group>
      </div>
    </section>

    <section id="settings-docs" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Docs</p>
          <h2>Reference</h2>
        </div>
      </div>
      <div class="settings-doc-links">
        <a
          href="https://github.com/magrhino/WUD-Updater/blob/main/docs/DEPLOYMENT.md#environment-variables"
          target="_blank"
          rel="noopener noreferrer"
          class="text-link"
        >
          Deployment environment variables
          <ExternalLink :size="15" />
        </a>
        <a
          href="https://github.com/magrhino/WUD-Updater/blob/main/docs/examples/settings.env.example"
          target="_blank"
          rel="noopener noreferrer"
          class="text-link"
        >
          WebUI env example
          <ExternalLink :size="15" />
        </a>
      </div>
    </section>

    <n-modal
      v-model:show="restartDialogVisible"
      preset="dialog"
      title="Restart WebUI container"
      positive-text="Restart container"
      negative-text="Cancel"
      :positive-button-props="{
        type: 'warning',
        loading: connection.loading,
        disabled: restartButtonDisabled,
      }"
      @positive-click="confirmRestartContainer"
    >
      <n-alert type="warning" :show-icon="false" class="block-alert">
        This restarts the container serving the WebUI. The page may disconnect until
        Docker brings it back.
      </n-alert>
      <p class="settings-dialog-copy">
        Target container:
        <code>{{ restartContainerTarget || "unavailable" }}</code>
      </p>
    </n-modal>
  </section>
</template>

<style scoped>
.settings-safety-strip {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.settings-safety-strip.is-read-only {
  border-color: color-mix(in srgb, var(--color-border) 72%, var(--color-operational-teal) 28%);
  background: color-mix(in srgb, var(--color-surface) 90%, var(--color-operational-teal) 10%);
}

.settings-safety-strip.is-mutable {
  border-color: color-mix(in srgb, var(--color-border) 68%, var(--color-warning) 32%);
  background: color-mix(in srgb, var(--color-surface) 86%, var(--color-warning-bg) 14%);
}

.settings-safety-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.settings-safety-main>svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--color-operational-teal);
}

.settings-safety-strip.is-mutable .settings-safety-main>svg {
  color: var(--color-warning);
}

.settings-safety-main>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-safety-main strong,
.settings-safety-main span,
.settings-safety-meta {
  min-width: 0;
}

.settings-safety-main span {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.settings-safety-meta {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.settings-jump-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.settings-jump-button {
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 0.86rem;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color 180ms ease-out,
    color 180ms ease-out,
    background-color 180ms ease-out;
}

.settings-jump-button:hover,
.settings-jump-button:focus-visible {
  border-color: var(--color-border-hover);
  background: var(--color-panel-tint);
  color: var(--color-ink);
}

.settings-jump-button:focus-visible {
  outline: 2px solid var(--color-border-hover);
  outline-offset: 2px;
}

.settings-zone,
#settings-diagnostics,
#settings-docs {
  scroll-margin-top: 18px;
}

.settings-zone {
  display: grid;
  gap: 12px;
}

.settings-zone-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
}

.settings-zone-heading>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-zone-heading h2,
.settings-zone-heading p {
  margin: 0;
}

.settings-zone-heading h2 {
  color: var(--color-ink);
  font-size: 1.08rem;
  line-height: 1.25;
}

.settings-zone-heading p {
  max-width: 72ch;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.settings-zone-grid {
  align-items: start;
}

.settings-risk-facts {
  margin-top: 14px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.settings-risk-fact {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-risk-fact span,
.settings-risk-fact strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-risk-fact span {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
}

.settings-risk-fact strong {
  color: var(--color-ink);
  font-size: 0.9rem;
}

.settings-source-legend {
  display: flex;
  flex: 0 1 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px 10px;
  min-width: min(100%, 320px);
  color: var(--color-muted-text);
  font-size: 0.78rem;
  line-height: 1.35;
}

.settings-source-legend span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-source-legend strong {
  color: var(--color-ink);
}

.settings-doc-links {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  margin-top: 14px;
}

.settings-doc-links .text-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.settings-preference-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.settings-preference-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  background: var(--color-panel-tint);
}

.settings-preference-row>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.settings-preference-row strong,
.settings-preference-row span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-preference-row span {
  color: var(--color-muted-text);
  font-size: 0.86rem;
}

.settings-preference-row>.settings-preference-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.settings-preference-controls :deep(.n-select) {
  flex: 1 1 180px;
  min-width: 180px;
}

.settings-preference-row>.settings-textarea-controls {
  align-items: stretch;
  flex-direction: column;
}

.settings-textarea-controls :deep(.n-input) {
  width: 100%;
}

.settings-action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-subtle);
}

.settings-action-row>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.settings-action-row strong,
.settings-action-row span,
.settings-action-row code,
.settings-dialog-copy code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-action-row span,
.settings-dialog-copy {
  color: var(--color-muted-text);
}

.settings-action-row code,
.settings-dialog-copy code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.84rem;
}

.settings-action-alert {
  margin-top: 12px;
}

.settings-actions-grid .settings-action-row {
  flex-wrap: wrap;
  align-items: flex-start;
}

.settings-actions-grid .settings-action-row>div {
  flex: 1 1 180px;
}

.settings-preference-actions {
  align-items: end;
}

.settings-dialog-copy {
  margin: 0;
  line-height: 1.45;
}

@media (max-width: 760px) {
  .settings-actions-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .settings-preference-row {
    grid-template-columns: 1fr;
  }

  .settings-safety-strip,
  .settings-zone-heading {
    display: grid;
  }

  .settings-safety-meta,
  .settings-source-legend {
    justify-content: flex-start;
  }

  .settings-jump-nav {
    flex-wrap: nowrap;
    max-width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .settings-jump-button {
    flex: 0 0 auto;
    min-height: 44px;
  }

  .settings-action-row {
    display: grid;
    align-items: start;
  }

  .settings-action-row :deep(.n-button) {
    justify-self: start;
  }

  .settings-preference-row>.settings-preference-controls {
    justify-content: flex-start;
  }

  .settings-overview-icon {
    display: none;
  }
}
</style>
