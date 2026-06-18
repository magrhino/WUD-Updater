<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { NAlert, NDataTable, NEmpty, NTag, type DataTableColumns } from "naive-ui";

import HistoryViewTabs from "../components/HistoryViewTabs.vue";
import { useRouteRefresh } from "../components/app/routeRefresh";
import type { RunSummary } from "../api/client";
import { useDataCardsBreakpoint } from "../responsive";
import { useRunsStore } from "../stores/runs";
import { runInBackground } from "../utils/promises";

const runs = useRunsStore();
const isMobile = useDataCardsBreakpoint();
const isLoadingRuns = ref(false);

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

const auditRuns = computed(() => runs.runs.filter(isAuditRun));
const auditCountLabel = computed(() => {
  const count = auditRuns.value.length;
  return `${count} operator ${count === 1 ? "action" : "actions"}`;
});

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

function sourceLabel(run: RunSummary): string {
  const source = metadataSource(run);
  if (source === "webui") return "WebUI";
  if (source === "cli" || (!source && CLI_UPDATE_MODES.has(run.mode))) return "CLI";
  if (run.mode.startsWith("web-")) return "WebUI";
  return source || "System";
}

function finishLabel(run: RunSummary): string {
  return run.finished_at ?? "Running";
}

function statusTagType(status: string): "success" | "warning" | "error" | "default" {
  switch (status.toLowerCase()) {
    case "success":
      return "success";
    case "running":
    case "queued":
      return "warning";
    case "failed":
    case "failure":
    case "error":
      return "error";
    default:
      return "default";
  }
}

function actionTagType(run: RunSummary): "info" | "warning" | "default" {
  if (run.dry_run) {
    return "info";
  }
  if (CLI_UPDATE_MODES.has(run.mode)) {
    return "warning";
  }
  return "default";
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
  {
    title: "Source",
    key: "source",
    minWidth: 100,
    render: (row) => sourceLabel(row),
  },
  {
    title: "Status",
    key: "status",
    minWidth: 110,
    render: (row) =>
      h(NTag, { class: "audit-status-tag", size: "small", type: statusTagType(row.status) }, () => row.status),
  },
  { title: "Finished", key: "finished_at", minWidth: 180, render: (row) => finishLabel(row) },
]);

async function loadAuditRuns(): Promise<void> {
  isLoadingRuns.value = true;
  try {
    await runs.loadRuns();
  } finally {
    isLoadingRuns.value = false;
  }
}

onMounted(() => {
  runInBackground(loadAuditRuns());
});

useRouteRefresh(loadAuditRuns);
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="runs.error" type="error" :show-icon="false">
      {{ runs.error }}
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow">Operator Actions</p>
        <h2>{{ auditCountLabel }}</h2>
      </div>
    </div>

    <HistoryViewTabs />

    <n-alert type="info" :show-icon="false">
      Shows matching operator actions from the 50 most recent runs. Open a run to inspect metadata and logs.
    </n-alert>

    <n-data-table
      v-if="!isMobile && (isLoadingRuns || auditRuns.length)"
      :columns="columns"
      :data="auditRuns"
      :loading="isLoadingRuns"
      :pagination="{ pageSize: 15 }"
      size="small"
      class="data-surface"
    />
    <n-empty
      v-else-if="!isMobile"
      class="empty-state"
      description="No operator actions recorded recently."
      :show-icon="false"
    />

    <div v-else class="mobile-list">
      <RouterLink
        v-for="run in auditRuns"
        :key="run.id"
        :to="`/runs/${run.id}`"
        class="mobile-card linked"
      >
        <div class="mobile-card-title">
          <strong>#{{ run.id }}</strong>
          <n-tag size="small" :type="actionTagType(run)">
            {{ formatAction(run) }}
          </n-tag>
        </div>
        <dl>
          <div>
            <dt>Status</dt>
            <dd class="audit-status-value">
              <n-tag class="audit-status-tag" size="small" :type="statusTagType(run.status)">
                {{ run.status }}
              </n-tag>
            </dd>
          </div>
          <div>
            <dt>Target</dt>
            <dd>{{ formatTarget(run) }}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{{ sourceLabel(run) }}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{{ run.started_at }}</dd>
          </div>
          <div>
            <dt>Finished</dt>
            <dd>{{ finishLabel(run) }}</dd>
          </div>
        </dl>
      </RouterLink>
      <n-empty
        v-if="!isLoadingRuns && !auditRuns.length"
        class="empty-state"
        description="No operator actions recorded recently."
        :show-icon="false"
      />
    </div>
  </section>
</template>
