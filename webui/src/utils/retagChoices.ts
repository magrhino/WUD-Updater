import type { RetagTargetChoice, RetagTargetItem } from "../api/client";

const DEFAULT_RETAG_CHOICE: RetagTargetChoice = "keep-current";
const tagValuePattern = /^\w[\w.-]{0,127}$/;

export function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

export function retagTargetTagValue(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): string {
  return (
    targetTags[item.service_key] ??
    (canSwitchToConcrete(item) ? item.proposed_tag : "")
  );
}

export function retagTargetTagValidationError(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): string {
  const tag = retagTargetTagValue(item, targetTags).trim();
  if (!tag) {
    return `${item.service_key} needs a target tag before retagging.`;
  }
  if (tag === "latest") {
    return `${item.service_key} needs a concrete target tag, not latest.`;
  }
  if (!tagValuePattern.test(tag)) {
    return `${item.service_key} has an invalid target tag. Use a Docker tag value like ${item.proposed_tag || "1.2.3"}.`;
  }
  return "";
}

export function hasManualRetagTarget(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return retagTargetTagValue(item, targetTags).trim() !== "";
}

export function canChooseRetagTarget(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return canSwitchToConcrete(item) || hasManualRetagTarget(item, targetTags);
}

export function normalizeRetagChoice(
  item: RetagTargetItem,
  choice: string | undefined,
  targetTags: Record<string, string> = {},
): RetagTargetChoice {
  if (choice === "switch-to-concrete" && canChooseRetagTarget(item, targetTags)) {
    return choice;
  }
  return DEFAULT_RETAG_CHOICE;
}

export function retagChoice(
  item: RetagTargetItem,
  choices: Record<string, RetagTargetChoice>,
  targetTags: Record<string, string> = {},
): RetagTargetChoice {
  return normalizeRetagChoice(item, choices[item.service_key], targetTags);
}
