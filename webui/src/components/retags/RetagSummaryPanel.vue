<script setup lang="ts">
import { NButton } from "naive-ui";

defineProps<{
  totalCount: number;
  availableCount: number;
  attentionCount: number;
  selectedSwitchCount: number;
  previewDisabled: boolean;
  applyDisabled: boolean;
  loading: boolean;
  applyJobActive: boolean;
  hasRetagPlan: boolean;
  mutationNotice: string;
  validationError: string;
}>();

defineEmits<{
  preview: [];
  apply: [];
}>();
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
        <span>Selected switches</span>
        <strong class="wrap-anywhere">{{ selectedSwitchCount }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.retag-summary-panel {
  display: grid;
  gap: 16px;
}

.retag-heading {
  align-items: flex-start;
}

.retag-preview-action {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
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
  font-size: 1.1rem;
  line-height: 1.2;
}

@media (--wud-app-shell) {
  .retag-summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .retag-summary-strip div:nth-child(2n) {
    border-right: 0;
  }
}

@media (--wud-compact) {
  .retag-preview-action {
    display: grid;
    justify-content: stretch;
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
