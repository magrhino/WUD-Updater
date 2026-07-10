<script setup lang="ts">
import { computed } from "vue";
import { KeyRound, ShieldCheck, SlidersHorizontal } from "@lucide/vue";
import { NEmpty, NFlex, NGi, NGrid, NSkeleton } from "naive-ui";

import SettingsDisclosureSection from "../../components/SettingsDisclosureSection.vue";
import { useSettingsStore } from "../../stores/settings";
import {
  BEHAVIOR_ENTRY_NAMES,
  entryCountLabel,
  PATH_ENTRY_NAMES,
  secretRows,
  settingRows,
} from "./settingsDisplay";

defineProps<{
  compact: boolean;
}>();

const settings = useSettingsStore();
const settingsData = computed(() => settings.settings);
const updaterEntries = computed(() => settingsData.value?.updater ?? []);
const webuiEntries = computed(() => settingsData.value?.webui ?? []);
const secrets = computed(() => settingsData.value?.secrets ?? []);
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
const pathRows = computed(() => settingRows(pathEntries.value));
const behaviorRows = computed(() => settingRows(behaviorEntries.value));
const webuiRows = computed(() => settingRows(webuiEntries.value));
const redactedSecretRows = computed(() => secretRows(secrets.value));
</script>

<template>
  <div id="settings-runtime" class="settings-zone">
    <div class="settings-zone-heading">
      <div>
        <h2>Effective configuration</h2>
      </div>
      <div v-if="settingsData" class="settings-source-legend" aria-label="Source label legend">
        <span class="wrap-anywhere"><strong>Default</strong> fallback</span>
        <span class="wrap-anywhere"><strong>Configured</strong> explicit</span>
        <span class="wrap-anywhere"><strong>Runtime derived</strong> computed</span>
        <span class="wrap-anywhere"><strong>Request scoped</strong> current request</span>
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
    :open="!compact"
    :compact="compact"
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
    :open="!compact"
    :compact="compact"
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
    :open="!compact"
    :compact="compact"
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
    :open="!compact"
    :compact="compact"
    ariaLabel="Secret settings"
    :header-tags="[
      { label: `${configuredSecretCount} configured` },
      ...(missingSecretCount ? [{ label: `${missingSecretCount} missing` }] : []),
    ]"
    :table-headers="['Secret', 'Value', 'Status']"
    :entries="redactedSecretRows"
    empty-description="No secret settings reported."
    :icon="KeyRound"
  />
</template>

<style scoped>
.settings-zone {
  display: grid;
  gap: 12px;
  scroll-margin-top: 18px;
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

.settings-source-legend strong {
  color: var(--color-ink);
}

@media (--wud-compact) {
  .settings-zone-heading {
    display: grid;
  }

  .settings-source-legend {
    justify-content: flex-start;
  }

  .settings-overview-icon {
    display: none;
  }
}
</style>
