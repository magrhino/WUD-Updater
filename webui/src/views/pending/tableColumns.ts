import { h, type VNodeChild } from "vue";
import { AlertTriangle, ExternalLink } from "@lucide/vue";
import { NInput, NTag, type DataTableColumns } from "naive-ui";

import type { PendingItem, ReleaseNoteInfo } from "../../api/client";
import type { SafetyCue } from "./safetyCues";

export type PendingTableColumnsContext = {
  displayDigest: (value: string) => string;
  displayValue: (value: string) => string;
  releaseNoteFor: (item: PendingItem) => ReleaseNoteInfo | null;
  releaseNoteReason: (note: ReleaseNoteInfo | null) => string;
  releaseNoteStatus: (note: ReleaseNoteInfo | null) => string;
  riskCues: (row: PendingItem) => SafetyCue[];
  tagInputProps: (item: Pick<PendingItem, "image">) => { "aria-label": string };
  tagOverrideValue: (item: PendingItem) => string;
  updateTagOverride: (item: PendingItem, value: string) => void;
};

export function createPendingColumns(
  context: PendingTableColumnsContext,
): DataTableColumns<PendingItem> {
  return [
    { type: "selection", width: 48 },
    { title: "Line", key: "line_no", width: 80 },
    {
      title: "Image",
      key: "image",
      minWidth: 240,
      render: (row) =>
        h("code", { class: "pending-table-value", title: row.image }, row.image),
    },
    {
      title: "Repository",
      key: "repo",
      minWidth: 200,
      render: (row) =>
        h("span", { class: "pending-table-value", title: row.repo }, row.repo),
    },
    {
      title: "Current tag",
      key: "current_tag",
      minWidth: 120,
      render: (row) => context.displayValue(row.current_tag),
    },
    {
      title: "New tag",
      key: "desired_tag",
      minWidth: 160,
      render: (row) => {
        if (!row.desired_tag) {
          return context.displayValue("");
        }
        return h(NInput, {
          value: context.tagOverrideValue(row),
          size: "small",
          class: "tag-override-input",
          placeholder: row.desired_tag,
          inputProps: context.tagInputProps(row),
          onUpdateValue: (value: string) => context.updateTagOverride(row, value),
        });
      },
    },
    {
      title: "New digest",
      key: "digest",
      minWidth: 220,
      render: (row) =>
        row.digest
          ? h(
              "code",
              { class: "digest-value", title: row.digest },
              context.displayDigest(row.digest),
            )
          : context.displayValue(""),
    },
    {
      title: "Safety cues",
      key: "safety_cues",
      minWidth: 200,
      render: (row) => renderRiskBadges(row, context.riskCues),
    },
    {
      title: "Release notes",
      key: "release_notes",
      minWidth: 220,
      render: (row) => renderReleaseNotes(row, context),
    },
  ];
}

export function renderRiskBadges(
  row: PendingItem,
  riskCues: (row: PendingItem) => SafetyCue[],
): VNodeChild {
  const badges = riskCues(row).map((cue) =>
    h(
      NTag,
      { key: cue.key, size: "small", type: cue.type, class: "safety-badge" },
      () => cue.label,
    ),
  );
  if (badges.length === 0) {
    return h("span", { class: "risk-badges-muted" }, "None");
  }
  return h("div", { class: "risk-badges-container" }, badges);
}

export function renderReleaseNotes(
  row: PendingItem,
  context: Pick<
    PendingTableColumnsContext,
    "releaseNoteFor" | "releaseNoteReason" | "releaseNoteStatus"
  >,
): VNodeChild {
  const note = context.releaseNoteFor(row);
  const reason = context.releaseNoteReason(note);
  if (!note?.links.length) {
    return h(
      "span",
      {
        class: "release-notes-muted",
        title: reason || undefined,
      },
      [
        h("span", { class: "release-notes-status" }, context.releaseNoteStatus(note)),
        reason ? h("span", { class: "release-notes-reason" }, reason) : null,
      ],
    );
  }
  return h("div", { class: "release-notes-cell" }, [
    ...note.links.map((link) =>
      h(
        "a",
        {
          key: `${row.line_no}-${link.kind}-${link.url}`,
          class: "release-note-link",
          href: link.url,
          target: "_blank",
          rel: "noreferrer",
        },
        [
          link.label,
          h(ExternalLink, {
            size: 14,
            "aria-hidden": "true",
          }),
        ],
      ),
    ),
    note.breaking ? breakingCue(note) : null,
  ]);
}

export function breakingCue(note: ReleaseNoteInfo): VNodeChild {
  return h(
    "span",
    {
      class: "release-breaking-cue",
      title: note.breaking_reasons.join(" "),
      "aria-label": "Possible breaking change",
    },
    [
      h(AlertTriangle, {
        size: 14,
        "aria-hidden": "true",
      }),
      "Possible breaking change",
    ],
  );
}
