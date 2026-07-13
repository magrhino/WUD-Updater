<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { AlertTriangle, CheckCircle2, Info, RefreshCw, Search } from "@lucide/vue";
import {
  NAlert,
  NButton,
  NInput,
  NSelect,
  NSwitch,
} from "naive-ui";

import type { RetagTargetChoice, RetagTargetItem } from "../api/client";
import { useRouteRefresh } from "../components/app/routeRefresh";
import PendingApplyJobPanel from "../components/pending/PendingApplyJobPanel.vue";
import RetagConfirmModal from "../components/retags/RetagConfirmModal.vue";
import RetagPlanReviewModal from "../components/retags/RetagPlanReviewModal.vue";
import RetagSummaryPanel from "../components/retags/RetagSummaryPanel.vue";
import RetagTargetsMobileList from "../components/retags/RetagTargetsMobileList.vue";
import RetagTargetsTable from "../components/retags/RetagTargetsTable.vue";
import { useDataCardsBreakpoint } from "../responsive";
import { useAuthStore } from "../stores/auth";
import { useUpdatesStore } from "../stores/updates";
import {
  canEnableRetagTargetChoice,
  retagChoice as selectedRetagChoice,
  retagTargetIdentity,
  retagTargetTagValidationError,
} from "../utils/retagChoices";
import {
  digestPinSummary,
  labelRewriteSummary,
  composeLocation,
  pluralize,
  retagPlanContextLabel,
  retagPlanSourceFile,
  searchableText,
} from "./retags/display";
import {
  usePendingApplyJob,
  type ApplyJobPlanSnapshot,
  type ApplyJobProgressPhase,
  type PendingApplyJobPanelRef,
} from "./pending/usePendingApplyJob";

type RetagFilter = "all" | "available" | "attention";
type RetagDuplicateServiceTarget = {
  key: string;
  label: string;
  location: string;
  image: string;
};
type RetagDuplicateServiceConflict = {
  serviceKey: string;
  targets: RetagDuplicateServiceTarget[];
};

const DUPLICATE_RETAG_CHOICES_PREFIXES = [
  "retag choices contain duplicate service(s):",
  "retag choices contain duplicate target(s):",
  "retag choices for duplicate service(s) must include target_id:",
];

const updates = useUpdatesStore();
const auth = useAuthStore();
const isMobile = useDataCardsBreakpoint();
const searchQuery = ref("");
const statusFilter = ref<RetagFilter>("all");
const applyJobPanelRef = ref<PendingApplyJobPanelRef | null>(null);
const showRetagApplyJobPanel = ref(false);
const showRetagConfirmModal = ref(false);
const showRetagPreviewModal = ref(false);
const isDemoMode =
  import.meta.env.MODE === "demo" ||
  import.meta.env.VITE_WUD_DEMO_MODE === "true";

const filterOptions = [
  { label: "All services", value: "all" },
  { label: "Retag available", value: "available" },
  { label: "Needs attention", value: "attention" },
];

const retagApplyJobProgressPhases: ApplyJobProgressPhase[] = [
  {
    key: "preflight",
    label: "Revalidate",
    waitingMessage: "Waiting to revalidate the selected retag plan.",
  },
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
const retagTargetTagError = computed(() => {
  for (const item of rows.value) {
    if (retagChoice(item) !== "switch-to-concrete") {
      continue;
    }
    const error = retagTargetTagValidationError(item, updates.retagTargetTags);
    if (error) {
      return error;
    }
  }
  return "";
});
const unavailable = computed(() => updates.retagTargets?.status === "unavailable");
const loaded = computed(() => updates.retagTargets !== null);
const mutationsEnabled = computed(() => auth.session?.mutations_enabled === true);
const retagMutationDisabled = computed(() => !mutationsEnabled.value);
const retagChoiceDisabled = computed(
  () => !isDemoMode && retagMutationDisabled.value,
);
const retagMutationNotice = computed(() => {
  if (isDemoMode) {
    return "Static demo mode is read-only. Preview stays available; apply is disabled.";
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
    Boolean(retagTargetTagError.value) ||
    rows.value.length === 0,
);
const applyDisabled = computed(
  () =>
    updates.loading ||
    applyJobActive.value ||
    retagMutationDisabled.value ||
    Boolean(retagTargetTagError.value) ||
    updates.retagPlan?.can_apply !== true,
);
const retagPlanStacks = computed(() => updates.retagPlan?.stacks ?? []);
const retagPlanUpdates = computed(() =>
  retagPlanStacks.value.flatMap((stack) =>
    stack.digest_pin_updates.map((update) => ({ stack, update })),
  ),
);
const retagPreviewError = computed(
  () => updates.retagPreviewError || updates.error,
);
const retagDuplicateServiceConflicts = computed<RetagDuplicateServiceConflict[]>(
  () => {
    const duplicateServiceKeys = duplicateServiceKeysFromError(
      retagPreviewError.value,
    );
    if (!duplicateServiceKeys.length) {
      return [];
    }

    const rowsByServiceKey = new Map<string, RetagTargetItem[]>();
    for (const item of rows.value) {
      rowsByServiceKey.set(item.service_key, [
        ...(rowsByServiceKey.get(item.service_key) ?? []),
        item,
      ]);
    }

    return duplicateServiceKeys.map((serviceKey) => ({
      serviceKey,
      targets: (rowsByServiceKey.get(serviceKey) ?? []).map((item, index) => {
        const location = composeLocation(item);
        return {
          key: `${item.service_key}-${index}-${location || item.image}`,
          label: `${item.stack} / ${item.service}`,
          location,
          image: item.image,
        };
      }),
    }));
  },
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
const eligibleRows = computed(() =>
  rows.value.filter((item) =>
    canEnableRetagTargetChoice(item, updates.retagTargetTags),
  ),
);
const filteredEligibleRows = computed(() =>
  filteredRows.value.filter((item) =>
    canEnableRetagTargetChoice(item, updates.retagTargetTags),
  ),
);
const bulkSelectionDisabled = computed(
  () =>
    updates.loading ||
    applyJobActive.value ||
    retagChoiceDisabled.value ||
    unavailable.value,
);
const retagAllDisabled = computed(
  () => bulkSelectionDisabled.value || eligibleRows.value.length === 0,
);
const retagFilteredDisabled = computed(
  () => bulkSelectionDisabled.value || filteredEligibleRows.value.length === 0,
);
const keepAllDisabled = computed(
  () => bulkSelectionDisabled.value || selectedSwitchCount.value === 0,
);

function retagChoice(item: RetagTargetItem): RetagTargetChoice {
  return selectedRetagChoice(
    item,
    updates.retagChoices,
    updates.retagTargetTags,
  );
}

function duplicateServiceKeysFromError(error: string): string[] {
  const match = DUPLICATE_RETAG_CHOICES_PREFIXES.map((prefix) => ({
    prefix,
    index: error.indexOf(prefix),
  })).find(({ index }) => index >= 0);
  if (!match) {
    return [];
  }
  return error
    .slice(match.index + match.prefix.length)
    .split(",")
    .map((serviceKey) => serviceKey.trim())
    .map((serviceKey) => serviceKey.replace(/\s+\([^)]+\)$/, ""))
    .filter(Boolean);
}

function onRetagChoiceUpdate(
  item: RetagTargetItem,
  choice: RetagTargetChoice,
): void {
  updates.setRetagChoice(retagTargetIdentity(item), choice);
}

function onRetagOnly(item: RetagTargetItem): void {
  updates.setRetagOnlyChoice(retagTargetIdentity(item));
}

function onRetagTargetTagUpdate(item: RetagTargetItem, tag: string): void {
  updates.setRetagTargetTag(retagTargetIdentity(item), tag);
}

function retagAllEligible(): void {
  if (retagAllDisabled.value) {
    return;
  }
  updates.setRetagChoicesForItems(rows.value, "switch-to-concrete");
}

function retagFilteredEligible(): void {
  if (retagFilteredDisabled.value) {
    return;
  }
  updates.setRetagChoicesForItems(filteredRows.value, "switch-to-concrete");
}

function keepAllRetags(): void {
  if (keepAllDisabled.value) {
    return;
  }
  updates.setRetagChoicesForItems(rows.value, "keep-current");
}

async function previewRetagChanges(): Promise<void> {
  if (previewDisabled.value) {
    return;
  }
  showRetagPreviewModal.value = true;
  await updates.createRetagPlan().catch(() => undefined);
}

async function onGithubLatestFallbackUpdate(enabled: boolean): Promise<void> {
  if (updates.loading || retagChoiceDisabled.value) {
    return;
  }
  await updates.setRetagGithubLatestFallback(enabled).catch(() => undefined);
}

async function refreshGithubLatestFallback(): Promise<void> {
  if (isDemoMode || updates.loading || retagMutationDisabled.value) {
    return;
  }
  await updates.refreshRetagGithubLatest().catch(() => undefined);
}

function openRetagApplyConfirm(): void {
  if (applyDisabled.value) {
    return;
  }
  showRetagConfirmModal.value = true;
}

function openRetagApplyConfirmFromPreview(): void {
  if (applyDisabled.value) {
    return;
  }
  showRetagPreviewModal.value = false;
  showRetagConfirmModal.value = true;
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
        key:
          update.target_id ||
          `${stack.directory}-${stack.compose_file}-${stack.project_directory}-${update.service_key}`,
        lineNo: null,
        stackName: stack.stack,
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

useRouteRefresh(() => updates.loadRetagTargets());

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

    <RetagConfirmModal
      v-model:show="showRetagConfirmModal"
      :plan="updates.retagPlan"
      :impact-label="retagConfirmImpactLabel"
      :mutation-notice="retagMutationNotice"
      :apply-disabled="applyDisabled"
      :loading="updates.loading"
      :apply-job-active="applyJobActive"
      @confirm="confirmRetagApply"
    />

    <RetagPlanReviewModal
      :show="showRetagPreviewModal"
      :plan="updates.retagPlan"
      :preview-job="updates.retagPreviewJob"
      :preview-error="retagPreviewError"
      :duplicate-service-conflicts="retagDuplicateServiceConflicts"
      :impact-label="retagConfirmImpactLabel"
      :mutation-notice="retagMutationNotice"
      :apply-disabled="applyDisabled"
      :loading="updates.loading"
      :apply-job-active="applyJobActive"
      @close="showRetagPreviewModal = false"
      @apply="openRetagApplyConfirmFromPreview"
    />

    <RetagSummaryPanel
      :total-count="totalCount"
      :available-count="availableCount"
      :attention-count="attentionCount"
      :selected-switch-count="selectedSwitchCount"
      :retag-all-eligible-count="eligibleRows.length"
      :retag-filtered-eligible-count="filteredEligibleRows.length"
      :preview-disabled="previewDisabled"
      :apply-disabled="applyDisabled"
      :retag-all-disabled="retagAllDisabled"
      :retag-filtered-disabled="retagFilteredDisabled"
      :keep-all-disabled="keepAllDisabled"
      :loading="updates.loading"
      :apply-job-active="applyJobActive"
      :has-retag-plan="updates.retagPlan !== null"
      :mutation-notice="retagMutationNotice"
      :validation-error="retagTargetTagError"
      @retag-all="retagAllEligible"
      @retag-filtered="retagFilteredEligible"
      @keep-all="keepAllRetags"
      @preview="previewRetagChanges"
      @apply="openRetagApplyConfirm"
    />

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
        <div class="retag-fallback-controls">
          <label class="retag-fallback-toggle" for="github-latest-fallback-switch">
            <n-switch
              id="github-latest-fallback-switch"
              :value="updates.retagGithubLatestFallback"
              :disabled="updates.loading || retagChoiceDisabled"
              aria-label="Use cached GitHub latest fallback"
              @update:value="onGithubLatestFallbackUpdate"
            />
            <span>Use cached GitHub latest fallback</span>
          </label>
          <n-button
            size="small"
            secondary
            :disabled="updates.loading || retagMutationDisabled"
            :title="
              retagMutationDisabled
                ? retagMutationNotice
                : 'Refresh GitHub latest candidates'
            "
            aria-label="Refresh GitHub latest candidates"
            @click="refreshGithubLatestFallback"
          >
            <template #icon>
              <RefreshCw :size="15" aria-hidden="true" />
            </template>
            Refresh
          </n-button>
        </div>
      </div>
    </section>

    <n-alert
      v-if="retagTargetTagError"
      type="warning"
      :show-icon="false"
    >
      {{ retagTargetTagError }}
    </n-alert>

    <output
      v-if="initialLoading"
      class="empty-state retag-state"
      aria-live="polite"
    >
      <Info :size="24" aria-hidden="true" />
      <strong>Loading retag targets</strong>
      <span>Reading discovered Compose services and stored digest provenance.</span>
    </output>

    <div
      v-else-if="initialLoadFailed"
      class="empty-state retag-state"
      role="alert"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Retag targets unavailable</strong>
      <span>The backend could not load retag review state.</span>
    </div>

    <output
      v-else-if="unavailable"
      class="empty-state retag-state"
      aria-live="polite"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Compose discovery unavailable</strong>
      <span>Resolve the warning above, then refresh this view.</span>
    </output>

    <template v-else-if="updates.retagTargets">
      <output
        v-if="!rows.length"
        class="empty-state retag-state"
        aria-live="polite"
      >
        <CheckCircle2 :size="24" aria-hidden="true" />
        <strong>No Compose services found</strong>
        <span>Retag review has no discovered services to show.</span>
      </output>

      <output
        v-else-if="!filteredRows.length"
        class="empty-state retag-state"
        aria-live="polite"
      >
        <Info :size="24" aria-hidden="true" />
        <strong>No matches</strong>
        <span>Adjust the search text or status filter.</span>
      </output>

      <RetagTargetsTable
        v-else-if="!isMobile"
        :rows="filteredRows"
        :loading="updates.loading"
        :choices="updates.retagChoices"
        :target-tags="updates.retagTargetTags"
        :mutation-disabled="retagChoiceDisabled"
        :mutation-notice="retagMutationNotice"
        @choice-update="onRetagChoiceUpdate"
        @retag-only="onRetagOnly"
        @target-tag-update="onRetagTargetTagUpdate"
      />

      <RetagTargetsMobileList
        v-else
        :rows="filteredRows"
        :choices="updates.retagChoices"
        :target-tags="updates.retagTargetTags"
        :mutation-disabled="retagChoiceDisabled"
        :mutation-notice="retagMutationNotice"
        @choice-update="onRetagChoiceUpdate"
        @retag-only="onRetagOnly"
        @target-tag-update="onRetagTargetTagUpdate"
      />
    </template>
  </section>
</template>

<style scoped>
.retag-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.retag-controls :deep(.n-input) {
  max-width: 520px;
}

.retag-fallback-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-muted-text);
  font-size: var(--text-body-size);
  white-space: nowrap;
}

.retag-fallback-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.retag-state svg {
  color: var(--color-operational-teal);
}

@media (--wud-data-cards) {
  .retag-controls {
    display: grid;
    justify-content: stretch;
  }

  .retag-fallback-toggle {
    min-width: 0;
    white-space: normal;
  }

  .retag-fallback-controls {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
</style>
