<script setup lang="ts">
import { computed, onMounted, ref, type Component } from "vue";
import { useClipboard } from "@vueuse/core";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  RefreshCw,
  Stethoscope,
  XCircle,
} from "@lucide/vue";
import { NAlert, NButton, NTag } from "naive-ui";

import type { DoctorCheck, DoctorCheckStatus } from "../api/client";
import { useConnectionStore } from "../stores/connection";

const connection = useConnectionStore();
const copiedSnippet = ref("");
const { copy, copied, isSupported } = useClipboard({ legacy: true });

const doctor = computed(() => connection.doctor);
const checks = computed(() => doctor.value?.checks ?? []);
const passCount = computed(
  () => checks.value.filter((check) => check.status === "PASS").length,
);
const groupedChecks = computed(() => {
  const groups = new Map<string, DoctorCheck[]>();
  for (const check of checks.value) {
    const key = check.category || "general";
    groups.set(key, [...(groups.get(key) ?? []), check]);
  }
  return [...groups.entries()].sort(([left], [right]) => {
    return categoryRank(left) - categoryRank(right) || left.localeCompare(right);
  });
});

onMounted(() => {
  if (connection.doctor === null) {
    void connection.loadDoctor().catch(() => undefined);
  }
});

async function refreshDoctor(): Promise<void> {
  await connection.loadDoctor();
}

async function copySuggestion(snippet: string): Promise<void> {
  if (!snippet.trim()) {
    return;
  }
  await copy(snippet);
  copiedSnippet.value = snippet;
}

function categoryRank(category: string): number {
  const order = [
    "configuration",
    "runtime",
    "docker",
    "paths",
    "compose",
    "webui",
    "truenas",
    "general",
  ];
  const index = order.indexOf(category);
  return index === -1 ? order.length : index;
}

function categoryLabel(category: string): string {
  if (category === "webui") {
    return "WebUI";
  }
  if (category === "truenas") {
    return "TrueNAS";
  }
  return category
    .split("-")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
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

function statusIcon(status: DoctorCheckStatus): Component {
  if (status === "PASS") {
    return CheckCircle2;
  }
  if (status === "WARN") {
    return AlertTriangle;
  }
  return XCircle;
}
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="connection.error" type="error" :show-icon="false">
      {{ connection.error }}
    </n-alert>

    <section class="section-panel">
      <div class="section-heading">
        <div class="section-heading-main">
          <p class="eyebrow">Deployment checks</p>
          <h2>Doctor results</h2>
          <p class="section-copy">
            Docker access, mounted paths, Compose rendering, database readiness, and
            browser safety checks from the same doctor logic used by the CLI.
          </p>
        </div>
        <div class="section-heading-meta">
          <n-tag v-if="doctor" size="small" :type="doctor.ok ? 'success' : 'error'">
            {{
              doctor.ok
                ? "No failures"
                : `${doctor.failures} failure${doctor.failures === 1 ? "" : "s"}`
            }}
          </n-tag>
          <n-button
            quaternary
            :loading="connection.loading"
            title="Refresh doctor results"
            @click="refreshDoctor"
          >
            <template #icon>
              <RefreshCw :size="17" />
            </template>
            Refresh
          </n-button>
          <Stethoscope :size="20" class="section-heading-icon" />
        </div>
      </div>

      <div v-if="!doctor && connection.loading" class="skeleton-list" aria-busy="true">
        <span class="sr-only">Loading doctor results.</span>
        <span aria-hidden="true" class="skeleton-row"></span>
        <span aria-hidden="true" class="skeleton-row"></span>
        <span aria-hidden="true" class="skeleton-row"></span>
      </div>
      <div v-else-if="doctor" class="summary-grid" aria-label="Doctor summary">
        <div class="summary-item">
          <span>Failures</span>
          <strong>{{ doctor.failures }}</strong>
        </div>
        <div class="summary-item">
          <span>Warnings</span>
          <strong>{{ doctor.warnings }}</strong>
        </div>
        <div class="summary-item">
          <span>Passing checks</span>
          <strong>{{ passCount }}</strong>
        </div>
        <div class="summary-item">
          <span>Total checks</span>
          <strong>{{ checks.length }}</strong>
        </div>
      </div>
    </section>

    <div v-if="doctor && !checks.length" class="empty-state">No doctor checks reported.</div>

    <section
      v-for="[category, groupChecks] in groupedChecks"
      :key="category"
      class="section-panel"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">{{ categoryLabel(category) }}</p>
          <h2>{{ groupChecks.length }} check{{ groupChecks.length === 1 ? "" : "s" }}</h2>
        </div>
      </div>

      <div class="doctor-check-list">
        <article
          v-for="check in groupChecks"
          :key="check.code"
          class="doctor-check-row"
          :class="`status-${check.status.toLowerCase()}`"
        >
          <div class="doctor-check-head">
            <div class="doctor-check-title">
              <component :is="statusIcon(check.status)" :size="18" aria-hidden="true" />
              <div>
                <strong>{{ check.name }}</strong>
                <code>{{ check.code }}</code>
              </div>
            </div>
            <n-tag size="small" :type="statusTagType(check.status)">
              {{ statusLabel(check.status) }}
            </n-tag>
          </div>

          <p v-if="check.detail" class="doctor-check-detail">{{ check.detail }}</p>

          <div v-if="check.suggestions.length" class="doctor-suggestion-list">
            <div
              v-for="suggestion in check.suggestions"
              :key="`${check.code}-${suggestion.label}`"
              class="doctor-suggestion"
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
                {{ copied && copiedSnippet === suggestion.snippet ? "Copied" : "Copy" }}
              </n-button>
            </div>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.doctor-check-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.doctor-check-row {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.doctor-check-row.status-warn {
  background: color-mix(in srgb, var(--color-panel-tint) 78%, #f6d57a 22%);
}

.doctor-check-row.status-fail {
  background: color-mix(in srgb, var(--color-surface) 88%, #c65454 12%);
}

.doctor-check-head,
.doctor-suggestion {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.doctor-check-title {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.doctor-check-title svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--color-operational-teal);
}

.doctor-check-row.status-warn .doctor-check-title svg {
  color: #9a640c;
}

.doctor-check-row.status-fail .doctor-check-title svg {
  color: #a73535;
}

.doctor-check-title>div,
.doctor-suggestion>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.doctor-check-title strong,
.doctor-suggestion strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.doctor-check-title code,
.doctor-suggestion code {
  min-width: 0;
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.doctor-check-detail,
.doctor-suggestion span {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.doctor-suggestion-list {
  display: grid;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border-subtle);
}

.doctor-suggestion {
  padding: 8px 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

@media (max-width: 560px) {
  .doctor-check-head,
  .doctor-suggestion {
    display: grid;
  }
}
</style>
