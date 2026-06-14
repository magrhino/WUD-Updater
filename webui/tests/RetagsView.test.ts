import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RetagsView from "../src/views/RetagsView.vue";
import { useUpdatesStore } from "../src/stores/updates";
import {
  retagTarget,
  retagTargetsResponse,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

describe("RetagsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders retag review rows and the disabled preview affordance", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse(
      [
        retagTarget(),
        retagTarget({
          service_key: "media/radarr",
          service: "radarr",
          image: "repo/radarr:latest",
          image_repo: "repo/radarr",
          proposed_tag: "",
          final_image: "",
          retag_available: false,
          retag_reason: "missing-provenance",
          choices: ["keep-current"],
          digest_provenance: null,
        }),
      ],
      { warnings: ["compose warning"] },
    );
    const loadRetagTargets = vi
      .spyOn(updates, "loadRetagTargets")
      .mockResolvedValue();

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    const text = wrapper.text();
    expect(loadRetagTargets).toHaveBeenCalledTimes(1);
    expect(text).toContain("Retag review");
    expect(text).toContain("Total services");
    expect(text).toContain("Retag candidates");
    expect(text).toContain("Needs attention");
    expect(text).toContain("compose warning");
    expect(text).toContain("media/app");
    expect(text).toContain("Retag available");
    expect(text).toContain("Candidate ready");
    expect(text).toContain("media/radarr");
    expect(text).toContain("Missing provenance");
    expect(text).toContain("Preview/apply is not available");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text().includes("Preview retag changes"))
        ?.attributes("disabled"),
    ).toBeDefined();
  });

  it("filters retag targets by search text and review status", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget(),
      retagTarget({
        service_key: "data/postgres",
        stack: "data",
        service: "postgres",
        image: "postgres:16",
        image_repo: "postgres",
        current_tag: "16",
        tracking_tag: "16",
        proposed_tag: "",
        final_image: "",
        retag_available: false,
        retag_reason: "not-latest-tracking",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ]);
    vi.spyOn(updates, "loadRetagTargets").mockResolvedValue();

    const wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();

    await wrapper
      .find('input[aria-label="Search retag targets"]')
      .setValue("postgres");
    await flushPromises();

    expect(wrapper.text()).toContain("data/postgres");
    expect(wrapper.text()).not.toContain("media/app");

    await wrapper.find('input[aria-label="Search retag targets"]').setValue("");
    await wrapper.find("select").setValue("available");
    await flushPromises();

    expect(wrapper.text()).toContain("media/app");
    expect(wrapper.text()).not.toContain("data/postgres");

    await wrapper.find("select").setValue("attention");
    await flushPromises();

    expect(wrapper.text()).not.toContain("media/app");
    expect(wrapper.text()).toContain("data/postgres");
  });

  it("renders empty, unavailable, loading, and error states", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const updates = useUpdatesStore();
    const loadRetagTargets = vi
      .spyOn(updates, "loadRetagTargets")
      .mockResolvedValue();

    updates.loading = true;
    let wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("Loading retag targets");
    expect(loadRetagTargets).toHaveBeenCalledTimes(1);

    updates.loading = false;
    updates.error = "retag targets unavailable";
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("retag targets unavailable");
    expect(wrapper.text()).toContain("The backend could not load retag review state.");

    updates.error = "";
    updates.retagTargets = retagTargetsResponse([]);
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("No Compose services found");

    updates.retagTargets = retagTargetsResponse([], {
      status: "unavailable",
      warnings: ["compose discovery failed"],
    });
    wrapper.unmount();
    wrapper = mountWithApp(RetagsView, { pinia });
    await flushPromises();
    expect(wrapper.text()).toContain("compose discovery failed");
    expect(wrapper.text()).toContain("Compose discovery unavailable");
  });
});
