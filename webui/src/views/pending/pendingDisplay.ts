import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  ReleaseNoteInfo,
} from "../../api/client";
import type { SafetyCue } from "./safetyCues";

export type PendingTagInputProps = { "aria-label": string };

export function rowKey(row: PendingItem): number {
  return row.line_no;
}

export function displayValue(value: string): string {
  return value || "None";
}

export function previewImageLabel(
  value: string,
  displayDigest: (digest: string) => string,
): string {
  return value.includes("sha256:") ? displayDigest(value) : value;
}

export function uniqueSorted(values: number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

export function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) =>
    left.localeCompare(right),
  );
}

export function groupedItemServiceKeys(
  group: Pick<PendingStackGroup, "name">,
  item: Pick<PendingGroupedItem, "services">,
): string[] {
  return item.services
    .filter(Boolean)
    .map((service) => `${group.name}/${service}`);
}

export function pendingSourceFileName(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "Pending file") {
    return "Pending file";
  }
  return trimmed.split(/[\\/]/).filter(Boolean).at(-1) ?? trimmed;
}

export function releaseNoteStatus(
  note: ReleaseNoteInfo | null,
  releaseNotesLoading: boolean,
): string {
  if (note?.links.length) {
    return "";
  }
  if (releaseNotesLoading) {
    return "Checking...";
  }
  if (note?.status === "unsupported") {
    return "Unavailable";
  }
  if (note?.status === "error") {
    return "Check failed";
  }
  return "Not checked";
}

export function releaseNoteReason(note: ReleaseNoteInfo | null): string {
  const error = note?.error.trim() ?? "";
  if (!error) {
    return "";
  }
  const missingMapping = error.match(/^missing LSIO upstream mapping for (.+)$/);
  if (missingMapping?.[1]) {
    return `Add a LinuxServer.io upstream map entry for ${missingMapping[1]}.`;
  }
  if (error === "no supported GitHub release source found") {
    return "Only GHCR and mapped LinuxServer.io images have release-note links.";
  }
  return error;
}

export function tagInputProps(
  item: Pick<PendingItem, "image">,
): PendingTagInputProps {
  return { "aria-label": `New tag for ${item.image}` };
}

export function groupTagChangeCount(group: PendingStackGroup): number {
  return group.items.filter(
    (item) => item.desired_tag || item.action === "tag-update",
  ).length;
}

export function itemsBreakingCount(
  items: PendingGroupedItem[],
  releaseNoteFor: (item: PendingGroupedItem) => ReleaseNoteInfo | null,
): number {
  return items.filter((item) => releaseNoteFor(item)?.breaking).length;
}

export function groupedItemServices(item: PendingGroupedItem): string {
  return item.services.length ? item.services.join(", ") : "stack-level";
}

export function groupedItemTarget(item: PendingGroupedItem): string {
  return item.target_image || item.resolved_image || item.image;
}

export function groupChangePreviewItems(
  group: PendingStackGroup,
): PendingGroupedItem[] {
  return group.items.slice(0, 2);
}

export function groupChangeOverflowCount(group: PendingStackGroup): number {
  return Math.max(0, group.items.length - groupChangePreviewItems(group).length);
}

export function groupedItemActionLabel(item: PendingGroupedItem): string {
  switch (item.action) {
    case "tag-update":
      return "Tag update";
    case "recreate_service":
      return "Recreate service";
    case "recreate_stack":
      return "Recreate stack";
    case "unmatched":
      return "Needs review";
    default:
      return "Image update";
  }
}

export function groupedItemActionTagType(
  item: PendingGroupedItem,
): SafetyCue["type"] {
  switch (item.action) {
    case "tag-update":
    case "recreate_stack":
    case "unmatched":
      return "warning";
    case "recreate_service":
      return "info";
    default:
      return "default";
  }
}

export function groupedItemTagRewriteLabel(item: PendingGroupedItem): string {
  if (!item.desired_tag) {
    return "";
  }
  return `${item.image} -> ${groupedItemTarget(item)}`;
}
