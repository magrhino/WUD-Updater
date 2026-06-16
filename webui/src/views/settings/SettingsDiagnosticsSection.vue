<script setup lang="ts">
import { Copy, Download, FileJson } from "@lucide/vue";
import { NAlert, NButton, NButtonGroup } from "naive-ui";

import { useSettingsDiagnostics } from "./useSettingsDiagnostics";

const {
  diagnosticsDownloading,
  diagnosticsMessage,
  diagnosticsError,
  isClipboardSupported,
  copySupportBundle,
  downloadSupportBundle,
} = useSettingsDiagnostics();
</script>

<template>
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
          v-if="isClipboardSupported"
          secondary
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
</template>

<style scoped>
#settings-diagnostics {
  scroll-margin-top: 18px;
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

.settings-action-alert {
  margin-top: 12px;
}

@media (max-width: 560px) {
  .settings-action-row {
    display: grid;
    align-items: start;
  }

  .settings-action-row :deep(.n-button) {
    justify-self: start;
  }
}
</style>
