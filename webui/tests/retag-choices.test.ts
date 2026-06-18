import { describe, expect, it, vi } from "vitest";

import {
  emitRetagChoice,
  retagChoice,
} from "../src/components/retags/retagChoices";
import { retagTarget } from "./helpers/fixtures";

describe("retag choice helpers", () => {
  it("falls back to keep-current for stale ineligible choices", () => {
    const unavailableItem = retagTarget({
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
});
