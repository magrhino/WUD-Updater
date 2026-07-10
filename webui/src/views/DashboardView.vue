<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink } from "vue-router";
import {
  AlertTriangle,
  BellOff,
  CheckCircle2,
  Clock3,
  Database,
  ListChecks,
  Settings2,
  Tags,
} from "@lucide/vue";
import { NAlert, NEmpty, NGi, NGrid } from "naive-ui";

import CoreUpdateTourPanel from "../components/CoreUpdateTourPanel.vue";
import { useRouteRefresh } from "../components/app/routeRefresh";
import { useConnectionStore } from "../stores/connection";
import { useUpdatesStore } from "../stores/updates";
import { useRunsStore } from "../stores/runs";
import { useSettingsStore } from "../stores/settings";
import { runInBackground } from "../utils/promises";

const connection = useConnectionStore();
const updates = useUpdatesStore();
const runs = useRunsStore();
const settings = useSettingsStore();

const latestRun = computed(() => runs.runs[0] ?? null);
const error = computed(() => connection.error || updates.error || runs.error || settings.error);
const warnings = computed(() => [
  ...(connection.status?.warnings ?? []),
  ...(updates.pending?.warnings ?? []),
]);
const wudApiLabel = computed(() => {
  const api = connection.status?.wud_api;
  if (!api) {
    return "Unknown";
  }
  if (api.metadata_available) {
    return "Metadata ready";
  }
  if (api.available && api.state === "auth_required") {
    return "Auth required";
  }
  if (api.available) {
    return "Degraded";
  }
  return "Unavailable";
});

async function loadDashboard(): Promise<void> {
  await Promise.all([
    connection.loadStatus(),
    updates.loadPending(),
    runs.loadRuns(),
    settings.loadServicePolicies(),
    settings.loadSnoozes(),
    settings.loadTagExclusions(),
  ]);
}

useRouteRefresh(loadDashboard);

onMounted(() => {
  runInBackground(loadDashboard());
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="error" type="error" :show-icon="false">
      {{ error }}
    </n-alert>

    <div v-if="warnings.length" class="warning-list">
      <n-alert
        v-for="warning in warnings"
        :key="warning"
        type="warning"
        :show-icon="false"
      >
        {{ warning }}
      </n-alert>
    </div>

    <CoreUpdateTourPanel
      step="dashboard"
      title="Start from current state"
      detail="Use the dashboard to confirm the queue, database, last run, and overall status before choosing updates."
      next-label="Open pending updates"
      next-step="pending_select"
      next-to="/pending"
    >
      <div class="core-tour-facts">
        <span>Pending: {{ connection.status?.pending_count ?? updates.pending?.count ?? 0 }}</span>
        <span>Database: {{ connection.status?.db_ready ? "ready" : "missing" }}</span>
        <span>Mutations: {{ connection.status?.mutations_enabled ? "enabled" : "read-only" }}</span>
        <span>WUD API: {{ wudApiLabel }}</span>
      </div>
    </CoreUpdateTourPanel>

    <dl class="dashboard-status-strip" aria-label="System status">
      <div class="dashboard-status-item">
        <dt><ListChecks :size="20" aria-hidden="true" />Pending</dt>
        <dd>{{ connection.status?.pending_count ?? updates.pending?.count ?? "0" }}</dd>
      </div>
      <div class="dashboard-status-item">
        <dt><Database :size="20" aria-hidden="true" />Database</dt>
        <dd>{{ connection.status?.db_ready ? "Ready" : "Missing" }}</dd>
      </div>
      <div class="dashboard-status-item">
        <dt><Clock3 :size="20" aria-hidden="true" />Last run</dt>
        <dd>{{ latestRun ? `#${latestRun.id}` : "None" }}</dd>
      </div>
      <div class="dashboard-status-item">
        <dt>
          <CheckCircle2 v-if="connection.status?.ok" :size="20" aria-hidden="true" />
          <AlertTriangle v-else :size="20" aria-hidden="true" />
          Status
        </dt>
        <dd>{{ connection.status?.ok ? "OK" : "Needs attention" }}</dd>
      </div>
      <div class="dashboard-status-item">
        <dt>
          <CheckCircle2
            v-if="connection.status?.wud_api?.metadata_available"
            :size="20"
            aria-hidden="true"
          />
          <AlertTriangle v-else :size="20" aria-hidden="true" />
          WUD API
        </dt>
        <dd>{{ wudApiLabel }}</dd>
      </div>
    </dl>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <h2>Pending updates</h2>
        </div>
        <RouterLink to="/pending" class="text-link">View pending</RouterLink>
      </div>
      <output
        v-if="!updates.pending?.items.length"
        class="empty-state clear-queue-state clear-queue-state-compact"
      >
        <span class="clear-queue-mark" aria-hidden="true">
          <CheckCircle2 :size="24" />
        </span>
        <strong>Queue clear</strong>
        <span>No pending updates are waiting for review.</span>
      </output>
      <div v-else class="compact-list">
        <div v-for="item in updates.pending.items.slice(0, 5)" :key="item.line_no" class="list-row">
          <span>#{{ item.line_no }}</span>
          <strong>{{ item.image }}</strong>
          <em>{{ item.desired_tag || item.digest || "latest available" }}</em>
        </div>
      </div>
    </section>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <h2>Recent runs</h2>
        </div>
        <RouterLink to="/runs" class="text-link">View history</RouterLink>
      </div>
      <n-empty
        v-if="!runs.runs.length"
        class="empty-state"
        description="No runs recorded."
        :show-icon="false"
      />
      <div v-else class="compact-list">
        <RouterLink
          v-for="run in runs.runs.slice(0, 5)"
          :key="run.id"
          :to="`/runs/${run.id}`"
          class="list-row linked"
        >
          <span>#{{ run.id }}</span>
          <strong>{{ run.status }}</strong>
          <em>{{ run.started_at }}</em>
        </RouterLink>
      </div>
    </section>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <h2>Management</h2>
        </div>
      </div>
      <n-grid class="shortcut-grid" responsive="self" cols="1 920:3" :x-gap="10" :y-gap="10">
        <n-gi>
          <RouterLink to="/policies" class="shortcut-card">
            <Settings2 :size="20" />
            <span>Policies</span>
            <strong>{{ settings.servicePolicies.length }}</strong>
          </RouterLink>
        </n-gi>
        <n-gi>
          <RouterLink to="/snoozes" class="shortcut-card">
            <BellOff :size="20" />
            <span>Active snoozes</span>
            <strong>{{ settings.snoozes.length }}</strong>
          </RouterLink>
        </n-gi>
        <n-gi>
          <RouterLink to="/tag-exclusions" class="shortcut-card">
            <Tags :size="20" />
            <span>Active exclusions</span>
            <strong>{{ settings.tagExclusions.length }}</strong>
          </RouterLink>
        </n-gi>
      </n-grid>
    </section>
  </section>
</template>

<style scoped>
.dashboard-status-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-border-subtle);
}

.dashboard-status-item {
  min-width: 0;
  padding: 14px 16px;
  background: var(--color-surface);
}

.dashboard-status-item dt {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: var(--color-muted-text);
  font-size: var(--text-metadata-size);
  font-weight: 600;
}

.dashboard-status-item dt svg {
  flex: 0 0 auto;
  color: var(--color-operational-teal);
}

.dashboard-status-item dd {
  min-width: 0;
  margin: 7px 0 0 27px;
  color: var(--color-ink);
  font-size: var(--text-body-size);
  font-weight: 700;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.shortcut-grid {
  margin-top: 16px;
}

.shortcut-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
  transition:
    border-color var(--motion-base) var(--ease-out-quart),
    transform var(--motion-fast) var(--ease-out-quart);
}

.shortcut-card:hover {
  border-color: var(--color-border-hover);
  transform: translateY(-1px);
}

.shortcut-card:active {
  transform: translateY(0);
}

.shortcut-card svg {
  color: var(--color-operational-teal);
}

.shortcut-card span,
.shortcut-card strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

@media (--wud-app-shell) {
  .dashboard-status-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-status-item:last-child:nth-child(odd) {
    grid-column: 1 / -1;
  }
}

@media (--wud-compact) {
  .dashboard-status-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .dashboard-status-item:last-child:nth-child(odd) {
    grid-column: auto;
  }
}

</style>
