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
      choices: { [item.service_key]: "switch-to-concrete" },
      targetTags: { [item.service_key]: "-bad" },
    });
    const switchInput = wrapper.find<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );

    expect(switchInput.attributes("disabled")).toBeDefined();
    expect(switchInput.attributes("title")).toContain("invalid target tag");
    expect(wrapper.text()).toContain("media/radarr has an invalid target tag");
  });
});
