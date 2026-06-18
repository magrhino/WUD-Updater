import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  ReleaseNoteInfo,
} from "../../api/client";
import {
  groupedItemActionLabel,
  groupedItemServices,
  groupedItemTarget,
  uniqueStrings,
} from "./pendingDisplay";
import type { SafetyCue } from "./safetyCues";

export type PendingSearchContext = {
  releaseNoteFor: (item: PendingItem) => ReleaseNoteInfo | null;
  releaseNoteReason: (note: ReleaseNoteInfo | null) => string;
  releaseNoteStatus: (note: ReleaseNoteInfo | null) => string;
  riskCues: (item: PendingItem) => SafetyCue[];
};

type SnoozedSearchItem = {
  group: PendingStackGroup;
  item: PendingGroupedItem;
};

export type FilteredPendingStackGroup = PendingStackGroup & {
  visibleLineNumbers: number[];
};

export function normalizePendingSearch(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

export function pendingItemMatchesSearch(
  item: PendingItem,
  query: string,
  context: PendingSearchContext,
): boolean {
  const normalizedQuery = normalizePendingSearch(query);
  if (!normalizedQuery) {
    return true;
  }
  return searchableText(pendingItemSearchParts(item, context)).includes(
    normalizedQuery,
  );
}

export function pendingGroupMatchesSearch(
  group: PendingStackGroup,
  query: string,
): boolean {
  const normalizedQuery = normalizePendingSearch(query);
  if (!normalizedQuery) {
    return true;
  }
  return searchableText([
    group.name,
    group.directory,
    group.compose_file,
    group.project_directory,
  ]).includes(normalizedQuery);
}

export function filterPendingStackGroups(
  groups: PendingStackGroup[],
  query: string,
  context: PendingSearchContext,
): FilteredPendingStackGroup[] {
  const normalizedQuery = normalizePendingSearch(query);
  if (!normalizedQuery) {
    return groups.map((group) => stackGroupWithMatchedItems(group, group.items));
  }
  return groups.flatMap((group) => {
    if (pendingGroupMatchesSearch(group, normalizedQuery)) {
      return [stackGroupWithMatchedItems(group, group.items)];
    }
    const items = group.items.filter((item) =>
      pendingItemMatchesSearch(item, normalizedQuery, context),
    );
    return items.length ? [stackGroupWithMatchedItems(group, items)] : [];
  });
}

export function filterPendingItems<T extends PendingItem>(
  items: T[],
  query: string,
  context: PendingSearchContext,
): T[] {
  const normalizedQuery = normalizePendingSearch(query);
  if (!normalizedQuery) {
    return items;
  }
  return items.filter((item) =>
    pendingItemMatchesSearch(item, normalizedQuery, context),
  );
}

export function filterSnoozedItems<
  T extends SnoozedSearchItem,
>(items: T[], query: string, context: PendingSearchContext): T[] {
  const normalizedQuery = normalizePendingSearch(query);
  if (!normalizedQuery) {
    return items;
  }
  return items.filter(
    ({ group, item }) =>
      pendingGroupMatchesSearch(group, normalizedQuery) ||
      pendingItemMatchesSearch(item, normalizedQuery, context),
  );
}

function stackGroupWithMatchedItems(
  group: PendingStackGroup,
  items: PendingGroupedItem[],
): FilteredPendingStackGroup {
  if (items === group.items) {
    return {
      ...group,
      visibleLineNumbers: group.line_numbers,
    };
  }
  const services = uniqueStrings(items.flatMap((item) => item.services));
  return {
    ...group,
    items,
    services,
    services_label: services.length ? services.join(", ") : group.services_label,
    visibleLineNumbers: items.map((item) => item.line_no),
  };
}

function pendingItemSearchParts(
  item: PendingItem,
  context: PendingSearchContext,
): string[] {
  const note = context.releaseNoteFor(item);
  const cues = context.riskCues(item);
  return [
    String(item.line_no),
    item.raw,
    item.image,
    item.key,
    item.repo,
    item.current_tag,
    item.desired_tag,
    item.digest,
    ...digestProvenanceParts(item),
    ...groupedItemParts(item),
    ...releaseNoteParts(note, context),
    ...cues.flatMap((cue) => [cue.key, cue.label]),
  ];
}

function digestProvenanceParts(item: PendingItem): string[] {
  const provenance = item.digest_provenance;
  if (!provenance) {
    return [];
  }
  return [
    provenance.source_image,
    provenance.resolved_tag,
    provenance.watch_tag,
    provenance.target_digest,
    provenance.final_image,
    provenance.provenance_source,
    provenance.provenance_confidence,
  ];
}

function groupedItemParts(item: PendingItem): string[] {
  if (!isGroupedItem(item)) {
    return [];
  }
  return [
    item.resolved_image,
    item.target_image,
    groupedItemTarget(item),
    groupedItemServices(item),
    item.action,
    item.action.replace(/[-_]+/g, " "),
    groupedItemActionLabel(item),
    ...item.compose_images,
    ...item.services,
    ...diagnosticParts(item),
  ];
}

function diagnosticParts(item: PendingGroupedItem): string[] {
  const diagnostic = item.diagnostic;
  if (!diagnostic) {
    return [];
  }
  return [
    diagnostic.code,
    diagnostic.message,
    diagnostic.hint,
    diagnostic.stack,
    diagnostic.service,
    diagnostic.compose_file,
    ...diagnostic.found_files,
    ...flattenUnknown(diagnostic.details),
  ];
}

function releaseNoteParts(
  note: ReleaseNoteInfo | null,
  context: Pick<
    PendingSearchContext,
    "releaseNoteReason" | "releaseNoteStatus"
  >,
): string[] {
  return [
    context.releaseNoteStatus(note),
    context.releaseNoteReason(note),
    note?.provider ?? "",
    note?.image_repo ?? "",
    note?.upstream_repo ?? "",
    note?.release_tag ?? "",
    note?.title ?? "",
    note?.breaking ? "possible breaking change" : "",
    ...(note?.breaking_reasons ?? []),
    ...(note?.links.flatMap((link) => [link.label, link.kind, link.url]) ?? []),
    note?.error ?? "",
  ];
}

function isGroupedItem(item: PendingItem): item is PendingGroupedItem {
  return "action" in item && "services" in item;
}

function searchableText(values: string[]): string {
  return values.filter(Boolean).join(" ").toLowerCase();
}

function flattenUnknown(value: unknown, seen = new WeakSet<object>()): string[] {
  if (value === null || value === undefined) {
    return [];
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return [String(value)];
  }
  if (typeof value === "object") {
    if (seen.has(value)) {
      return [];
    }
    seen.add(value);
    if (Array.isArray(value)) {
      return value.flatMap((item) => flattenUnknown(item, seen));
    }
    return Object.entries(value).flatMap(([key, entry]) => [
      key,
      ...flattenUnknown(entry, seen),
    ]);
  }
  return [];
}
