import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";

export type RetagChoiceEmitter = (
  event: "choice-update",
  item: RetagTargetItem,
  choice: RetagTargetChoice,
) => void;

export function retagChoice(
  item: RetagTargetItem,
  choices: Record<string, RetagTargetChoice>,
): RetagTargetChoice {
  return choices[item.service_key] ?? "keep-current";
}

export function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

export function emitRetagChoice(
  emit: RetagChoiceEmitter,
  item: RetagTargetItem,
  choice: string,
): void {
  if (choice !== "keep-current" && choice !== "switch-to-concrete") {
    return;
  }
  emit("choice-update", item, choice);
}
