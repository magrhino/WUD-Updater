<script setup lang="ts">
import { AlertTriangle, Check, CheckCircle2, Play, Trash2, XCircle } from "@lucide/vue";
import { NAlert, NButton, NModal, NTag } from "naive-ui";

import type {
  ApplyPreflightCheck,
  ApplyPreflightResponse,
  ApplyPreflightStatus,
  PlanAction,
  PlanCleanupItem,
  PlanDigestPinLabelRewrite,
  PlanIssue,
  PlanLine,
  PlanResponse,
} from "../../api/client";
import CoreUpdateTourPanel from "../CoreUpdateTourPanel.vue";

type TagType = "default" | "error" | "info" | "success" | "warning";
type PlanLineView = {
  stack: string;
  line: PlanLine;
};
type PlanActionView = {
  stack: string;
  action: PlanAction;
};
type DigestPinLabelRewriteView = {
  stack: string;
  rewrite: PlanDigestPinLabelRewrite;
};

defineProps<{
  actionCommand: (action: PlanAction) => string;
  applyButtonLabel: string;
  applyDisabled: boolean;
  applyPreflight: ApplyPreflightResponse | null;
  applyPreflightAttentionChecks: ApplyPreflightCheck[];
  applyPreflightCheckDetail: (check: ApplyPreflightCheck) => string;
  applyPreflightCheckLabel: (status: ApplyPreflightStatus) => string;
  applyPreflightCheckType: (status: ApplyPreflightStatus) => TagType;
  applyPreflightPassedChecks: ApplyPreflightCheck[];
  applyPreflightPassedText: string;
  applyReadinessStatusLabel: string;
  applyReadinessStatusType: "success" | "warning" | "error";
  applyReadinessSummary: string;
  applyVisible: boolean;
  cleanupAvailable: boolean;
  cleanupButtonLabel: string;
  cleanupDisabled: boolean;
  cleanupDisabledMessage: string;
  cleanupItems: PlanCleanupItem[];
  cleanupReviewSummary: string;
  digestPinLabelApprovalApproved: (issue: PlanIssue) => boolean;
  digestPinLabelApprovalIssues: PlanIssue[];
  digestPinLabelIssueProposedRegex: (issue: PlanIssue) => string;
  issueDetailString: (issue: PlanIssue, key: string) => string;
  issueHint: (issue: PlanIssue) => string;
  issueLabel: (issue: PlanIssue) => string;
  issueType: (issue: PlanIssue) => "error" | "warning" | "info";
  loading: boolean;
  mutationDisabledMessage: string;
  plan: PlanResponse;
  planActions: PlanActionView[];
  planAlertType: TagType;
  planDigestPinLabelRewrites: DigestPinLabelRewriteView[];
  planLineDigestPinLabel: (line: PlanLine) => string;
  planLineServiceLabel: (stack: string, line: PlanLine) => string;
  planLineTagRewriteLabel: (line: PlanLine) => string;
  planLines: PlanLineView[];
  preflightDigestPinNotice: string;
  preflightServiceImpactLabel: string;
  preflightSummary: string;
  preflightTagRewriteNotice: string;
  preflightTitle: string;
  pluralize: (count: number, singular: string, plural?: string) => string;
  show: boolean;
  staleDiagnosticDetail: (item: PlanCleanupItem) => string;
  staleDiagnosticLabel: (item: PlanCleanupItem) => string;
  visiblePlanIssues: PlanIssue[];
}>();

const emit = defineEmits<{
  (event: "apply"): void;
  (event: "approve-digest-pin-label-rewrite", issue: PlanIssue): void;
  (event: "close"): void;
  (event: "open-cleanup"): void;
}>();

function handleModalShowUpdate(value: boolean): void {
  if (!value) {
    emit("close");
  }
}
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    @update:show="handleModalShowUpdate"
  >
    <section
      class="preflight-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="preflight-modal-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">Preflight</p>
          <h2 id="preflight-modal-title">{{ preflightTitle }}</h2>
          <p class="preflight-summary-text">{{ preflightSummary }}</p>
          <p v-if="preflightServiceImpactLabel" class="preflight-impact-text">
            {{ preflightServiceImpactLabel }}
          </p>
        </div>
        <n-tag :type="planAlertType">{{ plan.status }}</n-tag>
      </div>

      <div class="preflight-metrics">
        <div>
          <span>Targets</span>
          <strong>{{ plan.summary.target_count }}</strong>
        </div>
        <div>
          <span>Matched</span>
          <strong>{{ plan.summary.matched_target_count }}</strong>
        </div>
        <div>
          <span>Stacks</span>
          <strong>{{ plan.summary.stack_count }}</strong>
        </div>
        <div>
          <span>Issues</span>
          <strong>{{ plan.summary.issue_count }}</strong>
        </div>
      </div>

      <section
        v-if="applyPreflight"
        class="apply-readiness preflight-block"
        aria-labelledby="apply-readiness-title"
      >
        <div class="apply-readiness-heading">
          <div>
            <strong id="apply-readiness-title">Apply readiness</strong>
            <span>{{ applyReadinessSummary }}</span>
          </div>
          <n-tag size="small" :type="applyReadinessStatusType">
            {{ applyReadinessStatusLabel }}
          </n-tag>
        </div>
        <div
          v-if="applyPreflightPassedChecks.length"
          class="apply-readiness-passed"
        >
          <CheckCircle2 :size="16" aria-hidden="true" />
          <p>
            <strong>
              {{ pluralize(applyPreflightPassedChecks.length, "check") }} passed:
            </strong>
            <span class="apply-readiness-pass-list">
              {{ applyPreflightPassedText }}
            </span>
          </p>
        </div>
        <div
          v-if="applyPreflightAttentionChecks.length"
          class="apply-readiness-list"
        >
          <div
            v-for="check in applyPreflightAttentionChecks"
            :key="check.code"
            class="apply-readiness-row"
            :class="`status-${check.status.toLowerCase()}`"
          >
            <CheckCircle2
              v-if="check.status === 'PASS'"
              :size="16"
              aria-hidden="true"
            />
            <AlertTriangle
              v-else-if="check.status === 'WARN'"
              :size="16"
              aria-hidden="true"
            />
            <XCircle v-else :size="16" aria-hidden="true" />
            <strong>{{ check.label }}</strong>
            <n-tag size="small" :type="applyPreflightCheckType(check.status)">
              {{ applyPreflightCheckLabel(check.status) }}
            </n-tag>
            <span
              v-if="applyPreflightCheckDetail(check)"
              class="apply-readiness-detail"
            >
              {{ applyPreflightCheckDetail(check) }}
            </span>
          </div>
        </div>
      </section>

      <CoreUpdateTourPanel
        step="pending_preflight"
        title="Read the plan like a checklist"
        detail="Matched services and images show what will change. Issues block apply, tag rewrites are called out, and cleanup actions only edit the pending file after confirmation."
        next-label="Continue to apply guidance"
        next-step="pending_apply"
        @advanced="emit('close')"
      />

      <n-alert
        v-if="mutationDisabledMessage"
        class="preflight-block"
        type="warning"
      >
        {{ mutationDisabledMessage }}
      </n-alert>
      <n-alert
        v-if="preflightTagRewriteNotice"
        class="preflight-block"
        type="warning"
      >
        {{ preflightTagRewriteNotice }}
      </n-alert>
      <n-alert
        v-if="preflightDigestPinNotice"
        class="preflight-block"
        type="info"
      >
        {{ preflightDigestPinNotice }}
      </n-alert>

      <section
        v-if="planDigestPinLabelRewrites.length"
        class="preflight-impact preflight-block"
        aria-labelledby="digest-pin-label-rewrites-title"
      >
        <div class="preflight-impact-heading">
          <strong id="digest-pin-label-rewrites-title">Digest-pin label updates</strong>
          <n-tag size="small">{{ pluralize(planDigestPinLabelRewrites.length, "label") }}</n-tag>
        </div>
        <div class="compact-list">
          <div
            v-for="item in planDigestPinLabelRewrites"
            :key="`${item.stack}-${item.rewrite.service}-${item.rewrite.label_key}-${item.rewrite.current_label_value}`"
            class="list-row plan-line-row"
          >
            <span>Label</span>
            <strong>{{ item.stack }} / {{ item.rewrite.service }}</strong>
            <em>
              <code>{{ item.rewrite.label_key }}={{ item.rewrite.current_label_value }}</code>
              <span aria-hidden="true"> -> </span>
              <code>{{ item.rewrite.proposed_label_regex }}</code>
            </em>
          </div>
        </div>
      </section>

      <section
        v-if="digestPinLabelApprovalIssues.length"
        class="preflight-impact preflight-block"
        aria-labelledby="digest-pin-label-approvals-title"
      >
        <div class="preflight-impact-heading">
          <strong id="digest-pin-label-approvals-title">Digest-pin label approvals</strong>
          <n-tag size="small" type="warning">
            {{ pluralize(digestPinLabelApprovalIssues.length, "approval") }}
          </n-tag>
        </div>
        <p class="preflight-summary-text">
          Approve replacing each current include rule with the exact planned tag before applying.
        </p>
        <div class="compact-list">
          <div
            v-for="issue in digestPinLabelApprovalIssues"
            :key="`${issue.stack}-${issue.service}-${issueDetailString(issue, 'current_label_value')}`"
            class="list-row plan-line-row digest-pin-approval-row"
          >
            <span>Review</span>
            <strong>{{ issue.stack }} / {{ issue.service }}</strong>
            <em>
              <code>{{ issueDetailString(issue, "label_key") }}={{ issueDetailString(issue, "current_label_value") }}</code>
              <span aria-hidden="true"> -> </span>
              <code>{{ digestPinLabelIssueProposedRegex(issue) }}</code>
              <n-button
                size="small"
                secondary
                type="primary"
                :disabled="digestPinLabelApprovalApproved(issue)"
                :loading="loading"
                @click="emit('approve-digest-pin-label-rewrite', issue)"
              >
                <template #icon>
                  <Check :size="16" />
                </template>
                {{ digestPinLabelApprovalApproved(issue) ? "Approved" : "Approve label rewrite" }}
              </n-button>
            </em>
          </div>
        </div>
      </section>

      <n-alert
        v-if="cleanupDisabledMessage"
        class="preflight-block"
        type="warning"
      >
        {{ cleanupDisabledMessage }}
      </n-alert>

      <section
        v-if="cleanupAvailable"
        class="preflight-impact preflight-block"
        aria-labelledby="cleanup-preview-title"
      >
        <div class="preflight-impact-heading">
          <strong id="cleanup-preview-title">Unmatched pending entries</strong>
          <n-tag size="small" type="warning">
            {{ pluralize(cleanupItems.length, "entry", "entries") }}
          </n-tag>
        </div>
        <p class="preflight-summary-text">{{ cleanupReviewSummary }}</p>
        <div class="compact-list">
          <div
            v-for="item in cleanupItems"
            :key="`cleanup-${item.line_no}`"
            class="list-row plan-line-row"
          >
            <span>#{{ item.line_no }}</span>
            <strong class="plan-line-heading">
              <span>{{ item.image }}</span>
              <n-tag size="small" type="warning">
                {{ staleDiagnosticLabel(item) }}
              </n-tag>
            </strong>
            <em>
              <span>{{ staleDiagnosticDetail(item) }}</span>
            </em>
          </div>
        </div>
      </section>

      <section
        v-if="plan.status === 'ready'"
        class="preflight-impact preflight-block"
        aria-labelledby="preflight-impact-title"
      >
        <div class="preflight-impact-heading">
          <strong id="preflight-impact-title">Services and images</strong>
          <n-tag size="small">{{ pluralize(planLines.length, "service") }}</n-tag>
        </div>
        <div v-if="planLines.length" class="compact-list">
          <div
            v-for="{ stack, line } in planLines"
            :key="`${stack}-${line.line_no}-${line.service}`"
            class="list-row plan-line-row"
          >
            <span>#{{ line.line_no }}</span>
            <strong>{{ planLineServiceLabel(stack, line) }}</strong>
            <em>
              <span v-if="planLineTagRewriteLabel(line)" class="tag-rewrite-detail">
                <n-tag size="small" type="warning">Tag rewrite</n-tag>
                {{ planLineTagRewriteLabel(line) }}
              </span>
              <span
                v-else-if="planLineDigestPinLabel(line)"
                class="tag-rewrite-detail"
              >
                <n-tag size="small" type="info">Digest pin</n-tag>
                {{ planLineDigestPinLabel(line) }}
              </span>
              <template v-else>
                <code>{{ line.compose_image }}</code>
                <span aria-hidden="true"> -> </span>
                <code>{{ line.target_image }}</code>
              </template>
            </em>
          </div>
        </div>
        <div v-else class="empty-state">No matched services.</div>
      </section>

      <div v-if="visiblePlanIssues.length" class="warning-list preflight-block">
        <n-alert
          v-for="issue in visiblePlanIssues"
          :key="`${issue.code}-${issue.line_no ?? ''}-${issue.stack}-${issue.service}`"
          :type="issueType(issue)"
        >
          <span>{{ issueLabel(issue) }}</span>
          <span v-if="issueHint(issue)" class="issue-hint">
            {{ issueHint(issue) }}
          </span>
        </n-alert>
      </div>

      <div class="preflight-details-list">
        <details
          v-if="plan.status !== 'ready'"
          class="preflight-details"
          :open="plan.status === 'blocked'"
        >
          <summary>Services and images</summary>
          <div v-if="planLines.length" class="compact-list">
            <div
              v-for="{ stack, line } in planLines"
              :key="`${stack}-${line.line_no}-${line.service}`"
              class="list-row plan-line-row"
            >
              <span>#{{ line.line_no }}</span>
              <strong>{{ planLineServiceLabel(stack, line) }}</strong>
              <em>
                <span v-if="planLineTagRewriteLabel(line)" class="tag-rewrite-detail">
                  <n-tag size="small" type="warning">Tag rewrite</n-tag>
                  {{ planLineTagRewriteLabel(line) }}
                </span>
                <span
                  v-else-if="planLineDigestPinLabel(line)"
                  class="tag-rewrite-detail"
                >
                  <n-tag size="small" type="info">Digest pin</n-tag>
                  {{ planLineDigestPinLabel(line) }}
                </span>
                <template v-else>
                  <code>{{ line.compose_image }}</code>
                  <span aria-hidden="true"> -> </span>
                  <code>{{ line.target_image }}</code>
                </template>
              </em>
            </div>
          </div>
          <div v-else class="empty-state">No matched services.</div>
        </details>

        <details v-if="planActions.length" class="preflight-details">
          <summary>Commands</summary>
          <div class="plan-actions">
            <div
              v-for="{ stack, action } in planActions"
              :key="`${stack}-${action.kind}-${actionCommand(action)}`"
              class="plan-action"
            >
              <n-tag size="small">{{ action.kind }}</n-tag>
              <code>{{ actionCommand(action) }}</code>
            </div>
          </div>
        </details>

        <details v-if="plan.skipped.length" class="preflight-details" open>
          <summary>Skipped</summary>
          <div class="compact-list">
            <div v-for="item in plan.skipped" :key="item.line_no" class="list-row">
              <span>#{{ item.line_no }}</span>
              <strong>{{ item.image }}</strong>
              <em>{{ item.reason }}</em>
            </div>
          </div>
        </details>

        <details class="preflight-details">
          <summary>Source lines</summary>
          <div class="compact-list">
            <div
              v-for="lineNo in plan.selected_line_numbers"
              :key="lineNo"
              class="list-row"
            >
              <span>Line</span>
              <strong>#{{ lineNo }}</strong>
              <em>{{ plan.source_file }}</em>
            </div>
          </div>
        </details>
      </div>

      <div class="preflight-footer">
        <n-button size="small" quaternary @click="emit('close')">
          Close
        </n-button>
        <n-button
          v-if="cleanupAvailable"
          type="warning"
          size="small"
          secondary
          :disabled="cleanupDisabled"
          :loading="loading"
          @click="emit('open-cleanup')"
        >
          <template #icon>
            <Trash2 :size="16" />
          </template>
          {{ cleanupButtonLabel }}
        </n-button>
        <n-button
          v-if="applyVisible"
          type="primary"
          size="small"
          :disabled="applyDisabled"
          :loading="loading"
          @click="emit('apply')"
        >
          <template #icon>
            <Play :size="16" />
          </template>
          {{ applyButtonLabel }}
        </n-button>
      </div>
    </section>
  </n-modal>
</template>
