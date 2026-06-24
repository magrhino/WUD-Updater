import { describe, expect, it, vi } from "vitest";

import {
  canChooseRetagTarget,
  emitRetagChoice,
  retagChoice,
  retagTargetTagValidationError,
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
        [unavailableItem.service_key]: "switch-to-concrete",
      }),
    ).toBe("keep-current");
    expect(
      retagChoice(missingChoiceItem, {
        [missingChoiceItem.service_key]: "switch-to-concrete",
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
    const targetTags = { [item.service_key]: "2.0" };
    const emit = vi.fn();

    expect(canChooseRetagTarget(item, targetTags)).toBe(true);
    expect(retagChoice(item, { [item.service_key]: "switch-to-concrete" }, targetTags))
      .toBe("switch-to-concrete");
    expect(retagTargetTagValidationError(item, targetTags)).toBe("");

    emitRetagChoice(emit, item, "switch-to-concrete", targetTags);

    expect(emit).toHaveBeenCalledWith("choice-update", item, "switch-to-concrete");
  });

  it("reports invalid manual fallback tags", () => {
    const item = retagTarget({ proposed_tag: "" });

    expect(
      retagTargetTagValidationError(item, {
        [item.service_key]: "v1.2_3-alpha",
      }),
    ).toBe("");
    expect(
      retagTargetTagValidationError(item, {
        [item.service_key]: "a".repeat(128),
      }),
    ).toBe("");
    expect(retagTargetTagValidationError(item, { [item.service_key]: "" }))
      .toContain("needs a target tag");
    expect(retagTargetTagValidationError(item, { [item.service_key]: "latest" }))
      .toContain("not latest");
    expect(retagTargetTagValidationError(item, { [item.service_key]: "-bad" }))
      .toContain("invalid target tag");
    expect(
      retagTargetTagValidationError(item, { [item.service_key]: "bad:value" }),
    ).toContain("invalid target tag");
    expect(
      retagTargetTagValidationError(item, {
        [item.service_key]: "a".repeat(129),
      }),
    ).toContain("invalid target tag");
  });
});
