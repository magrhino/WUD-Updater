import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import RetagTargetsMobileList from "../src/components/retags/RetagTargetsMobileList.vue";
import type { RetagTargetChoice, RetagTargetItem } from "../src/api/client";
import { retagTarget } from "./helpers/fixtures";
import { naiveStubs } from "./helpers/mount";

function mountMobileList({
  rows,
  choices = {},
  mutationDisabled = false,
  mutationNotice = "",
}: {
  rows: RetagTargetItem[];
  choices?: Record<string, RetagTargetChoice>;
  mutationDisabled?: boolean;
  mutationNotice?: string;
}) {
  return mount(RetagTargetsMobileList, {
    props: {
      rows,
      choices,
      mutationDisabled,
      mutationNotice,
    },
    global: {
      stubs: naiveStubs,
    },
  });
}

describe("RetagTargetsMobileList", () => {
  it("renders mobile review details and emits switch choices", async () => {
    const item = retagTarget();
    const wrapper = mountMobileList({ rows: [item] });

    expect(wrapper.text()).toContain("media/app");
    expect(wrapper.text()).toContain("media / app");
    expect(wrapper.text()).toContain("repo/app:latest");
    expect(wrapper.text()).toContain("latest (label)");
    expect(wrapper.text()).toContain("latest -> 1.1");
    expect(wrapper.text()).toContain("repo/app@sha256:abc123");
    expect(wrapper.text()).toContain("/docker/media/docker-compose.yml");
    expect(
      (wrapper.find<HTMLInputElement>('input[value="keep-current"]').element)
        .checked,
    ).toBe(true);

    const switchInput = wrapper.find<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );
    expect(switchInput.attributes("disabled")).toBeUndefined();

    await switchInput.setValue();

    expect(wrapper.emitted("choice-update")).toEqual([
      [item, "switch-to-concrete"],
    ]);
  });

  it("keeps read-only and unavailable rows from switching", () => {
    const readOnlyItem = retagTarget();
    const unavailableItem = retagTarget({
      service_key: "media/radarr",
      service: "radarr",
      image: "repo/radarr:latest",
      image_repo: "repo/radarr",
      tracking_tag: "",
      tracking_tag_source: "",
      proposed_tag: "",
      final_image: "",
      retag_available: false,
      retag_reason: "missing-provenance",
      choices: ["keep-current"],
      digest_provenance: null,
    });
    const wrapper = mountMobileList({
      rows: [readOnlyItem, unavailableItem],
      mutationDisabled: true,
      mutationNotice: "Read-only mode keeps retag switch/apply disabled.",
    });

    expect(wrapper.text()).toContain("media/radarr");
    expect(wrapper.text()).toContain("Unknown (unknown)");
    expect(wrapper.text()).toContain("No stored digest provenance is available");
    expect(wrapper.text()).toContain("None");

    const switchInputs = wrapper.findAll<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );
    expect(switchInputs).toHaveLength(2);
    expect(switchInputs[0].attributes("disabled")).toBeDefined();
    expect(switchInputs[0].attributes("title")).toBe(
      "Read-only mode keeps retag switch/apply disabled.",
    );
    expect(switchInputs[1].attributes("disabled")).toBeDefined();
    expect(switchInputs[1].attributes("title")).toBe(
      "No stored digest provenance is available for this service.",
    );
    expect(wrapper.emitted("choice-update")).toBeUndefined();
  });
});
