<script setup lang="ts">
import { computed, h, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { NAlert, NDataTable, NTag, type DataTableColumns } from "naive-ui";

import CoreUpdateTourPanel from "../components/CoreUpdateTourPanel.vue";
import HistoryViewTabs from "../components/HistoryViewTabs.vue";
import type { RunSummary } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");

function formatAction(run: RunSummary): string {
  const mode = run.mode || "Unknown";
  switch (mode) {
    case "cli": return run.dry_run ? "CLI (dry run)" : "CLI";
    case "apply": return "Apply";
    case "auto-update": return "Auto update";
    case "cleanup": return "Cleanup";
    case "snooze-created": return "Snooze created";
    case "snooze-removed": return "Snooze removed";
    case "service-policy-upserted": return "Policy changed";
    case "service-policy-deleted": return "Policy removed";
    case "tag-exclusion-upserted": return "Tag exclusion saved";
    case "tag-exclusion-status": return "Tag exclusion status changed";
    case "web-auth": return "Web auth";
    case "web-state": return "Web state";
    case "web-pending-cleanup": return "Pending cleanup";
    case "web-pending-removal": return "Pending removal";
    case "web-settings": return "Settings changed";
    case "container-restart": return "Container restarted";
    default: return mode;
  }
}

function formatServices(run: RunSummary): string {
  if (!run.events || !run.events.length) return "-";
  const names = Array.from(new Set(run.events.map(e => e.service_name || e.stack_name || "service")));
  if (names.length <= 3) return names.join(", ");
  return `${names.slice(0, 3).join(", ")}, +${names.length - 3} more`;
}

const columns = computed<DataTableColumns<RunSummary>>(() => [
  {
    title: "Run",
    key: "id",
    width: 90,
    render: (row) =>
      h(RouterLink, { to: `/runs/${row.id}`, class: "text-link" }, () => `#${row.id}`),
  },
  { title: "Status", key: "status", minWidth: 100 },
  { title: "Action", key: "mode", minWidth: 140, render: (row) => formatAction(row) },
  { title: "Updates", key: "updates", minWidth: 90, render: (row) => row.events?.length || 0 },
  { title: "Services", key: "services", minWidth: 140, render: (row) => formatServices(row) },
  { title: "Started", key: "started_at", minWidth: 180 },
  { title: "Finished", key: "finished_at", minWidth: 180, render: (row) => row.finished_at ?? "Running" },
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

    <HistoryViewTabs />

    <CoreUpdateTourPanel
      step="runs_history"
      title="Verify the run afterward"
      detail="History records each preview, apply, cleanup, and settings action. Open a run to inspect metadata, then use the log link when command output matters."
      complete
      next-label="Finish tour"
    >
      <div class="core-tour-facts">
        <span>{{ webui.runs.length }} recent runs</span>
        <span>Details and logs stay linked from each run</span>
      </div>
    </CoreUpdateTourPanel>

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
            {{ formatAction(run) }}
          </n-tag>
        </div>
        <dl>
          <div v-if="run.events && run.events.length">
            <dt>Updates</dt>
            <dd>{{ run.events.length }} ({{ formatServices(run) }})</dd>
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
