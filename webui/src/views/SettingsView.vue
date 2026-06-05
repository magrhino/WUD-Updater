<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useClipboard, useMediaQuery } from "@vueuse/core";
import { useRoute, useRouter } from "vue-router";
import {
  AlertTriangle,
  ChevronDown,
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
import { NAlert, NButton, NButtonGroup, NInput, NModal, NSelect, NTag } from "naive-ui";

import type {
  ManagedSettingEntry,
  SecretSettingStatus,
  SettingsEntry,
} from "../api/client";
import OnboardingChecklist from "../components/OnboardingChecklist.vue";
import { useAuthStore } from "../stores/auth";
import { useWebuiStore } from "../stores/webui";

const auth = useAuthStore();
const webui = useWebuiStore();
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

const settings = computed(() => webui.settings);
const updaterEntries = computed(() => settings.value?.updater ?? []);
const webuiEntries = computed(() => settings.value?.webui ?? []);
const secrets = computed(() => settings.value?.secrets ?? []);
const managedEntries = computed(() => settings.value?.managed ?? []);
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
  () => webui.loading || restartDisabledReason.value !== "",
);
const preferencesDisabledReason = computed(() => {
  if (!mutationsEnabled.value) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to save managed WebUI preferences.";
  }
  return "";
});
const preferenceControlsDisabled = computed(
  () => webui.loading || preferencesDisabledReason.value !== "",
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
  const status = webui.coreUpdateTour?.status ?? "not_started";
  return CORE_UPDATE_TOUR_STATUS_LABELS[status] ?? status;
});
const coreUpdateTourStepLabel = computed(() => {
  const step = webui.coreUpdateTour?.step ?? "dashboard";
  return CORE_UPDATE_TOUR_STEP_LABELS[step] ?? step;
});
const shouldFocusOnboardingChecklist = computed(
  () =>
    route?.query.onboarding === "1" &&
    settings.value !== null &&
    webui.onboarding?.visible === true,
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
  restartMessage.value = "";
  restartError.value = "";
  restartDialogVisible.value = true;
}

async function confirmRestartContainer(): Promise<void> {
  restartMessage.value = "";
  restartError.value = "";
  try {
    const response = await webui.restartContainer();
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
    const response = await webui.updateManagedSettings(values);
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
    const response = await webui.updateManagedSettings({
      onboarding_checklist: "visible",
    });
    hydratePreferenceForm();
    if (webui.onboarding?.visible === true) {
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
    await webui.updateCoreUpdateTour("in_progress", "dashboard");
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
    await webui.updateCoreUpdateTour(
      "dismissed",
      webui.coreUpdateTour?.step ?? "dashboard",
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
    const bundle = await webui.diagnosticsSupportBundle();
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
  const loads = [webui.loadSettings()];
  if (webui.coreUpdateTour === null) {
    loads.push(webui.loadCoreUpdateTour());
  }
  void Promise.all(loads);
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <div
      v-if="settings"
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

    <nav v-if="settings" class="settings-jump-nav" aria-label="Settings sections">
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

    <div v-if="settings" id="settings-actions" class="settings-zone">
      <div class="settings-zone-heading">
        <div>
          <h2>Actions</h2>
        </div>
      </div>

      <div class="settings-zone-grid settings-actions-grid">
        <section class="section-panel">
          <div class="section-heading">
            <div class="settings-heading-main">
              <p class="eyebrow">Maintenance</p>
              <h2>Container</h2>
              <p class="settings-section-copy">
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
          <div class="settings-risk-facts" aria-label="Container restart facts">
            <div>
              <span>Target</span>
              <strong>{{ restartContainerTarget || "Unavailable" }}</strong>
            </div>
            <div>
              <span>Permission</span>
              <strong>{{ mutationsEnabled ? "Allowed" : "Read-only" }}</strong>
            </div>
            <div>
              <span>Impact</span>
              <strong>Temporary disconnect</strong>
            </div>
          </div>
          <div class="settings-action-row">
            <div>
              <strong>Restart WebUI container</strong>
              <span>The current browser session will temporarily lose connection.</span>
              <code v-if="restartContainerTarget">{{ restartContainerTarget }}</code>
            </div>
            <n-button
              type="warning"
              :disabled="restartButtonDisabled"
              :loading="webui.loading"
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

        <OnboardingChecklist />
      </div>
    </div>

    <div v-if="settings" id="settings-preferences" class="settings-zone">
      <div class="settings-zone-heading">
        <div>
          <h2>Preferences</h2>
        </div>
      </div>

      <section class="section-panel">
        <div class="section-heading">
          <div class="settings-heading-main">
            <p class="eyebrow">Managed preferences</p>
            <h2>WebUI preferences</h2>
            <p class="settings-section-copy">
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
                :loading="webui.loading"
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
            <div class="settings-button-group">
              <n-button
                size="small"
                :loading="webui.loading"
                @click="dismissCoreUpdateTour"
              >
                Dismiss tour
              </n-button>
              <n-button
                size="small"
                type="primary"
                :loading="webui.loading"
                @click="replayCoreUpdateTour"
              >
                <template #icon>
                  <RotateCcw :size="16" />
                </template>
                Replay tour
              </n-button>
            </div>
          </div>
        </div>
        <div class="settings-action-row settings-preference-actions">
          <div>
            <strong>No restart required</strong>
            <span>Managed values apply to new WebUI requests immediately.</span>
          </div>
          <div class="settings-button-group">
            <n-button :disabled="webui.loading || !preferencesDirty" @click="resetPreferenceForm">
              <template #icon>
                <RotateCcw :size="16" />
              </template>
              Reset
            </n-button>
            <n-button
              type="primary"
              :disabled="preferenceSaveDisabled"
              :loading="webui.loading"
              @click="saveManagedPreferences"
            >
              <template #icon>
                <Save :size="16" />
              </template>
              Save preferences
            </n-button>
          </div>
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
        <div v-if="settings" class="settings-source-legend" aria-label="Source label legend">
          <span><strong>Default</strong> fallback</span>
          <span><strong>Configured</strong> explicit</span>
          <span><strong>Runtime derived</strong> computed</span>
          <span><strong>Request scoped</strong> current request</span>
        </div>
      </div>

      <section class="section-panel">
        <div class="section-heading">
          <div class="settings-heading-main">
            <p class="eyebrow">Overview</p>
            <h2>Runtime settings</h2>
            <p class="settings-section-copy">
              Secret names are shown, raw values stay hidden.
            </p>
          </div>
          <SlidersHorizontal :size="20" class="section-heading-icon settings-overview-icon" />
        </div>
        <div v-if="!settings && !webui.loading" class="empty-state">
          Settings are unavailable.
        </div>
        <div v-else-if="!settings" class="settings-loading" aria-busy="true">
          <span class="sr-only">Loading settings.</span>
          <span aria-hidden="true" class="settings-skeleton-row"></span>
          <span aria-hidden="true" class="settings-skeleton-row"></span>
          <span aria-hidden="true" class="settings-skeleton-row"></span>
        </div>
        <div v-else class="settings-summary-grid" aria-label="Settings summary">
          <div class="settings-summary-item">
            <span>Configured values</span>
            <strong>{{ configuredEntryCount }}</strong>
          </div>
          <div class="settings-summary-item">
            <span>Not explicitly set</span>
            <strong>{{ inheritedEntryCount }}</strong>
          </div>
          <div class="settings-summary-item">
            <span>Runtime scoped</span>
            <strong>{{ runtimeScopedEntryCount }}</strong>
          </div>
          <div class="settings-summary-item">
            <span>Secrets configured</span>
            <strong>{{ configuredSecretCount }} / {{ secrets.length }}</strong>
          </div>
        </div>
      </section>
    </div>

    <details
      v-if="settings"
      id="settings-paths"
      class="section-panel settings-disclosure"
      :open="!compactSettingsLayout"
    >
      <summary class="section-heading settings-disclosure-summary">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Paths</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ entryCountLabel(pathEntries) }}</n-tag>
          <ChevronDown :size="18" class="settings-disclosure-chevron" />
        </div>
      </summary>
      <div
        v-if="pathEntries.length"
        class="settings-list"
        role="table"
        aria-label="Updater path settings"
      >
        <div class="settings-table-head" role="row">
          <span role="columnheader">Setting</span>
          <span role="columnheader">Effective value</span>
          <span role="columnheader">Source</span>
        </div>
        <div v-for="entry in pathEntries" :key="entry.name" class="settings-row" role="row">
          <div role="cell">
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code role="cell">{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)" role="cell">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
      <div v-else class="empty-state">Path settings are unavailable.</div>
    </details>

    <details
      v-if="settings"
      id="settings-behavior"
      class="section-panel settings-disclosure"
      :open="!compactSettingsLayout"
    >
      <summary class="section-heading settings-disclosure-summary">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Behavior</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ entryCountLabel(behaviorEntries) }}</n-tag>
          <ChevronDown :size="18" class="settings-disclosure-chevron" />
        </div>
      </summary>
      <div
        v-if="behaviorEntries.length"
        class="settings-list"
        role="table"
        aria-label="Updater behavior settings"
      >
        <div class="settings-table-head" role="row">
          <span role="columnheader">Setting</span>
          <span role="columnheader">Effective value</span>
          <span role="columnheader">Source</span>
        </div>
        <div v-for="entry in behaviorEntries" :key="entry.name" class="settings-row" role="row">
          <div role="cell">
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code role="cell">{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)" role="cell">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
      <div v-else class="empty-state">Behavior settings are unavailable.</div>
    </details>

    <details
      v-if="settings"
      id="settings-webui"
      class="section-panel settings-disclosure"
      :open="!compactSettingsLayout"
    >
      <summary class="section-heading settings-disclosure-summary">
        <div>
          <p class="eyebrow">WebUI</p>
          <h2>Safety status</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ entryCountLabel(webuiEntries) }}</n-tag>
          <ShieldCheck :size="20" class="section-heading-icon" />
          <ChevronDown :size="18" class="settings-disclosure-chevron" />
        </div>
      </summary>
      <div
        v-if="webuiEntries.length"
        class="settings-list"
        role="table"
        aria-label="WebUI safety settings"
      >
        <div class="settings-table-head" role="row">
          <span role="columnheader">Setting</span>
          <span role="columnheader">Effective value</span>
          <span role="columnheader">Source</span>
        </div>
        <div v-for="entry in webuiEntries" :key="entry.name" class="settings-row" role="row">
          <div role="cell">
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code role="cell">{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)" role="cell">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
      <div v-else class="empty-state">WebUI safety settings are unavailable.</div>
    </details>

    <details
      v-if="settings"
      id="settings-secrets"
      class="section-panel settings-disclosure"
      :open="!compactSettingsLayout"
    >
      <summary class="section-heading settings-disclosure-summary">
        <div>
          <p class="eyebrow">Secrets</p>
          <h2>Configured values</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ configuredSecretCount }} configured</n-tag>
          <n-tag v-if="missingSecretCount" size="small">{{ missingSecretCount }} missing</n-tag>
          <KeyRound :size="20" class="section-heading-icon" />
          <ChevronDown :size="18" class="settings-disclosure-chevron" />
        </div>
      </summary>
      <div
        v-if="secrets.length"
        class="settings-list"
        role="table"
        aria-label="Secret settings"
      >
        <div class="settings-table-head" role="row">
          <span role="columnheader">Secret</span>
          <span role="columnheader">Value</span>
          <span role="columnheader">Status</span>
        </div>
        <div v-for="secret in secrets" :key="secret.name" class="settings-row" role="row">
          <div role="cell">
            <strong>{{ secret.name }}</strong>
            <span>Value never rendered</span>
          </div>
          <span class="settings-redacted-value" role="cell">Raw value hidden</span>
          <n-tag size="small" :type="secret.configured ? 'success' : 'default'" role="cell">
            {{ secretLabel(secret) }}
          </n-tag>
        </div>
      </div>
      <div v-else class="empty-state">No secret settings reported.</div>
    </details>

    <section id="settings-diagnostics" class="section-panel">
      <div class="section-heading">
        <div class="settings-heading-main">
          <p class="eyebrow">Diagnostics</p>
          <h2>Support Bundle</h2>
          <p class="settings-section-copy">
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
          href="https://github.com/magrhino/WUD-Updater/blob/main/docs/examples/webui.env.example"
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
      :positive-button-props="{ type: 'warning', loading: webui.loading }"
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
