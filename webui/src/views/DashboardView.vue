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
import { NAlert } from "naive-ui";

import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();

const latestRun = computed(() => webui.runs[0] ?? null);

onMounted(() => {
  void webui.loadDashboard();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>

    <div v-if="webui.warnings.length" class="warning-list">
      <n-alert
        v-for="warning in webui.warnings"
        :key="warning"
        type="warning"
        :show-icon="false"
      >
        {{ warning }}
      </n-alert>
    </div>

    <div class="metric-grid">
      <article class="metric-card">
        <ListChecks :size="22" />
        <span>Pending</span>
        <strong>{{ webui.status?.pending_count ?? webui.pending?.count ?? "0" }}</strong>
      </article>
      <article class="metric-card">
        <Database :size="22" />
        <span>Database</span>
        <strong>{{ webui.status?.db_ready ? "Ready" : "Missing" }}</strong>
      </article>
      <article class="metric-card">
        <Clock3 :size="22" />
        <span>Last run</span>
        <strong>{{ latestRun ? `#${latestRun.id}` : "None" }}</strong>
      </article>
      <article class="metric-card">
        <CheckCircle2 v-if="webui.status?.ok" :size="22" />
        <AlertTriangle v-else :size="22" />
        <span>Status</span>
        <strong>{{ webui.status?.ok ? "OK" : "Needs attention" }}</strong>
      </article>
    </div>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Queue</p>
          <h2>Pending updates</h2>
        </div>
        <RouterLink to="/pending" class="text-link">View pending</RouterLink>
      </div>
      <div v-if="!webui.pending?.items.length" class="empty-state">No pending updates.</div>
      <div v-else class="compact-list">
        <div v-for="item in webui.pending.items.slice(0, 5)" :key="item.line_no" class="list-row">
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
      <div v-if="!webui.runs.length" class="empty-state">No runs recorded.</div>
      <div v-else class="compact-list">
        <RouterLink
          v-for="run in webui.runs.slice(0, 5)"
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
      <div class="shortcut-grid">
        <RouterLink to="/policies" class="shortcut-card">
          <Settings2 :size="20" />
          <span>Policies</span>
          <strong>{{ webui.servicePolicies.length }}</strong>
        </RouterLink>
        <RouterLink to="/snoozes" class="shortcut-card">
          <BellOff :size="20" />
          <span>Active snoozes</span>
          <strong>{{ webui.snoozes.length }}</strong>
        </RouterLink>
        <RouterLink to="/tag-exclusions" class="shortcut-card">
          <Tags :size="20" />
          <span>Active exclusions</span>
          <strong>{{ webui.tagExclusions.length }}</strong>
        </RouterLink>
      </div>
    </section>
  </section>
</template>
