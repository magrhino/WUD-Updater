<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { AlertTriangle, CheckCircle2, Info, Search } from "@lucide/vue";
import {
  NAlert,
  NButton,
  NDataTable,
  NInput,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import type {
  RetagPlanResponse,
  RetagPlanDigestPinUpdate,
  RetagTargetChoice,
  RetagTargetItem,
} from "../api/client";
import PendingApplyJobPanel from "../components/pending/PendingApplyJobPanel.vue";
import { useAuthStore } from "../stores/auth";
import { useUpdatesStore } from "../stores/updates";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../utils/digestProvenance";
import {
  usePendingApplyJob,
  type ApplyJobPlanSnapshot,
  type ApplyJobProgressPhase,
  type PendingApplyJobPanelRef,
} from "./pending/usePendingApplyJob";

type RetagFilter = "all" | "available" | "attention";
type TagType = "default" | "success" | "warning" | "error" | "info";

const updates = useUpdatesStore();
const auth = useAuthStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const searchQuery = ref("");
const statusFilter = ref<RetagFilter>("all");
const applyJobPanelRef = ref<PendingApplyJobPanelRef | null>(null);
const showRetagApplyJobPanel = ref(false);
const showRetagConfirmModal = ref(false);
const isDemoMode =
  import.meta.env.MODE === "demo" ||
  import.meta.env.VITE_WUD_DEMO_MODE === "true";

const filterOptions = [
  { label: "All services", value: "all" },
  { label: "Retag available", value: "available" },
  { label: "Needs attention", value: "attention" },
];

const reasonLabels: Record<string, string> = {
  eligible: "Retag available",
  "missing-provenance": "Missing provenance",
  "not-latest-tracking": "Concrete tracking",
  "missing-concrete-tag": "Missing concrete tag",
  "missing-final-image": "Missing final image",
  "invalid-candidate-tag": "Invalid candidate tag",
  "stale-provenance": "Stale provenance",
  "unsupported-tracking-label": "Unsupported label",
};

const reasonDetails: Record<string, string> = {
  eligible: "A concrete tag and digest-pinned final image are available.",
  "missing-provenance": "No stored digest provenance is available for this service.",
  "not-latest-tracking": "This service already tracks a concrete tag.",
  "missing-concrete-tag": "Stored provenance does not include a concrete tag.",
  "missing-final-image": "Stored provenance is missing a digest or final image.",
  "invalid-candidate-tag": "The proposed tag is not a valid Docker tag value.",
  "stale-provenance": "Stored provenance does not match the current service image.",
  "unsupported-tracking-label": "The tracking label is not a single exact tag.",
};

const retagApplyJobProgressPhases: ApplyJobProgressPhase[] = [
  {
    key: "compose-digest-pin",
    label: "Write Compose",
    waitingMessage: "Waiting to write retag Compose metadata.",
  },
  {
    key: "pull",
    label: "Pull images",
    waitingMessage: "Waiting for retagged image pulls to begin.",
  },
  {
    key: "recreate",
    label: "Recreate",
    waitingMessage: "Waiting to recreate retagged services.",
  },
  {
    key: "health",
    label: "Health wait",
    waitingMessage: "Waiting for retagged service health checks.",
  },
  {
    key: "completion",
    label: "Complete",
    waitingMessage: "Waiting for the retag apply result.",
  },
];

const {
  applyJobActive,
  applyJobAlertType,
  applyJobImpactLabel,
  applyJobLatestLogMessage,
  applyJobLiveLogExpanded,
  applyJobLiveLogToggleLabel,
  applyJobLiveLogVisible,
  applyJobLogEmptyMessage,
  applyJobLogText,
  applyJobLogTitle,
  applyJobLogWaiting,
  applyJobNowDescriptionIds,
  applyJobNowDetail,
  applyJobNowMessage,
  applyJobNowStatusLabel,
  applyJobNowTitle,
  applyJobPanelStatusLabel,
  applyJobProgressSteps,
  applyJobProgressSummary,
  applyJobSnapshot,
  applyJobStartedLabel,
  applyJobStatusMessage,
  applyJobSucceeded,
  applyJobTitle,
  applyJobUpdateLabel,
  applyJobVerification,
  focusApplyJobPanel,
  subscribeApplyJob,
} = usePendingApplyJob({
  applyJobPanelRef,
  refreshAfterTerminalJob: async () => {
    await updates.loadRetagTargets();
  },
  progressPhases: retagApplyJobProgressPhases,
  updateNoun: "retag",
  completeNowTitle: "Retag complete",
  successStatusMessage: (updateLabel) =>
    `${updateLabel} finished. Retag targets and run history were refreshed.`,
});

const rows = computed(() => updates.retagTargets?.items ?? []);
const totalCount = computed(() => updates.retagTargets?.count ?? rows.value.length);
const availableCount = computed(
  () => rows.value.filter((item) => item.retag_available).length,
);
const attentionCount = computed(() => rows.value.length - availableCount.value);
const selectedSwitchCount = computed(
  () =>
    rows.value.filter(
      (item) => retagChoice(item) === "switch-to-concrete",
    ).length,
);
const unavailable = computed(() => updates.retagTargets?.status === "unavailable");
const loaded = computed(() => updates.retagTargets !== null);
const mutationsEnabled = computed(() => auth.session?.mutations_enabled === true);
const retagMutationDisabled = computed(() => !mutationsEnabled.value);
const retagMutationNotice = computed(() => {
  if (isDemoMode) {
    return "Demo mode previews retag apply without changing local Compose files.";
  }
  if (!mutationsEnabled.value) {
    return "Read-only mode keeps retag switch/apply disabled.";
  }
  return "";
});
const previewDisabled = computed(
  () =>
    updates.loading ||
    applyJobActive.value ||
    unavailable.value ||
    rows.value.length === 0,
);
const applyDisabled = computed(
  () =>
    updates.loading ||
    applyJobActive.value ||
    retagMutationDisabled.value ||
    updates.retagPlan?.can_apply !== true,
);
const retagPlanStacks = computed(() => updates.retagPlan?.stacks ?? []);
const retagPlanUpdates = computed(() =>
  retagPlanStacks.value.flatMap((stack) =>
    stack.digest_pin_updates.map((update) => ({ stack, update })),
  ),
);
const retagConfirmImpactLabel = computed(() => {
  const plan = updates.retagPlan;
  if (!plan) {
    return "";
  }
  const serviceCount = plan.selected_count || retagPlanUpdates.value.length;
  const stackCount = plan.stacks.length;
  if (stackCount > 1) {
    return `${pluralize(serviceCount, "service")} across ${pluralize(stackCount, "stack")}`;
  }
  return `${pluralize(serviceCount, "service")} in ${retagPlanContextLabel(plan)}`;
});
const initialLoading = computed(
  () => !loaded.value && !updates.error && updates.loading,
);
const initialLoadFailed = computed(
  () => !loaded.value && Boolean(updates.error) && !updates.loading,
);
const filteredRows = computed(() => {
  const query = searchQuery.value.trim().toLowerCase();
  return rows.value.filter((item) => {
    if (statusFilter.value === "available" && !item.retag_available) {
      return false;
    }
    if (statusFilter.value === "attention" && item.retag_available) {
      return false;
    }
    if (!query) {
      return true;
    }
    return searchableText(item).includes(query);
  });
});

const columns = computed<DataTableColumns<RetagTargetItem>>(() => [
  {
    title: "Service",
    key: "service_key",
    minWidth: 190,
    render: (row) =>
      h("div", { class: "retag-table-cell retag-service-cell" }, [
        h("strong", row.service_key),
        h("span", `${row.stack} / ${row.service}`),
      ]),
  },
  {
    title: "Current image",
    key: "image",
    minWidth: 230,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h("code", { class: "pending-table-value", title: row.image }, row.image),
        h("span", currentTagLabel(row)),
      ]),
  },
  {
    title: "Tracking",
    key: "tracking_tag",
    minWidth: 160,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h(
          NTag,
          { size: "small", type: trackingTagType(row), bordered: false },
          { default: () => trackingLabel(row) },
        ),
        h("span", trackingSourceLabel(row)),
      ]),
  },
  {
    title: "Candidate",
    key: "proposed_tag",
    minWidth: 220,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h(
          NTag,
          { size: "small", type: reasonTagType(row), bordered: false },
          { default: () => reasonLabel(row.retag_reason) },
        ),
        h("span", candidateLabel(row)),
        row.final_image
          ? h(
              "code",
              { class: "pending-table-value", title: row.final_image },
              displayDigest(row.final_image),
            )
          : null,
      ]),
  },
  {
    title: "Evidence",
    key: "digest_provenance",
    minWidth: 230,
    render: (row) => {
      const display = digestProvenanceDisplay(row.digest_provenance);
      return h("div", { class: "retag-table-cell" }, [
        display
          ? h("span", { title: display.title }, display.primary)
          : h("span", "None"),
        display?.digest
          ? h("code", { class: "pending-table-value" }, display.digest)
          : null,
      ]);
    },
  },
  {
    title: "Choice",
    key: "choices",
    minWidth: 230,
    render: (row) =>
      h("div", { class: "retag-choice-cell" }, [
        h(
          NRadioGroup,
          {
            value: retagChoice(row),
            size: "small",
            onUpdateValue: (value: string) => onRetagChoiceUpdate(row, value),
          },
          {
            default: () => [
              h(
                NRadioButton,
                { value: "keep-current" },
                { default: () => "Keep" },
              ),
              h(
                NRadioButton,
                {
                  value: "switch-to-concrete",
                  disabled:
                    !canSwitchToConcrete(row) || retagMutationDisabled.value,
                  title:
                    !canSwitchToConcrete(row)
                      ? reasonDetail(row.retag_reason)
                      : retagMutationNotice.value,
                },
                { default: () => "Switch" },
              ),
            ],
          },
        ),
        canSwitchToConcrete(row)
          ? h(
              NTag,
              { size: "small", type: "info", bordered: false },
              { default: () => "Candidate ready" },
            )
          : null,
      ]),
  },
]);

function rowKey(row: RetagTargetItem): string {
  return row.service_key;
}

function retagChoice(item: RetagTargetItem): RetagTargetChoice {
  return updates.retagChoices[item.service_key] ?? "keep-current";
}

function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

function onRetagChoiceUpdate(
  item: RetagTargetItem,
  choice: string,
): void {
  if (choice !== "keep-current" && choice !== "switch-to-concrete") {
    return;
  }
  updates.setRetagChoice(item.service_key, choice);
}

async function previewRetagChanges(): Promise<void> {
  await updates.createRetagPlan().catch(() => undefined);
}

function openRetagApplyConfirm(): void {
  if (applyDisabled.value) {
    return;
  }
  showRetagConfirmModal.value = true;
}

function closeRetagApplyConfirm(): void {
  showRetagConfirmModal.value = false;
}

function handleRetagConfirmShowUpdate(value: boolean): void {
  if (!value) {
    closeRetagApplyConfirm();
  }
}

async function confirmRetagApply(): Promise<void> {
  if (applyDisabled.value) {
    return;
  }
  const snapshot = createRetagApplyJobSnapshot();
  const job = await updates.applyRetagPlan().catch(() => undefined);
  if (!job) {
    return;
  }
  applyJobSnapshot.value = snapshot;
  showRetagApplyJobPanel.value = true;
  showRetagConfirmModal.value = false;
  subscribeApplyJob(job.job_id);
  await focusApplyJobPanel();
}

function createRetagApplyJobSnapshot(): ApplyJobPlanSnapshot | null {
  const plan = updates.retagPlan;
  if (!plan) {
    return null;
  }
  const lines = plan.stacks.flatMap((stack) =>
    stack.digest_pin_updates.map((update) => {
      const rewrite = labelRewriteSummary(update);
      return {
        key: update.service_key,
        lineNo: null,
        scopeLabel: stack.stack || "Retag",
        serviceLabel: update.service_key,
        tagRewriteLabel: "",
        digestPinLabel:
          rewrite === "No label rewrite"
            ? digestPinSummary(update)
            : `${digestPinSummary(update)}; ${rewrite}`,
        composeImage: update.source_image,
        targetImage: update.final_image,
      };
    }),
  );
  return {
    contextLabel: retagPlanContextLabel(plan),
    serviceCount: plan.selected_count || lines.length,
    stackCount: plan.stacks.length,
    sourceFile: retagPlanSourceFile(plan),
    lines,
  };
}

function reasonLabel(code: string): string {
  return reasonLabels[code] ?? "Unavailable reason";
}

function reasonDetail(code: string): string {
  return reasonDetails[code] ?? "The backend did not provide a recognized reason.";
}

function reasonTagType(item: RetagTargetItem): TagType {
  if (item.retag_available) {
    return "success";
  }
  if (item.retag_reason === "stale-provenance" || item.retag_reason === "invalid-candidate-tag") {
    return "warning";
  }
  return "default";
}

function trackingTagType(item: RetagTargetItem): TagType {
  return item.tracking_tag === "latest" ? "info" : "default";
}

function trackingLabel(item: RetagTargetItem): string {
  return item.tracking_tag || "Unknown";
}

function trackingSourceLabel(item: RetagTargetItem): string {
  return item.tracking_tag_source
    ? `Source: ${item.tracking_tag_source}`
    : "Source unavailable";
}

function currentTagLabel(item: RetagTargetItem): string {
  return item.current_tag ? `Current tag: ${item.current_tag}` : "Current tag unavailable";
}

function candidateLabel(item: RetagTargetItem): string {
  if (item.retag_available) {
    return `latest -> ${item.proposed_tag}`;
  }
  return reasonDetail(item.retag_reason);
}

function composeLocation(item: RetagTargetItem): string {
  return [item.directory, item.compose_file].filter(Boolean).join("/");
}

function searchableText(item: RetagTargetItem): string {
  return [
    item.service_key,
    item.stack,
    item.service,
    item.image,
    item.image_repo,
    item.current_tag,
    item.tracking_tag,
    item.proposed_tag,
    item.final_image,
    item.retag_reason,
    reasonLabel(item.retag_reason),
    reasonDetail(item.retag_reason),
  ]
    .join(" ")
    .toLowerCase();
}

function planStatusType(): TagType {
  if (updates.retagPlan?.status === "ready") {
    return "success";
  }
  if (updates.retagPlan?.status === "blocked") {
    return "error";
  }
  if (updates.retagPlan?.status === "unavailable") {
    return "warning";
  }
  return "default";
}

function planLocation(stack: { directory: string; compose_file: string }): string {
  return [stack.directory, stack.compose_file].filter(Boolean).join("/");
}

function retagPlanContextLabel(plan: RetagPlanResponse): string {
  if (plan.stacks.length === 1) {
    return plan.stacks[0].stack || "retag plan";
  }
  if (plan.stacks.length > 1) {
    return `${plan.stacks.length} stacks`;
  }
  return "retag plan";
}

function retagPlanSourceFile(plan: RetagPlanResponse): string {
  const locations = plan.stacks.map(planLocation).filter(Boolean);
  if (locations.length === 1) {
    return locations[0];
  }
  if (locations.length > 1) {
    return `${locations.length} Compose files`;
  }
  return "Retag plan";
}

function digestPinSummary(update: RetagPlanDigestPinUpdate): string {
  return `${update.source_image} -> ${update.final_image}`;
}

function labelRewriteSummary(update: RetagPlanDigestPinUpdate): string {
  if (!update.label_rewrites.length) {
    return "No label rewrite";
  }
  return update.label_rewrites
    .map(
      (rewrite) =>
        `${rewrite.label_key}: ${rewrite.current_label_value} -> ${rewrite.proposed_label_value}`,
    )
    .join("; ");
}

function pluralize(count: number, noun: string, plural = `${noun}s`): string {
  return `${count} ${count === 1 ? noun : plural}`;
}

onMounted(() => {
  updates.loadRetagTargets().catch(() => undefined);
});
</script>

<template>
  <section class="content-stack retag-review">
    <n-alert v-if="updates.error" type="error" :show-icon="false">
      {{ updates.error }}
    </n-alert>

    <n-alert
      v-for="warning in updates.retagTargets?.warnings ?? []"
      :key="warning"
      type="warning"
      :show-icon="false"
    >
      {{ warning }}
    </n-alert>

    <PendingApplyJobPanel
      v-if="showRetagApplyJobPanel && updates.applyJob"
      ref="applyJobPanelRef"
      v-model:live-log-expanded="applyJobLiveLogExpanded"
      :active="applyJobActive"
      :alert-type="applyJobAlertType"
      :impact-label="applyJobImpactLabel"
      :job="updates.applyJob"
      :latest-log-message="applyJobLatestLogMessage"
      :live-log-toggle-label="applyJobLiveLogToggleLabel"
      :live-log-visible="applyJobLiveLogVisible"
      :log="updates.applyJobLog"
      :log-empty-message="applyJobLogEmptyMessage"
      :log-text="applyJobLogText"
      :log-title="applyJobLogTitle"
      :log-waiting="applyJobLogWaiting"
      :now-description-ids="applyJobNowDescriptionIds"
      :now-detail="applyJobNowDetail"
      :now-message="applyJobNowMessage"
      :now-status-label="applyJobNowStatusLabel"
      :now-title="applyJobNowTitle"
      :panel-status-label="applyJobPanelStatusLabel"
      :progress-steps="applyJobProgressSteps"
      :progress-summary="applyJobProgressSummary"
      :snapshot="applyJobSnapshot"
      :started-label="applyJobStartedLabel"
      :status-message="applyJobStatusMessage"
      :succeeded="applyJobSucceeded"
      :title="applyJobTitle"
      :update-label="applyJobUpdateLabel"
      :verification="applyJobVerification"
    />

    <n-modal
      :show="showRetagConfirmModal"
      :mask-closable="false"
      @update:show="handleRetagConfirmShowUpdate"
    >
      <section
        class="preflight-modal retag-confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="retag-confirm-title"
      >
        <div class="section-heading">
          <div>
            <p class="eyebrow">Confirm retag apply</p>
            <h2 id="retag-confirm-title">Apply selected retags</h2>
            <p class="preflight-summary-text">
              Review the selected Compose metadata changes before starting the retag apply job.
            </p>
            <p v-if="retagConfirmImpactLabel" class="preflight-impact-text">
              {{ retagConfirmImpactLabel }}
            </p>
          </div>
          <n-tag v-if="updates.retagPlan" :type="planStatusType()">
            {{ updates.retagPlan.status }}
          </n-tag>
        </div>

        <n-alert
          v-if="retagMutationNotice"
          type="warning"
          :show-icon="false"
        >
          {{ retagMutationNotice }}
        </n-alert>

        <div
          v-if="updates.retagPlan"
          class="preflight-metrics retag-confirm-metrics"
          aria-label="Retag apply summary"
        >
          <div>
            <span>Services</span>
            <strong>{{ updates.retagPlan.selected_count }}</strong>
          </div>
          <div>
            <span>Stacks</span>
            <strong>{{ updates.retagPlan.stacks.length }}</strong>
          </div>
          <div>
            <span>Keep current</span>
            <strong>{{ updates.retagPlan.keep_current_count }}</strong>
          </div>
          <div>
            <span>Source</span>
            <strong>{{ retagPlanSourceFile(updates.retagPlan) }}</strong>
          </div>
        </div>

        <section
          class="preflight-impact preflight-block"
          aria-labelledby="retag-confirm-services-title"
        >
          <div class="preflight-impact-heading">
            <strong id="retag-confirm-services-title">Services and images</strong>
            <n-tag size="small">{{ pluralize(retagPlanUpdates.length, "service") }}</n-tag>
          </div>
          <div v-if="retagPlanUpdates.length" class="compact-list">
            <div
              v-for="{ stack, update } in retagPlanUpdates"
              :key="`confirm-${update.service_key}`"
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

        <div class="preflight-footer">
          <n-button size="small" quaternary @click="closeRetagApplyConfirm">
            Cancel
          </n-button>
          <n-button
            type="primary"
            size="small"
            :disabled="applyDisabled"
            :loading="updates.loading || applyJobActive"
            @click="confirmRetagApply"
          >
            Confirm and apply
          </n-button>
        </div>
      </section>
    </n-modal>

    <section class="section-panel retag-summary-panel">
      <div class="section-heading retag-heading">
        <div>
          <p class="eyebrow">Retag review</p>
          <h2>Compose service tracking</h2>
        </div>
        <div class="retag-preview-action">
          <n-button
            type="primary"
            size="small"
            :disabled="previewDisabled"
            :loading="updates.loading"
            @click="previewRetagChanges"
          >
            Preview retag changes
          </n-button>
          <n-button
            v-if="updates.retagPlan"
            size="small"
            :disabled="applyDisabled"
            :loading="updates.loading || applyJobActive"
            @click="openRetagApplyConfirm"
          >
            Apply selected retags
          </n-button>
          <span v-if="retagMutationNotice">{{ retagMutationNotice }}</span>
        </div>
      </div>

      <div class="retag-summary-strip" aria-label="Retag review summary">
        <div>
          <span>Total services</span>
          <strong>{{ totalCount }}</strong>
        </div>
        <div>
          <span>Retag candidates</span>
          <strong>{{ availableCount }}</strong>
        </div>
        <div>
          <span>Needs attention</span>
          <strong>{{ attentionCount }}</strong>
        </div>
        <div>
          <span>Selected switches</span>
          <strong>{{ selectedSwitchCount }}</strong>
        </div>
      </div>
    </section>

    <section
      v-if="updates.retagPlan"
      class="section-panel retag-plan-panel"
      aria-label="Retag plan preview"
    >
      <div class="section-heading retag-plan-heading">
        <div>
          <p class="eyebrow">Preview</p>
          <h2>Selected retag changes</h2>
        </div>
        <div class="retag-plan-tags">
          <n-tag size="small" :type="planStatusType()" :bordered="false">
            {{ updates.retagPlan.status }}
          </n-tag>
          <n-tag size="small" :bordered="false">
            {{ updates.retagPlan.selected_count }} selected
          </n-tag>
          <n-tag size="small" :bordered="false">
            {{ updates.retagPlan.keep_current_count }} keep current
          </n-tag>
        </div>
      </div>

      <n-alert
        v-for="warning in updates.retagPlan.warnings"
        :key="warning"
        type="warning"
        :show-icon="false"
      >
        {{ warning }}
      </n-alert>

      <n-alert
        v-for="issue in updates.retagPlan.issues"
        :key="`${issue.code}-${issue.service_key}-${issue.message}`"
        :type="issue.severity === 'error' ? 'error' : 'warning'"
        :show-icon="false"
      >
        {{ issue.message }}
      </n-alert>

      <div v-if="updates.retagPlan.stacks.length" class="retag-plan-stacks">
        <div
          v-for="stack in updates.retagPlan.stacks"
          :key="`${stack.stack}-${stack.compose_file}`"
          class="retag-plan-stack"
        >
          <div class="retag-plan-stack-heading">
            <strong>{{ stack.stack }}</strong>
            <code>{{ planLocation(stack) }}</code>
          </div>
          <ul class="retag-plan-update-list">
            <li
              v-for="update in stack.digest_pin_updates"
              :key="update.service_key"
            >
              <div>
                <strong>{{ update.service_key }}</strong>
                <span>{{ update.service }}</span>
              </div>
              <code>{{ digestPinSummary(update) }}</code>
              <span>{{ labelRewriteSummary(update) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <div
        v-else
        class="empty-state retag-state retag-plan-empty"
        role="status"
        aria-live="polite"
      >
        <Info :size="20" aria-hidden="true" />
        <strong>No retag changes selected</strong>
        <span>Current tracking remains unchanged for every service.</span>
      </div>
    </section>

    <section class="section-panel retag-controls-panel">
      <div class="retag-controls">
        <n-input
          v-model:value="searchQuery"
          clearable
          placeholder="Search services, images, tags, or reasons"
          :input-props="{ 'aria-label': 'Search retag targets' }"
        >
          <template #prefix>
            <Search :size="16" aria-hidden="true" />
          </template>
        </n-input>
        <n-select
          v-model:value="statusFilter"
          class="filter-control"
          :options="filterOptions"
          aria-label="Retag status filter"
        />
      </div>
    </section>

    <div
      v-if="initialLoading"
      class="empty-state retag-state"
      role="status"
      aria-live="polite"
    >
      <Info :size="24" aria-hidden="true" />
      <strong>Loading retag targets</strong>
      <span>Reading discovered Compose services and stored digest provenance.</span>
    </div>

    <div
      v-else-if="initialLoadFailed"
      class="empty-state retag-state"
      role="alert"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Retag targets unavailable</strong>
      <span>The backend could not load retag review state.</span>
    </div>

    <div
      v-else-if="unavailable"
      class="empty-state retag-state"
      role="status"
      aria-live="polite"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Compose discovery unavailable</strong>
      <span>Resolve the warning above, then refresh this view.</span>
    </div>

    <template v-else-if="updates.retagTargets">
      <div
        v-if="!rows.length"
        class="empty-state retag-state"
        role="status"
        aria-live="polite"
      >
        <CheckCircle2 :size="24" aria-hidden="true" />
        <strong>No Compose services found</strong>
        <span>Retag review has no discovered services to show.</span>
      </div>

      <div
        v-else-if="!filteredRows.length"
        class="empty-state retag-state"
        role="status"
        aria-live="polite"
      >
        <Info :size="24" aria-hidden="true" />
        <strong>No matches</strong>
        <span>Adjust the search text or status filter.</span>
      </div>

      <n-data-table
        v-else-if="!isMobile"
        :columns="columns"
        :data="filteredRows"
        :loading="updates.loading"
        :pagination="{ pageSize: 15 }"
        :row-key="rowKey"
        size="small"
        class="data-surface"
      />

      <div v-else class="mobile-list">
        <article
          v-for="item in filteredRows"
          :key="item.service_key"
          class="mobile-card retag-card"
        >
          <div class="mobile-card-title">
            <div class="retag-card-title">
              <strong>{{ item.service_key }}</strong>
              <span>{{ item.stack }} / {{ item.service }}</span>
            </div>
            <n-tag
              size="small"
              :type="reasonTagType(item)"
              :bordered="false"
            >
              {{ reasonLabel(item.retag_reason) }}
            </n-tag>
          </div>
          <dl>
            <div>
              <dt>Image</dt>
              <dd>
                <code>{{ item.image }}</code>
              </dd>
            </div>
            <div>
              <dt>Tracking</dt>
              <dd>{{ trackingLabel(item) }} ({{ item.tracking_tag_source || "unknown" }})</dd>
            </div>
            <div>
              <dt>Candidate</dt>
              <dd>{{ candidateLabel(item) }}</dd>
            </div>
            <div>
              <dt>Final image</dt>
              <dd>
                <code>{{ item.final_image ? displayDigest(item.final_image) : "None" }}</code>
              </dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>
                <code>{{ composeLocation(item) }}</code>
              </dd>
            </div>
            <div>
              <dt>Choice</dt>
              <dd>
                <n-radio-group
                  :value="retagChoice(item)"
                  size="small"
                  @update:value="onRetagChoiceUpdate(item, String($event))"
                >
                  <n-radio-button value="keep-current">Keep</n-radio-button>
                  <n-radio-button
                    value="switch-to-concrete"
                    :disabled="!canSwitchToConcrete(item) || retagMutationDisabled"
                    :title="
                      !canSwitchToConcrete(item)
                        ? reasonDetail(item.retag_reason)
                        : retagMutationNotice
                    "
                  >
                    Switch
                  </n-radio-button>
                </n-radio-group>
              </dd>
            </div>
          </dl>
        </article>
      </div>
    </template>
  </section>
</template>
