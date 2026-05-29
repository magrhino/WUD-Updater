<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { Check, ClipboardList, Play, X } from "@lucide/vue";
import { NInput, type DataTableColumns, type DataTableRowKey } from "naive-ui";

import {
  webApi,
  type ApplyJobResponse,
  type PendingItem,
  type PlanAction,
  type PlanIssue,
  type TagOverrideRequest,
} from "../api/client";
import { useAuthStore } from "../stores/auth";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const auth = useAuthStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const selectedLineNumbers = ref<number[]>([]);
const allowTagUpdates = ref(false);
const tagOverrides = ref<Record<number, string>>({});
const showApplyConfirm = ref(false);
const jobEventSource = ref<EventSource | null>(null);
const terminalJobStatuses = new Set(["success", "failure"]);
const tagValuePattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;

const columns = computed<DataTableColumns<PendingItem>>(() => [
  { type: "selection", width: 48 },
  { title: "Line", key: "line_no", width: 80 },
  { title: "Image", key: "image", minWidth: 240 },
  { title: "Repository", key: "repo", minWidth: 200 },
  {
    title: "Current tag",
    key: "current_tag",
    minWidth: 120,
    render: (row) => displayValue(row.current_tag),
  },
  {
    title: "New tag",
    key: "desired_tag",
    minWidth: 160,
    render: (row) => {
      if (!row.desired_tag) {
        return displayValue("");
      }
      return h(NInput, {
        value: tagOverrideValue(row),
        size: "small",
        class: "tag-override-input",
        placeholder: row.desired_tag,
        "aria-label": `New tag for ${row.image}`,
        onUpdateValue: (value: string) => updateTagOverride(row, value),
      });
    },
  },
  {
    title: "New digest",
    key: "digest",
    minWidth: 220,
    render: (row) =>
      row.digest
        ? h("code", { class: "digest-value", title: row.digest }, displayDigest(row.digest))
        : displayValue(""),
  },
]);

const allLineNumbers = computed(
  () => webui.pending?.items.map((item) => item.line_no) ?? [],
);
const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
const selectedTagOverrideError = computed(() => {
  for (const item of webui.pending?.items ?? []) {
    if (!selectedLineSet.value.has(item.line_no) || !item.desired_tag) {
      continue;
    }
    const tag = tagOverrideValue(item).trim();
    if (!tagValuePattern.test(tag)) {
      return `Line ${item.line_no} has an invalid new tag. Use a Docker tag value like ${item.desired_tag}.`;
    }
  }
  return "";
});
const requestTagOverrides = computed<TagOverrideRequest[]>(() =>
  (webui.pending?.items ?? [])
    .filter((item) => selectedLineSet.value.has(item.line_no) && item.desired_tag)
    .map((item) => ({
      line_no: item.line_no,
      tag: tagOverrideValue(item).trim(),
    }))
    .filter((item) => {
      const original = webui.pending?.items.find(
        (pendingItem) => pendingItem.line_no === item.line_no,
      );
      return original !== undefined && item.tag !== original.desired_tag;
    }),
);
const planningDisabled = computed(
  () =>
    selectedLineNumbers.value.length === 0 ||
    webui.loading ||
    Boolean(selectedTagOverrideError.value),
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
const applyAvailable = computed(
  () => webui.plan?.status === "ready" && webui.plan.can_apply,
);
const applyDisabled = computed(() => !applyAvailable.value || webui.loading);
const directUpdateDisabled = computed(
  () => planningDisabled.value || !auth.session?.mutations_enabled,
);
const directUpdateTitle = computed(() => {
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.";
  }
  if (selectedTagOverrideError.value) {
    return selectedTagOverrideError.value;
  }
  return "";
});
const readOnlySelectionMessage = computed(() => {
  if (selectedLineNumbers.value.length && !auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.";
  }
  return "";
});
const mutationDisabledMessage = computed(() => {
  if (!webui.plan || webui.plan.status !== "ready" || webui.plan.can_apply) {
    return "";
  }
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.";
  }
  return "This plan cannot be applied.";
});
const applyJobAlertType = computed(() => {
  if (webui.applyJob?.status === "failure") {
    return "error";
  }
  if (webui.applyJob?.status === "success") {
    return "success";
  }
  return "info";
});
const applyJobTitle = computed(() => {
  if (!webui.applyJob) {
    return "";
  }
  if (webui.applyJob.status === "success") {
    return "Apply complete";
  }
  if (webui.applyJob.status === "failure") {
    return "Apply failed";
  }
  return "Apply running";
});

function rowKey(row: PendingItem): number {
  return row.line_no;
}

function displayValue(value: string): string {
  return value || "None";
}

function displayDigest(value: string): string {
  if (!value || value.length <= 36) {
    return value;
  }
  return `${value.slice(0, 20)}...${value.slice(-12)}`;
}

function tagOverrideValue(item: PendingItem): string {
  return tagOverrides.value[item.line_no] ?? item.desired_tag;
}

function updateTagOverride(item: PendingItem, value: string): void {
  tagOverrides.value = {
    ...tagOverrides.value,
    [item.line_no]: value,
  };
  if (value.trim() !== item.desired_tag) {
    allowTagUpdates.value = true;
  }
  webui.clearPlan();
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
  await webui.createPlan(
    selectedLineNumbers.value,
    allowTagUpdates.value,
    requestTagOverrides.value,
  );
}

async function prepareDirectUpdate(): Promise<void> {
  if (directUpdateDisabled.value) {
    return;
  }
  await webui.createPlan(
    selectedLineNumbers.value,
    allowTagUpdates.value,
    requestTagOverrides.value,
  );
  if (webui.plan?.status === "ready" && webui.plan.can_apply) {
    showApplyConfirm.value = true;
  }
}

function clearPlanOnOptionChange(): void {
  webui.clearPlan();
}

function openApplyConfirm(): void {
  if (applyDisabled.value) {
    return;
  }
  showApplyConfirm.value = true;
}

async function confirmApply(): Promise<void> {
  if (!webui.plan || applyDisabled.value) {
    return;
  }
  const job = await webui.createJob(
    webui.plan.plan_id,
    webui.plan.selected_line_numbers,
    allowTagUpdates.value,
    requestTagOverrides.value,
  );
  subscribeApplyJob(job.job_id);
  showApplyConfirm.value = false;
}

function subscribeApplyJob(jobId: string): void {
  closeJobStream();
  const source = webApi.openJobStream(jobId);
  jobEventSource.value = source;
  source.addEventListener("job", (event) => {
    void handleJobEvent(event as MessageEvent<string>);
  });
  source.onerror = () => {
    if (webui.applyJob && terminalJobStatuses.has(webui.applyJob.status)) {
      closeJobStream();
      return;
    }
    void webui.loadApplyJob(jobId).catch(() => undefined);
  };
}

async function handleJobEvent(event: MessageEvent<string>): Promise<void> {
  let job: ApplyJobResponse;
  try {
    job = JSON.parse(event.data) as ApplyJobResponse;
  } catch {
    webui.setError("Job status stream returned invalid data.");
    closeJobStream();
    return;
  }
  webui.setApplyJob(job);
  if (!terminalJobStatuses.has(job.status)) {
    return;
  }
  closeJobStream();
  await Promise.all([webui.loadPending(), webui.loadRuns()]);
}

function closeJobStream(): void {
  jobEventSource.value?.close();
  jobEventSource.value = null;
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

watch(
  () => webui.pending?.items ?? [],
  (items) => {
    const next: Record<number, string> = {};
    for (const item of items) {
      if (item.desired_tag) {
        next[item.line_no] = tagOverrides.value[item.line_no] ?? item.desired_tag;
      }
    }
    tagOverrides.value = next;
  },
  { immediate: true },
);

onUnmounted(() => {
  closeJobStream();
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
        <p class="eyebrow value-eyebrow">
          {{ webui.pending?.source_file ?? "Pending file" }}
        </p>
        <h2>{{ webui.pending?.count ?? 0 }} pending updates</h2>
      </div>
      <div class="inline-actions pending-actions">
        <n-tag size="small">{{ selectedLineNumbers.length }} selected</n-tag>
        <n-button size="small" quaternary :disabled="!allLineNumbers.length" @click="selectAll">
          <template #icon>
            <Check :size="16" />
          </template>
          Select all
        </n-button>
        <n-button
          size="small"
          quaternary
          :disabled="!selectedLineNumbers.length"
          @click="clearSelection"
        >
          <template #icon>
            <X :size="16" />
          </template>
          Clear selection
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
          Preview plan
        </n-button>
        <n-button
          type="primary"
          size="small"
          secondary
          :disabled="directUpdateDisabled"
          :loading="webui.loading"
          :title="directUpdateTitle"
          @click="prepareDirectUpdate"
        >
          <template #icon>
            <Play :size="16" />
          </template>
          Update selected
        </n-button>
      </div>
    </div>

    <n-alert
      v-if="readOnlySelectionMessage"
      type="warning"
      :show-icon="false"
    >
      {{ readOnlySelectionMessage }}
    </n-alert>
    <n-alert
      v-if="selectedTagOverrideError"
      type="warning"
      :show-icon="false"
    >
      {{ selectedTagOverrideError }}
    </n-alert>

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
            <dt>Current tag</dt>
            <dd>{{ item.current_tag || "None" }}</dd>
          </div>
          <div>
            <dt>New tag</dt>
            <dd>
              <n-input
                v-if="item.desired_tag"
                :value="tagOverrideValue(item)"
                size="small"
                class="tag-override-input"
                :placeholder="item.desired_tag"
                :aria-label="`New tag for ${item.image}`"
                @update:value="updateTagOverride(item, $event)"
              />
              <span v-else>None</span>
            </dd>
          </div>
          <div>
            <dt>New digest</dt>
            <dd>
              <code v-if="item.digest" class="digest-value" :title="item.digest">
                {{ displayDigest(item.digest) }}
              </code>
              <span v-else>None</span>
            </dd>
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
        <div class="inline-actions pending-actions">
          <n-tag :type="planAlertType">{{ webui.plan.status }}</n-tag>
          <n-button
            v-if="applyAvailable"
            type="primary"
            size="small"
            :disabled="applyDisabled"
            :loading="webui.loading"
            @click="openApplyConfirm"
          >
            <template #icon>
              <Play :size="16" />
            </template>
            Apply plan
          </n-button>
        </div>
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

      <n-alert
        v-if="mutationDisabledMessage"
        class="plan-section"
        type="warning"
        :show-icon="false"
      >
        {{ mutationDisabledMessage }}
      </n-alert>

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
              <p class="eyebrow value-eyebrow">{{ stack.directory }}</p>
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

    <section v-if="webui.applyJob" class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Apply job</p>
          <h2>{{ applyJobTitle }}</h2>
        </div>
        <n-tag :type="applyJobAlertType">{{ webui.applyJob.status }}</n-tag>
      </div>

      <div class="compact-list">
        <div class="list-row">
          <span>Lines</span>
          <strong>{{ webui.applyJob.selected_line_numbers.join(", ") }}</strong>
          <em>{{ webui.applyJob.started_at || "Queued" }}</em>
        </div>
        <div v-if="webui.applyJob.run_id" class="list-row">
          <span>Run</span>
          <strong>#{{ webui.applyJob.run_id }}</strong>
          <em class="inline-actions">
            <RouterLink
              class="text-link"
              :to="{ name: 'run-detail', params: { id: webui.applyJob.run_id } }"
            >
              Details
            </RouterLink>
            <RouterLink
              class="text-link"
              :to="{ name: 'run-log', params: { id: webui.applyJob.run_id } }"
            >
              Log
            </RouterLink>
          </em>
        </div>
      </div>

      <n-alert
        v-if="webui.applyJob.error"
        class="plan-section"
        type="error"
        :show-icon="false"
      >
        {{ webui.applyJob.error }}
      </n-alert>
    </section>

    <n-modal
      v-model:show="showApplyConfirm"
      preset="dialog"
      title="Apply selected updates"
      positive-text="Apply updates"
      negative-text="Cancel"
      :positive-button-props="{ type: 'primary', loading: webui.loading }"
      @positive-click="confirmApply"
    >
      <div v-if="webui.plan" class="confirmation-list">
        <div>
          <span>Lines</span>
          <strong>{{ webui.plan.selected_line_numbers.join(", ") }}</strong>
        </div>
        <div v-for="stack in webui.plan.stacks" :key="stack.name">
          <span>{{ stack.name }}</span>
          <strong>{{ stack.services_label }}</strong>
        </div>
        <div v-for="override in requestTagOverrides" :key="override.line_no">
          <span>New tag #{{ override.line_no }}</span>
          <strong>{{ override.tag }}</strong>
        </div>
      </div>
    </n-modal>
  </section>
</template>
