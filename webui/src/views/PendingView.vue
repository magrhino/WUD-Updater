<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NFlex,
  NSkeleton,
  NTag,
} from "naive-ui";

import type { ReleaseNoteInfo } from "../api/client";
import CoreUpdateTourPanel from "../components/CoreUpdateTourPanel.vue";
import { useRouteRefresh } from "../components/app/routeRefresh";
import PendingApplyJobPanel from "../components/pending/PendingApplyJobPanel.vue";
import PendingCleanupModal from "../components/pending/PendingCleanupModal.vue";
import PendingFallbackQueue from "../components/pending/PendingFallbackQueue.vue";
import PendingPlanReviewModal from "../components/pending/PendingPlanReviewModal.vue";
import PendingRemovalModal from "../components/pending/PendingRemovalModal.vue";
import PendingSearchEmptyState from "../components/pending/PendingSearchEmptyState.vue";
import PendingSearchPanel from "../components/pending/PendingSearchPanel.vue";
import PendingSelectionToolbar from "../components/pending/PendingSelectionToolbar.vue";
import PendingStackSelection from "../components/pending/PendingStackSelection.vue";
import { useDataCardsBreakpoint } from "../responsive";
import { useRunsStore } from "../stores/runs";
import { useSettingsStore } from "../stores/settings";
import { useUpdatesStore } from "../stores/updates";
import { displayDigest } from "../utils/digestProvenance";
import { runInBackground } from "../utils/promises";
import {
  displayValue,
  releaseNoteReason,
  releaseNoteStatus as pendingReleaseNoteStatus,
  tagInputProps,
} from "./pending/pendingDisplay";
import { createPendingColumns } from "./pending/tableColumns";
import { pluralize } from "./pending/utils";
import {
  usePendingApplyJob,
  type PendingApplyJobPanelRef,
} from "./pending/usePendingApplyJob";
import { usePendingPlanActions } from "./pending/usePendingPlanActions";
import { usePendingPlanReviewState } from "./pending/usePendingPlanReviewState";
import { usePendingQueueState } from "./pending/usePendingQueueState";
import { usePendingSearchResultState } from "./pending/usePendingSearchResultState";
import { usePendingSearchState } from "./pending/usePendingSearchState";
import { usePendingSelectionState } from "./pending/usePendingSelectionState";

const updates = useUpdatesStore();
const runs = useRunsStore();
const settings = useSettingsStore();
const isMobile = useDataCardsBreakpoint();
const applyJobPanelRef = ref<PendingApplyJobPanelRef | null>(null);

const pendingItems = computed(() => updates.pending?.items ?? []);
const {
  groupingReady,
  latestRun,
  pendingHeadingText,
  pendingLoaded,
  pendingLoadFailed,
  pendingLoading,
  pendingSourceDegraded,
  pendingSourceDisplay,
  pendingSourceFile,
  pendingSourceLabel,
  pendingSourceWarning,
  releaseChangelogFor,
  releaseNoteFor,
  riskCues,
  selectableLineNumbers,
  selectAllLabel,
  snoozedItems,
  stackGroups,
  unmatchedItems,
} = usePendingQueueState();
const {
  clearPendingSearch,
  filteredPendingItems,
  filteredSnoozedItems,
  filteredStackGroups,
  filteredUnmatchedItems,
  pendingSearchActive,
  pendingSearchEmpty,
  pendingSearchQuery,
  pendingSearchResultLabel,
  visibleLineNumbers,
  visibleSelectableLineNumbers,
  visibleSelectAllLabel,
} = usePendingSearchState({
  pendingItems,
  groupingReady,
  snoozedItems,
  selectableLineNumbers,
  selectAllLabel,
  stackGroups,
  unmatchedItems,
  releaseChangelogFor,
  releaseNoteFor,
  releaseNoteReason,
  releaseNoteStatus,
  riskCues,
});

let clearPreflightHandler: () => void = () => undefined;
let loadPendingAndReleaseNotesHandler: () => Promise<void> = async () => undefined;

const {
  clearSelection,
  lineNumbersHaveTagUpdates,
  selectAllVisible,
  selectedLineNumbers,
  selectedLineSet,
  stackHasSelection,
  stackIndeterminate,
  stackSelected,
  tagOverrideErrorForLines,
  tagOverrideValue,
  tagOverridesForLines,
  toggleLine,
  toggleStack,
  updateCheckedRowKeys,
  updateDisabled,
  updateTagOverride,
} = usePendingSelectionState({
  pendingItems,
  selectableLineNumbers: visibleSelectableLineNumbers,
  onSelectionChanged: () => clearPreflightHandler(),
});

const columns = computed(() =>
  createPendingColumns({
    displayDigest,
    displayValue,
    releaseNoteFor,
    releaseNoteReason,
    releaseNoteStatus,
    riskCues,
    tagInputProps,
    tagOverrideValue,
    updateTagOverride,
  }),
);
const latestRunId = computed(() => latestRun.value?.id ?? null);
const showSetupLink = computed(
  () => settings.coreUpdateTour?.status === "in_progress",
);
const selectedHasTagUpdates = computed(() =>
  lineNumbersHaveTagUpdates(selectedLineNumbers.value),
);

const {
  actionCommand,
  applyButtonLabel,
  applyDisabled,
  applyPreflight,
  applyPreflightAttentionChecks,
  applyPreflightCheckDetail,
  applyPreflightCheckLabel,
  applyPreflightCheckType,
  applyPreflightPassedChecks,
  applyPreflightPassedText,
  applyPlanPayload,
  applyReadinessStatusLabel,
  applyReadinessStatusType,
  applyReadinessSummary,
  applyVisible,
  batchSummaryLabel,
  cleanupAssistantActions,
  cleanupAssistantFindings,
  cleanupAssistantReasons,
  cleanupAvailable,
  cleanupButtonLabel,
  cleanupDisabled,
  cleanupDisabledMessage,
  cleanupItems,
  cleanupLineLabel,
  cleanupReviewSummary,
  approveDigestPinLabelRewrite,
  clearUpdateIntent,
  digestPinLabelApprovalApproved,
  digestPinLabelApprovalIssues,
  digestPinLabelIssueProposedRegex,
  issueDetailString,
  issueHint,
  issueLabel,
  issueType,
  mutationDisabledMessage,
  mutationStateLabel,
  mutationStateType,
  pendingApplyTourDetail,
  pendingCleanupMessage,
  planActions,
  planAlertType,
  planDigestPinLabelRewrites,
  planDigestUnpinUpdates,
  planLines,
  preflightDigestPinNotice,
  preflightDigestUnpinNotice,
  preflightServiceImpactLabel,
  preflightSummary,
  preflightTagRewriteNotice,
  preflightTitle,
  removalButtonLabel,
  removalConfirmButtonLabel,
  removalDisabled,
  removalItems,
  removalLineLabel,
  removeSelectedDisabled,
  removeSelectedDisabledMessage,
  selectedTagOverrideError,
  selectedUpdateContext,
  setUpdateIntent,
  staleDiagnosticDetail,
  staleDiagnosticLabel,
  unmatchedIssueSummary,
  unmatchedReviewCountLabel,
  unmatchedReviewSummary,
  updateSelectedDisabled,
  visiblePlanIssues,
} = usePendingPlanReviewState({
  pendingSourceLabel,
  selectedLineNumbers,
  selectedLineSet,
  stackGroups,
  tagOverrideErrorForLines,
  unmatchedItems,
});
const {
  selectedHiddenCount,
  visibleUnmatchedIssueSummary,
  visibleUnmatchedReviewCountLabel,
  visibleUnmatchedReviewSummary,
} = usePendingSearchResultState({
  pendingSearchActive,
  visibleLineNumbers,
  selectedLineNumbers,
  filteredUnmatchedItems,
  unmatchedItems,
  unmatchedIssueSummary,
  unmatchedReviewCountLabel,
  unmatchedReviewSummary,
});

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
  createApplyJobSnapshot,
  focusApplyJobPanel,
  reconnectObservedApplyJob,
  subscribeApplyJob,
} = usePendingApplyJob({
  applyJobPanelRef,
  loadPendingAndReleaseNotes: () => loadPendingAndReleaseNotesHandler(),
});

const {
  clearPreflight,
  closeCleanupModal,
  closePreflightModal,
  closeRemovalModal,
  confirmApply,
  confirmCleanup,
  confirmSelectedRemoval,
  loadPendingAndReleaseNotes,
  openCleanupModal,
  retryPendingLoad,
  showCleanupModal,
  showPreflightModal,
  showRemovalModal,
  startSelectedRemoval,
  startSelectedUpdate,
  startStackUpdate,
} = usePendingPlanActions({
  applyDisabled,
  applyJobSnapshot,
  applyPlanPayload,
  cleanupAvailable,
  cleanupDisabled,
  clearUpdateIntent,
  createApplyJobSnapshot,
  focusApplyJobPanel,
  lineNumbersHaveTagUpdates,
  removalDisabled,
  removeSelectedDisabled,
  selectedLineNumbers,
  selectedUpdateContext,
  setUpdateIntent,
  subscribeApplyJob,
  tagOverrideErrorForLines,
  tagOverridesForLines,
});

clearPreflightHandler = clearPreflight;
loadPendingAndReleaseNotesHandler = () => loadPendingAndReleaseNotes();
useRouteRefresh(() => updates.loadPending());

function releaseNoteStatus(note: ReleaseNoteInfo | null): string {
  return pendingReleaseNoteStatus(note, updates.releaseNotesLoading);
}

onMounted(() => {
  runInBackground(retryPendingLoad());
  runInBackground(settings.loadPendingSafetyCues());
  runInBackground(reconnectObservedApplyJob());
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="(updates.error || runs.error)" type="error">
      {{ (updates.error || runs.error) }}
    </n-alert>
    <n-alert v-if="settings.pendingSafetyCueError" type="warning">
      Pending safety cues are unavailable: {{ settings.pendingSafetyCueError }}
    </n-alert>
    <n-alert v-if="updates.pending && !updates.pending.exists" type="warning">
      {{ updates.pending.source_file }} is missing.
    </n-alert>
    <n-alert v-if="updates.releaseNotesError" type="warning">
      Release-note metadata is unavailable: {{ updates.releaseNotesError }}
    </n-alert>
    <n-alert v-if="pendingCleanupMessage" type="success">
      {{ pendingCleanupMessage }}
      <n-flex inline class="inline-actions recovery-actions" align="center" :size="8">
        <RouterLink
          class="text-link"
          :to="{ name: 'run-detail', params: { id: updates.pendingCleanup?.audit_run_id } }"
        >
          Details
        </RouterLink>
      </n-flex>
    </n-alert>
    <n-alert
      v-if="updates.applyJobRecovery"
      type="warning"
    >
      {{ updates.applyJobRecovery }}
      <n-flex inline class="inline-actions recovery-actions" align="center" :size="8">
        <RouterLink class="text-link" to="/runs">Runs</RouterLink>
        <RouterLink
          v-if="latestRun"
          class="text-link"
          :to="{ name: 'run-detail', params: { id: latestRun.id } }"
        >
          Latest run
        </RouterLink>
        <RouterLink
          v-if="latestRun"
          class="text-link"
          :to="{ name: 'run-log', params: { id: latestRun.id } }"
        >
          Log
        </RouterLink>
      </n-flex>
    </n-alert>

    <PendingApplyJobPanel
      v-if="updates.applyJob"
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

    <div class="section-heading pending-heading">
      <div>
        <p class="eyebrow value-eyebrow pending-source" :title="pendingSourceFile">
          {{ pendingSourceDisplay }}
        </p>
        <h2>{{ pendingHeadingText }}</h2>
      </div>
      <n-tag size="small" :type="mutationStateType">{{ mutationStateLabel }}</n-tag>
    </div>

    <n-alert
      v-if="pendingSourceDegraded && pendingSourceWarning"
      type="warning"
      role="status"
    >
      {{ pendingSourceWarning }}
    </n-alert>

    <CoreUpdateTourPanel
      step="pending_select"
      title="Select the update scope"
      detail="Choose one stack or selected lines before previewing. Stack groups are the safest default because they keep related services together."
      next-label="Show preflight guidance"
      next-step="pending_preflight"
    >
      <div class="core-tour-facts">
        <span v-if="pendingLoaded">
          {{
            pendingSearchActive
              ? `${pluralize(filteredStackGroups.length, "stack")} matched`
              : pluralize(filteredStackGroups.length, "stack")
          }}
        </span>
        <span v-else>Loading stack matches</span>
        <span v-if="pendingLoaded">{{ visibleUnmatchedReviewCountLabel }}</span>
        <span v-else>Waiting for pending file</span>
        <span>{{ mutationStateLabel }}</span>
      </div>
    </CoreUpdateTourPanel>

    <CoreUpdateTourPanel
      step="pending_preflight"
      title="Preview before anything changes"
      detail="Open a preview to see affected services, image targets, tag rewrites, skipped lines, and any blocking issues. Creating a plan does not pull, restart, or edit Docker state."
      next-label="Continue to apply guidance"
      next-step="pending_apply"
      :show="!showPreflightModal"
    />

    <CoreUpdateTourPanel
      step="pending_apply"
      title="Apply only after the plan is clear"
      :detail="pendingApplyTourDetail"
      next-label="Open run history"
      next-step="runs_history"
      next-to="/runs"
    />

    <PendingSearchPanel
      v-if="pendingLoaded"
      v-model:query="pendingSearchQuery"
      :active="pendingSearchActive"
      :result-label="pendingSearchResultLabel"
      @clear="clearPendingSearch"
    />

    <PendingSelectionToolbar
      :batch-summary-label="batchSummaryLabel"
      :grouping-ready="groupingReady"
      :has-selected-tag-updates="selectedHasTagUpdates"
      :is-mobile="isMobile"
      :loading="updates.loading"
      :pending-loaded="pendingLoaded"
      :removal-button-label="removalButtonLabel"
      :remove-selected-disabled="removeSelectedDisabled"
      :remove-selected-disabled-message="removeSelectedDisabledMessage"
      :selectable-count="visibleSelectableLineNumbers.length"
      :select-all-label="visibleSelectAllLabel"
      :selected-count="selectedLineNumbers.length"
      :selected-hidden-count="selectedHiddenCount"
      :snoozed-count="filteredSnoozedItems.length"
      :stack-count="filteredStackGroups.length"
      :unmatched-review-count-label="visibleUnmatchedReviewCountLabel"
      :update-selected-disabled="updateSelectedDisabled"
      @clear-selection="clearSelection"
      @select-all="selectAllVisible"
      @start-removal="startSelectedRemoval"
      @start-update="startSelectedUpdate"
    />

    <n-alert
      v-if="selectedTagOverrideError"
      type="warning"
    >
      {{ selectedTagOverrideError }}
    </n-alert>

    <PendingSearchEmptyState
      v-if="pendingSearchEmpty"
      :query="pendingSearchQuery"
      @clear="clearPendingSearch"
    />

    <template v-if="groupingReady">
      <PendingStackSelection
        v-if="!pendingSearchEmpty"
        :latest-run-id="latestRunId"
        :loading="updates.loading"
        :pending-source-label="pendingSourceLabel"
        :release-note-for="releaseNoteFor"
        :release-note-reason="releaseNoteReason"
        :release-note-status="releaseNoteStatus"
        :risk-cues="riskCues"
        :selected-line-set="selectedLineSet"
        :show-setup-link="showSetupLink"
        :snoozed-items="filteredSnoozedItems"
        :stack-groups="filteredStackGroups"
        :stack-has-selection="stackHasSelection"
        :stack-indeterminate="stackIndeterminate"
        :stack-selected="stackSelected"
        :stale-diagnostic-detail="staleDiagnosticDetail"
        :stale-diagnostic-label="staleDiagnosticLabel"
        :tag-input-props="tagInputProps"
        :tag-override-value="tagOverrideValue"
        :unmatched-issue-summary="visibleUnmatchedIssueSummary"
        :unmatched-items="filteredUnmatchedItems"
        :unmatched-review-summary="visibleUnmatchedReviewSummary"
        :update-disabled="updateDisabled"
        @preview-stack="startStackUpdate"
        @toggle-line="toggleLine"
        @toggle-stack="toggleStack"
        @update-tag="updateTagOverride"
      />
    </template>

    <template v-else-if="updates.pending">
      <PendingFallbackQueue
        v-if="!pendingSearchEmpty"
        :columns="columns"
        :is-mobile="isMobile"
        :items="filteredPendingItems"
        :latest-run-id="latestRunId"
        :loading="updates.loading"
        :pending-source-label="pendingSourceLabel"
        :release-note-for="releaseNoteFor"
        :release-note-reason="releaseNoteReason"
        :release-note-status="releaseNoteStatus"
        :risk-cues="riskCues"
        :selected-line-numbers="selectedLineNumbers"
        :selected-line-set="selectedLineSet"
        :show-setup-link="showSetupLink"
        :tag-input-props="tagInputProps"
        :tag-override-value="tagOverrideValue"
        @toggle-line="toggleLine"
        @update-checked-row-keys="updateCheckedRowKeys"
        @update-tag="updateTagOverride"
      />
    </template>

    <output
      v-else-if="pendingLoading"
      class="pending-loading-state"
      aria-live="polite"
      aria-label="Loading pending updates"
    >
      <n-skeleton aria-hidden="true" height="48px" />
      <n-skeleton aria-hidden="true" height="48px" />
      <n-skeleton aria-hidden="true" height="48px" />
    </output>

    <div
      v-else-if="pendingLoadFailed"
      class="empty-state pending-error-state"
      role="alert"
      aria-live="assertive"
    >
      <strong>Pending updates did not load</strong>
      <span>Check the WebUI API connection, then try again.</span>
      <n-button size="small" secondary :loading="updates.loading" @click="retryPendingLoad">
        Retry pending load
      </n-button>
    </div>

    <PendingPlanReviewModal
      v-if="updates.plan"
      :show="showPreflightModal"
      :plan="updates.plan"
      :action-command="actionCommand"
      :apply-button-label="applyButtonLabel"
      :apply-disabled="applyDisabled"
      :apply-preflight="applyPreflight"
      :apply-preflight-attention-checks="applyPreflightAttentionChecks"
      :apply-preflight-check-detail="applyPreflightCheckDetail"
      :apply-preflight-check-label="applyPreflightCheckLabel"
      :apply-preflight-check-type="applyPreflightCheckType"
      :apply-preflight-passed-checks="applyPreflightPassedChecks"
      :apply-preflight-passed-text="applyPreflightPassedText"
      :apply-readiness-status-label="applyReadinessStatusLabel"
      :apply-readiness-status-type="applyReadinessStatusType"
      :apply-readiness-summary="applyReadinessSummary"
      :apply-visible="applyVisible"
      :cleanup-available="cleanupAvailable"
      :cleanup-button-label="cleanupButtonLabel"
      :cleanup-disabled="cleanupDisabled"
      :cleanup-disabled-message="cleanupDisabledMessage"
      :cleanup-items="cleanupItems"
      :cleanup-review-summary="cleanupReviewSummary"
      :digest-pin-label-approval-approved="digestPinLabelApprovalApproved"
      :digest-pin-label-approval-issues="digestPinLabelApprovalIssues"
      :digest-pin-label-issue-proposed-regex="digestPinLabelIssueProposedRegex"
      :issue-detail-string="issueDetailString"
      :issue-hint="issueHint"
      :issue-label="issueLabel"
      :issue-type="issueType"
      :loading="updates.loading"
      :mutation-disabled-message="mutationDisabledMessage"
      :plan-actions="planActions"
      :plan-alert-type="planAlertType"
      :plan-digest-pin-label-rewrites="planDigestPinLabelRewrites"
      :plan-digest-unpin-updates="planDigestUnpinUpdates"
      :plan-lines="planLines"
      :preflight-digest-pin-notice="preflightDigestPinNotice"
      :preflight-digest-unpin-notice="preflightDigestUnpinNotice"
      :preflight-service-impact-label="preflightServiceImpactLabel"
      :preflight-summary="preflightSummary"
      :preflight-tag-rewrite-notice="preflightTagRewriteNotice"
      :preflight-title="preflightTitle"
      :stale-diagnostic-detail="staleDiagnosticDetail"
      :stale-diagnostic-label="staleDiagnosticLabel"
      :visible-plan-issues="visiblePlanIssues"
      @apply="confirmApply"
      @approve-digest-pin-label-rewrite="approveDigestPinLabelRewrite"
      @close="closePreflightModal"
      @open-cleanup="openCleanupModal"
    />

    <PendingCleanupModal
      v-if="updates.plan && cleanupAvailable"
      :show="showCleanupModal"
      :assistant-actions="cleanupAssistantActions"
      :assistant-findings="cleanupAssistantFindings"
      :assistant-reasons="cleanupAssistantReasons"
      :cleanup-button-label="cleanupButtonLabel"
      :cleanup-disabled="cleanupDisabled"
      :cleanup-items="cleanupItems"
      :cleanup-line-label="cleanupLineLabel"
      :loading="updates.loading"
      :pending-source-label="pendingSourceLabel"
      @close="closeCleanupModal"
      @confirm="confirmCleanup"
    />

    <PendingRemovalModal
      v-if="updates.pendingRemovalPlan"
      :show="showRemovalModal"
      :loading="updates.loading"
      :pending-source-label="pendingSourceLabel"
      :removal-confirm-button-label="removalConfirmButtonLabel"
      :removal-disabled="removalDisabled"
      :removal-items="removalItems"
      :removal-line-label="removalLineLabel"
      @close="closeRemovalModal"
      @confirm="confirmSelectedRemoval"
    />
  </section>
</template>

<style scoped>
.pending-heading {
  align-items: center;
}

.pending-loading-state {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.pending-error-state {
  gap: 8px;
  padding: 18px;
  text-align: center;
}

.recovery-actions {
  flex-wrap: wrap;
  margin-top: 8px;
}
</style>
