import type { RetagTargetChoice, RetagTargetItem } from "../api/client";

const DEFAULT_RETAG_CHOICE: RetagTargetChoice = "keep-current";

export function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

export function normalizeRetagChoice(
  item: RetagTargetItem,
  choice: string | undefined,
): RetagTargetChoice {
  if (choice === "switch-to-concrete" && canSwitchToConcrete(item)) {
    return choice;
  }
  return DEFAULT_RETAG_CHOICE;
}

export function retagChoice(
  item: RetagTargetItem,
  choices: Record<string, RetagTargetChoice>,
): RetagTargetChoice {
  return normalizeRetagChoice(item, choices[item.service_key]);
}
