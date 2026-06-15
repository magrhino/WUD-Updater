<script setup lang="ts">
import { NTag } from "naive-ui";

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
    <div class="panel-subheading">
      <strong>{{ title || "Verification" }}</strong>
      <n-tag size="small" :type="overallTagType(verification.status)">
        {{ overallLabel(verification.status) }}
      </n-tag>
    </div>
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
