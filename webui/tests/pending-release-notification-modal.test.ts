import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PendingReleaseNotificationModal from "../src/components/pending/PendingReleaseNotificationModal.vue";
import { releaseNotificationResponse } from "./helpers/fixtures";
import { naiveStubs } from "./helpers/mount";

describe("PendingReleaseNotificationModal", () => {
  it("renders the exact categorized Discord messages returned by preview", () => {
    const messages = [
      "🧾 WUDup batch — 2 updates found\n\n⚠️ Needs review\n• media/app `1.0.0` → `2.0.0` — major version bump\n\nOpen WUDup for full notes, digests, and apply plan.",
      "🧾 WUDup batch — 2 updates found\n\n🟢 Routine\n• data/db `1.0.0` → `1.0.1` — patch update with release notes\n\nOpen WUDup for full notes, digests, and apply plan.",
    ];
    const wrapper = mount(PendingReleaseNotificationModal, {
      props: {
        error: "",
        loading: false,
        response: releaseNotificationResponse({
          batch_count: messages.length,
          messages,
        }),
        sendDisabled: false,
        sendDisabledMessage: "",
        show: true,
      },
      global: { stubs: naiveStubs },
    });

    expect(wrapper.find("#release-digest-title").text()).toBe(
      "Discord digest preview",
    );
    expect(wrapper.findAll(".release-digest-message pre").map((node) => node.text())).toEqual(
      messages,
    );
    expect(wrapper.text()).toContain("Message 1 of 2");
    expect(wrapper.text()).toContain("Message 2 of 2");
  });
});
