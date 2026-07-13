import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import {
  canChooseRetagTarget,
  canEnableRetagTargetChoice,
  normalizeRetagChoice,
  retagRuntimeChoiceWarning,
  retagTargetTagValidationError,
} from "../../utils/retagChoices";

export {
  canChooseRetagTarget,
  canBulkEnableRetagTargetChoice,
  canEnableRetagTargetChoice,
  canSwitchToConcrete,
  retagChoice,
  retagRuntimeChoiceWarning,
  retagTargetIdentity,
  retagTargetTagValidationError,
  retagTargetTagValue,
} from "../../utils/retagChoices";

export type RetagChoiceEmitter = (
  event: "choice-update",
  item: RetagTargetItem,
  choice: RetagTargetChoice,
) => void;

export type RetagOnlyEmitter = (
  event: "retag-only",
  item: RetagTargetItem,
) => void;

export function emitRetagChoice(
  emit: RetagChoiceEmitter,
  item: RetagTargetItem,
  choice: string,
  targetTags: Record<string, string> = {},
): void {
  const eligibleChoice = normalizeRetagChoice(item, choice, targetTags);
  if (eligibleChoice !== choice) {
    return;
  }
  emit("choice-update", item, eligibleChoice);
}

export function canShowRetagOnlyAction(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return canChooseRetagTarget(item, targetTags);
}

export function retagOnlyActionDisabled(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
  mutationDisabled: boolean,
): boolean {
  return !canEnableRetagTargetChoice(item, targetTags) || mutationDisabled;
}

export function retagTargetChoiceTitle(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
  mutationNotice: string,
): string {
  const canChooseTarget = canChooseRetagTarget(item, targetTags);
  const targetError = canChooseTarget
    ? retagTargetTagValidationError(item, targetTags)
    : "";
  if (targetError) {
    return targetError;
  }
  if (!canChooseTarget) {
    return "Enter a target tag before retagging.";
  }
  return mutationNotice || retagRuntimeChoiceWarning(item);
}

export function retagOnlyActionTitle(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
  mutationDisabled: boolean,
  mutationNotice: string,
): string {
  const targetChoiceTitle = retagTargetChoiceTitle(
    item,
    targetTags,
    mutationNotice,
  );
  if (retagOnlyActionDisabled(item, targetTags, mutationDisabled)) {
    return targetChoiceTitle || "Retagging is disabled.";
  }
  return (
    targetChoiceTitle || `Select only ${item.service_key} for retag preview.`
  );
}

export function emitRetagOnly(
  emit: RetagOnlyEmitter,
  item: RetagTargetItem,
  targetTags: Record<string, string>,
  mutationDisabled: boolean,
): void {
  if (retagOnlyActionDisabled(item, targetTags, mutationDisabled)) {
    return;
  }
  emit("retag-only", item);
}
