<script setup lang="ts">
import { computed, onMounted, ref, type Component } from "vue";
import { useClipboard } from "@vueuse/core";
import { useRouter } from "vue-router";
import {
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Map,
  RefreshCw,
  XCircle,
  X,
} from "@lucide/vue";
import { NButton, NFlex, NTag } from "naive-ui";

import type { DoctorCheckStatus, OnboardingChecklistItem } from "../api/client";
import { useCompactBreakpoint } from "../responsive";
import { useSettingsStore } from "../stores/settings";
import { runInBackground } from "../utils/promises";

const settings = useSettingsStore();
const router = useRouter();
const copiedSnippet = ref("");
const dismissing = ref(false);
const { copy, copied, isSupported } = useClipboard({ legacy: true });
const compactActions = useCompactBreakpoint();
const tourRouteByStep = {
  dashboard: "dashboard",
  pending_select: "pending",
  pending_preflight: "pending",
  pending_apply: "pending",
  runs_history: "runs",
} as const;

const onboarding = computed(() => settings.onboarding);
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
const firstFailingItem = computed(
  () => items.value.find((item) => item.status === "FAIL") ?? null,
);
const firstWarningItem = computed(
  () =>
    items.value.find((item) => item.status === "WARN" && item.key !== "mutation-mode") ??
    null,
);
const canStartUpdateTour = computed(() => failingItems.value === 0);
const tourStep = computed(() =>
  settings.coreUpdateTour?.status === "in_progress"
    ? settings.coreUpdateTour.step
    : "dashboard",
);
const tourActionLabel = computed(() =>
  settings.coreUpdateTour?.status === "in_progress"
    ? "Resume update tour"
    : "Start update tour",
);
const nextActionTitle = computed(() => nextChecklistActionTitle());
const nextActionDetail = computed(() => nextChecklistActionDetail());

onMounted(() => {
  if (settings.onboarding === null) {
    runInBackground(refreshOnboarding());
  }
  runInBackground(settings.ensureCoreUpdateTour());
});

function nextChecklistActionTitle(): string {
  if (firstFailingItem.value) {
    return `Next: fix ${firstFailingItem.value.title.toLowerCase()}`;
  }
  if (firstWarningItem.value) {
    return "Setup has warnings, update tour is available";
  }
  return "Setup is ready for the update tour";
}

function nextChecklistActionDetail(): string {
  if (firstFailingItem.value) {
    return firstFailingItem.value.detail;
  }
  if (firstWarningItem.value) {
    return `${firstWarningItem.value.detail} You can still follow the tour while resolving this warning.`;
  }
  return "Use the core update tour to review pending updates, preview a plan, apply only when browser mutations are enabled, and verify the run log.";
}

async function refreshOnboarding(): Promise<void> {
  await settings.loadOnboarding();
}

async function dismissChecklist(): Promise<void> {
  dismissing.value = true;
  try {
    await settings.dismissOnboarding();
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

async function startUpdateTour(): Promise<void> {
  await settings.updateCoreUpdateTour("in_progress", tourStep.value);
  await router?.push({ name: tourRouteByStep[tourStep.value] });
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

function normalizedCode(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function primaryCheckCodes(item: OnboardingChecklistItem): string[] {
  if (item.status === "PASS") {
    return item.check_codes;
  }
  const detailCode = normalizedCode(item.detail);
  return item.check_codes.filter((code) => detailCode.includes(code));
}

function diagnosticCheckCodes(item: OnboardingChecklistItem): string[] {
  if (item.status === "PASS") {
    return [];
  }
  const primary = new Set(primaryCheckCodes(item));
  return item.check_codes.filter((code) => !primary.has(code));
}

function primaryCheckCodeLabel(item: OnboardingChecklistItem): string {
  if (item.status === "WARN") {
    return "Warning check codes";
  }
  if (item.status === "FAIL") {
    return "Failed check codes";
  }
  return "Verified check codes";
}

function sourceCheckSummaryLabel(item: OnboardingChecklistItem): string {
  const count = item.check_codes.length;
  return `Source check codes (${count})`;
}
</script>

<template>
  <section
    v-if="visible"
    id="onboarding-checklist"
    class="section-panel onboarding-panel"
    tabindex="-1"
  >
    <div class="section-heading onboarding-heading">
      <div class="section-heading-main">
        <p class="eyebrow">First run</p>
        <h2>Setup checklist</h2>
        <p class="section-copy">
          Confirm the WebUI can see WUD output, Docker, Compose stacks, persistent
          state, and the intended browser safety mode.
        </p>
      </div>
      <n-flex
        class="section-heading-meta onboarding-actions"
        align="center"
        :justify="compactActions ? 'flex-start' : 'flex-end'"
        :size="8"
      >
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
          :loading="settings.loading"
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
      </n-flex>
    </div>

    <div
      class="onboarding-next-action"
      :class="{ 'is-ready': canStartUpdateTour }"
    >
      <div class="onboarding-next-main">
        <component
          :is="canStartUpdateTour ? Map : AlertTriangle"
          :size="18"
          aria-hidden="true"
        />
        <div>
          <strong>{{ nextActionTitle }}</strong>
          <span>{{ nextActionDetail }}</span>
        </div>
      </div>
      <n-button
        v-if="canStartUpdateTour"
        type="primary"
        size="small"
        :loading="settings.loading"
        @click="startUpdateTour"
      >
        <template #icon>
          <ArrowRight :size="16" />
        </template>
        {{ tourActionLabel }}
      </n-button>
      <n-button
        v-else
        size="small"
        secondary
        :loading="settings.loading"
        @click="refreshOnboarding"
      >
        <template #icon>
          <RefreshCw :size="16" />
        </template>
        Recheck setup
      </n-button>
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
            <div
              v-if="primaryCheckCodes(item).length"
              class="onboarding-check-code-group"
            >
              <span>{{ primaryCheckCodeLabel(item) }}</span>
              <div class="onboarding-check-codes is-primary">
                <code
                  v-for="code in primaryCheckCodes(item)"
                  :key="`${item.key}-${code}`"
                >
                  {{ code }}
                </code>
              </div>
            </div>
            <details
              v-if="diagnosticCheckCodes(item).length"
              class="onboarding-check-diagnostics"
            >
              <summary>{{ sourceCheckSummaryLabel(item) }}</summary>
              <div class="onboarding-check-codes">
                <code v-for="code in diagnosticCheckCodes(item)" :key="`${item.key}-${code}`">
                  {{ code }}
                </code>
              </div>
            </details>
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

<style scoped>
.onboarding-panel {
  border-color: color-mix(in srgb, var(--color-border) 72%, var(--color-operational-teal) 28%);
}

.onboarding-heading {
  align-items: flex-start;
}

.onboarding-heading .section-heading-main {
  flex: 1 1 240px;
}

.onboarding-actions {
  flex: 0 1 430px;
  max-width: 100%;
  min-width: min(100%, 240px);
}

.onboarding-next-action {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.onboarding-next-action.is-ready {
  border-color: color-mix(in srgb, var(--color-border) 74%, var(--color-action-blue) 26%);
  background: color-mix(in srgb, var(--color-surface) 92%, var(--color-action-blue) 8%);
}

.onboarding-next-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.onboarding-next-main>svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--color-warning);
}

.onboarding-next-action.is-ready .onboarding-next-main>svg {
  color: var(--color-action-blue);
}

.onboarding-next-main>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.onboarding-next-main strong,
.onboarding-next-main span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.onboarding-next-main span {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.onboarding-check-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.onboarding-check-row {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.onboarding-check-row.status-warn {
  background: color-mix(in srgb, var(--color-panel-tint) 78%, #f6d57a 22%);
}

.onboarding-check-row.status-fail {
  background: color-mix(in srgb, var(--color-surface) 88%, #c65454 12%);
}

.onboarding-check-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.onboarding-check-main>svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--color-operational-teal);
}

.onboarding-check-row.status-warn .onboarding-check-main>svg {
  color: #9a640c;
}

.onboarding-check-row.status-fail .onboarding-check-main>svg {
  color: #a73535;
}

.onboarding-check-main>div {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.onboarding-check-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.onboarding-check-title strong,
.onboarding-check-main p,
.onboarding-suggestion strong,
.onboarding-suggestion span,
.onboarding-suggestion code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.onboarding-check-main p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.onboarding-check-code-group {
  display: grid;
  gap: 5px;
}

.onboarding-check-code-group>span,
.onboarding-check-diagnostics summary {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  font-weight: 700;
  line-height: 1.2;
}

.onboarding-check-codes,
.onboarding-doc-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.onboarding-check-codes code {
  padding: 2px 6px;
  border-radius: 999px;
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.76rem;
  background: var(--color-panel-tint);
}

.onboarding-check-codes.is-primary code {
  border: 1px solid var(--color-border-subtle);
}

.onboarding-check-row.status-fail .onboarding-check-codes.is-primary code {
  border-color: color-mix(in srgb, var(--color-border) 58%, #a73535 42%);
  background: color-mix(in srgb, var(--color-surface) 80%, #c65454 20%);
}

.onboarding-check-row.status-warn .onboarding-check-codes.is-primary code {
  border-color: color-mix(in srgb, var(--color-border) 58%, #9a640c 42%);
  background: color-mix(in srgb, var(--color-surface) 78%, #f6d57a 22%);
}

.onboarding-check-diagnostics {
  display: grid;
  gap: 7px;
  margin-top: 2px;
}

.onboarding-check-diagnostics summary {
  width: fit-content;
  cursor: pointer;
}

.onboarding-check-diagnostics summary:hover,
.onboarding-check-diagnostics summary:focus-visible {
  color: var(--color-ink);
}

.onboarding-check-diagnostics summary:focus-visible {
  outline: 2px solid var(--color-action-blue);
  outline-offset: 2px;
  border-radius: 4px;
}

.onboarding-check-diagnostics[open] .onboarding-check-codes {
  padding-top: 2px;
}

.onboarding-check-help {
  display: grid;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border-subtle);
}

.onboarding-suggestion {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.onboarding-suggestion>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.onboarding-suggestion span {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.onboarding-suggestion code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
  line-height: 1.45;
  white-space: pre-wrap;
}

.onboarding-doc-links .text-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

@media (--wud-compact) {
  .onboarding-suggestion,
  .onboarding-next-action {
    display: grid;
  }
}
</style>
