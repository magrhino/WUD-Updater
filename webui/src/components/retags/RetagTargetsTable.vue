<script setup lang="ts">
import { computed, h } from "vue";
import {
  NDataTable,
  NRadioButton,
  NRadioGroup,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../../utils/digestProvenance";
import {
  candidateLabel,
  currentTagLabel,
  reasonDetail,
  reasonLabel,
  reasonTagType,
  trackingLabel,
  trackingSourceLabel,
  trackingTagType,
} from "../../views/retags/display";

const props = defineProps<{
  rows: RetagTargetItem[];
  loading: boolean;
  choices: Record<string, RetagTargetChoice>;
  mutationDisabled: boolean;
  mutationNotice: string;
}>();

const emit = defineEmits<{
  "choice-update": [item: RetagTargetItem, choice: RetagTargetChoice];
}>();

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
    title: "Choice",
    key: "choices",
    minWidth: 230,
    render: (row) =>
      h("div", { class: "retag-choice-cell" }, [
        h(
          NRadioGroup,
          {
            value: retagChoice(row),
            size: "small",
            onUpdateValue: (value: string) => emitRetagChoice(row, value),
          },
          {
            default: () => [
              h(
                NRadioButton,
                { value: "keep-current" },
                { default: () => "Keep" },
              ),
              h(
                NRadioButton,
                {
                  value: "switch-to-concrete",
                  disabled:
                    !canSwitchToConcrete(row) || props.mutationDisabled,
                  title:
                    canSwitchToConcrete(row)
                      ? props.mutationNotice
                      : reasonDetail(row.retag_reason),
                },
                { default: () => "Switch" },
              ),
            ],
          },
        ),
        canSwitchToConcrete(row)
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

function retagChoice(item: RetagTargetItem): RetagTargetChoice {
  return props.choices[item.service_key] ?? "keep-current";
}

function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

function emitRetagChoice(item: RetagTargetItem, choice: string): void {
  if (choice !== "keep-current" && choice !== "switch-to-concrete") {
    return;
  }
  emit("choice-update", item, choice);
}
</script>

<template>
  <n-data-table
    :columns="columns"
    :data="rows"
    :loading="loading"
    :pagination="{ pageSize: 15 }"
    :row-key="rowKey"
    size="small"
    class="data-surface"
  />
</template>
