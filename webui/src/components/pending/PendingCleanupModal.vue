<script setup lang="ts">
import { Trash2 } from "@lucide/vue";
import { NAlert, NButton, NModal, NTag } from "naive-ui";

import type { PlanCleanupItem } from "../../api/client";
import { pluralize } from "../../views/pending/utils";

defineProps<{
  assistantActions: string[];
  assistantFindings: string[];
  assistantReasons: string[];
  cleanupButtonLabel: string;
  cleanupDisabled: boolean;
  cleanupItems: PlanCleanupItem[];
  cleanupLineLabel: (item: PlanCleanupItem) => string;
  loading: boolean;
  pendingSourceLabel: string;
  show: boolean;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "confirm"): void;
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
      aria-labelledby="cleanup-modal-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">Pending cleanup</p>
          <h2 id="cleanup-modal-title">Remove unmatched entries</h2>
          <p class="preflight-summary-text">
            These lines will be removed from {{ pendingSourceLabel }} without running Docker updates.
          </p>
        </div>
        <n-tag type="warning">{{ pluralize(cleanupItems.length, "entry", "entries") }}</n-tag>
      </div>

      <n-alert class="preflight-block" type="warning">
        The server will re-read {{ pendingSourceLabel }} and reject the cleanup if any selected line changed or now matches an active Compose stack.
      </n-alert>
      <n-alert class="preflight-block" type="warning">
        This only edits {{ pendingSourceLabel }}. Containers, images, Compose services, and Compose files are not deleted or updated.
      </n-alert>

      <section
        v-if="
          assistantFindings.length ||
          assistantReasons.length ||
          assistantActions.length
        "
        class="preflight-impact preflight-block"
        aria-labelledby="cleanup-guidance-title"
      >
        <div class="preflight-impact-heading">
          <strong id="cleanup-guidance-title">Stale entry guidance</strong>
        </div>
        <div class="cleanup-assistant">
          <div v-if="assistantFindings.length" class="cleanup-assistant-section">
            <strong>Preflight found</strong>
            <ul>
              <li v-for="finding in assistantFindings" :key="finding">
                {{ finding }}
              </li>
            </ul>
          </div>
          <div v-if="assistantReasons.length" class="cleanup-assistant-section">
            <strong>Likely causes</strong>
            <ul>
              <li v-for="reason in assistantReasons" :key="reason">
                {{ reason }}
              </li>
            </ul>
          </div>
          <div v-if="assistantActions.length" class="cleanup-assistant-section">
            <strong>Recommended actions</strong>
            <ul>
              <li v-for="action in assistantActions" :key="action">
                {{ action }}
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section class="preflight-impact preflight-block" aria-labelledby="cleanup-lines-title">
        <div class="preflight-impact-heading">
          <strong id="cleanup-lines-title">Source lines</strong>
          <n-tag size="small">{{ pluralize(cleanupItems.length, "line") }}</n-tag>
        </div>
        <div class="compact-list">
          <div
            v-for="item in cleanupItems"
            :key="`cleanup-confirm-${item.line_no}`"
            class="list-row plan-line-row"
          >
            <span>Line</span>
            <strong>{{ cleanupLineLabel(item) }}</strong>
            <em><code>{{ item.raw }}</code></em>
          </div>
        </div>
      </section>

      <div class="preflight-footer">
        <n-button size="small" quaternary @click="emit('close')">
          Cancel
        </n-button>
        <n-button
          type="warning"
          size="small"
          :disabled="cleanupDisabled"
          :loading="loading"
          @click="emit('confirm')"
        >
          <template #icon>
            <Trash2 :size="16" />
          </template>
          {{ cleanupButtonLabel }}
        </n-button>
      </div>
    </section>
  </n-modal>
</template>
