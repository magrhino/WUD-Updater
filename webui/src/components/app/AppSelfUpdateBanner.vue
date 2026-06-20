<script setup lang="ts">
import { ArrowUpCircle } from "@lucide/vue";
import { NButton } from "naive-ui";

defineProps<{
  currentTag?: string;
  latestTag?: string;
  facts: string;
  disabledReason: string;
  buttonDisabled: boolean;
  actionTitle: string;
  actionLabel: string;
}>();

defineEmits<{
  open: [];
}>();
</script>

<template>
  <section
    class="self-update-banner"
    aria-label="WUDup self-update"
  >
    <div class="self-update-banner-main">
      <ArrowUpCircle :size="20" aria-hidden="true" />
      <div>
        <strong>
          Update available:
          {{ currentTag }} &rarr; {{ latestTag }}
        </strong>
        <span>{{ facts }}</span>
      </div>
    </div>
    <div class="self-update-banner-actions">
      <span
        v-if="disabledReason"
        class="self-update-disabled"
      >
        {{ disabledReason }}
      </span>
      <n-button
        type="primary"
        size="small"
        :disabled="buttonDisabled"
        :title="actionTitle"
        @click="$emit('open')"
      >
        {{ actionLabel }}
      </n-button>
    </div>
  </section>
</template>

<style scoped>
.self-update-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--color-operational-teal) 34%, var(--color-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--color-operational-teal) 8%, var(--color-surface));
  color: var(--color-ink);
}

.self-update-banner-main,
.self-update-banner-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.self-update-banner-main>svg {
  flex: 0 0 auto;
  color: var(--color-operational-teal);
}

.self-update-banner-main div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.self-update-banner-main span,
.self-update-disabled {
  color: var(--color-muted-text);
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.self-update-disabled {
  max-width: 42ch;
}

@media (--wud-app-shell) {
  .self-update-banner {
    align-items: flex-start;
    flex-direction: column;
  }

  .self-update-banner-actions {
    width: 100%;
  }
}

@media (--wud-compact) {
  .self-update-banner-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .self-update-banner-actions :deep(.n-button) {
    min-width: 44px;
    min-height: 44px;
  }
}
</style>
