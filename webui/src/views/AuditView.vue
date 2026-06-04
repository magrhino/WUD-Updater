<script setup lang="ts">
import { computed, h, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { NAlert, NDataTable, NTag, type DataTableColumns } from "naive-ui";

import HistoryViewTabs from "../components/HistoryViewTabs.vue";
import type { RunSummary } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");

const CLI_UPDATE_MODES = new Set(["pause", "stop", "live"]);
const WEB_AUDIT_MODES = new Set([
  "web-state",
  "web-settings",
  "web-pending-cleanup",
  "web-pending-removal",
  "web-container-restart",
  "web-self-update",
  "web-auth",
]);

const auditRuns = computed(() => webui.runs.filter(isAuditRun));

function metadataSource(run: RunSummary): string {
  const source = run.metadata?.source;
  return typeof source === "string" ? source : "";
}

function isAuditRun(run: RunSummary): boolean {
  const source = metadataSource(run);
  if (source === "webui-auto") return false;
  if (source === "webui" || source === "cli") return true;
  if (!source && CLI_UPDATE_MODES.has(run.mode)) return true;
  return WEB_AUDIT_MODES.has(run.mode);
}

function formatAction(run: RunSummary): string {
  const mode = run.mode || "Unknown";
  if (CLI_UPDATE_MODES.has(mode)) {
    return metadataSource(run) === "webui" ? "Manual Apply" : `CLI ${mode}`;
  }
  switch (mode) {
    case "cli": return run.dry_run ? "CLI (dry run)" : "CLI";
    case "apply": return "Manual Apply";
    case "web-state": return "State changed";
    case "web-pending-cleanup": return "Pending cleanup";
    case "web-pending-removal": return "Pending removal";
    case "web-container-restart": return "Container restart";
    case "web-self-update": return "Self update";
    case "web-auth": return "Auth changed";
    case "web-settings": return "Settings changed";
    default: return mode;
  }
}

function formatTarget(run: RunSummary): string {
  if (run.metadata && run.metadata.resource_id) {
    return String(run.metadata.resource_id);
  }
  if (run.metadata && run.metadata.service_key) {
    return String(run.metadata.service_key);
  }
  if (run.events && run.events.length) {
    const names = Array.from(new Set(run.events.map(e => e.service_name || e.stack_name || "service")));
    if (names.length === 1) return names[0];
    if (names.length === 2) return `${names[0]}, ${names[1]}`;
    return `${names.length} services`;
  }
  return "-";
}

const columns = computed<DataTableColumns<RunSummary>>(() => [
  {
    title: "Run",
    key: "id",
    width: 90,
    render: (row) =>
      h(RouterLink, { to: `/runs/${row.id}`, class: "text-link" }, () => `#${row.id}`),
  },
  { title: "Started", key: "started_at", minWidth: 180 },
  { title: "Action", key: "mode", minWidth: 180, render: (row) => formatAction(row) },
  { title: "Target", key: "target", minWidth: 150, render: (row) => formatTarget(row) },
  { title: "Status", key: "status", minWidth: 100 },
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
        <p class="eyebrow">Operator Actions</p>
        <h2>Audit log</h2>
      </div>
    </div>

    <HistoryViewTabs />

    <n-alert type="info" :show-icon="false" style="margin-bottom: 16px;">
      Shows matching operator actions from the 50 most recent runs.
    </n-alert>

    <n-data-table
      v-if="!isMobile"
      :columns="columns"
      :data="auditRuns"
      :loading="webui.loading"
      :pagination="{ pageSize: 15 }"
      size="small"
      class="data-surface"
    />

    <div v-else class="mobile-list">
      <RouterLink
        v-for="run in auditRuns"
        :key="run.id"
        :to="`/runs/${run.id}`"
        class="mobile-card linked"
      >
        <div class="mobile-card-title">
          <strong>#{{ run.id }} {{ run.status }}</strong>
          <n-tag size="small" :type="run.dry_run ? 'info' : 'warning'">
            {{ formatAction(run) }}
          </n-tag>
        </div>
        <dl>
          <div>
            <dt>Target</dt>
            <dd>{{ formatTarget(run) }}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{{ run.started_at }}</dd>
          </div>
        </dl>
      </RouterLink>
      <div v-if="!auditRuns.length" class="empty-state">No operator actions recorded recently.</div>
    </div>
  </section>
</template>
