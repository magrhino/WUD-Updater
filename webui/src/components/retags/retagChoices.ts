import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import { normalizeRetagChoice } from "../../utils/retagChoices";

export {
  canChooseRetagTarget,
  canEnableRetagTargetChoice,
  canSwitchToConcrete,
  retagChoice,
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
