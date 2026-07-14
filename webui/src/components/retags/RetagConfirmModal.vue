<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  NAlert,
  NButton,
  NFlex,
  NGi,
  NGrid,
  NModal,
  NTag,
} from "naive-ui";

import type { RetagPlanResponse } from "../../api/client";
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
  impactLabel: string;
  mutationNotice: string;
  runtimeWarning: string;
  applyError: string;
  applyDisabled: boolean;
  loading: boolean;
  applyJobActive: boolean;
}>();

const emit = defineEmits<{
  "update:show": [value: boolean];
  confirm: [];
  "rebuild-preview": [];
}>();

const applyErrorAlert = ref<HTMLElement | null>(null);

const retagPlanUpdates = computed(() =>
  (props.plan?.stacks ?? []).flatMap((stack) =>
    stack.digest_pin_updates.map((update) => ({ stack, update })),
  ),
);

function closeModal(): void {
  emit("update:show", false);
}

watch(
  () => props.applyError,
  async (error) => {
    if (!error) {
      return;
    }
    await nextTick();
    applyErrorAlert.value?.focus();
  },
);
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    @update:show="$emit('update:show', $event)"
  >
    <dialog
      open
      class="preflight-modal retag-confirm-modal"
      aria-labelledby="retag-confirm-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">Confirm retag apply</p>
          <h2 id="retag-confirm-title">Apply selected retags</h2>
          <p class="preflight-summary-text">
            Applying rewrites Compose image metadata, pulls images, and recreates selected services.
            Review these changes before starting the retag apply job.
          </p>
          <p v-if="impactLabel" class="preflight-impact-text">
            {{ impactLabel }}
          </p>
        </div>
        <n-tag v-if="plan" :type="planStatusType(plan)">
          {{ plan.status }}
        </n-tag>
      </div>

      <n-alert
        v-if="mutationNotice"
        type="warning"
        :show-icon="false"
      >
        {{ mutationNotice }}
      </n-alert>

      <n-alert
        v-if="runtimeWarning"
        type="warning"
        :show-icon="false"
      >
        {{ runtimeWarning }}
      </n-alert>

      <div
        v-if="applyError"
        ref="applyErrorAlert"
        role="alert"
        tabindex="-1"
      >
        <n-alert type="error" :show-icon="false">
          {{ applyError }}
        </n-alert>
      </div>

      <n-grid
        v-if="plan"
        class="preflight-metrics retag-confirm-metrics"
        aria-label="Retag apply summary"
        responsive="self"
        cols="2 560:4"
        :x-gap="8"
        :y-gap="8"
      >
        <n-gi>
          <div class="preflight-metric">
            <span>Services</span>
            <strong class="wrap-anywhere">{{ plan.selected_count }}</strong>
          </div>
        </n-gi>
        <n-gi>
          <div class="preflight-metric">
            <span>Stacks</span>
            <strong class="wrap-anywhere">{{ plan.stacks.length }}</strong>
          </div>
        </n-gi>
        <n-gi>
          <div class="preflight-metric">
            <span>Keep current</span>
            <strong class="wrap-anywhere">{{ plan.keep_current_count }}</strong>
          </div>
        </n-gi>
        <n-gi>
          <div class="preflight-metric">
            <span>Source</span>
            <strong class="wrap-anywhere">{{ retagPlanSourceFile(plan) }}</strong>
          </div>
        </n-gi>
      </n-grid>

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
            v-for="({ stack, update }, index) in retagPlanUpdates"
            :key="`confirm-${stack.directory}-${stack.compose_file}-${stack.project_directory}-${update.service_key}-${index}`"
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

      <n-flex class="preflight-footer" justify="flex-end" :size="8">
        <n-button size="small" quaternary @click="closeModal">
          Cancel
        </n-button>
        <n-button
          v-if="applyError"
          size="small"
          secondary
          :loading="loading"
          @click="$emit('rebuild-preview')"
        >
          Rebuild preview
        </n-button>
        <n-button
          type="primary"
          size="small"
          :disabled="applyDisabled"
          :loading="loading || applyJobActive"
          @click="$emit('confirm')"
        >
          Confirm and apply
        </n-button>
      </n-flex>
    </dialog>
  </n-modal>
</template>

<style scoped>
.retag-confirm-modal .plan-line-row em {
  display: grid;
  gap: 3px;
}
</style>
