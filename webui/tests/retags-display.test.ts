import { describe, expect, it } from "vitest";

import {
  candidateLabel,
  composeLocation,
  currentTagLabel,
  digestPinSummary,
  labelRewriteSummary,
  planStatusType,
  pluralize,
  reasonDetail,
  reasonLabel,
  reasonTagType,
  retagPlanContextLabel,
  retagPlanSourceFile,
  searchableText,
  trackingLabel,
  trackingSourceLabel,
  trackingTagType,
} from "../src/views/retags/display";
import { retagPlanResponse, retagTarget } from "./helpers/fixtures";

describe("retag display helpers", () => {
  it("formats target state for review and search", () => {
    const available = retagTarget();
    const stale = retagTarget({
      current_tag: "",
      tracking_tag: "",
      tracking_tag_source: "",
      proposed_tag: "",
      final_image: "",
      retag_available: false,
      retag_reason: "stale-provenance",
      choices: ["keep-current"],
      compose_file: "",
      digest_provenance: null,
    });

    expect(reasonLabel("eligible")).toBe("Retag available");
    expect(reasonLabel("backend-added-reason")).toBe("Unavailable reason");
    expect(reasonDetail("backend-added-reason")).toBe(
      "The backend did not provide a recognized reason.",
    );
    expect(reasonTagType(available)).toBe("success");
    expect(reasonTagType(stale)).toBe("warning");

    expect(trackingTagType(available)).toBe("info");
    expect(trackingLabel(stale)).toBe("Unknown");
    expect(trackingSourceLabel(stale)).toBe("Source unavailable");
    expect(currentTagLabel(stale)).toBe("Current tag unavailable");
    expect(candidateLabel(available)).toBe("latest -> 1.1");
    expect(candidateLabel(stale)).toBe(
      "Stored provenance does not match the current service image.",
    );
    expect(composeLocation(stale)).toBe("/docker/media");
    expect(searchableText(stale)).toContain("stale provenance");
  });

  it("summarizes retag plans and digest-pin changes", () => {
    const plan = retagPlanResponse();
    const update = plan.stacks[0].digest_pin_updates[0];
    const twoStackPlan = retagPlanResponse({
      stacks: [
        plan.stacks[0],
        {
          ...plan.stacks[0],
          stack: "data",
          directory: "/docker/data",
          project_directory: "/docker/data",
          services: ["postgres"],
        },
      ],
    });
    const emptyPlan = retagPlanResponse({ status: "empty", stacks: [] });

    expect(planStatusType(plan)).toBe("success");
    expect(planStatusType(retagPlanResponse({ status: "blocked" }))).toBe("error");
    expect(planStatusType(retagPlanResponse({ status: "unavailable" }))).toBe(
      "warning",
    );
    expect(planStatusType(emptyPlan)).toBe("default");
    expect(planStatusType(null)).toBe("default");

    expect(retagPlanContextLabel(plan)).toBe("media");
    expect(retagPlanContextLabel(twoStackPlan)).toBe("2 stacks");
    expect(retagPlanContextLabel(emptyPlan)).toBe("retag plan");
    expect(retagPlanSourceFile(plan)).toBe("/docker/media/docker-compose.yml");
    expect(retagPlanSourceFile(twoStackPlan)).toBe("2 Compose files");
    expect(retagPlanSourceFile(emptyPlan)).toBe("Retag plan");
    expect(digestPinSummary(update)).toBe("repo/app:latest -> repo/app@sha256:abc123");
    expect(labelRewriteSummary(update)).toBe(
      String.raw`wud.tag.include: ^latest$$ -> ^1\.1$$`,
    );
    expect(labelRewriteSummary({ ...update, label_rewrites: [] })).toBe(
      "No label rewrite",
    );
    expect(pluralize(1, "service")).toBe("1 service");
    expect(pluralize(2, "policy", "policies")).toBe("2 policies");
  });
});
