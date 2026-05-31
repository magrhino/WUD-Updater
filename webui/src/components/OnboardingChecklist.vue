<script setup lang="ts">
import { computed, onMounted, ref, type Component } from "vue";
import { useClipboard } from "@vueuse/core";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  RefreshCw,
  XCircle,
  X,
} from "@lucide/vue";
import { NButton, NTag } from "naive-ui";

import type { DoctorCheckStatus, OnboardingChecklistItem } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const copiedSnippet = ref("");
const dismissing = ref(false);
const { copy, copied, isSupported } = useClipboard({ legacy: true });

const onboarding = computed(() => webui.onboarding);
const visible = computed(() => onboarding.value?.visible === true);
const items = computed(() => onboarding.value?.items ?? []);
const failingItems = computed(
  () => items.value.filter((item) => item.status === "FAIL").length,
);
const warningItems = computed(
  () => items.value.filter((item) => item.status === "WARN").length,
);
const passingItems = computed(
  () => items.value.filter((item) => item.status === "PASS").length,
);

onMounted(() => {
  if (webui.onboarding === null) {
    void refreshOnboarding().catch(() => undefined);
  }
});

async function refreshOnboarding(): Promise<void> {
  await webui.loadOnboarding();
}

async function dismissChecklist(): Promise<void> {
  dismissing.value = true;
  try {
    await webui.dismissOnboarding();
  } finally {
    dismissing.value = false;
  }
}

async function copySuggestion(snippet: string): Promise<void> {
  if (!snippet.trim()) {
    return;
  }
  await copy(snippet);
  copiedSnippet.value = snippet;
}

function statusIcon(status: DoctorCheckStatus): Component {
  if (status === "PASS") {
    return CheckCircle2;
  }
  if (status === "WARN") {
    return AlertTriangle;
  }
  return XCircle;
}

function statusLabel(status: DoctorCheckStatus): string {
  if (status === "PASS") {
    return "Pass";
  }
  if (status === "WARN") {
    return "Warn";
  }
  return "Fail";
}

function statusTagType(
  status: DoctorCheckStatus,
): "success" | "warning" | "error" {
  if (status === "PASS") {
    return "success";
  }
  if (status === "WARN") {
    return "warning";
  }
  return "error";
}

function itemKey(item: OnboardingChecklistItem): string {
  return item.key;
}
</script>

<template>
  <section v-if="visible" class="section-panel onboarding-panel">
    <div class="section-heading onboarding-heading">
      <div class="settings-heading-main">
        <p class="eyebrow">First run</p>
        <h2>Setup checklist</h2>
        <p class="settings-section-copy">
          Confirm the WebUI can see WUD output, Docker, Compose stacks, persistent
          state, and the intended browser safety mode.
        </p>
      </div>
      <div class="settings-heading-meta onboarding-actions">
        <n-tag v-if="failingItems" size="small" type="error">
          {{ failingItems }} failing
        </n-tag>
        <n-tag v-if="warningItems" size="small" type="warning">
          {{ warningItems }} warning{{ warningItems === 1 ? "" : "s" }}
        </n-tag>
        <n-tag v-if="passingItems" size="small" type="success">
          {{ passingItems }} passing
        </n-tag>
        <n-button
          quaternary
          :loading="webui.loading"
          title="Refresh setup checklist"
          @click="refreshOnboarding"
        >
          <template #icon>
            <RefreshCw :size="16" />
          </template>
          Refresh
        </n-button>
        <n-button
          quaternary
          :loading="dismissing"
          title="Dismiss setup checklist"
          @click="dismissChecklist"
        >
          <template #icon>
            <X :size="16" />
          </template>
          Dismiss
        </n-button>
      </div>
    </div>

    <div class="onboarding-check-list">
      <article
        v-for="item in items"
        :key="itemKey(item)"
        class="onboarding-check-row"
        :class="`status-${item.status.toLowerCase()}`"
      >
        <div class="onboarding-check-main">
          <component :is="statusIcon(item.status)" :size="18" aria-hidden="true" />
          <div>
            <div class="onboarding-check-title">
              <strong>{{ item.title }}</strong>
              <n-tag size="small" :type="statusTagType(item.status)">
                {{ statusLabel(item.status) }}
              </n-tag>
            </div>
            <p>{{ item.detail }}</p>
            <div v-if="item.check_codes.length" class="onboarding-check-codes">
              <code v-for="code in item.check_codes" :key="`${item.key}-${code}`">
                {{ code }}
              </code>
            </div>
          </div>
        </div>

        <div
          v-if="item.suggestions.length || item.docs.length"
          class="onboarding-check-help"
        >
          <div
            v-for="suggestion in item.suggestions"
            :key="`${item.key}-${suggestion.label}`"
            class="onboarding-suggestion"
          >
            <div>
              <strong>{{ suggestion.label }}</strong>
              <span v-if="suggestion.description">{{ suggestion.description }}</span>
              <code v-if="suggestion.snippet">{{ suggestion.snippet }}</code>
            </div>
            <n-button
              v-if="suggestion.snippet"
              quaternary
              :disabled="!isSupported"
              :title="`Copy ${suggestion.label}`"
              @click="copySuggestion(suggestion.snippet)"
            >
              <template #icon>
                <Copy :size="16" />
              </template>
              {{
                copied && copiedSnippet === suggestion.snippet ? "Copied" : "Copy"
              }}
            </n-button>
          </div>
          <div v-if="item.docs.length" class="onboarding-doc-links">
            <a
              v-for="doc in item.docs"
              :key="`${item.key}-${doc.url}`"
              :href="doc.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-link"
            >
              {{ doc.label }}
              <ExternalLink :size="14" />
            </a>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
