import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useUpdateTargetOptions } from "../src/composables/useUpdateTargetOptions";
import { useUpdatesStore } from "../src/stores/updates";
import { updateTarget, updateTargetsResponse } from "./helpers/fixtures";

describe("useUpdateTargetOptions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("returns empty options when update targets have not loaded", () => {
    const options = useUpdateTargetOptions();

    expect(options.targets.value).toEqual([]);
    expect(options.serviceKeyOptions.value).toEqual([]);
    expect(options.imageRepoOptions.value).toEqual([]);
    expect(options.tagOptionsForImageRepo("repo/app")).toEqual([]);
  });

  it("derives sorted, de-duplicated service and image options from the updates store", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
      updateTarget({
        service_key: "media/radarr",
        image_repo: "repo/radarr",
        current_tag: "5.0",
      }),
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.1",
      }),
      updateTarget({
        service_key: "",
        image_repo: "",
        current_tag: "ignored",
      }),
    ]);
    const options = useUpdateTargetOptions();

    expect(options.serviceKeyOptions.value).toEqual([
      { label: "media/radarr", value: "media/radarr" },
      { label: "media/sonarr", value: "media/sonarr" },
    ]);
    expect(options.imageRepoOptions.value).toEqual([
      { label: "repo/radarr", value: "repo/radarr" },
      { label: "repo/sonarr", value: "repo/sonarr" },
    ]);
  });

  it("finds targets and tag options by service key and image repository", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "media/radarr",
        image_repo: "repo/radarr",
        current_tag: "5.0",
      }),
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
      updateTarget({
        service_key: "media/sonarr-beta",
        image_repo: "repo/sonarr",
        current_tag: "  ",
      }),
      updateTarget({
        service_key: "media/sonarr-nightly",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
    ]);
    const options = useUpdateTargetOptions();

    expect(options.targetForServiceKey("media/radarr")?.image_repo).toBe(
      "repo/radarr",
    );
    expect(options.targetForImageRepo("repo/sonarr")?.service_key).toBe(
      "media/sonarr",
    );
    expect(options.tagOptionsForImageRepo("repo/sonarr")).toEqual([
      { label: "4.0", value: "4.0" },
    ]);
    expect(options.tagOptionsForImageRepo("repo/missing")).toEqual([]);
  });
});
