<script setup lang="ts">
import { computed, onMounted } from "vue";
import {
  ExternalLink,
  KeyRound,
  ShieldCheck,
  SlidersHorizontal,
} from "@lucide/vue";

import type { SecretSettingStatus, SettingsEntry } from "../api/client";
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
const pathEntries = computed(() =>
  updaterEntries.value.filter((entry) => PATH_ENTRY_NAMES.has(entry.name)),
);
const behaviorEntries = computed(() =>
  updaterEntries.value.filter((entry) => BEHAVIOR_ENTRY_NAMES.has(entry.name)),
);

function displayValue(value: string): string {
  return value || "unset";
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

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Effective configuration</p>
          <h2>Runtime settings</h2>
        </div>
        <SlidersHorizontal :size="20" class="section-heading-icon" />
      </div>
      <div v-if="!settings && !webui.loading" class="empty-state">
        Settings are unavailable.
      </div>
      <div v-else-if="!settings" class="empty-state">Loading settings.</div>
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Paths</h2>
        </div>
      </div>
      <div class="settings-list">
        <div v-for="entry in pathEntries" :key="entry.name" class="settings-row">
          <div>
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code>{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Updater</p>
          <h2>Behavior</h2>
        </div>
      </div>
      <div class="settings-list">
        <div v-for="entry in behaviorEntries" :key="entry.name" class="settings-row">
          <div>
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code>{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">WebUI</p>
          <h2>Safety status</h2>
        </div>
        <ShieldCheck :size="20" class="section-heading-icon" />
      </div>
      <div class="settings-list">
        <div v-for="entry in webuiEntries" :key="entry.name" class="settings-row">
          <div>
            <strong>{{ entry.name }}</strong>
            <span>Default: {{ displayValue(entry.default_value) }}</span>
          </div>
          <code>{{ displayValue(entry.value) }}</code>
          <n-tag size="small" :type="sourceTagType(entry)">
            {{ sourceLabel(entry) }}
          </n-tag>
        </div>
      </div>
    </section>

    <section v-if="settings" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Secrets</p>
          <h2>Configured values</h2>
        </div>
        <KeyRound :size="20" class="section-heading-icon" />
      </div>
      <div class="settings-list">
        <div v-for="secret in secrets" :key="secret.name" class="settings-row">
          <div>
            <strong>{{ secret.name }}</strong>
            <span>Raw value hidden</span>
          </div>
          <code>{{ secretLabel(secret) }}</code>
          <n-tag size="small" :type="secret.configured ? 'success' : 'default'">
            {{ secretLabel(secret) }}
          </n-tag>
        </div>
      </div>
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
