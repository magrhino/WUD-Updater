<script setup lang="ts">
import { Info } from "@lucide/vue";
import { NAlert, NTag } from "naive-ui";

import type { RetagPlanResponse } from "../../api/client";
import {
  digestPinSummary,
  labelRewriteSummary,
  planLocation,
  planStatusType,
} from "../../views/retags/display";

defineProps<{
  plan: RetagPlanResponse;
}>();
</script>

<template>
  <section
    class="section-panel retag-plan-panel"
    aria-label="Retag plan preview"
  >
    <div class="section-heading retag-plan-heading">
      <div>
        <p class="eyebrow">Preview</p>
        <h2>Selected retag changes</h2>
      </div>
      <div class="retag-plan-tags">
        <n-tag size="small" :type="planStatusType(plan)" :bordered="false">
          {{ plan.status }}
        </n-tag>
        <n-tag size="small" :bordered="false">
          {{ plan.selected_count }} selected
        </n-tag>
        <n-tag size="small" :bordered="false">
          {{ plan.keep_current_count }} keep current
        </n-tag>
      </div>
    </div>

    <n-alert
      v-for="warning in plan.warnings"
      :key="warning"
      type="warning"
      :show-icon="false"
    >
      {{ warning }}
    </n-alert>

    <n-alert
      v-for="issue in plan.issues"
      :key="`${issue.code}-${issue.service_key}-${issue.message}`"
      :type="issue.severity === 'error' ? 'error' : 'warning'"
      :show-icon="false"
    >
      {{ issue.message }}
    </n-alert>

    <div v-if="plan.stacks.length" class="retag-plan-stacks">
      <div
        v-for="stack in plan.stacks"
        :key="`${stack.stack}-${stack.compose_file}`"
        class="retag-plan-stack"
      >
        <div class="retag-plan-stack-heading">
          <strong>{{ stack.stack }}</strong>
          <code class="wrap-anywhere">{{ planLocation(stack) }}</code>
        </div>
        <ul class="retag-plan-update-list">
          <li
            v-for="update in stack.digest_pin_updates"
            :key="update.service_key"
          >
            <div>
              <strong>{{ update.service_key }}</strong>
              <span class="wrap-anywhere">{{ update.service }}</span>
            </div>
            <code class="wrap-anywhere">{{ digestPinSummary(update) }}</code>
            <span class="wrap-anywhere">{{ labelRewriteSummary(update) }}</span>
          </li>
        </ul>
      </div>
    </div>

    <output
      v-else
      class="empty-state retag-state retag-plan-empty"
      aria-live="polite"
    >
      <Info :size="20" aria-hidden="true" />
      <strong>No retag changes selected</strong>
      <span>Current tracking remains unchanged for every service.</span>
    </output>
  </section>
</template>

<style scoped>
.retag-plan-panel {
  display: grid;
  gap: 12px;
}

.retag-plan-heading {
  align-items: flex-start;
}

.retag-plan-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.retag-plan-stacks {
  display: grid;
  gap: 10px;
}

.retag-plan-stack {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 8px;
  background: var(--color-panel-tint);
}

.retag-plan-stack-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.retag-plan-stack-heading code,
.retag-plan-update-list code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
}

.retag-plan-update-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.retag-plan-update-list li {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.retag-plan-update-list li div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.retag-plan-update-list li span {
  color: var(--color-muted-text);
  font-size: 0.84rem;
  line-height: 1.35;
}

.retag-plan-empty {
  min-height: 140px;
}

.retag-state svg {
  color: var(--color-operational-teal);
}
</style>
