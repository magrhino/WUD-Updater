import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import { normalizeRetagChoice } from "../../utils/retagChoices";

export {
  canSwitchToConcrete,
  retagChoice,
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
): void {
  const eligibleChoice = normalizeRetagChoice(item, choice);
  if (eligibleChoice !== choice) {
    return;
  }
  emit("choice-update", item, eligibleChoice);
}
