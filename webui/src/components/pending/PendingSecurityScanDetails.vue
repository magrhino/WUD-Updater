<script setup lang="ts">
import { computed } from "vue";
import { NTag } from "naive-ui";

import type { SecurityScanFinding, SecurityScanInfo } from "../../api/client";
import { pluralize } from "../../views/pending/utils";

type TagType = "default" | "error" | "info" | "success" | "warning";
type Severity = SecurityScanFinding["severity"];

const props = defineProps<{
  scan: SecurityScanInfo;
}>();

const severityOrder: Severity[] = ["critical", "high", "medium", "low", "unknown"];

const visible = computed(
  () =>
    props.scan.verdict === "findings" ||
    props.scan.warnings.length > 0 ||
    Boolean(props.scan.error_message),
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

    <div v-if="scan.findings.length" class="security-finding-list">
      <article
        v-for="finding in scan.findings"
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
.security-counts,
.security-finding-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  min-width: 0;
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
