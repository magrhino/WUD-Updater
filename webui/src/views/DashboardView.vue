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

onMounted(() => {
  runInBackground(Promise.all([
    connection.loadStatus(),
    updates.loadPending(),
    runs.loadRuns(),
    settings.loadServicePolicies(),
    settings.loadSnoozes(),
    settings.loadTagExclusions(),
  ]));
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
      </div>
    </CoreUpdateTourPanel>

    <n-grid responsive="self" cols="1 560:2 920:4" :x-gap="12" :y-gap="12">
      <n-gi>
        <article class="metric-card">
          <ListChecks :size="22" />
          <span>Pending</span>
          <strong>{{ connection.status?.pending_count ?? updates.pending?.count ?? "0" }}</strong>
        </article>
      </n-gi>
      <n-gi>
        <article class="metric-card">
          <Database :size="22" />
          <span>Database</span>
          <strong>{{ connection.status?.db_ready ? "Ready" : "Missing" }}</strong>
        </article>
      </n-gi>
      <n-gi>
        <article class="metric-card">
          <Clock3 :size="22" />
          <span>Last run</span>
          <strong>{{ latestRun ? `#${latestRun.id}` : "None" }}</strong>
        </article>
      </n-gi>
      <n-gi>
        <article class="metric-card">
          <CheckCircle2 v-if="connection.status?.ok" :size="22" />
          <AlertTriangle v-else :size="22" />
          <span>Status</span>
          <strong>{{ connection.status?.ok ? "OK" : "Needs attention" }}</strong>
        </article>
      </n-gi>
    </n-grid>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Queue</p>
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
          <p class="eyebrow">History</p>
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
          <p class="eyebrow">Controls</p>
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

</style>
