<script setup lang="ts">
import { onMounted } from "vue";
import { Copy, Download, RefreshCw } from "@lucide/vue";
import { NAlert, NButton, NEmpty, NFlex } from "naive-ui";

import { useRouteRefresh } from "../components/app/routeRefresh";
import { runInBackground } from "../utils/promises";
import { useSettingsDiagnostics } from "./settings/useSettingsDiagnostics";

const {
  diagnosticsDownloading,
  diagnosticsText,
  diagnosticsMessage,
  diagnosticsError,
  isClipboardSupported,
  refreshSupportBundle,
  copySupportBundle,
  downloadSupportBundle,
} = useSettingsDiagnostics({ reuseLoadedText: true });

useRouteRefresh(refreshSupportBundle);

onMounted(() => {
  runInBackground(refreshSupportBundle());
});
</script>

<template>
  <section class="content-stack">
    <div class="section-heading">
      <div>
        <p class="eyebrow value-eyebrow">Read-only diagnostics</p>
        <h2>WUD issue dump</h2>
        <p class="section-copy">
          This formatted support bundle is redacted for troubleshooting. Review
          it before sharing it with an issue.
        </p>
      </div>
      <n-flex class="inline-actions" align="center" :size="8">
        <n-button
          quaternary
          circle
          title="Refresh issue dump"
          aria-label="Refresh issue dump"
          :loading="diagnosticsDownloading"
          @click="refreshSupportBundle"
        >
          <template #icon>
            <RefreshCw :size="17" aria-hidden="true" />
          </template>
        </n-button>
        <n-button
          v-if="isClipboardSupported"
          secondary
          :loading="diagnosticsDownloading"
          @click="copySupportBundle"
        >
          <template #icon>
            <Copy :size="17" aria-hidden="true" />
          </template>
          Copy issue dump
        </n-button>
        <n-button
          secondary
          :loading="diagnosticsDownloading"
          @click="downloadSupportBundle"
        >
          <template #icon>
            <Download :size="17" aria-hidden="true" />
          </template>
          Download issue dump
        </n-button>
      </n-flex>
    </div>

    <n-alert
      v-if="diagnosticsMessage"
      type="success"
      :show-icon="false"
      role="status"
    >
      {{ diagnosticsMessage }}
    </n-alert>
    <n-alert
      v-if="diagnosticsError"
      type="error"
      :show-icon="false"
      role="alert"
    >
      {{ diagnosticsError }}
    </n-alert>

    <n-empty
      v-if="!diagnosticsText && !diagnosticsDownloading"
      class="empty-state"
      description="Issue dump is unavailable. Refresh to try again."
      :show-icon="false"
    />
    <pre v-else class="log-viewer issue-dump-viewer">{{ diagnosticsText || "Loading issue dump…" }}</pre>
  </section>
</template>
