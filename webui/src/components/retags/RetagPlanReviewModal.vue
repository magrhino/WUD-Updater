<script setup lang="ts">
import { computed } from "vue";
import { NAlert, NTag } from "naive-ui";

import type { RetagPlanResponse, RetagPreviewJobResponse } from "../../api/client";
import PreflightFooterActions from "../preflight/PreflightFooterActions.vue";
import PreflightMetricsGrid, {
  type PreflightMetric,
} from "../preflight/PreflightMetricsGrid.vue";
import PreflightModalShell from "../preflight/PreflightModalShell.vue";
import PreflightNoticeList from "../preflight/PreflightNoticeList.vue";
import PreflightProgressDisplay from "../preflight/PreflightProgressDisplay.vue";
import {
  digestPinSummary,
  labelRewriteSummary,
  planStatusType,
  pluralize,
  retagPlanSourceFile,
} from "../../views/retags/display";

const props = defineProps<{
  show: boolean;
  plan: RetagPlanResponse | null;
  previewJob: RetagPreviewJobResponse | null;
  impactLabel: string;
  mutationNotice: string;
  applyDisabled: boolean;
  loading: boolean;
  applyJobActive: boolean;
}>();

const emit = defineEmits<{
  close: [];
  apply: [];
}>();

const previewActive = computed(
  () =>
    props.loading ||
    props.previewJob?.status === "queued" ||
    props.previewJob?.status === "running",
);

const statusLabel = computed(
  () => props.plan?.status ?? props.previewJob?.status ?? "preview",
);

const statusType = computed(() =>
  props.plan ? planStatusType(props.plan) : previewActive.value ? "info" : "default",
);

const summary = computed(() => {
  if (props.previewJob?.status === "failure") {
    return props.previewJob.error || "Retag preview failed.";
  }
  if (!props.plan) {
    return "Refreshing retag candidates and building a preview.";
  }
  if (props.plan.status === "blocked") {
    return `${pluralize(props.plan.issues.length, "issue")} must be resolved before applying.`;
  }
  if (props.plan.status === "empty") {
    return "No selected services need retag changes.";
  }
  return `${pluralize(props.plan.selected_count, "service")} ready to retag.`;
});

const metrics = computed<PreflightMetric[]>(() => {
  const plan = props.plan;
  if (!plan) {
    return [
      { label: "Status", value: statusLabel.value },
      { label: "Progress", value: props.previewJob?.progress.length ?? 0 },
    ];
  }
  return [
    { label: "Services", value: plan.selected_count },
    { label: "Stacks", value: plan.stacks.length },
    { label: "Keep current", value: plan.keep_current_count },
    { label: "Source", value: retagPlanSourceFile(plan) },
  ];
});

const retagPlanUpdates = computed(() =>
  (props.plan?.stacks ?? []).flatMap((stack) =>
    stack.digest_pin_updates.map((update) => ({ stack, update })),
  ),
);

const warnings = computed(() => [
  ...(props.previewJob?.warnings ?? []),
  ...(props.plan?.warnings ?? []),
]);

const uniqueWarnings = computed(() => [...new Set(warnings.value)]);
</script>

<template>
  <PreflightModalShell
    :show="show"
    eyebrow="Preflight"
    title="Review retag preview"
    :summary="summary"
    :impact-label="impactLabel"
    :status-label="statusLabel"
    :status-type="statusType"
    @close="$emit('close')"
  >
    <n-alert
      v-if="mutationNotice"
      type="warning"
      :show-icon="false"
    >
      {{ mutationNotice }}
    </n-alert>

    <PreflightMetricsGrid :items="metrics" />

    <PreflightProgressDisplay
      :active="previewActive"
      :progress="previewJob?.progress ?? []"
      empty-message="Waiting for the retag preview job to start."
    />

    <PreflightNoticeList
      :warnings="uniqueWarnings"
      :issues="plan?.issues ?? []"
    />

    <section
      v-if="plan"
      class="preflight-impact preflight-block"
      aria-labelledby="retag-preview-services-title"
    >
      <div class="preflight-impact-heading">
        <strong id="retag-preview-services-title">Services and images</strong>
        <n-tag size="small">{{ pluralize(retagPlanUpdates.length, "service") }}</n-tag>
      </div>
      <div v-if="retagPlanUpdates.length" class="compact-list">
        <div
          v-for="{ stack, update } in retagPlanUpdates"
          :key="`preview-${update.service_key}`"
          class="list-row plan-line-row"
        >
          <span>{{ stack.stack }}</span>
          <strong>{{ update.service_key }}</strong>
          <em>
            <code>{{ digestPinSummary(update) }}</code>
            <span>{{ labelRewriteSummary(update) }}</span>
          </em>
        </div>
      </div>
      <div v-else class="empty-state">No retag changes selected.</div>
    </section>

    <PreflightFooterActions
      primary-label="Apply selected retags"
      :primary-disabled="!plan || applyDisabled"
      :primary-loading="loading || applyJobActive"
      secondary-label="Close"
      @primary="$emit('apply')"
      @secondary="$emit('close')"
    />
  </PreflightModalShell>
</template>

<style scoped>
.plan-line-row em {
  display: grid;
  gap: 3px;
}
</style>
