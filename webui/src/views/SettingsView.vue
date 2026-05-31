<script setup lang="ts">
import { computed, onMounted } from "vue";
import {
  ExternalLink,
  KeyRound,
  ShieldCheck,
  SlidersHorizontal,
} from "@lucide/vue";

import type { SecretSettingStatus, SettingsEntry } from "../api/client";
import OnboardingChecklist from "../components/OnboardingChecklist.vue";
import { useWebuiStore } from "../stores/webui";

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

const settings = computed(() => webui.settings);
const updaterEntries = computed(() => settings.value?.updater ?? []);
const webuiEntries = computed(() => settings.value?.webui ?? []);
const secrets = computed(() => settings.value?.secrets ?? []);
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

onMounted(() => {
  void webui.loadSettings();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <OnboardingChecklist />

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
  </section>
</template>
