<script setup lang="ts">
import { computed } from "vue";
import { useRouter, type RouteLocationRaw } from "vue-router";
import { ArrowRight, CheckCircle2, X } from "@lucide/vue";
import { NButton, NTag } from "naive-ui";

import type { CoreUpdateTourStep } from "../api/client";
import { useSettingsStore } from "../stores/settings";

const props = withDefaults(
  defineProps<{
    step: CoreUpdateTourStep;
    title: string;
    detail: string;
    nextLabel?: string;
    nextStep?: CoreUpdateTourStep;
    nextTo?: RouteLocationRaw;
    complete?: boolean;
    show?: boolean;
  }>(),
  {
    nextLabel: "",
    nextStep: undefined,
    nextTo: undefined,
    complete: false,
    show: true,
  },
);
const emit = defineEmits<{
  (event: "advanced"): void;
}>();

const settings = useSettingsStore();
const router = useRouter();

const active = computed(
  () =>
    props.show &&
    settings.coreUpdateTour?.status === "in_progress" &&
    settings.coreUpdateTour.step === props.step,
);
const actionLabel = computed(() => {
  if (props.nextLabel) {
    return props.nextLabel;
  }
  return props.complete ? "Finish tour" : "Continue tour";
});

async function advanceTour(): Promise<void> {
  const nextStatus = props.complete ? "completed" : "in_progress";
  const nextStep = props.nextStep ?? props.step;
  await settings.updateCoreUpdateTour(nextStatus, nextStep);
  emit("advanced");
  if (props.nextTo) {
    await router?.push(props.nextTo);
  }
}

async function dismissTour(): Promise<void> {
  await settings.updateCoreUpdateTour("dismissed", props.step);
}
</script>

<template>
  <section v-if="active" class="core-tour-panel" aria-label="Core update tour">
    <div class="core-tour-main">
      <n-tag size="small" type="info">Update tour</n-tag>
      <div>
        <h2>{{ title }}</h2>
        <p>{{ detail }}</p>
        <slot />
      </div>
    </div>
    <div class="core-tour-actions">
      <n-button size="small" quaternary :loading="settings.loading" @click="dismissTour">
        <template #icon>
          <X :size="16" />
        </template>
        Dismiss tour
      </n-button>
      <n-button size="small" type="primary" :loading="settings.loading" @click="advanceTour">
        <template #icon>
          <CheckCircle2 v-if="complete" :size="16" />
          <ArrowRight v-else :size="16" />
        </template>
        {{ actionLabel }}
      </n-button>
    </div>
  </section>
</template>

<style scoped>
.core-tour-panel {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--color-border) 74%, var(--color-action-blue) 26%);
  border-radius: 7px;
  background: color-mix(in srgb, var(--color-surface) 92%, var(--color-action-blue) 8%);
}

.core-tour-main {
  display: flex;
  flex: 1 1 auto;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.core-tour-main > :deep(.n-tag) {
  flex: 0 0 auto;
  margin-top: 1px;
}

.core-tour-main>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.core-tour-main h2,
.core-tour-main p {
  min-width: 0;
  overflow-wrap: anywhere;
}

.core-tour-main h2 {
  margin: 0;
  color: var(--color-ink);
  font-size: 1rem;
  line-height: 1.25;
}

.core-tour-main p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.core-tour-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 560px) {
  .core-tour-panel {
    display: grid;
  }

  .core-tour-actions {
    justify-content: flex-start;
  }
}
</style>
