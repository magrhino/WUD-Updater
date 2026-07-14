import type { RetagTargetChoice, RetagTargetItem } from "../api/client";

const DEFAULT_RETAG_CHOICE: RetagTargetChoice = "keep-current";
// Keep this aligned with src/wudup/images.py tag_value_valid.
const tagValuePattern = /^\w[\w.-]{0,127}$/;

export function retagTargetIdentity(item: RetagTargetItem): string {
  return item.target_id || item.service_key;
}

export function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

export function retagTargetTagValue(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): string {
  const targetTag = targetTags[retagTargetIdentity(item)];
  if (targetTag?.trim()) {
    return targetTag;
  }
  return canSwitchToConcrete(item) ? item.proposed_tag : "";
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

export function canEnableRetagTargetChoice(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return (
    canChooseRetagTarget(item, targetTags) &&
    !retagTargetTagValidationError(item, targetTags)
  );
}

export function canBulkEnableRetagTargetChoice(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return (
    item.runtime_state === "running" &&
    canEnableRetagTargetChoice(item, targetTags)
  );
}

export function retagRuntimeChoiceWarning(item: RetagTargetItem): string {
  if (item.runtime_state === "not-running") {
    return "No running Compose container was found. Applying will create or recreate and start this service.";
  }
  if (item.runtime_state !== "running") {
    return "Runtime state could not be verified. Applying may create or recreate and start this service.";
  }
  return "";
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
  return normalizeRetagChoice(
    item,
    choices[retagTargetIdentity(item)],
    targetTags,
  );
}
