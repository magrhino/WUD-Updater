<script setup lang="ts">
import { computed, h } from "vue";
import {
  NDataTable,
  NInput,
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
  canChooseRetagTarget,
  canEnableRetagTargetChoice,
  canSwitchToConcrete,
  emitRetagChoice,
  retagChoice,
  retagTargetTagValidationError,
  retagTargetTagValue,
} from "./retagChoices";
import {
  candidateLabel,
  currentTagLabel,
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
  targetTags: Record<string, string>;
  mutationDisabled: boolean;
  mutationNotice: string;
}>();

const emit = defineEmits<{
  "choice-update": [item: RetagTargetItem, choice: RetagTargetChoice];
  "target-tag-update": [item: RetagTargetItem, tag: string];
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
    render: (row) => {
      const candidateText = candidateLabel(row);
      return h("div", { class: "retag-table-cell" }, [
        h(
          NTag,
          { size: "small", type: reasonTagType(row), bordered: false },
          { default: () => reasonLabel(row.retag_reason) },
        ),
        h("span", candidateText),
        row.candidate_link_url
          ? h(
              "a",
              {
                class: "text-link retag-source-link",
                href: row.candidate_link_url,
                target: "_blank",
                rel: "noreferrer",
              },
              row.candidate_link_label || "Open source",
            )
          : null,
        row.candidate_warning
          ? h("span", { class: "release-notes-reason" }, row.candidate_warning)
          : null,
        row.final_image
          ? h(
              "code",
              { class: "pending-table-value", title: row.final_image },
              displayDigest(row.final_image),
            )
          : null,
      ]);
    },
  },
  {
    title: "Target tag",
    key: "target_tag",
    minWidth: 180,
    render: (row) => {
      const error =
        retagChoice(row, props.choices, props.targetTags) === "switch-to-concrete"
          ? retagTargetTagValidationError(row, props.targetTags)
          : "";
      return h("div", { class: "retag-table-cell retag-target-tag-cell" }, [
        h(NInput, {
          value: retagTargetTagValue(row, props.targetTags),
          size: "small",
          class: "tag-override-input retag-target-input",
          placeholder: row.proposed_tag || "Enter tag",
          disabled: props.mutationDisabled,
          status: error ? "error" : undefined,
          title: error || undefined,
          inputProps: {
            "aria-label": `Target tag for ${row.service_key}`,
          },
          onUpdateValue: (value: string) =>
            emit("target-tag-update", row, value),
        }),
        error ? h("span", { class: "retag-input-error" }, error) : null,
      ]);
    },
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
    render: (row) => {
      const canChooseTarget = canChooseRetagTarget(row, props.targetTags);
      const targetError = canChooseTarget
        ? retagTargetTagValidationError(row, props.targetTags)
        : "";
      return h("div", { class: "retag-choice-cell" }, [
        h(
          NRadioGroup,
          {
            value: retagChoice(row, props.choices, props.targetTags),
            size: "small",
            onUpdateValue: (value: string) =>
              emitRetagChoice(emit, row, value, props.targetTags),
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
                    !canEnableRetagTargetChoice(row, props.targetTags) ||
                    props.mutationDisabled,
                  title: targetError
                    ? targetError
                    : canChooseTarget
                      ? props.mutationNotice
                      : "Enter a target tag before retagging.",
                },
                { default: () => "Retag" },
              ),
            ],
          },
        ),
        canSwitchToConcrete(row)
          ? h(
              NTag,
              { size: "small", type: "info", bordered: false },
              { default: () => "Automatch ready" },
            )
          : null,
      ]);
    },
  },
]);

function rowKey(row: RetagTargetItem): string {
  return row.service_key;
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

<style scoped>
.retag-source-link {
  width: fit-content;
  font-size: 0.84rem;
}

.retag-target-tag-cell {
  align-items: stretch;
}

.retag-input-error {
  color: var(--color-warning-fg);
  font-size: 0.78rem;
  line-height: 1.35;
}
</style>
