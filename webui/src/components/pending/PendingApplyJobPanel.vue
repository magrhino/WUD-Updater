<script setup lang="ts">
import { ref } from "vue";
import { Check, CheckCircle2, ChevronDown, ChevronUp, Play, X } from "@lucide/vue";
import { NAlert, NButton, NTag } from "naive-ui";

import type { ApplyJobLogResponse, ApplyJobResponse } from "../../api/client";
import type {
  ApplyJobPlanSnapshot,
  ApplyJobProgressStep,
} from "../../views/pending/usePendingApplyJob";
import { pluralize } from "../../views/pending/utils";

type TagType = "default" | "error" | "info" | "success" | "warning";

const props = defineProps<{
  active: boolean;
  alertType: TagType;
  impactLabel: string;
  latestLogMessage: string;
  liveLogExpanded: boolean;
  liveLogToggleLabel: string;
  liveLogVisible: boolean;
  log: ApplyJobLogResponse | null;
  logEmptyMessage: string;
  logText: string;
  logTitle: string;
  logWaiting: boolean;
  nowDescriptionIds: string;
  nowDetail: string;
  nowMessage: string;
  nowStatusLabel: string;
  nowTitle: string;
  panelStatusLabel: string;
  progressSteps: ApplyJobProgressStep[];
  progressSummary: string;
  snapshot: ApplyJobPlanSnapshot | null;
  startedLabel: string;
  statusMessage: string;
  succeeded: boolean;
  title: string;
  updateLabel: string;
  job: ApplyJobResponse;
}>();

const emit = defineEmits<{
  (event: "update:liveLogExpanded", value: boolean): void;
}>();

const applyJobPanelRef = ref<HTMLElement | null>(null);
const applyJobPanelLogRef = ref<HTMLElement | null>(null);

defineExpose({
  focusPanel,
  logElement,
});

function focusPanel(behavior: ScrollBehavior): void {
  const panel = applyJobPanelRef.value;
  if (!panel) {
    return;
  }
  panel.scrollIntoView?.({
    block: "start",
    behavior,
  });
  panel.focus({ preventScroll: true });
}

function logElement(): HTMLElement | null {
  return applyJobPanelLogRef.value;
}

function progressTagType(
  status: ApplyJobProgressStep["status"],
): "default" | "success" | "warning" | "error" {
  if (status === "success") {
    return "success";
  }
  if (status === "running") {
    return "warning";
  }
  if (status === "failure") {
    return "error";
  }
  return "default";
}
</script>

<template>
  <section
    ref="applyJobPanelRef"
    class="section-panel apply-job-panel"
    :class="{
      'apply-job-panel-active': active,
      'apply-job-panel-success': succeeded,
    }"
    tabindex="-1"
    aria-labelledby="apply-job-panel-title"
  >
    <div class="section-heading apply-job-heading">
      <div>
        <p class="eyebrow">Apply job</p>
        <div class="apply-job-heading-title">
          <span v-if="succeeded" class="apply-job-complete-mark" aria-hidden="true">
            <CheckCircle2 :size="18" />
          </span>
          <h2 id="apply-job-panel-title">{{ title }}</h2>
        </div>
        <p class="apply-job-summary" role="status" aria-live="polite">
          {{ statusMessage }}
        </p>
      </div>
      <n-tag :type="alertType">{{ panelStatusLabel }}</n-tag>
    </div>

    <div v-if="active" class="apply-job-progress" aria-hidden="true">
      <span />
    </div>

    <section
      id="apply-job-panel-status"
      class="apply-job-now"
      :class="{
        'apply-job-now-success': job.status === 'success',
        'apply-job-now-failure': job.status === 'failure',
      }"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      tabindex="-1"
      aria-labelledby="apply-job-now-title"
      :aria-describedby="nowDescriptionIds"
    >
      <div class="apply-job-now-copy">
        <span>Current status</span>
        <strong id="apply-job-now-title">{{ nowTitle }}</strong>
        <em id="apply-job-now-message">{{ nowMessage }}</em>
        <small v-if="nowDetail" id="apply-job-now-detail">
          {{ nowDetail }}
        </small>
      </div>
      <n-tag size="small" :type="alertType">{{ nowStatusLabel }}</n-tag>
    </section>

    <section class="apply-job-latest-log" aria-labelledby="apply-job-latest-log-title">
      <span id="apply-job-latest-log-title">Latest log line</span>
      <code>{{ latestLogMessage }}</code>
    </section>

    <section class="apply-job-progress-steps" aria-labelledby="apply-job-progress-title">
      <div class="apply-job-impact-heading">
        <strong id="apply-job-progress-title">Update progress</strong>
        <n-tag size="small">{{ progressSummary }}</n-tag>
      </div>
      <ol class="apply-progress-list">
        <li
          v-for="step in progressSteps"
          :key="step.key"
          class="apply-progress-step"
          :class="`apply-progress-step-${step.status}`"
        >
          <span class="apply-progress-icon" aria-hidden="true">
            <Check v-if="step.status === 'success'" :size="14" />
            <X v-else-if="step.status === 'failure'" :size="14" />
            <Play v-else-if="step.status === 'running'" :size="14" />
          </span>
          <span class="apply-progress-copy">
            <strong>{{ step.label }}</strong>
            <span>{{ step.message }}</span>
            <em v-if="step.detail">{{ step.detail }}</em>
          </span>
          <n-tag size="small" :type="progressTagType(step.status)">
            {{ step.statusLabel }}
          </n-tag>
        </li>
      </ol>
    </section>

    <details class="apply-job-details" :open="!active">
      <summary>
        <span>Applied scope</span>
        <n-tag size="small">{{ impactLabel || updateLabel }}</n-tag>
      </summary>
      <div class="apply-job-grid">
        <div class="compact-list">
          <div class="list-row">
            <span>Updates</span>
            <strong>{{ updateLabel }}</strong>
            <em>{{ startedLabel }}</em>
          </div>
          <div v-if="impactLabel" class="list-row">
            <span>Impact</span>
            <strong>{{ impactLabel }}</strong>
            <em>{{ snapshot?.sourceFile }}</em>
          </div>
          <div v-if="job.run_id" class="list-row">
            <span>Run</span>
            <strong>#{{ job.run_id }}</strong>
            <em class="inline-actions">
              <RouterLink
                class="text-link"
                :to="{ name: 'run-detail', params: { id: job.run_id } }"
              >
                Details
              </RouterLink>
              <RouterLink
                class="text-link"
                :to="{ name: 'run-log', params: { id: job.run_id } }"
              >
                Log
              </RouterLink>
            </em>
          </div>
        </div>

        <section
          class="apply-job-impact"
          aria-labelledby="apply-job-impact-title"
        >
          <div class="apply-job-impact-heading">
            <strong id="apply-job-impact-title">Services and images</strong>
            <n-tag size="small">{{ pluralize(snapshot?.lines.length ?? 0, "service") }}</n-tag>
          </div>
          <div v-if="snapshot?.lines.length" class="compact-list">
            <div
              v-for="line in snapshot.lines"
              :key="line.key"
              class="list-row plan-line-row"
            >
              <span>#{{ line.lineNo }}</span>
              <strong>{{ line.serviceLabel }}</strong>
              <em>
                <span v-if="line.tagRewriteLabel" class="tag-rewrite-detail">
                  <n-tag size="small" type="warning">Tag rewrite</n-tag>
                  {{ line.tagRewriteLabel }}
                </span>
                <span v-else-if="line.digestPinLabel" class="tag-rewrite-detail">
                  <n-tag size="small" type="info">Digest pin</n-tag>
                  {{ line.digestPinLabel }}
                </span>
                <template v-else>
                  <code>{{ line.composeImage }}</code>
                  <span aria-hidden="true"> -> </span>
                  <code>{{ line.targetImage }}</code>
                </template>
              </em>
            </div>
          </div>
          <div v-else class="empty-state">
            Plan details are unavailable after page reload.
          </div>
        </section>
      </div>
    </details>

    <section class="apply-job-live-log" aria-labelledby="apply-job-log-title">
      <div class="apply-job-impact-heading apply-job-live-log-heading">
        <div class="apply-job-log-heading-copy">
          <strong id="apply-job-log-title">Live log</strong>
          <span class="apply-job-log-note">Raw command output</span>
          <span class="apply-job-log-path">{{ logTitle }}</span>
        </div>
        <n-button
          v-show="!active"
          class="apply-job-log-toggle"
          size="small"
          secondary
          :aria-expanded="liveLogExpanded"
          :title="liveLogToggleLabel"
          @click="emit('update:liveLogExpanded', !liveLogExpanded)"
        >
          <template #icon>
            <ChevronUp v-if="liveLogExpanded" :size="16" />
            <ChevronDown v-else :size="16" />
          </template>
          {{ liveLogExpanded ? "Hide output" : "Show output" }}
        </n-button>
      </div>
      <div v-show="liveLogVisible" class="apply-job-live-log-body">
        <n-alert
          v-if="log?.truncated"
          class="preflight-block"
          type="warning"
          :show-icon="false"
        >
          Showing the last {{ log.max_bytes }} bytes.
        </n-alert>
        <n-alert
          v-if="log?.error"
          class="preflight-block"
          type="warning"
          :show-icon="false"
        >
          Live log unavailable: {{ log.error }}
        </n-alert>
        <div v-if="logWaiting" class="empty-state">
          {{ logEmptyMessage }}
        </div>
        <pre
          v-else-if="!log?.error"
          ref="applyJobPanelLogRef"
          class="log-viewer apply-job-log-viewer"
        >{{ logText }}</pre>
      </div>
    </section>

    <n-alert
      v-if="job.error"
      class="plan-section"
      type="error"
    >
      {{ job.error }}
    </n-alert>
  </section>
</template>
