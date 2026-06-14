<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import { AlertTriangle, CheckCircle2, Info, Search } from "@lucide/vue";
import {
  NAlert,
  NButton,
  NDataTable,
  NInput,
  NSelect,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import type { RetagTargetItem } from "../api/client";
import { useUpdatesStore } from "../stores/updates";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../utils/digestProvenance";

type RetagFilter = "all" | "available" | "attention";
type TagType = "default" | "success" | "warning" | "error" | "info";

const updates = useUpdatesStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const searchQuery = ref("");
const statusFilter = ref<RetagFilter>("all");

const filterOptions = [
  { label: "All services", value: "all" },
  { label: "Retag available", value: "available" },
  { label: "Needs attention", value: "attention" },
];

const reasonLabels: Record<string, string> = {
  eligible: "Retag available",
  "missing-provenance": "Missing provenance",
  "not-latest-tracking": "Concrete tracking",
  "missing-concrete-tag": "Missing concrete tag",
  "missing-final-image": "Missing final image",
  "invalid-candidate-tag": "Invalid candidate tag",
  "stale-provenance": "Stale provenance",
  "unsupported-tracking-label": "Unsupported label",
};

const reasonDetails: Record<string, string> = {
  eligible: "A concrete tag and digest-pinned final image are available.",
  "missing-provenance": "No stored digest provenance is available for this service.",
  "not-latest-tracking": "This service already tracks a concrete tag.",
  "missing-concrete-tag": "Stored provenance does not include a concrete tag.",
  "missing-final-image": "Stored provenance is missing a digest or final image.",
  "invalid-candidate-tag": "The proposed tag is not a valid Docker tag value.",
  "stale-provenance": "Stored provenance does not match the current service image.",
  "unsupported-tracking-label": "The tracking label is not a single exact tag.",
};

const rows = computed(() => updates.retagTargets?.items ?? []);
const totalCount = computed(() => updates.retagTargets?.count ?? rows.value.length);
const availableCount = computed(
  () => rows.value.filter((item) => item.retag_available).length,
);
const attentionCount = computed(() => rows.value.length - availableCount.value);
const unavailable = computed(() => updates.retagTargets?.status === "unavailable");
const loaded = computed(() => updates.retagTargets !== null);
const initialLoading = computed(
  () => !loaded.value && !updates.error && updates.loading,
);
const initialLoadFailed = computed(
  () => !loaded.value && Boolean(updates.error) && !updates.loading,
);
const filteredRows = computed(() => {
  const query = searchQuery.value.trim().toLowerCase();
  return rows.value.filter((item) => {
    if (statusFilter.value === "available" && !item.retag_available) {
      return false;
    }
    if (statusFilter.value === "attention" && item.retag_available) {
      return false;
    }
    if (!query) {
      return true;
    }
    return searchableText(item).includes(query);
  });
});

const columns = computed<DataTableColumns<RetagTargetItem>>(() => [
  {
    title: "Service",
    key: "service_key",
    minWidth: 190,
    render: (row) =>
      h("div", { class: "retag-table-cell retag-service-cell" }, [
        h("strong", row.service_key),
        h("span", `${row.stack} / ${row.service}`),
      ]),
  },
  {
    title: "Current image",
    key: "image",
    minWidth: 230,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h("code", { class: "pending-table-value", title: row.image }, row.image),
        h("span", currentTagLabel(row)),
      ]),
  },
  {
    title: "Tracking",
    key: "tracking_tag",
    minWidth: 160,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h(
          NTag,
          { size: "small", type: trackingTagType(row), bordered: false },
          { default: () => trackingLabel(row) },
        ),
        h("span", trackingSourceLabel(row)),
      ]),
  },
  {
    title: "Candidate",
    key: "proposed_tag",
    minWidth: 220,
    render: (row) =>
      h("div", { class: "retag-table-cell" }, [
        h(
          NTag,
          { size: "small", type: reasonTagType(row), bordered: false },
          { default: () => reasonLabel(row.retag_reason) },
        ),
        h("span", candidateLabel(row)),
        row.final_image
          ? h(
              "code",
              { class: "pending-table-value", title: row.final_image },
              displayDigest(row.final_image),
            )
          : null,
      ]),
  },
  {
    title: "Evidence",
    key: "digest_provenance",
    minWidth: 230,
    render: (row) => {
      const display = digestProvenanceDisplay(row.digest_provenance);
      return h("div", { class: "retag-table-cell" }, [
        display
          ? h("span", { title: display.title }, display.primary)
          : h("span", "None"),
        display?.digest
          ? h("code", { class: "pending-table-value" }, display.digest)
          : null,
      ]);
    },
  },
  {
    title: "Default choice",
    key: "choices",
    minWidth: 150,
    render: (row) =>
      h("div", { class: "retag-choice-cell" }, [
        h(
          NTag,
          { size: "small", bordered: false },
          { default: () => "Keep current" },
        ),
        row.choices.includes("switch-to-concrete")
          ? h(
              NTag,
              { size: "small", type: "info", bordered: false },
              { default: () => "Candidate ready" },
            )
          : null,
      ]),
  },
]);

function rowKey(row: RetagTargetItem): string {
  return row.service_key;
}

function reasonLabel(code: string): string {
  return reasonLabels[code] ?? "Unavailable reason";
}

function reasonDetail(code: string): string {
  return reasonDetails[code] ?? "The backend did not provide a recognized reason.";
}

function reasonTagType(item: RetagTargetItem): TagType {
  if (item.retag_available) {
    return "success";
  }
  if (item.retag_reason === "stale-provenance" || item.retag_reason === "invalid-candidate-tag") {
    return "warning";
  }
  return "default";
}

function trackingTagType(item: RetagTargetItem): TagType {
  return item.tracking_tag === "latest" ? "info" : "default";
}

function trackingLabel(item: RetagTargetItem): string {
  return item.tracking_tag || "Unknown";
}

function trackingSourceLabel(item: RetagTargetItem): string {
  return item.tracking_tag_source
    ? `Source: ${item.tracking_tag_source}`
    : "Source unavailable";
}

function currentTagLabel(item: RetagTargetItem): string {
  return item.current_tag ? `Current tag: ${item.current_tag}` : "Current tag unavailable";
}

function candidateLabel(item: RetagTargetItem): string {
  if (item.retag_available) {
    return `latest -> ${item.proposed_tag}`;
  }
  return reasonDetail(item.retag_reason);
}

function composeLocation(item: RetagTargetItem): string {
  return [item.directory, item.compose_file].filter(Boolean).join("/");
}

function searchableText(item: RetagTargetItem): string {
  return [
    item.service_key,
    item.stack,
    item.service,
    item.image,
    item.image_repo,
    item.current_tag,
    item.tracking_tag,
    item.proposed_tag,
    item.final_image,
    item.retag_reason,
    reasonLabel(item.retag_reason),
    reasonDetail(item.retag_reason),
  ]
    .join(" ")
    .toLowerCase();
}

onMounted(() => {
  void updates.loadRetagTargets().catch(() => undefined);
});
</script>

<template>
  <section class="content-stack retag-review">
    <n-alert v-if="updates.error" type="error" :show-icon="false">
      {{ updates.error }}
    </n-alert>

    <n-alert
      v-for="warning in updates.retagTargets?.warnings ?? []"
      :key="warning"
      type="warning"
      :show-icon="false"
    >
      {{ warning }}
    </n-alert>

    <section class="section-panel retag-summary-panel">
      <div class="section-heading retag-heading">
        <div>
          <p class="eyebrow">Retag review</p>
          <h2>Compose service tracking</h2>
        </div>
        <div class="retag-preview-action">
          <n-button
            type="primary"
            size="small"
            disabled
            title="Retag preview and apply endpoints are not available yet"
          >
            Preview retag changes
          </n-button>
          <span>Preview/apply is not available in this frontend pass.</span>
        </div>
      </div>

      <div class="retag-summary-strip" aria-label="Retag review summary">
        <div>
          <span>Total services</span>
          <strong>{{ totalCount }}</strong>
        </div>
        <div>
          <span>Retag candidates</span>
          <strong>{{ availableCount }}</strong>
        </div>
        <div>
          <span>Needs attention</span>
          <strong>{{ attentionCount }}</strong>
        </div>
        <div>
          <span>Status</span>
          <strong>{{ unavailable ? "Unavailable" : "Ready" }}</strong>
        </div>
      </div>
    </section>

    <section class="section-panel retag-controls-panel">
      <div class="retag-controls">
        <n-input
          v-model:value="searchQuery"
          clearable
          placeholder="Search services, images, tags, or reasons"
          :input-props="{ 'aria-label': 'Search retag targets' }"
        >
          <template #prefix>
            <Search :size="16" aria-hidden="true" />
          </template>
        </n-input>
        <n-select
          v-model:value="statusFilter"
          class="filter-control"
          :options="filterOptions"
          aria-label="Retag status filter"
        />
      </div>
    </section>

    <div
      v-if="initialLoading"
      class="empty-state retag-state"
      role="status"
      aria-live="polite"
    >
      <Info :size="24" aria-hidden="true" />
      <strong>Loading retag targets</strong>
      <span>Reading discovered Compose services and stored digest provenance.</span>
    </div>

    <div
      v-else-if="initialLoadFailed"
      class="empty-state retag-state"
      role="alert"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Retag targets unavailable</strong>
      <span>The backend could not load retag review state.</span>
    </div>

    <div
      v-else-if="unavailable"
      class="empty-state retag-state"
      role="status"
      aria-live="polite"
    >
      <AlertTriangle :size="24" aria-hidden="true" />
      <strong>Compose discovery unavailable</strong>
      <span>Resolve the warning above, then refresh this view.</span>
    </div>

    <template v-else-if="updates.retagTargets">
      <div
        v-if="!rows.length"
        class="empty-state retag-state"
        role="status"
        aria-live="polite"
      >
        <CheckCircle2 :size="24" aria-hidden="true" />
        <strong>No Compose services found</strong>
        <span>Retag review has no discovered services to show.</span>
      </div>

      <div
        v-else-if="!filteredRows.length"
        class="empty-state retag-state"
        role="status"
        aria-live="polite"
      >
        <Info :size="24" aria-hidden="true" />
        <strong>No matches</strong>
        <span>Adjust the search text or status filter.</span>
      </div>

      <n-data-table
        v-else-if="!isMobile"
        :columns="columns"
        :data="filteredRows"
        :loading="updates.loading"
        :pagination="{ pageSize: 15 }"
        :row-key="rowKey"
        size="small"
        class="data-surface"
      />

      <div v-else class="mobile-list">
        <article
          v-for="item in filteredRows"
          :key="item.service_key"
          class="mobile-card retag-card"
        >
          <div class="mobile-card-title">
            <div class="retag-card-title">
              <strong>{{ item.service_key }}</strong>
              <span>{{ item.stack }} / {{ item.service }}</span>
            </div>
            <n-tag
              size="small"
              :type="reasonTagType(item)"
              :bordered="false"
            >
              {{ reasonLabel(item.retag_reason) }}
            </n-tag>
          </div>
          <dl>
            <div>
              <dt>Image</dt>
              <dd>
                <code>{{ item.image }}</code>
              </dd>
            </div>
            <div>
              <dt>Tracking</dt>
              <dd>{{ trackingLabel(item) }} ({{ item.tracking_tag_source || "unknown" }})</dd>
            </div>
            <div>
              <dt>Candidate</dt>
              <dd>{{ candidateLabel(item) }}</dd>
            </div>
            <div>
              <dt>Final image</dt>
              <dd>
                <code>{{ item.final_image ? displayDigest(item.final_image) : "None" }}</code>
              </dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>
                <code>{{ composeLocation(item) }}</code>
              </dd>
            </div>
            <div>
              <dt>Choice</dt>
              <dd>Keep current</dd>
            </div>
          </dl>
        </article>
      </div>
    </template>
  </section>
</template>
