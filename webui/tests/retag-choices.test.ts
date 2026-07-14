import { describe, expect, it, vi } from "vitest";

import {
  canBulkEnableRetagTargetChoice,
  canChooseRetagTarget,
  canEnableRetagTargetChoice,
  emitRetagChoice,
  retagChoice,
  retagRuntimeChoiceWarning,
  retagTargetIdentity,
  retagTargetTagValidationError,
  retagTargetTagValue,
} from "../src/components/retags/retagChoices";
import { retagTarget } from "./helpers/fixtures";

describe("retag choice helpers", () => {
  it("falls back to keep-current for stale ineligible choices", () => {
    const unavailableItem = retagTarget({
      proposed_tag: "",
      retag_available: false,
      retag_reason: "missing-provenance",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    const missingChoiceItem = retagTarget({
      choices: ["keep-current"],
    });

    expect(
      retagChoice(unavailableItem, {
        [unavailableItem.target_id]: "switch-to-concrete",
      }),
    ).toBe("keep-current");
    expect(
      retagChoice(missingChoiceItem, {
        [missingChoiceItem.target_id]: "switch-to-concrete",
      }),
    ).toBe("keep-current");
  });

  it("does not emit stale ineligible switch choices", () => {
    const item = retagTarget({
      proposed_tag: "",
      retag_available: false,
      retag_reason: "missing-provenance",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    const emit = vi.fn();

    emitRetagChoice(emit, item, "switch-to-concrete");

    expect(emit).not.toHaveBeenCalled();

    emitRetagChoice(emit, item, "keep-current");

    expect(emit).toHaveBeenCalledWith("choice-update", item, "keep-current");
  });

  it("allows manual fallback choices when a target tag is provided", () => {
    const item = retagTarget({
      proposed_tag: "",
      retag_available: false,
      retag_reason: "not-latest-tracking",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    const targetTags = { [item.target_id]: "2.0" };
    const emit = vi.fn();

    expect(canChooseRetagTarget(item, targetTags)).toBe(true);
    expect(retagChoice(item, { [item.target_id]: "switch-to-concrete" }, targetTags))
      .toBe("switch-to-concrete");
    expect(retagTargetTagValidationError(item, targetTags)).toBe("");

    emitRetagChoice(emit, item, "switch-to-concrete", targetTags);

    expect(emit).toHaveBeenCalledWith("choice-update", item, "switch-to-concrete");
  });

  it("reports invalid manual fallback tags", () => {
    const item = retagTarget({ proposed_tag: "" });

    expect(
      retagTargetTagValidationError(item, {
        [item.target_id]: "v1.2_3-alpha",
      }),
    ).toBe("");
    expect(
      retagTargetTagValidationError(item, {
        [item.target_id]: "a".repeat(128),
      }),
    ).toBe("");
    expect(retagTargetTagValidationError(item, { [item.target_id]: "" }))
      .toContain("needs a target tag");
    expect(retagTargetTagValidationError(item, { [item.target_id]: "latest" }))
      .toContain("not latest");
    expect(retagTargetTagValidationError(item, { [item.target_id]: "-bad" }))
      .toContain("invalid target tag");
    expect(
      retagTargetTagValidationError(item, { [item.target_id]: "bad:value" }),
    ).toContain("invalid target tag");
    expect(
      retagTargetTagValidationError(item, {
        [item.target_id]: "a".repeat(129),
      }),
    ).toContain("invalid target tag");
  });

  it("treats blank automatch edits as no manual override", () => {
    const item = retagTarget();
    const targetTags = { [item.target_id]: "   " };

    expect(retagTargetTagValue(item, targetTags)).toBe("1.1");
    expect(retagTargetTagValidationError(item, targetTags)).toBe("");
  });

  it("resolves legacy target state by service key when target_id is absent", () => {
    const item = retagTarget({
      proposed_tag: "",
      retag_available: false,
      retag_reason: "not-latest-tracking",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    delete item.target_id;
    const targetTags = { [item.service_key]: "2.0" };

    expect(retagTargetIdentity(item)).toBe(item.service_key);
    expect(retagTargetTagValue(item, targetTags)).toBe("2.0");
    expect(canChooseRetagTarget(item, targetTags)).toBe(true);
    expect(
      retagChoice(item, {
        [item.service_key]: "switch-to-concrete",
      }, targetTags),
    ).toBe("switch-to-concrete");
  });

  it("keeps invalid manual targets from enabling retag selection", () => {
    const item = retagTarget({
      proposed_tag: "",
      retag_available: false,
      retag_reason: "not-latest-tracking",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    const targetTags = { [item.target_id]: "-bad" };

    expect(canChooseRetagTarget(item, targetTags)).toBe(true);
    expect(canEnableRetagTargetChoice(item, targetTags)).toBe(false);
    expect(retagTargetTagValidationError(item, targetTags)).toContain(
      "invalid target tag",
    );
  });

  it("limits bulk selection to running targets without disabling explicit choices", () => {
    const running = retagTarget();
    const notRunning = retagTarget({
      service_key: "archive/app",
      runtime_state: "not-running",
    });
    const unknown = retagTarget({
      service_key: "unknown/app",
      runtime_state: "unknown",
    });

    expect(canBulkEnableRetagTargetChoice(running, {})).toBe(true);
    expect(canEnableRetagTargetChoice(notRunning, {})).toBe(true);
    expect(canBulkEnableRetagTargetChoice(notRunning, {})).toBe(false);
    expect(canEnableRetagTargetChoice(unknown, {})).toBe(true);
    expect(canBulkEnableRetagTargetChoice(unknown, {})).toBe(false);
    expect(retagRuntimeChoiceWarning(notRunning)).toContain(
      "will create or recreate and start this service",
    );
    expect(retagRuntimeChoiceWarning(unknown)).toContain(
      "may create or recreate and start this service",
    );
  });

  it("derives fixture target identity from resolved service key parts", () => {
    const item = retagTarget({ service_key: "data/postgres" });

    expect(item.stack).toBe("data");
    expect(item.service).toBe("postgres");
    expect(item.target_id ?? "").toContain("|data|postgres");
  });
});
