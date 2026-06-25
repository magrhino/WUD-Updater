import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import RetagTargetsMobileList from "../src/components/retags/RetagTargetsMobileList.vue";
import type { RetagTargetChoice, RetagTargetItem } from "../src/api/client";
import { retagTarget } from "./helpers/fixtures";
import { naiveStubs } from "./helpers/mount";

function mountMobileList({
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
  return mount(RetagTargetsMobileList, {
    props: {
      rows,
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

describe("RetagTargetsMobileList", () => {
  it("renders mobile review details and emits switch choices", async () => {
    const item = retagTarget({
      candidate_source: "github-latest",
      candidate_warning: "GitHub latest fallback will update latest tracking to 1.1.",
      candidate_link_label: "GitHub release",
      candidate_link_url: "https://github.com/acme/app/releases/tag/1.1",
    });
    const wrapper = mountMobileList({ rows: [item] });

    expect(wrapper.text()).toContain("media/app");
    expect(wrapper.text()).toContain("media / app");
    expect(wrapper.text()).toContain("repo/app:latest");
    expect(wrapper.text()).toContain("latest (label)");
    expect(wrapper.text()).toContain("latest -> 1.1");
    expect(wrapper.text()).toContain("GitHub release");
    expect(wrapper.text()).toContain(
      "GitHub latest fallback will update latest tracking to 1.1.",
    );
    expect(wrapper.find("a").attributes("href")).toBe(
      "https://github.com/acme/app/releases/tag/1.1",
    );
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
    expect(
      wrapper.find<HTMLInputElement>('input[aria-label="Target tag for media/app"]')
        .element.value,
    ).toBe("1.1");

    const retagOnlyButton = wrapper.get(
      'button[aria-label="Retag only media/app"]',
    );
    expect(retagOnlyButton.text()).toBe("Retag this service");
    expect(retagOnlyButton.attributes("disabled")).toBeUndefined();
    expect(retagOnlyButton.attributes("title")).toBe(
      "Select only media/app for retag preview.",
    );
    await retagOnlyButton.trigger("click");
    expect(wrapper.emitted("retag-only")).toEqual([[item]]);

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
      "Enter a target tag before retagging.",
    );
    const retagOnlyButtons = wrapper.findAll("button");
    expect(retagOnlyButtons).toHaveLength(1);
    expect(retagOnlyButtons[0].attributes("disabled")).toBeDefined();
    expect(retagOnlyButtons[0].attributes("title")).toBe(
      "Read-only mode keeps retag switch/apply disabled.",
    );
    expect(wrapper.emitted("choice-update")).toBeUndefined();
    expect(wrapper.emitted("retag-only")).toBeUndefined();
  });

  it("enables manual fallback rows after a target tag is supplied", async () => {
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
    const wrapper = mountMobileList({
      rows: [item],
      targetTags: { "media/radarr": "5.22.4" },
    });

    const targetInput = wrapper.find<HTMLInputElement>(
      'input[aria-label="Target tag for media/radarr"]',
    );
    expect(targetInput.element.value).toBe("5.22.4");
    await targetInput.setValue("5.22.5");
    expect(wrapper.emitted("target-tag-update")).toEqual([[item, "5.22.5"]]);

    const switchInput = wrapper.find<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );
    expect(switchInput.attributes("disabled")).toBeUndefined();
    await switchInput.setValue();
    expect(wrapper.emitted("choice-update")).toEqual([
      [item, "switch-to-concrete"],
    ]);
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
    const wrapper = mountMobileList({
      rows: [item],
      choices: { [item.service_key]: "switch-to-concrete" },
      targetTags: { [item.service_key]: "-bad" },
    });

    const switchInput = wrapper.find<HTMLInputElement>(
      'input[value="switch-to-concrete"]',
    );
    expect(switchInput.attributes("disabled")).toBeDefined();
    expect(switchInput.attributes("title")).toContain("invalid target tag");
    const retagOnlyButton = wrapper.get(
      'button[aria-label="Retag only media/radarr"]',
    );
    expect(retagOnlyButton.attributes("disabled")).toBeDefined();
    expect(retagOnlyButton.attributes("title")).toContain("invalid target tag");
    expect(wrapper.text()).toContain("media/radarr has an invalid target tag");
  });
});
