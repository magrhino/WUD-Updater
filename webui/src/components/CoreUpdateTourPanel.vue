<script setup lang="ts">
import { computed } from "vue";
import { useRouter, type RouteLocationRaw } from "vue-router";
import { ArrowRight, CheckCircle2, X } from "@lucide/vue";
import { NButton, NTag } from "naive-ui";

import type { CoreUpdateTourStep } from "../api/client";
import { useWebuiStore } from "../stores/webui";

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

const webui = useWebuiStore();
const router = useRouter();

const active = computed(
  () =>
    props.show &&
    webui.coreUpdateTour?.status === "in_progress" &&
    webui.coreUpdateTour.step === props.step,
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
  await webui.updateCoreUpdateTour(nextStatus, nextStep);
  if (props.nextTo) {
    await router?.push(props.nextTo);
  }
}

async function dismissTour(): Promise<void> {
  await webui.updateCoreUpdateTour("dismissed", props.step);
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
      <n-button size="small" quaternary :loading="webui.loading" @click="dismissTour">
        <template #icon>
          <X :size="16" />
        </template>
        Dismiss tour
      </n-button>
      <n-button size="small" type="primary" :loading="webui.loading" @click="advanceTour">
        <template #icon>
          <CheckCircle2 v-if="complete" :size="16" />
          <ArrowRight v-else :size="16" />
        </template>
        {{ actionLabel }}
      </n-button>
    </div>
  </section>
</template>
