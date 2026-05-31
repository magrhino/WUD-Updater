<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  ExternalLink,
  KeyRound,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
} from "@lucide/vue";
import { NAlert, NButton, NModal, NSelect, NTag } from "naive-ui";

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
const preferencesMessage = ref("");
const preferencesError = ref("");
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
const restartContainerTarget = computed(() => restartContainerEntry.value?.value ?? "");
const mutationsEnabled = computed(() => auth.session?.mutations_enabled === true);
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
const preferencesDirty = computed(
  () =>
    themePreferenceValue.value !== (themePreferenceEntry.value?.value ?? "system") ||
    onboardingChecklistValue.value !==
      (onboardingChecklistEntry.value?.value ?? "visible"),
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

function displayValue(value: string): string {
  return value || "unset";
}

function entryCountLabel(entries: SettingsEntry[]): string {
  return `${entries.length} value${entries.length === 1 ? "" : "s"}`;
}

function sourceLabel(entry: SettingsEntry): string {
  if (entry.source === "request") {
    return "Request";
  }
  if (entry.source === "derived") {
    return "Derived";
  }
  return entry.configured ? "Configured" : "Default";
}

function sourceTagType(entry: SettingsEntry): "default" | "info" | "success" | "warning" {
  if (entry.source === "request") {
    return "info";
  }
  if (entry.source === "derived") {
    return "warning";
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

watch(managedEntries, hydratePreferenceForm, { immediate: true });

onMounted(() => {
  void webui.loadSettings();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div class="settings-heading-main">
          <p class="eyebrow">Maintenance</p>
          <h2>Container</h2>
          <p class="settings-section-copy">
            Restart the running WebUI container after a helper image update or runtime
            configuration change.
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

    <section v-if="settings" class="section-panel">
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
          <n-select
            v-model:value="onboardingChecklistValue"
            :options="onboardingChecklistOptions"
            :disabled="preferenceControlsDisabled"
            aria-label="Onboarding checklist"
          />
        </div>
      </div>
      <div class="settings-action-row settings-preference-actions">
        <div>
          <strong>No restart required</strong>
          <span>Managed preferences do not alter updater runtime behavior.</span>
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

    <section class="section-panel">
      <div class="section-heading">
        <div class="settings-heading-main">
          <p class="eyebrow">Effective configuration</p>
          <h2>Runtime settings</h2>
          <p class="settings-section-copy">
            Effective values from environment, defaults, and request context. Secret
            names are shown, raw values stay hidden.
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
          <span>Derived or request</span>
          <strong>{{ runtimeScopedEntryCount }}</strong>
        </div>
        <div class="settings-summary-item">
          <span>Secrets configured</span>
          <strong>{{ configuredSecretCount }} / {{ secrets.length }}</strong>
        </div>
      </div>
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Paths</h2>
        </div>
        <n-tag size="small">{{ entryCountLabel(pathEntries) }}</n-tag>
      </div>
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
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Behavior</h2>
        </div>
        <n-tag size="small">{{ entryCountLabel(behaviorEntries) }}</n-tag>
      </div>
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
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">WebUI</p>
          <h2>Safety status</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ entryCountLabel(webuiEntries) }}</n-tag>
          <ShieldCheck :size="20" class="section-heading-icon" />
        </div>
      </div>
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
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Secrets</p>
          <h2>Configured values</h2>
        </div>
        <div class="settings-heading-meta">
          <n-tag size="small">{{ configuredSecretCount }} configured</n-tag>
          <n-tag v-if="missingSecretCount" size="small">{{ missingSecretCount }} missing</n-tag>
          <KeyRound :size="20" class="section-heading-icon" />
        </div>
      </div>
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
    </section>

    <section class="section-panel">
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
