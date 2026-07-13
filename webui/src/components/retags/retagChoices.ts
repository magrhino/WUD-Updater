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

export function canShowRetagAction(
  item: RetagTargetItem,
  targetTags: Record<string, string>,
): boolean {
  return canChooseRetagTarget(item, targetTags);
}

export function retagActionDisabled(
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

export function retagActionTitle(
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
  if (retagActionDisabled(item, targetTags, mutationDisabled)) {
    return targetChoiceTitle || "Retagging is disabled.";
  }
  return (
    targetChoiceTitle || `Add ${item.service_key} to the retag preview.`
  );
}

export function emitRetagAction(
  emit: RetagChoiceEmitter,
  item: RetagTargetItem,
  targetTags: Record<string, string>,
  mutationDisabled: boolean,
): void {
  if (retagActionDisabled(item, targetTags, mutationDisabled)) {
    return;
  }
  emit("choice-update", item, "switch-to-concrete");
}
