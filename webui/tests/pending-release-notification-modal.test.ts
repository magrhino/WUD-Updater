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

  it("orders and labels verified security updates before ordinary items", () => {
    const base = releaseNotificationResponse().items[0];
    const wrapper = mount(PendingReleaseNotificationModal, {
      props: {
        error: "",
        loading: false,
        response: releaseNotificationResponse({
          count: 2,
          sendable_count: 2,
          items: [
            { ...base, line_no: 2, title: "Routine update" },
            {
              ...base,
              line_no: 1,
              title: "Urgent update",
              category: "security_urgent",
              security: {
                outcome: "verified_critical_high",
                severity: "critical",
                reason_code: "verified_exposure",
                reason: "Verified exposure.",
                advisory_ids: ["GHSA-AAAA-BBBB-CCCC"],
                lookup_truncated: false,
              },
            },
          ],
        }),
        sendDisabled: false,
        sendDisabledMessage: "",
        show: true,
      },
      global: { stubs: naiveStubs },
    });

    expect(
      wrapper.findAll(".plan-line-row strong").map((node) => node.text()),
    ).toEqual(["Urgent update", "Routine update"]);
    expect(wrapper.text()).toContain("Critical security");
    expect(wrapper.text()).toContain("Not notified");
  });
});
