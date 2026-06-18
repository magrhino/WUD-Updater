<script setup lang="ts">
import { NModal, NTag } from "naive-ui";

type TagType = "default" | "error" | "info" | "success" | "warning";

defineProps<{
  show: boolean;
  eyebrow: string;
  title: string;
  titleId?: string;
  summary: string;
  impactLabel?: string;
  statusLabel?: string;
  statusType?: TagType;
}>();

const emit = defineEmits<{
  close: [];
}>();

function handleShowUpdate(value: boolean): void {
  if (!value) {
    emit("close");
  }
}
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    @update:show="handleShowUpdate"
  >
    <section
      class="preflight-modal"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId ?? `${eyebrow}-preflight-title`"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">{{ eyebrow }}</p>
          <h2 :id="titleId ?? `${eyebrow}-preflight-title`">{{ title }}</h2>
          <p class="preflight-summary-text">{{ summary }}</p>
          <p v-if="impactLabel" class="preflight-impact-text">
            {{ impactLabel }}
          </p>
        </div>
        <n-tag v-if="statusLabel" :type="statusType ?? 'default'">
          {{ statusLabel }}
        </n-tag>
      </div>

      <slot />
    </section>
  </n-modal>
</template>
