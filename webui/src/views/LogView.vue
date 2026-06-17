<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useClipboard } from "@vueuse/core";
import { Copy, RefreshCw } from "@lucide/vue";
import { NAlert, NButton, NEmpty, NFlex } from "naive-ui";

import { useRunsStore } from "../stores/runs";
import { runInBackground } from "../utils/promises";

const route = useRoute();
const runs = useRunsStore();
const runId = computed(() => Number(route.params.id));
const log = computed(() => runs.runLogs[runId.value] ?? null);
const logText = computed(() => log.value?.content ?? "");
const { copy, copied, isSupported } = useClipboard({ source: logText });

async function load(): Promise<void> {
  await runs.loadRunLog(runId.value);
}

onMounted(() => {
  runInBackground(load());
});

watch(runId, () => {
  runInBackground(load());
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="runs.error" type="error" :show-icon="false">
      {{ runs.error }}
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow value-eyebrow">{{ log?.log_file ?? "Run log" }}</p>
        <h2>#{{ runId }} log</h2>
      </div>
      <n-flex class="inline-actions" align="center" :size="8">
        <n-button
          quaternary
          circle
          title="Refresh"
          aria-label="Refresh log"
          @click="load"
        >
          <template #icon>
            <RefreshCw :size="17" />
          </template>
        </n-button>
        <n-button quaternary :disabled="!isSupported || !logText" @click="copy(logText)">
          <template #icon>
            <Copy :size="17" />
          </template>
          {{ copied ? "Copied" : "Copy log" }}
        </n-button>
      </n-flex>
    </div>

    <n-alert v-if="log?.truncated" type="warning" :show-icon="false">
      Showing the last {{ log.max_bytes }} bytes.
    </n-alert>
    <n-empty
      v-if="log && !log.exists"
      class="empty-state"
      description="Log file not found."
      :show-icon="false"
    />
    <pre v-else class="log-viewer">{{ logText }}</pre>
  </section>
</template>
