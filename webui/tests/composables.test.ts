import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useUpdateTargetOptions } from "../src/composables/useUpdateTargetOptions";
import { useUpdatesStore } from "../src/stores/updates";
import { updateTarget, updateTargetsResponse } from "./helpers/fixtures";

describe("useUpdateTargetOptions composable", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("returns empty options when updates store has no targets", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = null;

    const { serviceKeyOptions, imageRepoOptions, targets } =
      useUpdateTargetOptions();

    expect(targets.value).toHaveLength(0);
    expect(serviceKeyOptions.value).toHaveLength(0);
    expect(imageRepoOptions.value).toHaveLength(0);
  });

  it("returns service key options derived from updates.updateTargets", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/sonarr", image_repo: "linuxserver/sonarr" }),
      updateTarget({ service_key: "media/radarr", image_repo: "linuxserver/radarr" }),
    ]);

    const { serviceKeyOptions } = useUpdateTargetOptions();

    expect(serviceKeyOptions.value).toHaveLength(2);
    const values = serviceKeyOptions.value.map((opt) => opt.value);
    expect(values).toContain("media/radarr");
    expect(values).toContain("media/sonarr");
  });

  it("returns image repo options derived from updates.updateTargets", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/app", image_repo: "repo/app" }),
      updateTarget({ service_key: "media/worker", image_repo: "repo/worker" }),
    ]);

    const { imageRepoOptions } = useUpdateTargetOptions();

    expect(imageRepoOptions.value).toHaveLength(2);
    const values = imageRepoOptions.value.map((opt) => opt.value);
    expect(values).toContain("repo/app");
    expect(values).toContain("repo/worker");
  });

  it("deduplicates service key options when multiple targets share a key", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "1.0" }),
      updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "2.0" }),
    ]);

    const { serviceKeyOptions } = useUpdateTargetOptions();

    expect(serviceKeyOptions.value).toHaveLength(1);
    expect(serviceKeyOptions.value[0].value).toBe("media/app");
  });

  it("deduplicates image repo options when multiple targets share a repo", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "prod/app", image_repo: "repo/app", current_tag: "1.0" }),
      updateTarget({ service_key: "staging/app", image_repo: "repo/app", current_tag: "2.0" }),
    ]);

    const { imageRepoOptions } = useUpdateTargetOptions();

    expect(imageRepoOptions.value).toHaveLength(1);
    expect(imageRepoOptions.value[0].value).toBe("repo/app");
  });

  it("returns sorted service key options", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "z-stack/service", image_repo: "repo/z" }),
      updateTarget({ service_key: "a-stack/service", image_repo: "repo/a" }),
      updateTarget({ service_key: "m-stack/service", image_repo: "repo/m" }),
    ]);

    const { serviceKeyOptions } = useUpdateTargetOptions();

    const values = serviceKeyOptions.value.map((opt) => String(opt.value));
    expect(values).toEqual(["a-stack/service", "m-stack/service", "z-stack/service"]);
  });

  it("finds a target by service key", () => {
    const target = updateTarget({ service_key: "media/app", image_repo: "repo/app" });
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([target]);

    const { targetForServiceKey } = useUpdateTargetOptions();

    expect(targetForServiceKey("media/app")).toEqual(target);
    expect(targetForServiceKey("media/missing")).toBeUndefined();
  });

  it("finds a target by image repo", () => {
    const target = updateTarget({ service_key: "media/app", image_repo: "repo/app" });
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([target]);

    const { targetForImageRepo } = useUpdateTargetOptions();

    expect(targetForImageRepo("repo/app")).toEqual(target);
    expect(targetForImageRepo("repo/missing")).toBeUndefined();
  });

  it("returns tag options for a given image repo", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "prod/app",
        image_repo: "repo/app",
        current_tag: "1.0",
      }),
      updateTarget({
        service_key: "staging/app",
        image_repo: "repo/app",
        current_tag: "2.0",
      }),
    ]);

    const { tagOptionsForImageRepo } = useUpdateTargetOptions();

    const tags = tagOptionsForImageRepo("repo/app").map((opt) => opt.value);
    expect(tags).toContain("1.0");
    expect(tags).toContain("2.0");
    expect(tags).toHaveLength(2);
  });

  it("excludes blank current_tag values from tag options", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "" }),
      updateTarget({ service_key: "media/app2", image_repo: "repo/app", current_tag: "  " }),
      updateTarget({ service_key: "media/app3", image_repo: "repo/app", current_tag: "1.0" }),
    ]);

    const { tagOptionsForImageRepo } = useUpdateTargetOptions();

    const tags = tagOptionsForImageRepo("repo/app");
    expect(tags).toHaveLength(1);
    expect(tags[0].value).toBe("1.0");
  });

  it("returns empty tag options for an unknown image repo", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/app", image_repo: "repo/app", current_tag: "1.0" }),
    ]);

    const { tagOptionsForImageRepo } = useUpdateTargetOptions();

    expect(tagOptionsForImageRepo("repo/other")).toHaveLength(0);
  });

  it("reads from updates store, not the old webui store namespace", () => {
    // Verify the composable correctly uses 'updates' Pinia store id
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({ service_key: "media/test", image_repo: "repo/test" }),
    ]);

    const { serviceKeyOptions } = useUpdateTargetOptions();

    expect(updates.$id).toBe("updates");
    expect(serviceKeyOptions.value[0].value).toBe("media/test");
  });
});