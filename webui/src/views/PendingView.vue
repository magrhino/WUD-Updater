<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { Check, ClipboardList, X } from "@lucide/vue";
import type { DataTableColumns, DataTableRowKey } from "naive-ui";

import type { PendingItem, PlanAction, PlanIssue } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const selectedLineNumbers = ref<number[]>([]);
const allowTagUpdates = ref(false);

const columns = computed<DataTableColumns<PendingItem>>(() => [
  { type: "selection", width: 48 },
  { title: "Line", key: "line_no", width: 80 },
  { title: "Image", key: "image", minWidth: 240 },
  { title: "Repository", key: "repo", minWidth: 200 },
  { title: "Tag", key: "desired_tag", minWidth: 120 },
  { title: "Digest", key: "digest", minWidth: 220 },
]);

const allLineNumbers = computed(
  () => webui.pending?.items.map((item) => item.line_no) ?? [],
);
const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
const planningDisabled = computed(
  () => selectedLineNumbers.value.length === 0 || webui.loading,
);
const planAlertType = computed(() => {
  if (webui.plan?.status === "blocked") {
    return "error";
  }
  if (webui.plan?.status === "empty") {
    return "warning";
  }
  return "info";
});
const planTitle = computed(() => {
  if (!webui.plan) {
    return "";
  }
  if (webui.plan.status === "blocked") {
    return "Blocked dry run";
  }
  if (webui.plan.status === "empty") {
    return "No planned changes";
  }
  return "Ready dry run";
});

function rowKey(row: PendingItem): number {
  return row.line_no;
}

function updateCheckedRowKeys(keys: DataTableRowKey[]): void {
  selectedLineNumbers.value = keys
    .map((key) => Number(key))
    .filter((key) => Number.isFinite(key))
    .sort((left, right) => left - right);
  webui.clearPlan();
}

function toggleLine(lineNo: number, checked: boolean): void {
  const selected = new Set(selectedLineNumbers.value);
  if (checked) {
    selected.add(lineNo);
  } else {
    selected.delete(lineNo);
  }
  selectedLineNumbers.value = [...selected].sort((left, right) => left - right);
  webui.clearPlan();
}

function selectAll(): void {
  selectedLineNumbers.value = [...allLineNumbers.value];
  webui.clearPlan();
}

function clearSelection(): void {
  selectedLineNumbers.value = [];
  webui.clearPlan();
}

async function createPlan(): Promise<void> {
  if (planningDisabled.value) {
    return;
  }
  await webui.createPlan(selectedLineNumbers.value, allowTagUpdates.value);
}

function clearPlanOnOptionChange(): void {
  webui.clearPlan();
}

function actionCommand(action: PlanAction): string {
  return action.args.length ? action.args.join(" ") : action.description;
}

function issueType(issue: PlanIssue): "error" | "warning" | "info" {
  return issue.severity === "error" ? "error" : "warning";
}

function issueLabel(issue: PlanIssue): string {
  const target = [
    issue.line_no ? `line ${issue.line_no}` : "",
    issue.stack,
    issue.service,
  ]
    .filter(Boolean)
    .join(" / ");
  return target ? `${target}: ${issue.message}` : issue.message;
}

onMounted(() => {
  void webui.loadPending();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>
    <n-alert v-if="webui.pending && !webui.pending.exists" type="warning" :show-icon="false">
      {{ webui.pending.source_file }} is missing.
    </n-alert>

    <div class="section-heading pending-heading">
      <div>
        <p class="eyebrow">{{ webui.pending?.source_file ?? "Pending file" }}</p>
        <h2>{{ webui.pending?.count ?? 0 }} pending updates</h2>
      </div>
      <div class="inline-actions pending-actions">
        <n-tag size="small">{{ selectedLineNumbers.length }} selected</n-tag>
        <n-button size="small" quaternary :disabled="!allLineNumbers.length" @click="selectAll">
          <template #icon>
            <Check :size="16" />
          </template>
          All
        </n-button>
        <n-button size="small" quaternary :disabled="!selectedLineNumbers.length" @click="clearSelection">
          <template #icon>
            <X :size="16" />
          </template>
          Clear
        </n-button>
        <n-checkbox
          v-model:checked="allowTagUpdates"
          @update:checked="clearPlanOnOptionChange"
        >
          Tag updates
        </n-checkbox>
        <n-button
          type="primary"
          size="small"
          :disabled="planningDisabled"
          :loading="webui.loading"
          @click="createPlan"
        >
          <template #icon>
            <ClipboardList :size="16" />
          </template>
          Dry-run plan
        </n-button>
      </div>
    </div>

    <n-data-table
      v-if="!isMobile"
      :columns="columns"
      :data="webui.pending?.items ?? []"
      :loading="webui.loading"
      :pagination="{ pageSize: 15 }"
      :row-key="rowKey"
      :checked-row-keys="selectedLineNumbers"
      size="small"
      class="data-surface"
      @update:checked-row-keys="updateCheckedRowKeys"
    />

    <div v-else class="mobile-list">
      <article v-for="item in webui.pending?.items ?? []" :key="item.line_no" class="mobile-card">
        <div class="mobile-card-title">
          <n-checkbox
            :checked="selectedLineSet.has(item.line_no)"
            @update:checked="toggleLine(item.line_no, Boolean($event))"
          >
            <strong>{{ item.image }}</strong>
          </n-checkbox>
          <n-tag size="small">#{{ item.line_no }}</n-tag>
        </div>
        <dl>
          <div>
            <dt>Repository</dt>
            <dd>{{ item.repo }}</dd>
          </div>
          <div>
            <dt>Tag</dt>
            <dd>{{ item.desired_tag || "None" }}</dd>
          </div>
          <div>
            <dt>Digest</dt>
            <dd>{{ item.digest || "None" }}</dd>
          </div>
        </dl>
      </article>
      <div v-if="!webui.pending?.items.length" class="empty-state">No pending updates.</div>
    </div>

    <section v-if="webui.plan" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Dry run</p>
          <h2>{{ planTitle }}</h2>
        </div>
        <n-tag :type="planAlertType">{{ webui.plan.status }}</n-tag>
      </div>

      <div class="plan-summary">
        <div>
          <span>Targets</span>
          <strong>{{ webui.plan.summary.target_count }}</strong>
        </div>
        <div>
          <span>Matched</span>
          <strong>{{ webui.plan.summary.matched_target_count }}</strong>
        </div>
        <div>
          <span>Stacks</span>
          <strong>{{ webui.plan.summary.stack_count }}</strong>
        </div>
        <div>
          <span>Issues</span>
          <strong>{{ webui.plan.summary.issue_count }}</strong>
        </div>
      </div>

      <div v-if="webui.plan.issues.length" class="warning-list plan-section">
        <n-alert
          v-for="issue in webui.plan.issues"
          :key="`${issue.code}-${issue.line_no ?? ''}-${issue.stack}-${issue.service}`"
          :type="issueType(issue)"
          :show-icon="false"
        >
          {{ issueLabel(issue) }}
        </n-alert>
      </div>

      <div v-if="webui.plan.stacks.length" class="plan-section">
        <article v-for="stack in webui.plan.stacks" :key="stack.name" class="plan-stack">
          <div class="section-heading">
            <div>
              <p class="eyebrow">{{ stack.directory }}</p>
              <h2>{{ stack.name }}</h2>
            </div>
            <n-tag size="small">{{ stack.services_label }}</n-tag>
          </div>

          <div v-if="stack.lines.length" class="compact-list">
            <div
              v-for="line in stack.lines"
              :key="`${stack.name}-${line.line_no}-${line.service}`"
              class="list-row plan-line-row"
            >
              <span>#{{ line.line_no }}</span>
              <strong>{{ line.service || "stack-level" }}</strong>
              <em>{{ line.compose_image }} -> {{ line.target_image }}</em>
            </div>
          </div>

          <div class="plan-actions">
            <div
              v-for="action in stack.actions"
              :key="`${stack.name}-${action.kind}-${actionCommand(action)}`"
              class="plan-action"
            >
              <n-tag size="small">{{ action.kind }}</n-tag>
              <code>{{ actionCommand(action) }}</code>
            </div>
          </div>
        </article>
      </div>

      <div v-if="webui.plan.skipped.length" class="plan-section">
        <p class="eyebrow">Skipped</p>
        <div class="compact-list">
          <div v-for="item in webui.plan.skipped" :key="item.line_no" class="list-row">
            <span>#{{ item.line_no }}</span>
            <strong>{{ item.image }}</strong>
            <em>{{ item.reason }}</em>
          </div>
        </div>
      </div>
    </section>
  </section>
</template>
