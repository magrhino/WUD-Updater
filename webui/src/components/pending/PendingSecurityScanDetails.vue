<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useClipboard } from "@vueuse/core";
import { Copy } from "@lucide/vue";
import { NButton, NPagination, NSelect, NTag } from "naive-ui";

import type { SecurityScanFinding, SecurityScanInfo } from "../../api/client";
import { securityScanMaintainerReport } from "../../utils/securityScans";
import { pluralize } from "../../views/pending/utils";

type TagType = "default" | "error" | "info" | "success" | "warning";
type Severity = SecurityScanFinding["severity"];
type SeverityFilter = Severity | "all";

const props = defineProps<{
  scan: SecurityScanInfo;
}>();

const findingPageSize = 10;
const severityOrder: Severity[] = ["critical", "high", "medium", "low", "unknown"];
const selectedSeverity = ref<SeverityFilter>("all");
const findingPage = ref(1);
const { copy, copied, isSupported } = useClipboard({ legacy: true });

const comparison = computed(() => props.scan.comparison);
const reportText = computed(() => securityScanMaintainerReport(props.scan));
const reportAvailable = computed(() => Boolean(reportText.value));
const currentDigest = computed(
  () =>
    comparison.value.current_subject.manifest_digest ||
    comparison.value.current_subject.reported_digest,
);
const candidateDigest = computed(
  () => props.scan.subject.manifest_digest || props.scan.subject.reported_digest,
);
const comparisonDigestVisible = computed(
  () => Boolean(currentDigest.value || candidateDigest.value || props.scan.subject.platform),
);
const comparisonVisible = computed(() => Boolean(comparison.value.message));
const fixedCount = computed(() => comparison.value.fixed_findings.length);
const remainingCount = computed(() => comparison.value.remaining_findings.length);
const introducedCount = computed(() => comparison.value.introduced_findings.length);
const comparisonFindingCountsVisible = computed(
  () => Boolean(fixedCount.value || remainingCount.value || introducedCount.value),
);
const visible = computed(
  () =>
    props.scan.verdict === "findings" ||
    props.scan.warnings.length > 0 ||
    Boolean(props.scan.error_message) ||
    comparisonVisible.value,
);
const fixableTotal = computed(() =>
  severityOrder.reduce((total, severity) => total + props.scan.fixable_counts[severity], 0),
);
const severityItems = computed(() =>
  severityOrder
    .map((severity) => ({
      count: props.scan.severity_counts[severity],
      severity,
    }))
    .filter((item) => item.count > 0),
);
const findingsTagType = computed<TagType>(() =>
  severityItems.value.some(
    (item) => item.severity === "critical" || item.severity === "high",
  )
    ? "error"
    : "warning",
);
const findingCount = computed(
  () =>
    props.scan.findings.length ||
    severityItems.value.reduce((total, item) => total + item.count, 0),
);
const severityFilterTotal = computed(() =>
  severityItems.value.reduce((total, item) => total + item.count, 0),
);
const severityFilterOptions = computed(() => [
  {
    label: `All categories (${severityFilterTotal.value})`,
    value: "all",
  },
  ...severityItems.value.map((item) => ({
    label: `${titleCase(item.severity)} (${item.count})`,
    value: item.severity,
  })),
]);
const filteredFindings = computed(() =>
  selectedSeverity.value === "all"
    ? props.scan.findings
    : props.scan.findings.filter((finding) => finding.severity === selectedSeverity.value),
);
const pagedFindings = computed(() => {
  const start = (findingPage.value - 1) * findingPageSize;
  return filteredFindings.value.slice(start, start + findingPageSize);
});
const findingPageCount = computed(() =>
  Math.max(1, Math.ceil(filteredFindings.value.length / findingPageSize)),
);
const findingPageStart = computed(() =>
  filteredFindings.value.length ? (findingPage.value - 1) * findingPageSize + 1 : 0,
);
const findingPageEnd = computed(() =>
  Math.min(findingPage.value * findingPageSize, filteredFindings.value.length),
);
const showFindingControls = computed(
  () =>
    severityItems.value.length > 1 ||
    filteredFindings.value.length > findingPageSize,
);
const comparisonTagType = computed<TagType>(() => {
  if (comparison.value.status === "improved") {
    return "success";
  }
  if (comparison.value.status === "worse") {
    return "error";
  }
  if (comparison.value.status === "mixed") {
    return "warning";
  }
  if (comparison.value.status === "unchanged") {
    return remainingCount.value > 0 ? "warning" : "success";
  }
  return "default";
});

watch(
  [selectedSeverity, () => props.scan],
  () => {
    if (
      selectedSeverity.value !== "all" &&
      !severityItems.value.some((item) => item.severity === selectedSeverity.value)
    ) {
      selectedSeverity.value = "all";
    }
    findingPage.value = 1;
  },
);

function severityType(severity: Severity): TagType {
  if (severity === "critical" || severity === "high") {
    return "error";
  }
  if (severity === "medium") {
    return "warning";
  }
  if (severity === "low") {
    return "info";
  }
  return "default";
}

function titleCase(value: string): string {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Unknown";
}

function findingTitle(finding: SecurityScanFinding): string {
  return finding.vulnerability_id || finding.package_name || "Unknown advisory";
}

async function copyReport(): Promise<void> {
  if (!reportText.value) {
    return;
  }
  await copy(reportText.value);
}
</script>

<template>
  <section
    v-if="visible"
    class="security-review"
    aria-label="Security scan review"
  >
    <div class="security-review-header">
      <strong>Security scan</strong>
      <n-tag
        v-if="scan.verdict === 'findings'"
        size="small"
        :type="findingsTagType"
      >
        {{ pluralize(findingCount, "finding") }}
      </n-tag>
    </div>

    <div
      v-if="comparisonVisible"
      class="security-comparison"
      aria-label="Security scan update comparison"
    >
      <div class="security-comparison-header">
        <strong>Update comparison</strong>
        <n-tag size="small" :type="comparisonTagType">
          {{ titleCase(comparison.status) }}
        </n-tag>
        <n-button
          v-if="reportAvailable"
          size="small"
          tertiary
          :disabled="!isSupported"
          title="Copy security scan report"
          @click="copyReport"
        >
          <template #icon>
            <Copy :size="15" />
          </template>
          {{ copied ? "Copied" : "Copy report" }}
        </n-button>
      </div>
      <p class="security-review-meta wrap-anywhere">
        {{ comparison.message }}
      </p>
      <div
        v-if="comparisonFindingCountsVisible"
        class="security-comparison-counts"
      >
        <n-tag v-if="fixedCount" size="small" type="success">
          {{ pluralize(fixedCount, "fixed finding") }}
        </n-tag>
        <n-tag v-if="remainingCount" size="small" type="warning">
          {{ pluralize(remainingCount, "remaining finding") }}
        </n-tag>
        <n-tag v-if="introducedCount" size="small" type="error">
          {{ pluralize(introducedCount, "introduced finding") }}
        </n-tag>
      </div>
      <dl v-if="comparisonDigestVisible" class="security-comparison-digests">
        <div>
          <dt>Installed</dt>
          <dd class="wrap-anywhere" :title="currentDigest">
            {{ currentDigest || "Unknown" }}
          </dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd class="wrap-anywhere" :title="candidateDigest">
            {{ candidateDigest || "Unknown" }}
          </dd>
        </div>
        <div>
          <dt>Platform</dt>
          <dd class="wrap-anywhere">{{ scan.subject.platform || "Unknown" }}</dd>
        </div>
      </dl>
    </div>

    <div v-if="severityItems.length" class="security-counts" aria-label="Severity counts">
      <n-tag
        v-for="item in severityItems"
        :key="item.severity"
        size="small"
        :type="severityType(item.severity)"
      >
        {{ item.count }} {{ titleCase(item.severity) }}
      </n-tag>
      <span class="security-count-note">
        {{ pluralize(fixableTotal, "fixable finding") }}
      </span>
      <span v-if="scan.unfixed_count" class="security-count-note">
        {{ pluralize(scan.unfixed_count, "unfixed") }}
      </span>
    </div>

    <p v-if="scan.scanned_at" class="security-review-meta wrap-anywhere">
      {{ scan.scanner || "Scanner" }} {{ scan.scanner_version }}
      scanned {{ scan.scanned_at }}
      <template v-if="scan.db_updated_at">with DB {{ scan.db_updated_at }}</template>
    </p>

    <p v-if="scan.error_message" class="security-review-message wrap-anywhere">
      {{ scan.error_message }}
    </p>

    <ul v-if="scan.warnings.length" class="security-review-warnings">
      <li v-for="warning in scan.warnings" :key="warning" class="wrap-anywhere">
        {{ warning }}
      </li>
    </ul>

    <p
      v-if="scan.verdict === 'findings' && !scan.findings.length"
      class="security-review-meta"
    >
      This cached scan only has summary counts. Refresh scans to collect vulnerability rows.
    </p>

    <div v-if="scan.findings.length && showFindingControls" class="security-finding-controls">
      <n-select
        v-if="severityItems.length > 1"
        v-model:value="selectedSeverity"
        class="security-finding-filter"
        size="small"
        :options="severityFilterOptions"
        aria-label="Security finding category filter"
      />
      <span class="security-review-meta">
        Showing {{ findingPageStart }}-{{ findingPageEnd }} of
        {{ pluralize(filteredFindings.length, "finding") }}
      </span>
    </div>

    <div v-if="scan.findings.length" class="security-finding-list">
      <article
        v-for="finding in pagedFindings"
        :key="`${finding.vulnerability_id}-${finding.package_name}`"
        class="security-finding-row"
      >
        <div class="security-finding-heading">
          <strong class="wrap-anywhere">{{ findingTitle(finding) }}</strong>
          <n-tag size="small" :type="severityType(finding.severity)">
            {{ titleCase(finding.severity) }}
          </n-tag>
          <a
            v-if="finding.primary_url"
            class="text-link"
            :href="finding.primary_url"
            target="_blank"
            rel="noopener noreferrer"
          >
            Advisory
          </a>
        </div>
        <p v-if="finding.title" class="security-finding-title wrap-anywhere">
          {{ finding.title }}
        </p>
        <dl class="security-finding-meta">
          <div>
            <dt>Package</dt>
            <dd class="wrap-anywhere">{{ finding.package_name || "Unknown" }}</dd>
          </div>
          <div>
            <dt>Installed</dt>
            <dd class="wrap-anywhere">{{ finding.installed_version || "Unknown" }}</dd>
          </div>
          <div>
            <dt>Fixed</dt>
            <dd class="wrap-anywhere">{{ finding.fixed_version || "Not published" }}</dd>
          </div>
        </dl>
      </article>
    </div>

    <n-pagination
      v-if="filteredFindings.length > findingPageSize"
      v-model:page="findingPage"
      size="small"
      :page-count="findingPageCount"
      :page-slot="5"
    />
  </section>
</template>

<style scoped>
.security-review {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.security-review-header,
.security-comparison-header,
.security-comparison-counts,
.security-counts,
.security-finding-controls,
.security-finding-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  min-width: 0;
}

.security-finding-controls {
  justify-content: space-between;
}

.security-comparison {
  display: grid;
  gap: 6px;
  padding: 8px 0;
  border-top: 1px solid var(--color-border-subtle);
  border-bottom: 1px solid var(--color-border-subtle);
}

.security-comparison-header {
  justify-content: space-between;
}

.security-comparison-digests {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 6px 12px;
  margin: 0;
  color: var(--color-muted-text);
  font-size: 0.78rem;
}

.security-comparison-digests div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.security-comparison-digests dt {
  font-weight: 700;
}

.security-comparison-digests dd {
  margin: 0;
  color: var(--color-ink);
}

.security-finding-filter {
  width: 180px;
}

.security-count-note,
.security-review-meta,
.security-review-message,
.security-review-warnings,
.security-finding-title,
.security-finding-meta {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

.security-review-message {
  margin: 0;
  color: var(--color-error-fg);
}

.security-review-warnings {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
}

.security-finding-list {
  display: grid;
  gap: 8px;
}

.security-finding-row {
  display: grid;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.security-finding-title {
  margin: 0;
}

.security-finding-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 6px 12px;
  margin: 0;
}

.security-finding-meta div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.security-finding-meta dt {
  font-weight: 700;
}

.security-finding-meta dd {
  margin: 0;
  color: var(--color-ink);
}
</style>
