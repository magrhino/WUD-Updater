<script setup lang="ts">
import { NFlex, NTag } from "naive-ui";

import type {
  RunVerificationContainerStatus,
  RunVerificationHealthStatus,
  RunVerificationImageStatus,
  RunVerificationSummary,
  RunVerificationWudStatus,
} from "../api/client";

type TagType = "default" | "error" | "info" | "success" | "warning";

defineProps<{
  verification: RunVerificationSummary;
  title?: string;
}>();

function overallLabel(status: RunVerificationSummary["status"]): string {
  return status === "verified" ? "Verified" : "Needs review";
}

function overallTagType(status: RunVerificationSummary["status"]): TagType {
  return status === "verified" ? "success" : "warning";
}

function statusTagType(status: string): TagType {
  if (
    status === "failed" ||
    status === "timed_out" ||
    status === "service_disappeared" ||
    status === "restored" ||
    status === "stale_removed"
  ) {
    return "error";
  }
  if (status === "unknown") {
    return "warning";
  }
  if (
    status === "new_image_running" ||
    status === "recreated" ||
    status === "passed" ||
    status === "removed"
  ) {
    return "success";
  }
  return "default";
}

function fallbackStatusLabel(status: string): string {
  return status || "Unknown";
}

function imageLabel(status: RunVerificationImageStatus): string {
  return {
    new_image_running: "New image running",
    already_current: "Already current",
    failed: "Image failed",
    unknown: "Image unknown",
  }[status] ?? fallbackStatusLabel(status);
}

function containerLabel(status: RunVerificationContainerStatus): string {
  return {
    recreated: "Recreated",
    skipped: "Recreate skipped",
    failed: "Recreate failed",
    unknown: "Container unknown",
  }[status] ?? fallbackStatusLabel(status);
}

function healthLabel(status: RunVerificationHealthStatus): string {
  return {
    passed: "Health passed",
    skipped: "Health skipped",
    timed_out: "Health timed out",
    service_disappeared: "Service disappeared",
    failed: "Health failed",
    unknown: "Health unknown",
  }[status] ?? fallbackStatusLabel(status);
}

function wudLabel(status: RunVerificationWudStatus): string {
  return {
    removed: "WUD line removed",
    restored: "WUD line restored",
    stale_removed: "Stale line removed",
    removed_before_run: "Removed before run",
    unknown: "WUD line unknown",
  }[status] ?? fallbackStatusLabel(status);
}
</script>

<template>
  <section
    v-if="verification.items.length"
    class="run-verification-panel"
    aria-label="Post-update verification"
  >
    <n-flex class="panel-subheading" align="center" justify="space-between" :size="8">
      <strong>{{ title || "Verification" }}</strong>
      <n-tag size="small" :type="overallTagType(verification.status)">
        {{ overallLabel(verification.status) }}
      </n-tag>
    </n-flex>
    <div class="run-verification-summary">
      <span>{{ verification.verified_count }} verified</span>
      <span v-if="verification.needs_review_count">
        {{ verification.needs_review_count }} need review
      </span>
    </div>
    <div class="run-verification-list">
      <article
        v-for="item in verification.items"
        :key="`${item.line_no}-${item.service_key}-${item.image}`"
        class="run-verification-row"
      >
        <div class="run-verification-main">
          <span>#{{ item.line_no }}</span>
          <strong>{{ item.service_key || item.service_name || item.image }}</strong>
          <em>{{ item.target_image || item.image }}</em>
        </div>
        <div class="run-verification-tags">
          <n-tag size="small" :type="statusTagType(item.image_status)">
            {{ imageLabel(item.image_status) }}
          </n-tag>
          <n-tag size="small" :type="statusTagType(item.container_status)">
            {{ containerLabel(item.container_status) }}
          </n-tag>
          <n-tag size="small" :type="statusTagType(item.health_status)">
            {{ healthLabel(item.health_status) }}
          </n-tag>
          <n-tag size="small" :type="statusTagType(item.wud_status)">
            {{ wudLabel(item.wud_status) }}
          </n-tag>
          <n-tag
            size="small"
            :type="item.follow_up_needed ? 'warning' : 'success'"
          >
            {{ item.follow_up_needed ? "Follow-up needed" : "No follow-up" }}
          </n-tag>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.run-verification-panel {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.run-verification-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  color: var(--color-muted-text);
  font-size: 0.8rem;
}

.run-verification-list {
  display: grid;
  gap: 8px;
}

.run-verification-row {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.run-verification-main {
  display: grid;
  grid-template-columns: auto minmax(0, 0.75fr) minmax(0, 1.25fr);
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.run-verification-main span {
  color: var(--color-muted-text);
  font-size: 0.8rem;
  font-weight: 700;
}

.run-verification-main strong {
  min-width: 0;
  color: var(--color-ink);
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.run-verification-main em {
  min-width: 0;
  color: var(--color-muted-text);
  font-size: 0.8rem;
  font-style: normal;
  overflow-wrap: anywhere;
}

.run-verification-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

@media (max-width: 920px) {
  .run-verification-main {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .run-verification-main em {
    grid-column: 2;
  }
}
</style>
