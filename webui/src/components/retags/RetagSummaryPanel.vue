<script setup lang="ts">
import { NAlert, NButton } from "naive-ui";

defineProps<{
  totalCount: number;
  availableCount: number;
  attentionCount: number;
  selectedSwitchCount: number;
  runningEligibleCount: number;
  filteredRunningEligibleCount: number;
  previewDisabled: boolean;
  applyDisabled: boolean;
  retagAllDisabled: boolean;
  retagFilteredDisabled: boolean;
  keepAllDisabled: boolean;
  loading: boolean;
  applyJobActive: boolean;
  hasRetagPlan: boolean;
  mutationNotice: string;
  runtimeWarning: string;
  validationError: string;
}>();

defineEmits<{
  "retag-all": [];
  "retag-filtered": [];
  "keep-all": [];
  preview: [];
  apply: [];
}>();

function runningSelectionTitle(count: number, filtered: boolean): string {
  if (!count) {
    return filtered
      ? "No running eligible Compose services in the current results."
      : "No running eligible Compose services to select.";
  }
  const scope = filtered ? " in the current results" : "";
  return `Replace the current selection with ${count} running eligible Compose ${count === 1 ? "service" : "services"}${scope}. Not-running and unknown services stay on Keep.`;
}
</script>

<template>
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
          :loading="loading"
          @click="$emit('preview')"
        >
          Preview retag changes
        </n-button>
        <n-button
          v-if="hasRetagPlan"
          size="small"
          :disabled="applyDisabled"
          :loading="loading || applyJobActive"
          @click="$emit('apply')"
        >
          Apply selected retags
        </n-button>
        <span v-if="mutationNotice">{{ mutationNotice }}</span>
        <span v-else-if="validationError">{{ validationError }}</span>
      </div>
    </div>

    <div class="retag-summary-strip" aria-label="Retag review summary">
      <div>
        <span>Total services</span>
        <strong class="wrap-anywhere">{{ totalCount }}</strong>
      </div>
      <div>
        <span>Retag candidates</span>
        <strong class="wrap-anywhere">{{ availableCount }}</strong>
      </div>
      <div>
        <span>Needs attention</span>
        <strong class="wrap-anywhere">{{ attentionCount }}</strong>
      </div>
      <div>
        <span>Selected retags</span>
        <strong class="wrap-anywhere">{{ selectedSwitchCount }}</strong>
      </div>
    </div>

    <n-alert
      v-if="runtimeWarning"
      type="warning"
      :show-icon="false"
    >
      {{ runtimeWarning }}
    </n-alert>

    <div class="retag-bulk-actions" aria-label="Bulk retag selection">
      <n-button
        size="small"
        :disabled="retagAllDisabled"
        :title="runningSelectionTitle(runningEligibleCount, false)"
        @click="$emit('retag-all')"
      >
        Select running candidates
      </n-button>
      <n-button
        size="small"
        :disabled="retagFilteredDisabled"
        :title="runningSelectionTitle(filteredRunningEligibleCount, true)"
        @click="$emit('retag-filtered')"
      >
        Select running in results
      </n-button>
      <n-button
        size="small"
        :disabled="keepAllDisabled"
        :title="
          keepAllDisabled
            ? 'No selected retags to clear.'
            : 'Set every Compose service to Keep and clear the current selection.'
        "
        @click="$emit('keep-all')"
      >
        Clear selection
      </n-button>
      <span class="retag-bulk-help">
        Targets are discovered Compose services; standalone <code>docker run</code> containers are not included.
        Bulk selection replaces the current selection and includes only running services.
        Select a not-running or unknown row individually to include it. Applying a not-running service will create or recreate and start it; an unknown service may be created or recreated and started.
      </span>
    </div>
  </section>
</template>

<style scoped>
.retag-summary-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.retag-heading {
  align-items: flex-start;
  min-width: 0;
}

.retag-preview-action {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  max-width: 420px;
}

.retag-preview-action span {
  color: var(--color-muted-text);
  font-size: 0.85rem;
  line-height: 1.35;
}

.retag-summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--color-border-subtle);
  border-radius: 8px;
  background: var(--color-panel-tint);
}

.retag-summary-strip div {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border-right: 1px solid var(--color-border-subtle);
}

.retag-summary-strip div:last-child {
  border-right: 0;
}

.retag-summary-strip span {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
}

.retag-summary-strip strong {
  color: var(--color-ink);
  font-size: var(--text-body-size);
  line-height: 1.2;
}

.retag-bulk-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.retag-bulk-help {
  flex-basis: 100%;
  color: var(--color-muted-text);
  font-size: var(--text-metadata-size);
  line-height: 1.4;
}

@media (--wud-app-shell) {
  .retag-summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .retag-summary-strip div:nth-child(2n) {
    border-right: 0;
  }
}

@media (--wud-data-cards) {
  .retag-heading {
    display: grid;
  }

  .retag-preview-action {
    display: grid;
    justify-content: stretch;
    width: 100%;
  }

  .retag-bulk-actions {
    display: grid;
    width: 100%;
  }

  .retag-summary-strip {
    grid-template-columns: 1fr;
  }

  .retag-summary-strip div {
    border-right: 0;
    border-bottom: 1px solid var(--color-border-subtle);
  }

  .retag-summary-strip div:last-child {
    border-bottom: 0;
  }
}
</style>
