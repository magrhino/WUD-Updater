<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { FileText } from "@lucide/vue";
import { NAlert, NEmpty, NGi, NGrid } from "naive-ui";

import type { RunEventRecord } from "../api/client";
import { useRouteRefresh } from "../components/app/routeRefresh";
import RunVerificationPanel from "../components/RunVerificationPanel.vue";
import RunRollbackPlanPanel from "../components/RunRollbackPlanPanel.vue";
import { useRunsStore } from "../stores/runs";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../utils/digestProvenance";
import { runInBackground } from "../utils/promises";

const route = useRoute();
const runs = useRunsStore();
const runId = computed(() => Number(route.params.id));
const run = computed(() => runs.runDetails[runId.value] ?? null);
const hasRunMetadata = computed(
  () => Object.keys(run.value?.metadata ?? {}).length > 0,
);
const runMetadataJson = computed(() =>
  run.value ? JSON.stringify(run.value.metadata, null, 2) : "",
);
const rollbackPlan = computed(
  () => runs.rollbackPlans[runId.value] ?? null,
);
const rollbackEligible = computed(
  () =>
    Boolean(run.value?.finished_at) &&
    !run.value?.dry_run &&
    ["pause", "stop", "live"].includes(run.value?.mode ?? "") &&
    Boolean(run.value?.events.length),
);

async function load(): Promise<void> {
  await runs.loadRunDetail(runId.value);
}

async function loadRollbackPlan(): Promise<void> {
  await runs.loadRollbackPlan(runId.value);
}

useRouteRefresh(load);

onMounted(() => {
  runInBackground(load());
});

watch(runId, () => {
  runInBackground(load());
});

function eventDigestLabel(event: RunEventRecord): string {
  if (event.digest_provenance?.target_digest) {
    return displayDigest(event.digest_provenance.target_digest);
  }
  const oldDigest = event.old_digest ? shortEventDigest(event.old_digest) : "none";
  const newDigest = event.new_digest ? shortEventDigest(event.new_digest) : "none";
  return `${oldDigest} -> ${newDigest}`;
}

function shortEventDigest(value: string): string {
  return `${value.substring(0, 15)}...`;
}
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="runs.error" type="error" :show-icon="false">
      {{ runs.error }}
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow">Run detail</p>
        <h2>#{{ runId }}</h2>
      </div>
      <RouterLink v-if="run?.log_file" :to="`/runs/${runId}/log`" class="icon-link">
        <FileText :size="17" />
        View log
      </RouterLink>
    </div>

    <div v-if="run" class="content-stack">
      <n-grid responsive="self" cols="1 560:2 920:4" :x-gap="12" :y-gap="12">
        <n-gi>
          <article class="metric-card">
            <span>Status</span>
            <strong>{{ run.status }}</strong>
          </article>
        </n-gi>
        <n-gi>
          <article class="metric-card">
            <span>Mode</span>
            <strong>{{ run.mode }}</strong>
          </article>
        </n-gi>
        <n-gi>
          <article class="metric-card">
            <span>Dry run</span>
            <strong>{{ run.dry_run ? "Yes" : "No" }}</strong>
          </article>
        </n-gi>
        <n-gi>
          <article class="metric-card">
            <span>Updates</span>
            <strong>{{ run.pending_updates.length }}</strong>
          </article>
        </n-gi>
      </n-grid>

      <RunVerificationPanel
        :verification="run.verification"
        title="Post-update verification"
      />

      <RunRollbackPlanPanel
        v-if="rollbackEligible"
        :plan="rollbackPlan"
        :loading="runs.loading"
        @check="runInBackground(loadRollbackPlan())"
      />

      <section v-if="hasRunMetadata" class="section-panel">
        <div class="section-heading">
          <div>
            <p class="eyebrow value-eyebrow">{{ run.mode }}</p>
            <h2>Run metadata</h2>
          </div>
        </div>
        <pre class="log-viewer run-metadata-block">{{ runMetadataJson }}</pre>
      </section>

      <section class="section-panel">
        <div class="section-heading">
          <div>
            <p class="eyebrow value-eyebrow">{{ run.wud_file }}</p>
            <h2>Pending records</h2>
          </div>
        </div>
        <n-empty
          v-if="!run.pending_updates.length"
          class="empty-state"
          description="No pending records."
          :show-icon="false"
        />
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
        <n-empty
          v-if="!run.events.length"
          class="empty-state"
          description="No events recorded."
          :show-icon="false"
        />
        <div v-else class="compact-list">
          <div v-for="event in run.events" :key="event.id" class="list-row" style="flex-direction: column; align-items: flex-start; gap: 4px;">
            <div style="display: flex; gap: 8px; width: 100%;">
              <span>{{ event.service_name || event.stack_name || "service" }}</span>
              <strong>{{ event.status }}</strong>
              <em>{{ event.image }}</em>
            </div>
            <div style="font-size: 0.85em; color: var(--text-muted); display: flex; flex-direction: column; gap: 2px;">
              <span
                v-if="digestProvenanceDisplay(event.digest_provenance)"
                :title="digestProvenanceDisplay(event.digest_provenance)?.title"
              >
                {{ digestProvenanceDisplay(event.digest_provenance)?.primary }}
              </span>
              <span v-if="event.old_digest || event.new_digest || event.digest_provenance">
                Digest: {{ eventDigestLabel(event) }}
              </span>
              <span v-if="event.old_image_id || event.new_image_id">Image ID: {{ event.old_image_id ? event.old_image_id.substring(0, 15) + '...' : 'none' }} -> {{ event.new_image_id ? event.new_image_id.substring(0, 15) + '...' : 'none' }}</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.run-metadata-block {
  min-height: 0;
  max-height: 18rem;
  font-size: 0.82rem;
}
</style>
