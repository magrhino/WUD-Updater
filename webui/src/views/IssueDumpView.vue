<script setup lang="ts">
import { onMounted } from "vue";
import { Copy, Download, RefreshCw } from "@lucide/vue";
import { NAlert, NButton, NEmpty, NFlex } from "naive-ui";

import { useRouteRefresh } from "../components/app/routeRefresh";
import type { DiagnosticsSupportBundleResponse } from "../api/client";
import { runInBackground } from "../utils/promises";
import { useSettingsDiagnostics } from "./settings/useSettingsDiagnostics";

function affectedContainerDetails(bundle: DiagnosticsSupportBundleResponse) {
  const observations = bundle.wud_api_observations;
  return {
    summary: {
      containers_affected: observations.counts.degraded,
      using_previous_results: observations.counts.retained,
      recovered_from_pending_file: observations.counts.recovered,
      update_status_unknown: observations.counts.unresolved,
    },
    containers: observations.items.filter(
      (item) => item.outcome !== "unsupported_ignored",
    ),
  };
}

const {
  diagnosticsDownloading,
  diagnosticsText,
  diagnosticsMessage,
  diagnosticsError,
  isClipboardSupported,
  refreshSupportBundle,
  copySupportBundle,
  downloadSupportBundle,
} = useSettingsDiagnostics({
  reuseLoadedText: true,
  artifactLabel: "Affected container details",
  downloadFilename: "wudup-affected-containers.json",
  selectBundle: affectedContainerDetails,
});

useRouteRefresh(refreshSupportBundle);

onMounted(() => {
  runInBackground(refreshSupportBundle());
});
</script>

<template>
  <section class="content-stack">
    <div class="section-heading">
      <div>
        <h2>Affected WUD containers</h2>
        <p class="section-copy">
          WUD could not refresh these containers during its latest check. This
          view shows the reported problem for each affected container and omits
          unrelated diagnostics.
        </p>
      </div>
      <n-flex class="inline-actions" align="center" :size="8">
        <n-button
          quaternary
          circle
          title="Refresh affected containers"
          aria-label="Refresh affected containers"
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
          Copy container details
        </n-button>
        <n-button
          secondary
          :loading="diagnosticsDownloading"
          @click="downloadSupportBundle"
        >
          <template #icon>
            <Download :size="17" aria-hidden="true" />
          </template>
          Download container details
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
      description="Affected container details are unavailable. Refresh to try again."
      :show-icon="false"
    />
    <pre v-else class="log-viewer issue-dump-viewer">{{ diagnosticsText || "Loading affected containers…" }}</pre>
  </section>
</template>
