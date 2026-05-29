<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useClipboard } from "@vueuse/core";
import { Copy, RefreshCw } from "@lucide/vue";

import { useWebuiStore } from "../stores/webui";

const route = useRoute();
const webui = useWebuiStore();
const runId = computed(() => Number(route.params.id));
const log = computed(() => webui.runLogs[runId.value] ?? null);
const logText = computed(() => log.value?.content ?? "");
const { copy, copied, isSupported } = useClipboard({ source: logText });

async function load(): Promise<void> {
  await webui.loadRunLog(runId.value);
}

onMounted(() => {
  void load();
});

watch(runId, () => {
  void load();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow value-eyebrow">{{ log?.log_file ?? "Run log" }}</p>
        <h2>#{{ runId }} log</h2>
      </div>
      <div class="inline-actions">
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
      </div>
    </div>

    <n-alert v-if="log?.truncated" type="warning" :show-icon="false">
      Showing the last {{ log.max_bytes }} bytes.
    </n-alert>
    <div v-if="log && !log.exists" class="empty-state">Log file not found.</div>
    <pre v-else class="log-viewer">{{ logText }}</pre>
  </section>
</template>
