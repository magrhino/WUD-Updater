<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { FileText } from "@lucide/vue";
import { NAlert } from "naive-ui";

import { useWebuiStore } from "../stores/webui";

const route = useRoute();
const webui = useWebuiStore();
const runId = computed(() => Number(route.params.id));
const run = computed(() => webui.runDetails[runId.value] ?? null);

async function load(): Promise<void> {
  await webui.loadRunDetail(runId.value);
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
        <p class="eyebrow">Run detail</p>
        <h2>#{{ runId }}</h2>
      </div>
      <RouterLink :to="`/runs/${runId}/log`" class="icon-link">
        <FileText :size="17" />
        View log
      </RouterLink>
    </div>

    <div v-if="run" class="content-stack">
      <div class="metric-grid">
        <article class="metric-card">
          <span>Status</span>
          <strong>{{ run.status }}</strong>
        </article>
        <article class="metric-card">
          <span>Mode</span>
          <strong>{{ run.mode }}</strong>
        </article>
        <article class="metric-card">
          <span>Dry run</span>
          <strong>{{ run.dry_run ? "Yes" : "No" }}</strong>
        </article>
        <article class="metric-card">
          <span>Updates</span>
          <strong>{{ run.pending_updates.length }}</strong>
        </article>
      </div>

      <section class="section-panel">
        <div class="section-heading">
          <div>
            <p class="eyebrow value-eyebrow">{{ run.wud_file }}</p>
            <h2>Pending records</h2>
          </div>
        </div>
        <div v-if="!run.pending_updates.length" class="empty-state">No pending records.</div>
        <div v-else class="compact-list">
          <div v-for="item in run.pending_updates" :key="item.id" class="list-row">
            <span>#{{ item.line_no }}</span>
            <strong>{{ item.service_key || item.image }}</strong>
            <em>{{ item.status }} {{ item.status_reason }}</em>
          </div>
        </div>
      </section>

      <section class="section-panel">
        <div class="section-heading">
          <div>
            <p class="eyebrow value-eyebrow">{{ run.log_file || "No log path" }}</p>
            <h2>Events</h2>
          </div>
        </div>
        <div v-if="!run.events.length" class="empty-state">No events recorded.</div>
        <div v-else class="compact-list">
          <div v-for="event in run.events" :key="event.id" class="list-row">
            <span>{{ event.service_name || event.stack_name || "service" }}</span>
            <strong>{{ event.status }}</strong>
            <em>{{ event.image }}</em>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>
