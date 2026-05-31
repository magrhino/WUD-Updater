<script setup lang="ts">
import { computed, h, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { NAlert, NDataTable, NTag, type DataTableColumns } from "naive-ui";

import type { RunSummary } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");

const columns = computed<DataTableColumns<RunSummary>>(() => [
  {
    title: "Run",
    key: "id",
    width: 90,
    render: (row) =>
      h(RouterLink, { to: `/runs/${row.id}`, class: "text-link" }, () => `#${row.id}`),
  },
  { title: "Status", key: "status", minWidth: 120 },
  { title: "Mode", key: "mode", minWidth: 100 },
  { title: "Dry run", key: "dry_run", minWidth: 100, render: (row) => (row.dry_run ? "Yes" : "No") },
  { title: "Started", key: "started_at", minWidth: 220 },
  { title: "Finished", key: "finished_at", minWidth: 220 },
]);

onMounted(() => {
  void webui.loadRuns();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow">SQLite history</p>
        <h2>{{ webui.runs.length }} recent runs</h2>
      </div>
    </div>

    <n-data-table
      v-if="!isMobile"
      :columns="columns"
      :data="webui.runs"
      :loading="webui.loading"
      :pagination="{ pageSize: 15 }"
      size="small"
      class="data-surface"
    />

    <div v-else class="mobile-list">
      <RouterLink
        v-for="run in webui.runs"
        :key="run.id"
        :to="`/runs/${run.id}`"
        class="mobile-card linked"
      >
        <div class="mobile-card-title">
          <strong>#{{ run.id }} {{ run.status }}</strong>
          <n-tag size="small" :type="run.dry_run ? 'info' : 'warning'">
            {{ run.dry_run ? "Dry run" : "Apply" }}
          </n-tag>
        </div>
        <dl>
          <div>
            <dt>Mode</dt>
            <dd>{{ run.mode }}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{{ run.started_at }}</dd>
          </div>
          <div>
            <dt>Finished</dt>
            <dd>{{ run.finished_at ?? "Running" }}</dd>
          </div>
        </dl>
      </RouterLink>
      <div v-if="!webui.runs.length" class="empty-state">No runs recorded.</div>
    </div>
  </section>
</template>
