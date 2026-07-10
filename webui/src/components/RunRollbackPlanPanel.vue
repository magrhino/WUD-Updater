<script setup lang="ts">
import { NAlert, NButton, NTag } from "naive-ui";

import type {
  RollbackPlanResponse,
  RollbackPlanStatus,
} from "../api/client";

defineProps<{
  plan: RollbackPlanResponse | null;
  loading: boolean;
}>();

defineEmits<{
  check: [];
}>();

function statusType(
  status: RollbackPlanStatus,
): "success" | "warning" | "error" | "default" {
  if (status === "ready") return "success";
  if (status === "partial") return "warning";
  if (status === "blocked" || status === "unavailable") return "error";
  return "default";
}

function statusLabel(status: RollbackPlanStatus): string {
  return status.replaceAll("_", " ");
}
</script>

<template>
  <section class="section-panel rollback-plan-panel">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Verified recovery evidence</p>
        <h2>Rollback plan</h2>
      </div>
      <n-button
        secondary
        size="small"
        :loading="loading"
        @click="$emit('check')"
      >
        {{ plan ? "Check again" : "Check rollback plan" }}
      </n-button>
    </div>

    <n-alert type="info" :show-icon="false">
      Read-only guidance. This check does not pull images, edit Compose, or restart
      services.
    </n-alert>

    <template v-if="plan">
      <div class="rollback-plan-summary">
        <n-tag size="small" :type="statusType(plan.status)">
          {{ statusLabel(plan.status) }}
        </n-tag>
        <span>{{ plan.detail }}</span>
        <span v-if="plan.items.length" class="rollback-plan-counts">
          {{ plan.ready_count }} ready · {{ plan.blocked_count }} blocked ·
          {{ plan.not_needed_count }} not needed
        </span>
      </div>

      <div v-if="plan.items.length" class="rollback-plan-items">
        <article
          v-for="item in plan.items"
          :key="item.event_id"
          class="rollback-plan-item"
        >
          <div class="rollback-plan-item-heading">
            <strong>{{ item.service_key || "Unknown service" }}</strong>
            <n-tag
              size="small"
              :type="item.status === 'ready' ? 'success' : item.status === 'blocked' ? 'error' : 'default'"
            >
              {{ statusLabel(item.status) }}
            </n-tag>
          </div>
          <p>{{ item.reason }}</p>
          <dl class="rollback-plan-evidence">
            <div v-if="item.current_compose_image">
              <dt>Current Compose image</dt>
              <dd><code>{{ item.current_compose_image }}</code></dd>
            </div>
            <div>
              <dt>Recorded target</dt>
              <dd><code>{{ item.recorded_target_image || "unavailable" }}</code></dd>
            </div>
            <div>
              <dt>Recorded previous image</dt>
              <dd><code>{{ item.recorded_previous_image || "unavailable" }}</code></dd>
            </div>
            <div v-if="item.rollback_image">
              <dt>Exact rollback target</dt>
              <dd><code>{{ item.rollback_image }}</code></dd>
            </div>
            <div v-if="item.previous_image_id">
              <dt>Previous image ID</dt>
              <dd><code>{{ item.previous_image_id }}</code></dd>
            </div>
            <div v-if="item.previous_digest">
              <dt>Recorded previous digest</dt>
              <dd><code>{{ item.previous_digest }}</code></dd>
            </div>
            <div v-if="item.current_container_image_ids.length">
              <dt>Current container image IDs</dt>
              <dd><code>{{ item.current_container_image_ids.join(", ") }}</code></dd>
            </div>
          </dl>

          <ol v-if="item.status === 'ready'" class="rollback-plan-steps">
            <li>Replace this service image with the exact rollback target.</li>
            <li>Recreate only this service through your normal Compose workflow.</li>
            <li>Verify service health before making another update.</li>
            <li>Review and reconcile the WUD pending queue.</li>
          </ol>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.rollback-plan-panel {
  display: grid;
  gap: 12px;
}

.rollback-plan-summary,
.rollback-plan-item-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rollback-plan-counts {
  color: var(--color-muted-text);
  font-size: 0.84rem;
}

.rollback-plan-items {
  display: grid;
  gap: 8px;
}

.rollback-plan-item {
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 8px;
}

.rollback-plan-item p {
  margin: 6px 0 10px;
  color: var(--color-muted-text);
}

.rollback-plan-evidence {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px 12px;
  margin: 0;
}

.rollback-plan-evidence div {
  min-width: 0;
}

.rollback-plan-evidence dt {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
}

.rollback-plan-evidence dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}

.rollback-plan-steps {
  margin: 12px 0 0;
  padding-left: 1.25rem;
}

.rollback-plan-steps li + li {
  margin-top: 4px;
}
</style>
