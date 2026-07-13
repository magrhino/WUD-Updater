import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import RetagTargetsTable from "../src/components/retags/RetagTargetsTable.vue";
import type { RetagTargetChoice, RetagTargetItem } from "../src/api/client";
import { retagTarget } from "./helpers/fixtures";
import { naiveStubs } from "./helpers/mount";

function mountTable({
  rows,
  choices = {},
  targetTags = {},
  mutationDisabled = false,
  mutationNotice = "",
}: {
  rows: RetagTargetItem[];
  choices?: Record<string, RetagTargetChoice>;
  targetTags?: Record<string, string>;
  mutationDisabled?: boolean;
  mutationNotice?: string;
}) {
  return mount(RetagTargetsTable, {
    props: {
      rows,
      loading: false,
      choices,
      targetTags,
      mutationDisabled,
      mutationNotice,
    },
    global: {
      stubs: naiveStubs,
    },
  });
}

describe("RetagTargetsTable", () => {
  it("renders a per-row retag action and emits an additive choice", async () => {
    const item = retagTarget();
    const wrapper = mountTable({ rows: [item] });

    const retagOnlyButton = wrapper.get(
      'button[aria-label="Retag media/app"]',
    );
    expect(retagOnlyButton.text()).toBe("Retag this service");
    expect(retagOnlyButton.attributes("disabled")).toBeUndefined();
    expect(retagOnlyButton.attributes("title")).toBe(
      "Add media/app to the retag preview.",
    );
    expect(wrapper.get('[role="radiogroup"]').attributes("aria-label")).toBe(
      "Retag choice for media/app",
    );

    await retagOnlyButton.trigger("click");

    expect(wrapper.emitted("choice-update")).toEqual([
      [item, "switch-to-concrete"],
    ]);
  });

  it("keeps a not-running service selectable with a visible start warning", () => {
    const item = retagTarget({ runtime_state: "not-running" });
    const wrapper = mountTable({ rows: [item] });

    expect(wrapper.text()).toContain("Not running");
    expect(wrapper.text()).toContain(
      "Applying will create or recreate and start this service",
    );
    const retagOnlyButton = wrapper.get(
      'button[aria-label="Retag media/app"]',
    );
    expect(retagOnlyButton.attributes("disabled")).toBeUndefined();
    expect(retagOnlyButton.attributes("title")).toContain(
      "will create or recreate and start this service",
    );
    const switchInput = wrapper.get('input[value="switch-to-concrete"]');
    expect(switchInput.attributes("disabled")).toBeUndefined();
    expect(switchInput.attributes("title")).toContain(
      "will create or recreate and start this service",
    );
  });

  it("disables retag selection when a manual target tag is invalid", () => {
    const item = retagTarget({
      service_key: "media/radarr",
      service: "radarr",
      image: "repo/radarr:5.21.1",
      image_repo: "repo/radarr",
      current_tag: "5.21.1",
      tracking_tag: "5.21.1",
      tracking_tag_source: "image",
      proposed_tag: "",
      final_image: "",
      retag_available: false,
      retag_reason: "not-latest-tracking",
      choices: ["keep-current"],
      digest_provenance: null,
    });

    const wrapper = mountTable({
      rows: [item],
      choices: { [item.target_id]: "switch-to-concrete" },
      targetTags: { [item.target_id]: "-bad" },
    });
    const switchInput = wrapper.find<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );

    expect(switchInput.attributes("disabled")).toBeDefined();
    expect(switchInput.attributes("title")).toContain("invalid target tag");
    const retagOnlyButton = wrapper.get(
      'button[aria-label="Retag media/radarr"]',
    );
    expect(retagOnlyButton.attributes("disabled")).toBeDefined();
    expect(retagOnlyButton.attributes("title")).toContain("invalid target tag");
    expect(wrapper.text()).toContain("media/radarr has an invalid target tag");
    const targetInput = wrapper.get(
      'input[aria-label="Target tag for media/radarr"]',
    );
    expect(targetInput.attributes("aria-invalid")).toBe("true");
    const errorId = targetInput.attributes("aria-describedby");
    expect(errorId).toBeTruthy();
    expect(wrapper.get(`[id="${errorId}"]`).text()).toContain(
      "media/radarr has an invalid target tag",
    );
    const choiceGroup = wrapper.get('[role="radiogroup"]');
    const choiceHelpId = choiceGroup.attributes("aria-describedby");
    expect(choiceHelpId).toBeTruthy();
    expect(wrapper.get(`[id="${choiceHelpId}"]`).text()).toContain(
      "media/radarr has an invalid target tag",
    );
  });
});
