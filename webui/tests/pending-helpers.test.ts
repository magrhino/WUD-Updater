import { defineComponent, h, type VNodeChild } from "vue";
import { describe, expect, it, vi } from "vitest";

import type { PendingItem } from "../src/api/client";
import { safetyCues } from "../src/views/pending/safetyCues";
import { createPendingColumns } from "../src/views/pending/tableColumns";
import {
  pendingGroupedItem,
  pendingResponse,
  releaseNoteInfo,
  servicePolicy,
  snooze,
} from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

type RenderColumn = {
  key?: string;
  render?: (row: PendingItem) => VNodeChild;
};

describe("pending helper modules", () => {
  it("builds safety cues from versions, release notes, policies, and snoozes", () => {
    const major = pendingGroupedItem({
      line_no: 1,
      current_tag: "1.2.3",
      desired_tag: "2.0.0",
      services: ["app"],
    });
    const minor = pendingGroupedItem({
      line_no: 2,
      current_tag: "1.2.3",
      desired_tag: "1.3.0",
      services: ["worker"],
    });
    const patch = pendingGroupedItem({
      line_no: 3,
      current_tag: "1.2.3",
      desired_tag: "1.2.4",
      services: ["api"],
    });
    const digestLatest = pendingGroupedItem({
      line_no: 4,
      current_tag: "latest",
      desired_tag: "",
      digest: "sha256:abc",
      action: "recreate_stack",
      services: ["cache"],
    });
    const pending = pendingResponse([major, minor, patch, digestLatest]);
    const note = releaseNoteInfo({
      line_no: 1,
      breaking: true,
      breaking_reasons: ["Major version update."],
    });
    const noReleaseNote = releaseNoteInfo({
      line_no: 4,
      status: "unsupported",
      links: [],
      error: "no supported GitHub release source found",
    });

    const majorLabels = safetyCues(major, {
      pending,
      releaseNote: note,
      releaseNotesLoaded: true,
      releaseNotesLoading: false,
      servicePolicies: [servicePolicy({ service_key: "media/app", auto_update: true })],
      snoozes: [snooze({ service_key: "media/app" })],
    }).map((cue) => cue.label);
    expect(majorLabels).toContain("Major bump");
    expect(majorLabels).toContain("Possible breaking");
    expect(majorLabels).toContain("Snoozed");
    expect(majorLabels).toContain("Auto-update");

    expect(
      safetyCues(minor, {
        pending,
        releaseNote: null,
        releaseNotesLoaded: false,
        releaseNotesLoading: false,
        servicePolicies: [],
        snoozes: [],
      }).map((cue) => cue.label),
    ).toContain("Minor bump");
    expect(
      safetyCues(patch, {
        pending,
        releaseNote: null,
        releaseNotesLoaded: false,
        releaseNotesLoading: false,
        servicePolicies: [],
        snoozes: [],
      }).map((cue) => cue.label),
    ).toContain("Patch bump");

    const digestLabels = safetyCues(digestLatest, {
      pending,
      releaseNote: noReleaseNote,
      releaseNotesLoaded: true,
      releaseNotesLoading: false,
      servicePolicies: [],
      snoozes: [],
    }).map((cue) => cue.label);
    expect(digestLabels).toContain("Digest-only");
    expect(digestLabels).toContain("Mutable latest");
    expect(digestLabels).toContain("Stack restart");
    expect(digestLabels).toContain("No release notes");
  });

  it("creates fallback table renderers for tags, digests, safety, and release notes", async () => {
    const item = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:1.0",
      repo: "repo/app",
      desired_tag: "2.0.0",
      digest: "sha256:abcdefghijklmnopqrstuvwxyz0123456789",
    });
    const updateTagOverride = vi.fn();
    const columns = createPendingColumns({
      displayDigest: () => "sha256:abcdef...789",
      displayValue: (value) => value || "None",
      releaseNoteFor: () =>
        releaseNoteInfo({
          breaking: true,
          breaking_reasons: ["Major version update."],
        }),
      releaseNoteReason: () => "",
      releaseNoteStatus: () => "",
      riskCues: () => [{ key: "major-bump", label: "Major bump", type: "error" }],
      tagInputProps: (row) => ({ "aria-label": `New tag for ${row.image}` }),
      tagOverrideValue: () => "2.0.0",
      updateTagOverride,
    });

    const renderColumn = (key: string) => {
      const column = columns.find((item) => (item as RenderColumn).key === key) as
        | RenderColumn
        | undefined;
      return column?.render?.(item) ?? null;
    };
    const TestRenderer = defineComponent({
      setup() {
        return () =>
          h("div", [
            renderColumn("desired_tag"),
            renderColumn("digest"),
            renderColumn("safety_cues"),
            renderColumn("release_notes"),
          ]);
      },
    });

    const wrapper = mountWithApp(TestRenderer);
    expect(wrapper.find("input").attributes("aria-label")).toBe(
      "New tag for repo/app:1.0",
    );
    await wrapper.find("input").setValue("2.1.0");
    expect(updateTagOverride).toHaveBeenCalledWith(item, "2.1.0");
    expect(wrapper.text()).toContain("sha256:abcdef...789");
    expect(wrapper.text()).toContain("Major bump");
    expect(wrapper.text()).toContain("GitHub release");
    expect(wrapper.text()).toContain("Possible breaking change");
  });
});
