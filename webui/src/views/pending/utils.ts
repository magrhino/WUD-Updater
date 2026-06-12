import type {
  PlanAction,
  PlanDigestPinLabelRewrite,
  PlanDigestUnpinUpdate,
  PlanLine,
  PlanResponse,
  PlanTagUpdate,
} from "../../api/client";
import { digestProvenanceDisplay } from "../../utils/digestProvenance";

export type PlanLineView = {
  stack: string;
  line: PlanLine;
};

export type PlanActionView = {
  stack: string;
  action: PlanAction;
};

export type PlanTagUpdateView = {
  stack: string;
  update: PlanTagUpdate;
};

export type PlanDigestPinLabelRewriteView = {
  stack: string;
  rewrite: PlanDigestPinLabelRewrite;
};

export type PlanDigestUnpinUpdateView = {
  stack: string;
  update: PlanDigestUnpinUpdate;
};

export function pluralize(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function reviewCountLabel(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  const verb = count === 1 ? "needs" : "need";
  return `${pluralize(count, singular, plural)} ${verb} review`;
}

export function summarizeList(values: string[], limit = 3): string {
  const uniqueValues = [...new Set(values.filter(Boolean))];
  if (uniqueValues.length <= limit) {
    return uniqueValues.join(", ");
  }
  return `${uniqueValues.slice(0, limit).join(", ")} +${uniqueValues.length - limit} more`;
}

export function pendingPlanContextLabel(
  plan: PlanResponse | null | undefined,
  fallback = "selected updates",
): string {
  if (!plan) {
    return fallback;
  }
  if (plan.stacks.length === 1) {
    return plan.stacks[0].name;
  }
  if (plan.summary.stack_count > 1) {
    return pluralize(plan.summary.stack_count, "stack");
  }
  return fallback;
}

export function planLinesFromPlan(
  plan: PlanResponse | null | undefined,
): PlanLineView[] {
  return (
    plan?.stacks.flatMap((stack) =>
      stack.lines.map((line) => ({ stack: stack.name, line })),
    ) ?? []
  );
}

export function planActionsFromPlan(
  plan: PlanResponse | null | undefined,
): PlanActionView[] {
  return (
    plan?.stacks.flatMap((stack) =>
      stack.actions.map((action) => ({ stack: stack.name, action })),
    ) ?? []
  );
}

export function planTagUpdatesFromPlan(
  plan: PlanResponse | null | undefined,
): PlanTagUpdateView[] {
  return (
    plan?.stacks.flatMap((stack) =>
      stack.tag_updates.map((update) => ({ stack: stack.name, update })),
    ) ?? []
  );
}

export function planDigestPinLabelRewritesFromPlan(
  plan: PlanResponse | null | undefined,
): PlanDigestPinLabelRewriteView[] {
  return (
    plan?.stacks.flatMap((stack) =>
      (stack.digest_pin_updates ?? []).flatMap((update) =>
        (update.label_rewrites ?? []).map((rewrite) => ({
          stack: stack.name,
          rewrite,
        })),
      ),
    ) ?? []
  );
}

export function planDigestUnpinUpdatesFromPlan(
  plan: PlanResponse | null | undefined,
): PlanDigestUnpinUpdateView[] {
  return (
    plan?.stacks.flatMap((stack) =>
      (stack.digest_unpin_updates ?? []).map((update) => ({
        stack: stack.name,
        update,
      })),
    ) ?? []
  );
}

export function planLineServiceLabel(
  stackCount: number,
  stack: string,
  line: PlanLine,
): string {
  const service = line.service || "stack-level";
  return stackCount > 1 ? `${stack} / ${service}` : service;
}

export function planLineTagRewriteLabel(line: PlanLine): string {
  if (!line.desired_tag || line.action === "digest-pin") {
    return "";
  }
  return `${line.compose_image} -> ${line.target_image}`;
}

export function planLineDigestPinLabel(line: PlanLine): string {
  if (line.action !== "digest-pin") {
    return "";
  }
  const provenance = digestProvenanceDisplay(line.digest_provenance);
  if (!provenance) {
    return `${line.compose_image} -> ${line.target_image}`;
  }
  return provenance.digest
    ? `${provenance.primary} (${provenance.digest})`
    : provenance.primary;
}

export function planLineDigestUnpinLabel(line: PlanLine): string {
  if (line.action !== "digest-unpin") {
    return "";
  }
  return `${line.compose_image} -> ${line.target_image}`;
}
